"""Inline chat input widget with channel selector."""

from typing import Optional
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from rich.text import Text

from ..state import AppState
from ..formatting import Colors


class ChatInput(Vertical):
    """Input widget for chat with channel indicator and reply mode support."""

    DEFAULT_CSS = """
    ChatInput {
        height: auto;
        width: 100%;
        background: $surface;
    }

    ChatInput .reply-context {
        height: 1;
        width: 100%;
        padding: 0 1;
        background: $surface-darken-1;
        display: none;
    }

    ChatInput .reply-context.visible {
        display: block;
    }

    ChatInput .input-row {
        height: 1;
        width: 100%;
    }

    ChatInput .channel-indicator {
        width: auto;
        min-width: 6;
        max-width: 18;
        padding: 0;
    }

    ChatInput .chat-input-field {
        width: 1fr;
        border: none;
        height: 1;
        padding: 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel_reply", "Cancel Reply", show=False, priority=True),
        Binding("pageup", "scroll_chat_up", "Scroll Up", show=False, priority=True),
        Binding("pagedown", "scroll_chat_down", "Scroll Down", show=False, priority=True),
    ]

    channel = reactive(0)
    dm_node_id = reactive(None)  # None = broadcast mode, str = DM mode
    dm_node_name = reactive("")  # Display name for DM recipient

    # Reply mode state
    reply_to_entry = reactive(None)  # Entry being replied to
    reply_to_name = reactive("")  # Sender name of message being replied to

    class MessageSubmitted(Message):
        """Posted when a message is submitted."""

        def __init__(
            self,
            text: str,
            channel: int,
            dest_node_id: str = None,
            reply_to_packet_id: int = None
        ):
            self.text = text
            self.channel = channel
            self.dest_node_id = dest_node_id  # None for broadcast, node_id for DM
            self.reply_to_packet_id = reply_to_packet_id  # Packet ID of parent if reply
            super().__init__()

    class ReplyCancelled(Message):
        """Posted when reply mode is cancelled."""
        pass

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        yield Static(self._format_reply_context(), classes="reply-context", id="reply-context")
        with Horizontal(classes="input-row"):
            yield Static(self._format_channel(), classes="channel-indicator", id="channel-indicator")
            yield Input(placeholder="Type message...", classes="chat-input-field", id="chat-input-field")

    def _format_channel(self) -> Text:
        """Format channel indicator: Ch:[N] or DM:Name with hint."""
        text = Text()
        if self.reply_to_entry:
            text.append("↩", style="bright_yellow")
            text.append(" ", style=Colors.DIM)
        if self.dm_node_id:
            text.append("DM:", style=Colors.DIM)
            name = self.dm_node_name or self.dm_node_id[-4:]
            text.append(f"[{name}]", style="bold bright_magenta")
        else:
            text.append("Ch:", style=Colors.DIM)
            text.append(f"[{self.channel}]", style="bold bright_green")
        text.append(">", style=Colors.DIM)
        return text

    def _format_reply_context(self) -> Text:
        """Format the reply context header."""
        if not self.reply_to_entry:
            return Text("")

        text = Text()
        text.append("↩ Replying to ", style="bright_yellow")
        text.append(self.reply_to_name or "?", style="bold bright_cyan")

        # Get message preview
        packet = self.reply_to_entry.get('packet', {})
        decoded = packet.get('decoded', {})
        msg_text = decoded.get('text', '')
        preview = msg_text[:40] + '...' if len(msg_text) > 40 else msg_text
        text.append(f': "{preview}"', style="dim italic")
        text.append("  [Esc to cancel]", style="dim")
        return text

    def _update_channel_display(self):
        """Update the channel indicator display."""
        indicator = self.query_one("#channel-indicator", Static)
        indicator.update(self._format_channel())

    def _update_reply_context(self):
        """Update the reply context display."""
        context = self.query_one("#reply-context", Static)
        context.update(self._format_reply_context())

        # Show/hide the reply context line
        if self.reply_to_entry:
            context.add_class("visible")
        else:
            context.remove_class("visible")

    def set_channel(self, channel: int):
        """Set the channel (broadcast mode)."""
        self.dm_node_id = None
        self.dm_node_name = ""
        self.channel = channel
        self.clear_reply_mode()  # Clear reply when switching channels
        self._update_channel_display()

    def set_dm_mode(self, node_id: str, node_name: str = ""):
        """Set DM mode for a specific node."""
        self.dm_node_id = node_id
        self.dm_node_name = node_name
        self.clear_reply_mode()  # Clear reply when switching DMs
        self._update_channel_display()

    def set_reply_mode(self, entry: dict, sender_name: str = ""):
        """Enter reply mode for a specific message.

        Args:
            entry: The message entry being replied to
            sender_name: Display name of the message sender
        """
        self.reply_to_entry = entry
        self.reply_to_name = sender_name
        self._update_reply_context()
        self._update_channel_display()
        self.focus_input()

    def clear_reply_mode(self):
        """Exit reply mode."""
        if self.reply_to_entry:
            self.reply_to_entry = None
            self.reply_to_name = ""
            self._update_reply_context()
            self._update_channel_display()

    def action_cancel_reply(self):
        """Cancel reply mode, clear input, or go back to channel selection."""
        # First priority: cancel reply mode
        if self.reply_to_entry:
            self.clear_reply_mode()
            self.post_message(self.ReplyCancelled())
            return

        # Second priority: clear input if there's text
        try:
            input_field = self.query_one("#chat-input-field", Input)
            if input_field.value:
                input_field.value = ""
                return
        except Exception:
            pass

        # Third priority: go back to channel selection (header bar)
        try:
            from .header_bar import HeaderBar
            header = self.app.query_one("#header-bar", HeaderBar)
            header.focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted):
        """Handle Enter key in input."""
        if event.input.id == "chat-input-field":
            text = event.input.value.strip()
            if text:
                # Get reply-to packet ID if in reply mode
                reply_to_packet_id = None
                if self.reply_to_entry:
                    packet = self.reply_to_entry.get('packet', {})
                    reply_to_packet_id = packet.get('id')

                self.post_message(self.MessageSubmitted(
                    text,
                    self.channel,
                    self.dm_node_id,
                    reply_to_packet_id
                ))

                # Clear input and reply mode
                event.input.value = ""
                self.clear_reply_mode()

    def focus_input(self):
        """Focus the input field."""
        self.query_one("#chat-input-field", Input).focus()

    def action_scroll_chat_up(self):
        """Scroll the chat log up (Page Up)."""
        try:
            from .chat_log import ChatLog
            chat_log = self.app.query_one("#chat-log", ChatLog)
            chat_log.action_page_up()
        except Exception:
            pass

    def action_scroll_chat_down(self):
        """Scroll the chat log down (Page Down)."""
        try:
            from .chat_log import ChatLog
            chat_log = self.app.query_one("#chat-log", ChatLog)
            chat_log.action_page_down()
        except Exception:
            pass
