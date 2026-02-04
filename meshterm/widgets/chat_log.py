"""IRC-style chat log widget."""

from collections import Counter
from datetime import datetime
from typing import Optional, List, Dict, TYPE_CHECKING
from textual.widgets import RichLog
from textual.reactive import reactive
from textual.binding import Binding
from textual.message import Message
from rich.text import Text
from rich.cells import cell_len

from ..state import AppState
from ..formatting import Colors, format_node_id

if TYPE_CHECKING:
    from ..storage import LogStorage


class ChatLog(RichLog):
    """Scrollable panel showing IRC-style chat messages."""

    channel = reactive(0)
    dm_node_id = reactive(None)  # None = broadcast mode, str = DM mode

    # Selection mode state
    selection_active = reactive(False)
    selection_mode = reactive("")  # "react" or "reply"
    selected_index = reactive(0)

    HISTORY_PAGE_SIZE = 50
    SCROLLBAR_WIDTH = 8  # Scrollbar (2) + buffer for narrow screens

    # Key bindings active during selection mode
    BINDINGS = [
        Binding("j", "select_next", "Next", show=False, priority=True),
        Binding("k", "select_prev", "Prev", show=False, priority=True),
        Binding("down", "select_next", "Next", show=False, priority=True),
        Binding("up", "select_prev", "Prev", show=False, priority=True),
        Binding("enter", "confirm_selection", "Select", show=False, priority=True),
        Binding("escape", "cancel_selection", "Cancel", show=False, priority=True),
        Binding("1", "select_by_number('1')", show=False, priority=True),
        Binding("2", "select_by_number('2')", show=False, priority=True),
        Binding("3", "select_by_number('3')", show=False, priority=True),
        Binding("4", "select_by_number('4')", show=False, priority=True),
        Binding("5", "select_by_number('5')", show=False, priority=True),
        Binding("6", "select_by_number('6')", show=False, priority=True),
        Binding("7", "select_by_number('7')", show=False, priority=True),
        Binding("8", "select_by_number('8')", show=False, priority=True),
        Binding("9", "select_by_number('9')", show=False, priority=True),
    ]

    class MessageSelected(Message):
        """Posted when a message is selected for reaction/reply."""
        def __init__(self, entry: dict, mode: str):
            self.entry = entry
            self.mode = mode  # "react" or "reply"
            super().__init__()

    class SelectionCancelled(Message):
        """Posted when selection mode is cancelled."""
        pass

    def __init__(self, state: AppState, **kwargs):
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)
        self.state = state
        self._oldest_id: Optional[int] = None
        self._history_exhausted = False
        self._loading_history = False
        self._displayed_entries: list = []  # Track message entries for re-rendering
        self._reactions_cache: Dict[int, List[dict]] = {}  # db_id -> reactions
        self._reply_refs_cache: Dict[int, dict] = {}  # db_id -> reply ref info
        self.can_focus = False  # Only focusable during selection mode

        # Subscribe to message updates
        self.state.messages.subscribe(self._handle_packet_event)

    @property
    def storage(self) -> "Optional[LogStorage]":
        """Get storage from state."""
        return self.state.storage

    def _handle_packet_event(self, event_type: str, data):
        """Handle new message, delivery update, or reaction update."""
        if event_type == "message_added" and data:
            packet = data['packet']
            decoded = packet.get('decoded', {})
            portnum = str(decoded.get('portnum', ''))

            # Only handle TEXT_MESSAGE_APP
            if portnum in ('TEXT_MESSAGE_APP', '1'):
                packet_channel = packet.get('channel', 0)

                if self.dm_node_id:
                    # DM mode: only show messages to/from the DM node on channel 0
                    if packet_channel != 0:
                        return
                    from_id = format_node_id(packet.get('from', ''))
                    to_id = format_node_id(packet.get('to', ''))
                    dm_node_id = format_node_id(self.dm_node_id)
                    if from_id == dm_node_id or to_id == dm_node_id:
                        self._render_message(data)
                else:
                    # Broadcast mode: show messages on the current channel
                    if packet_channel == self.channel:
                        # On channel 0, only show broadcasts (to=^all), not DMs
                        if self.channel == 0:
                            to_id = format_node_id(packet.get('to', ''))
                            if to_id not in ('^all', '!ffffffff'):
                                return  # Skip DMs on channel 0
                        self._render_message(data)
        elif event_type == "delivery_updated" and data:
            # Refresh the entire log to update the delivery indicator
            # (RichLog doesn't support updating individual lines)
            packet = data
            decoded = packet.get('decoded', {})
            portnum = str(decoded.get('portnum', ''))
            if portnum in ('TEXT_MESSAGE_APP', '1'):
                packet_channel = packet.get('channel', 0)
                if self.dm_node_id:
                    if packet_channel == 0:
                        from_id = format_node_id(packet.get('from', ''))
                        to_id = format_node_id(packet.get('to', ''))
                        dm_node_id = format_node_id(self.dm_node_id)
                        if from_id == dm_node_id or to_id == dm_node_id:
                            self.load_messages()
                elif packet_channel == self.channel:
                    self.load_messages()
        elif event_type == "reaction_updated" and data:
            # Refresh to show updated reactions
            self.load_messages()

    def _render_message(self, entry: dict, track: bool = True):
        """Render a message entry in IRC format: [HH:MM] <shortName> message

        Wraps long messages with proper indentation so continuation lines
        align with the first character of the message text.

        Shows reply indicators and reactions below messages.

        Args:
            entry: The message entry dict containing packet and timestamp.
            track: If True, add entry to _displayed_entries for re-rendering.
        """
        if track:
            self._displayed_entries.append(entry)
        packet = entry['packet']
        timestamp = entry.get('timestamp', datetime.now().timestamp())
        time_str = datetime.fromtimestamp(timestamp).strftime('%H:%M')
        db_id = entry.get('_db_id')

        decoded = packet.get('decoded', {})
        message_text = decoded.get('text', '')

        if not message_text:
            return

        # Check if this is a TX packet (sent by us)
        is_tx = packet.get('_tx', False)

        # Get sender name
        if is_tx:
            # Get my node's name
            my_node = self.state.nodes.get_node(self.state.my_node_id)
            if my_node:
                user = my_node.get('user', {})
                sender_name = user.get('longName') or user.get('shortName') or "You"
            else:
                sender_name = "You"
            name_style = "bold bright_magenta"
        else:
            from_id = packet.get('from', packet.get('fromId'))
            sender_name = format_node_id(from_id) if from_id else "???"

            # Try to get short name from node store
            if from_id:
                node = self.state.nodes.get_node(from_id)
                if node:
                    user = node.get('user', {})
                    sender_name = user.get('shortName') or user.get('longName') or sender_name
            name_style = "bold bright_cyan"

        # Build prefix parts and calculate width for wrapping
        # Format: [S] [HH:MM] <Name> message
        # S = status (1 char) or hop count (1 digit usually)

        if is_tx:
            delivered = packet.get('_delivered')
            if delivered is None:
                status_str = "[…]"
                status_style = "dim"
            elif delivered:
                status_str = "[✓]"
                status_style = "bright_green"
            else:
                status_str = "[✗]"
                status_style = "bright_red"
        else:
            hop_start = packet.get('hopStart')
            hop_limit = packet.get('hopLimit')
            if hop_start is not None and hop_limit is not None:
                hops = hop_start - hop_limit
                status_str = f"[{hops}]"
                status_style = "bright_cyan"
            else:
                status_str = "[-]"
                status_style = "dim"

        # Calculate prefix widths for wrapping (use cell_len for unicode chars)
        # Base prefix: [S] + space + [HH:MM] + space (continuation lines align here, under <)
        base_prefix_width = cell_len(status_str) + 1 + 7 + 1
        # Full first-line prefix includes: < + name + > + space
        name_extra = 1 + cell_len(sender_name) + 2
        full_prefix_width = base_prefix_width + name_extra

        # Get available width (account for scrollbar and buffer)
        try:
            available_width = self.size.width - self.SCROLLBAR_WIDTH
            if available_width < 30:
                available_width = 78  # fallback if too small or not sized yet
        except Exception:
            available_width = 78  # fallback

        # First line has less space (includes <name> ), continuation lines have more
        first_line_width = available_width - full_prefix_width
        continuation_width = available_width - base_prefix_width
        if first_line_width < 20:
            first_line_width = 20
        if continuation_width < 20:
            continuation_width = 20

        # Check for reply indicator
        reply_ref = self._reply_refs_cache.get(db_id) if db_id else None
        reply_preview = None

        if reply_ref:
            reply_preview = self._get_reply_preview(reply_ref)

        # Wrap message text (first line narrower, continuation lines wider)
        wrapped_lines = self._wrap_text(message_text, continuation_width, first_line_width)

        # Build the first line with full prefix
        text = Text()
        text.append(status_str, style=status_style)
        text.append(" ")
        text.append(f"[{time_str}]", style=Colors.DIM)
        text.append(" <", style=Colors.DIM)
        text.append(sender_name, style=name_style)
        text.append("> ", style=Colors.DIM)

        # Add reply indicator if this is a reply (before message text)
        if reply_preview:
            text.append("↩ ", style="bright_yellow")
            text.append(reply_preview, style="dim italic")
            text.append(" ")

        # First line of message on same line as header
        if wrapped_lines:
            text.append(wrapped_lines[0], style=Colors.TEXT)

        self.write(text)

        # Write continuation lines with indentation (align under <)
        indent = " " * base_prefix_width
        for line in wrapped_lines[1:]:
            cont_text = Text()
            cont_text.append(indent)
            cont_text.append(line, style=Colors.TEXT)
            self.write(cont_text)

        # Show error reason for failed TX messages
        if is_tx and packet.get('_delivered') is False:
            error_reason = packet.get('_error_reason')
            if error_reason:
                error_text = Text()
                error_text.append(indent)
                error_text.append(f"Error: {error_reason}", style="dim bright_red")
                self.write(error_text)

        # Show reactions below message
        reactions = self._reactions_cache.get(db_id, []) if db_id else []
        if reactions:
            self._render_reactions(reactions, base_prefix_width)

    def _get_reply_preview(self, reply_ref: dict) -> str:
        """Get a preview string for a reply's parent message."""
        parent_db_id = reply_ref.get('parent_db_id')
        parent_packet_id = reply_ref.get('parent_packet_id')

        # Try to find the parent message
        if parent_db_id and self.storage:
            parent = self.storage.get_parent_message(parent_db_id)
            if parent:
                # Get parent sender name
                sender_name = parent.from_node
                node = self.state.nodes.get_node(parent.from_node)
                if node:
                    user = node.get('user', {})
                    sender_name = user.get('shortName') or user.get('longName') or sender_name

                # Get message preview (truncated)
                text = parent.payload.get('text', '')
                preview = text[:30] + '...' if len(text) > 30 else text
                return f"{sender_name}: \"{preview}\""

        return f"msg #{parent_packet_id}"

    def _render_reactions(self, reactions: List[dict], prefix_width: int):
        """Render reactions below a message."""
        if not reactions:
            return

        # Group reactions by emoji and count
        emoji_counts = Counter(r['emoji'] for r in reactions)

        # Build reactions line
        indent = " " * prefix_width
        react_text = Text()
        react_text.append(indent)

        first = True
        for emoji, count in emoji_counts.items():
            if not first:
                react_text.append(" ", style="dim")
            first = False
            react_text.append(emoji)
            if count > 1:
                react_text.append(f"×{count}", style="dim")

        self.write(react_text)

    def _wrap_text(self, text: str, width: int, first_line_width: int = None) -> list:
        """Wrap text to specified width, preserving words where possible.

        Uses cell_len for proper unicode/emoji width handling.

        Args:
            text: The text to wrap.
            width: Width for continuation lines.
            first_line_width: Width for the first line (defaults to width).
        """
        if width <= 0:
            return [text]

        if first_line_width is None:
            first_line_width = width

        words = text.split(' ')
        lines = []
        current_line = []
        current_len = 0

        def get_current_width():
            """Get width for current line (first line may be narrower)."""
            return first_line_width if len(lines) == 0 else width

        for word in words:
            word_len = cell_len(word)
            current_width = get_current_width()

            # If word itself is longer than current width, force break it
            if word_len > current_width:
                # Flush current line first
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = []
                    current_len = 0
                    current_width = get_current_width()

                # Break long word into chunks (by characters, checking cell width)
                chunk = ""
                chunk_len = 0
                for char in word:
                    char_len = cell_len(char)
                    if chunk_len + char_len > current_width:
                        lines.append(chunk)
                        chunk = char
                        chunk_len = char_len
                        current_width = get_current_width()
                    else:
                        chunk += char
                        chunk_len += char_len
                if chunk:
                    current_line = [chunk]
                    current_len = chunk_len
            elif current_len + (1 if current_line else 0) + word_len <= current_width:
                # Word fits on current line
                current_line.append(word)
                current_len += (1 if len(current_line) > 1 else 0) + word_len
            else:
                # Start new line
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_len = word_len

        # Don't forget the last line
        if current_line:
            lines.append(' '.join(current_line))

        return lines if lines else ['']

    def load_messages(self):
        """Load messages for the current channel or DM."""
        self.clear()
        self._oldest_id = None
        self._history_exhausted = False
        self._displayed_entries = []  # Clear entries
        self._reactions_cache = {}  # Clear reactions cache
        self._reply_refs_cache = {}  # Clear reply refs cache

        if self.dm_node_id:
            # DM mode: load messages to/from the DM node
            self._load_dm_messages()
        else:
            # Broadcast mode: load messages on the current channel
            self._load_channel_messages()

    def _load_channel_messages(self):
        """Load messages for a broadcast channel."""
        # On channel 0, only show broadcasts (to=^all), not DMs
        broadcast_only = (self.channel == 0)

        # Try to load from storage first
        if self.storage:
            messages = self.storage.get_text_messages(
                channel=self.channel,
                limit=self.HISTORY_PAGE_SIZE,
                broadcast_only=broadcast_only
            )
            if messages:
                # Batch load reactions and reply refs
                db_ids = [msg.id for msg in messages]
                self._reactions_cache = self.storage.get_reactions_for_messages(db_ids)
                self._reply_refs_cache = self.storage.get_reply_refs_for_messages(db_ids)

                for msg in messages:
                    entry = msg.to_entry()
                    self._render_message(entry)
                    if self._oldest_id is None or msg.id < self._oldest_id:
                        self._oldest_id = msg.id
                return

        # Fall back to in-memory buffer (or if storage was empty)
        messages = self.state.messages.get_text_messages(self.channel, broadcast_only=broadcast_only)
        for entry in messages[-100:]:
            self._render_message(entry)

    def _load_dm_messages(self):
        """Load DM messages to/from a specific node."""
        # Try to load from storage first
        if self.storage:
            messages = self.storage.get_messages_for_node(
                node_id=self.dm_node_id,
                limit=self.HISTORY_PAGE_SIZE,
                channel=0  # DMs are on channel 0
            )
            if messages:
                # Batch load reactions and reply refs
                db_ids = [msg.id for msg in messages]
                self._reactions_cache = self.storage.get_reactions_for_messages(db_ids)
                self._reply_refs_cache = self.storage.get_reply_refs_for_messages(db_ids)

                for msg in messages:
                    entry = msg.to_entry()
                    self._render_message(entry)
                    if self._oldest_id is None or msg.id < self._oldest_id:
                        self._oldest_id = msg.id
                return

        # Fall back to in-memory buffer (or if storage was empty)
        messages = self.state.messages.get_text_messages_for_node(self.dm_node_id, channel=0)
        for entry in messages[-100:]:
            self._render_message(entry)

    def _load_more_history(self):
        """Load older messages from storage."""
        if not self.storage or self._history_exhausted or self._loading_history:
            return

        self._loading_history = True

        if self.dm_node_id:
            # DM mode: load more DM messages
            messages = self.storage.get_messages_for_node(
                node_id=self.dm_node_id,
                limit=self.HISTORY_PAGE_SIZE,
                before_id=self._oldest_id,
                channel=0  # DMs are on channel 0
            )
        else:
            # Broadcast mode: load more channel messages
            # On channel 0, only show broadcasts (to=^all), not DMs
            broadcast_only = (self.channel == 0)
            messages = self.storage.get_text_messages(
                channel=self.channel,
                limit=self.HISTORY_PAGE_SIZE,
                before_id=self._oldest_id,
                broadcast_only=broadcast_only
            )

        if not messages:
            self._history_exhausted = True
            self._loading_history = False
            self.app.bell()
            return

        # Convert to entries and prepend to our list
        new_entries = []
        new_db_ids = []
        for msg in messages:
            if self._oldest_id is None or msg.id < self._oldest_id:
                self._oldest_id = msg.id
            new_entries.append(msg.to_entry())
            new_db_ids.append(msg.id)

        # Load reactions and reply refs for new entries
        new_reactions = self.storage.get_reactions_for_messages(new_db_ids)
        new_reply_refs = self.storage.get_reply_refs_for_messages(new_db_ids)
        self._reactions_cache.update(new_reactions)
        self._reply_refs_cache.update(new_reply_refs)

        # Prepend new entries and re-render all from data
        self._displayed_entries = new_entries + self._displayed_entries

        scroll_y = self.scroll_y
        self.clear()

        for entry in self._displayed_entries:
            self._render_message(entry, track=False)

        # Adjust scroll position (approximate lines added based on new entries)
        new_line_count = len(new_entries) * 2  # Approximate: each message ~2 lines
        self.scroll_y = scroll_y + new_line_count

        self._loading_history = False

    def action_page_up(self):
        """Handle Page Up to load more history when at top."""
        if self.scroll_y <= 0 and self.storage and not self._history_exhausted:
            self._load_more_history()
        else:
            super().action_page_up()

    def set_channel(self, channel: int):
        """Set the channel and reload messages (broadcast mode)."""
        self.dm_node_id = None  # Exit DM mode
        self.channel = channel
        self.load_messages()

    def set_dm_mode(self, node_id: str):
        """Set DM mode for a specific node and reload messages."""
        self.dm_node_id = node_id
        self.load_messages()

    def on_unmount(self):
        """Cleanup subscriptions."""
        self.state.messages.unsubscribe(self._handle_packet_event)

    # Selection mode methods

    def enter_selection_mode(self, mode: str):
        """Enter selection mode for react or reply.

        Args:
            mode: "react" or "reply"
        """
        if not self._displayed_entries:
            self.app.bell()
            return

        self.selection_mode = mode
        self.selected_index = len(self._displayed_entries) - 1  # Start at most recent
        self.selection_active = True
        self.can_focus = True
        self.focus()  # Take focus so key bindings work
        self._refresh_with_selection()

    def exit_selection_mode(self):
        """Exit selection mode."""
        self.selection_active = False
        self.selection_mode = ""
        self.can_focus = False
        self.load_messages()  # Re-render without selection highlighting

    def _refresh_with_selection(self, scroll_to_selected: bool = True):
        """Re-render messages with selection highlighting."""
        self.clear()
        for i, entry in enumerate(self._displayed_entries):
            self._render_message_with_index(entry, i, track=False)

        if scroll_to_selected:
            # Scroll to show selected message
            # Estimate ~2 lines per message (header + content, sometimes reactions)
            lines_per_msg = 2
            approx_line = self.selected_index * lines_per_msg

            # Get visible height
            try:
                visible_height = self.size.height - 2  # Account for borders
            except Exception:
                visible_height = 20

            # Keep selected item in view with some context
            if approx_line < self.scroll_y:
                # Selected is above visible area - scroll up
                self.scroll_y = max(0, approx_line - 2)
            elif approx_line >= self.scroll_y + visible_height:
                # Selected is below visible area - scroll down
                self.scroll_y = approx_line - visible_height + 4

    def _render_message_with_index(self, entry: dict, index: int, track: bool = False):
        """Render a message with index number and optional selection highlight."""
        packet = entry['packet']
        timestamp = entry.get('timestamp', datetime.now().timestamp())
        time_str = datetime.fromtimestamp(timestamp).strftime('%H:%M')
        db_id = entry.get('_db_id')

        decoded = packet.get('decoded', {})
        message_text = decoded.get('text', '')

        if not message_text:
            return

        is_selected = self.selection_active and index == self.selected_index
        is_tx = packet.get('_tx', False)

        # Get sender name
        if is_tx:
            my_node = self.state.nodes.get_node(self.state.my_node_id)
            if my_node:
                user = my_node.get('user', {})
                sender_name = user.get('longName') or user.get('shortName') or "You"
            else:
                sender_name = "You"
            name_style = "bold bright_magenta"
        else:
            from_id = packet.get('from', packet.get('fromId'))
            sender_name = format_node_id(from_id) if from_id else "???"
            if from_id:
                node = self.state.nodes.get_node(from_id)
                if node:
                    user = node.get('user', {})
                    sender_name = user.get('shortName') or user.get('longName') or sender_name
            name_style = "bold bright_cyan"

        # Build prefix parts
        if is_tx:
            delivered = packet.get('_delivered')
            if delivered is None:
                status_str = "[…]"
                status_style = "dim"
            elif delivered:
                status_str = "[✓]"
                status_style = "bright_green"
            else:
                status_str = "[✗]"
                status_style = "bright_red"
        else:
            hop_start = packet.get('hopStart')
            hop_limit = packet.get('hopLimit')
            if hop_start is not None and hop_limit is not None:
                hops = hop_start - hop_limit
                status_str = f"[{hops}]"
                status_style = "bright_cyan"
            else:
                status_str = "[-]"
                status_style = "dim"

        # In selection mode, show line numbers
        display_num = index + 1
        if self.selection_active:
            num_str = f"[{display_num}]"
            num_width = len(num_str)
        else:
            num_str = ""
            num_width = 0

        # Calculate prefix widths for wrapping
        # Base prefix: [num] + space (if selection) + [S] + space + [HH:MM] + space
        base_prefix_width = cell_len(status_str) + 1 + 7 + 1
        if self.selection_active:
            base_prefix_width += num_width + 1
        # Full first-line prefix includes: < + name + > + space
        name_extra = 1 + cell_len(sender_name) + 2
        full_prefix_width = base_prefix_width + name_extra

        # Get available width
        try:
            available_width = self.size.width - self.SCROLLBAR_WIDTH
            if available_width < 30:
                available_width = 78
        except Exception:
            available_width = 78

        # First line has less space (includes <name> ), continuation lines have more
        first_line_width = available_width - full_prefix_width
        continuation_width = available_width - base_prefix_width
        if first_line_width < 20:
            first_line_width = 20
        if continuation_width < 20:
            continuation_width = 20

        # Check for reply indicator
        reply_ref = self._reply_refs_cache.get(db_id) if db_id else None
        reply_preview = None
        if reply_ref:
            reply_preview = self._get_reply_preview(reply_ref)

        # Build the first line
        text = Text()

        # Selection indicator and number
        if self.selection_active:
            if is_selected:
                text.append(num_str, style="bold reverse bright_yellow")
            else:
                text.append(num_str, style="dim")
            text.append(" ")

        text.append(status_str, style=status_style)
        text.append(" ")
        text.append(f"[{time_str}]", style=Colors.DIM)
        text.append(" <", style=Colors.DIM)
        text.append(sender_name, style=name_style)
        text.append("> ", style=Colors.DIM)

        # Add reply indicator
        if reply_preview:
            text.append("↩ ", style="bright_yellow")
            text.append(reply_preview, style="dim italic")
            text.append(" ")

        # Wrap message text (first line narrower, continuation lines wider)
        wrapped_lines = self._wrap_text(message_text, continuation_width, first_line_width)
        line_style = "reverse" if is_selected else Colors.TEXT

        # First line of message on same line as header
        if wrapped_lines:
            text.append(wrapped_lines[0], style=line_style)

        self.write(text)

        # Write continuation lines with indentation (align under <)
        indent = " " * base_prefix_width
        for line in wrapped_lines[1:]:
            msg_text = Text()
            msg_text.append(indent)
            msg_text.append(line, style=line_style)
            self.write(msg_text)

        # Show error reason
        if is_tx and packet.get('_delivered') is False:
            error_reason = packet.get('_error_reason')
            if error_reason:
                error_text = Text()
                error_text.append(indent)
                error_text.append(f"Error: {error_reason}", style="dim bright_red")
                self.write(error_text)

        # Show reactions
        reactions = self._reactions_cache.get(db_id, []) if db_id else []
        if reactions:
            self._render_reactions(reactions, base_prefix_width)

    def action_select_next(self):
        """Select the next (newer) message."""
        if not self.selection_active:
            return
        if self.selected_index < len(self._displayed_entries) - 1:
            self.selected_index += 1
            self._refresh_with_selection()

    def action_select_prev(self):
        """Select the previous (older) message."""
        if not self.selection_active:
            return
        if self.selected_index > 0:
            self.selected_index -= 1
            self._refresh_with_selection()

    def action_select_by_number(self, num: str):
        """Select a message by its display number."""
        if not self.selection_active:
            return
        try:
            index = int(num) - 1  # Convert to 0-based index
            if 0 <= index < len(self._displayed_entries):
                self.selected_index = index
                self._refresh_with_selection()
        except ValueError:
            pass

    def action_confirm_selection(self):
        """Confirm the current selection."""
        if not self.selection_active:
            return
        if 0 <= self.selected_index < len(self._displayed_entries):
            entry = self._displayed_entries[self.selected_index]
            mode = self.selection_mode
            self.exit_selection_mode()
            self.post_message(self.MessageSelected(entry, mode))

    def action_cancel_selection(self):
        """Cancel selection mode."""
        if not self.selection_active:
            return
        self.exit_selection_mode()
        self.post_message(self.SelectionCancelled())

    def get_selected_entry(self) -> Optional[dict]:
        """Get the currently selected entry, if any."""
        if self.selection_active and 0 <= self.selected_index < len(self._displayed_entries):
            return self._displayed_entries[self.selected_index]
        return None

    def on_key(self, event) -> None:
        """Handle key events during selection mode."""
        if not self.selection_active:
            return

        key = event.key
        if key in ("j", "down"):
            self.action_select_next()
            event.prevent_default()
            event.stop()
        elif key in ("k", "up"):
            self.action_select_prev()
            event.prevent_default()
            event.stop()
        elif key == "enter":
            self.action_confirm_selection()
            event.prevent_default()
            event.stop()
        elif key == "escape":
            self.action_cancel_selection()
            event.prevent_default()
            event.stop()
        elif key.isdigit() and key != "0":
            self.action_select_by_number(key)
            event.prevent_default()
            event.stop()
