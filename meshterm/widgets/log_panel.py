"""Scrollable log panel widget."""

from typing import Optional, TYPE_CHECKING
from textual.widgets import RichLog
from textual.reactive import reactive
from rich.text import Text

from ..state import AppState
from ..formatting import format_packet, format_payload, format_verbose, pretty_print_json, Colors, format_node_id

if TYPE_CHECKING:
    from ..storage import LogStorage


class LogPanel(RichLog):
    """Scrollable panel showing packet log."""

    HISTORY_PAGE_SIZE = 50

    def __init__(self, state: AppState, **kwargs):
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)
        self.state = state
        self._oldest_id: Optional[int] = None
        self._history_exhausted = False
        self._loading_history = False

        # Subscribe to message updates
        self.state.messages.subscribe(self._handle_packet_event)

    @property
    def storage(self) -> "Optional[LogStorage]":
        """Get storage from state."""
        return self.state.storage

    def _handle_packet_event(self, event_type: str, data):
        """Handle new message."""
        if event_type == "message_added" and data:
            self._render_message(data)

    def _render_message(self, entry: dict):
        """Render a message entry to the log."""
        packet = entry['packet']

        # Check if this is a TX packet (sent by us)
        is_tx = packet.get('_tx', False)

        # Check if this is from a favorited node
        from_id = packet.get('from', packet.get('fromId'))
        from_id_str = format_node_id(from_id) if from_id else None
        is_favorite = (
            self.state.settings.favorites_highlight
            and from_id_str
            and self.state.nodes.is_favorite(from_id_str)
        )

        # Ring bell for favorited node activity when highlighting is enabled
        if is_favorite:
            self.app.bell()

        # Main packet line
        header = format_packet(packet, self.state.nodes)

        # Add TX indicator or favorite highlight
        if is_tx:
            tx_header = Text()
            tx_header.append("[TX] ", style="bold bright_magenta")
            tx_header.append_text(header)
            header = tx_header
        elif is_favorite:
            fav_header = Text()
            fav_header.append("[★] ", style="bold bright_yellow")
            fav_header.append_text(header)
            header = fav_header

        self.write(header)

        # Payload details
        payload = format_payload(packet, self.state.nodes)
        if payload.plain:
            self.write(payload)

        # Verbose output
        if self.state.settings.verbose:
            verbose = format_verbose(packet)
            if verbose.plain:
                self.write(verbose)

            # Pretty print raw packet
            raw_header = Text()
            raw_header.append("  ", style="default")
            raw_header.append("--- raw packet ---", style=Colors.DIM)
            self.write(raw_header)

            json_text = Text("  ", style="default")
            json_text.append_text(pretty_print_json(packet, indent=1))
            self.write(json_text)

    def load_history(self, count: int = 100):
        """Load recent message history."""
        self._oldest_id = None
        self._history_exhausted = False

        # Try to load from storage first
        if self.storage:
            messages = self.storage.get_all_packets(limit=self.HISTORY_PAGE_SIZE)
            if messages:
                for msg in messages:
                    entry = msg.to_entry()
                    self._render_message(entry)
                    if self._oldest_id is None or msg.id < self._oldest_id:
                        self._oldest_id = msg.id
                return

        # Fall back to in-memory buffer (or if storage was empty)
        messages = self.state.messages.get_recent(count)
        for entry in messages:
            self._render_message(entry)

    def _load_more_history(self):
        """Load older messages from storage."""
        if not self.storage or self._history_exhausted or self._loading_history:
            return

        self._loading_history = True

        messages = self.storage.get_all_packets(
            limit=self.HISTORY_PAGE_SIZE,
            before_id=self._oldest_id
        )

        if not messages:
            self._history_exhausted = True
            self._loading_history = False
            self.app.bell()
            return

        # Get current scroll position
        scroll_y = self.scroll_y

        # Prepend messages (render at top)
        lines_to_add = []
        for msg in messages:
            if self._oldest_id is None or msg.id < self._oldest_id:
                self._oldest_id = msg.id
            lines_to_add.append(msg.to_entry())

        # Clear and re-render with new messages at top
        old_lines = list(self.lines)
        self.clear()

        for entry in lines_to_add:
            self._render_message(entry)
        new_line_count = len(self.lines)

        for line in old_lines:
            self.write(line)

        # Adjust scroll to maintain position
        self.scroll_y = scroll_y + new_line_count

        self._loading_history = False

    def action_page_up(self):
        """Handle Page Up to load more history when at top."""
        if self.scroll_y <= 0 and self.storage and not self._history_exhausted:
            self._load_more_history()
        else:
            super().action_page_up()

    def on_unmount(self):
        """Cleanup subscriptions."""
        self.state.messages.unsubscribe(self._handle_packet_event)
