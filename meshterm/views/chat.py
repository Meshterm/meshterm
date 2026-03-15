"""Chat view - IRC-style chat with channel filtering."""

from typing import Union
from textual.app import ComposeResult
from textual.containers import Container
from textual.binding import Binding

from ..state import AppState
from ..formatting import format_node_id
from ..widgets.chat_log import ChatLog
from ..widgets.chat_input import ChatInput
from ..widgets.reaction_picker import ReactionPicker
from ..widgets.channel_manager import ChannelManager
from ..widgets.message_action_menu import MessageActionMenu
from ..widgets.message_details_modal import MessageDetailsModal


class ChatView(Container):
    """IRC-style chat view with channel filtering."""

    DEFAULT_CSS = """
    ChatView {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    ChatView > .chat-log {
        height: 1fr;
        width: 100%;
        border: solid $primary;
        overflow-x: hidden;
    }

    ChatView > .chat-footer {
        height: auto;
        background: $surface;
        padding: 0;
    }
    """

    BINDINGS = [
        Binding("0", "switch_channel('0')", "Ch 0", show=False, priority=True),
        Binding("1", "switch_channel('1')", "Ch 1", show=False, priority=True),
        Binding("2", "switch_channel('2')", "Ch 2", show=False, priority=True),
        Binding("3", "switch_channel('3')", "Ch 3", show=False, priority=True),
        Binding("4", "switch_channel('4')", "Ch 4", show=False, priority=True),
        Binding("5", "switch_channel('5')", "Ch 5", show=False, priority=True),
        Binding("6", "switch_channel('6')", "Ch 6", show=False, priority=True),
        Binding("7", "switch_channel('7')", "Ch 7", show=False, priority=True),
        Binding("left", "prev_channel", "Prev Channel", show=False, priority=True),
        Binding("right", "next_channel", "Next Channel", show=False, priority=True),
        Binding("x", "close_dm", "Close DM", show=False, priority=True),
        Binding("ctrl+r", "start_select", "Select Msg", show=False, priority=True),
        Binding("ctrl+j", "open_channel_manager", "Manage", show=False, priority=True),
    ]

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        # current_channel: int for broadcast channels (0-7), str for DM ("dm:node_id")
        self.current_channel: Union[int, str] = 0
        # Subscribe to delivery updates for input unlocking
        self.state.messages.subscribe(self._handle_delivery_event)

    def compose(self) -> ComposeResult:
        yield ChatLog(self.state, classes="chat-log", id="chat-log")
        yield ChatInput(self.state, classes="chat-footer", id="chat-input")

    def on_show(self):
        """Called when view becomes visible."""
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.load_messages()
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.focus_input()

    def action_switch_channel(self, channel: str):
        """Switch to a different channel or DM.

        Args:
            channel: Either a channel number ("0"-"7") or DM ID ("dm:node_id")
        """
        # Don't switch channels when in message selection mode
        chat_log = self.query_one("#chat-log", ChatLog)
        if chat_log.selection_active:
            return

        if channel.startswith("dm:"):
            # DM mode
            self.current_channel = channel
            node_id = channel[3:]  # Remove "dm:" prefix
            # Clear notification when switching to DM
            self.state.open_dms.clear_notification(node_id)
        else:
            # Broadcast mode
            self.current_channel = int(channel)

        self._sync_channel()

        # Update header bar
        try:
            from ..widgets.header_bar import HeaderBar
            header = self.app.query_one("#header-bar", HeaderBar)
            header.set_active_subtab(channel)
        except Exception:
            pass

    def action_next_channel(self):
        """Switch to next channel/DM."""
        tabs = self._get_available_tabs()
        if not tabs:
            return

        current_str = str(self.current_channel) if isinstance(self.current_channel, int) else self.current_channel
        try:
            current_idx = tabs.index(current_str)
            next_idx = (current_idx + 1) % len(tabs)
        except ValueError:
            next_idx = 0

        self.action_switch_channel(tabs[next_idx])

    def action_prev_channel(self):
        """Switch to previous channel/DM."""
        tabs = self._get_available_tabs()
        if not tabs:
            return

        current_str = str(self.current_channel) if isinstance(self.current_channel, int) else self.current_channel
        try:
            current_idx = tabs.index(current_str)
            prev_idx = (current_idx - 1) % len(tabs)
        except ValueError:
            prev_idx = 0

        self.action_switch_channel(tabs[prev_idx])

    def action_close_dm(self):
        """Close the currently active DM tab."""
        if isinstance(self.current_channel, str) and self.current_channel.startswith("dm:"):
            node_id = self.current_channel[3:]  # Remove "dm:" prefix
            self.state.open_dms.close_dm(node_id)
            # Switch back to channel 0
            self.action_switch_channel("0")

    def _get_available_tabs(self) -> list:
        """Get list of available chat tabs (channels + DMs)."""
        tabs = ["0"]  # Always include channel 0

        # Include channels 1-7 only if they have configured names
        for i in range(1, 8):
            if self.state.get_channel_name(i):
                tabs.append(str(i))

        # Append open DMs
        for dm in self.state.open_dms.get_open_dms():
            tabs.append(f"dm:{dm.node_id}")

        return tabs

    def _sync_channel(self):
        """Sync channel across all widgets."""
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_input = self.query_one("#chat-input", ChatInput)

        if isinstance(self.current_channel, str) and self.current_channel.startswith("dm:"):
            # DM mode
            node_id = self.current_channel[3:]  # Remove "dm:" prefix
            # Get node name from open_dms state
            node_name = ""
            for dm in self.state.open_dms.get_open_dms():
                if dm.node_id == node_id:
                    node_name = dm.node_name
                    break
            chat_log.set_dm_mode(node_id)
            chat_input.set_dm_mode(node_id, node_name)
        else:
            # Broadcast mode
            chat_log.set_channel(self.current_channel)
            chat_input.set_channel(self.current_channel)

    # Message selection and actions

    def action_start_select(self):
        """Start unified message selection mode."""
        chat_log = self.query_one("#chat-log", ChatLog)
        if chat_log.selection_active:
            return
        chat_log.enter_selection_mode("select")

    def _get_sender_name(self, packet: dict) -> str:
        """Get display name for a packet's sender."""
        from_id = packet.get('from', packet.get('fromId'))
        sender_name = format_node_id(from_id) if from_id else "?"
        if from_id:
            node = self.state.nodes.get_node(from_id)
            if node:
                user = node.get('user', {})
                sender_name = user.get('shortName') or user.get('longName') or sender_name
        return sender_name

    def on_chat_log_message_selected(self, event: ChatLog.MessageSelected):
        """Handle message selection - show action menu."""
        entry = event.entry
        packet = entry.get('packet', {})
        sender_name = self._get_sender_name(packet)

        is_own = packet.get('_tx', False)
        delivered = packet.get('_delivered')
        can_retransmit = is_own and delivered is not True

        # Show DM option if it's someone else's message and we're not already in a DM with them
        from_id = packet.get('from', packet.get('fromId'))
        in_dm_with_sender = (
            isinstance(self.current_channel, str)
            and self.current_channel.startswith("dm:")
            and self.current_channel[3:] == format_node_id(from_id)
        )
        show_dm = not is_own and not in_dm_with_sender

        self.app.push_screen(MessageActionMenu(
            entry=entry,
            sender_name=sender_name,
            is_own_message=is_own,
            can_retransmit=can_retransmit,
            show_dm=show_dm,
        ), self._handle_action_result)

    def on_chat_log_selection_cancelled(self, event: ChatLog.SelectionCancelled):
        """Handle selection mode cancellation."""
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.focus_input()

    def _handle_action_result(self, result):
        """Handle action menu dismiss result."""
        if result is None:
            self._focus_input()
            return

        action, entry = result
        packet = entry.get('packet', {})
        sender_name = self._get_sender_name(packet)

        if action == "reply":
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.set_reply_mode(entry, sender_name)
            self._focus_input()
        elif action == "react":
            def handle_reaction(reaction_result):
                if reaction_result is not None:
                    self._send_reaction(entry, reaction_result)
                self._focus_input()
            self.app.push_screen(ReactionPicker(entry, sender_name), handle_reaction)
        elif action == "details":
            self.app.push_screen(
                MessageDetailsModal(entry, self.state),
                lambda _: self._focus_input(),
            )
        elif action == "dm":
            from_id = packet.get('from', packet.get('fromId'))
            if from_id:
                node_id = format_node_id(from_id)
                self.state.open_dms.open_dm(node_id, sender_name)
                self.action_switch_channel(f"dm:{node_id}")
            self._focus_input()
        elif action == "retransmit":
            self._retransmit_message(entry)
            self._focus_input()

    def _retransmit_message(self, entry: dict):
        """Re-transmit a failed/pending message."""
        packet = entry.get('packet', {})
        decoded = packet.get('decoded', {})
        text = decoded.get('text', '')
        if not text:
            return

        dest = packet.get('to', '^all')
        channel = packet.get('channel', 0)
        reply_to = packet.get('_reply_to_packet_id')

        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.post_message(ChatInput.MessageSubmitted(
            text=text,
            channel=channel,
            dest_node_id=dest if dest not in ('^all', '!ffffffff', 4294967295) else None,
            reply_to_packet_id=reply_to,
        ))

    def _send_reaction(self, entry: dict, emoji: str):
        """Send a reaction emoji to a message."""
        packet = entry.get('packet', {})
        packet_id = packet.get('id')

        if not packet_id:
            self.app.notify("Cannot react: message has no packet ID", severity="error")
            return

        if isinstance(self.current_channel, str) and self.current_channel.startswith("dm:"):
            node_id = self.current_channel[3:]
            dest = node_id
            channel = 0
        else:
            dest = "^all"
            channel = self.current_channel if isinstance(self.current_channel, int) else 0

        if hasattr(self.app, 'connection'):
            success, _ = self.app.connection.send_reaction(packet_id, emoji, dest, channel)
            if success:
                self.app.notify(f"Reacted with {emoji}", timeout=2)
            else:
                self.app.notify("Failed to send reaction", severity="error")

    def _focus_input(self):
        """Focus the chat input widget."""
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.focus_input()

    # Channel Manager

    def action_open_channel_manager(self):
        """Open the channel/DM manager modal."""
        chat_log = self.query_one("#chat-log", ChatLog)
        if chat_log.selection_active:
            return  # Don't open while in selection mode

        def handle_result(result):
            """Handle channel manager result."""
            if result is None:
                # Cancelled
                pass
            elif result[0] == "channel":
                # Switch to channel
                channel = result[1]
                self.action_switch_channel(str(channel))
            elif result[0] == "dm":
                # Switch to existing DM
                node_id = result[1]
                self.action_switch_channel(f"dm:{node_id}")
            elif result[0] == "new_dm":
                # Switch to newly opened DM
                node_id = result[1]
                self.action_switch_channel(f"dm:{node_id}")

            # Refocus input
            chat_input = self.query_one("#chat-input", ChatInput)
            chat_input.focus_input()

        self.app.push_screen(ChannelManager(self.state), handle_result)

    def _handle_delivery_event(self, event_type: str, data):
        """Unlock input when delivery status is updated."""
        if event_type == "delivery_updated":
            try:
                chat_input = self.query_one("#chat-input", ChatInput)
                if chat_input.send_locked:
                    chat_input.unlock_input()
            except Exception:
                pass

    def on_unmount(self):
        """Cleanup subscriptions."""
        self.state.messages.unsubscribe(self._handle_delivery_event)
