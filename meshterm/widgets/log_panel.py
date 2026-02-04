"""Scrollable log panel widget."""

from typing import Optional, TYPE_CHECKING
from textual.widgets import RichLog
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text

from ..state import AppState
from ..formatting import format_packet, format_payload, format_verbose, pretty_print_json, Colors, format_node_id

if TYPE_CHECKING:
    from ..storage import LogStorage


class LogPanel(RichLog):

    class HistoryLoaded(Message):
        """Posted when history loading completes."""
        pass
    """Scrollable panel showing packet log."""

    HISTORY_PAGE_SIZE = 50

    def __init__(self, state: AppState, **kwargs):
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)
        self.state = state
        self._oldest_id: Optional[int] = None
        self._history_exhausted = False
        self._loading_history = False

        # Search state
        self._displayed_entries: list = []
        self._search_term: str = ""
        self._match_entries: list = []
        self._filter_active: bool = False

        # Database search state
        self._total_db_matches: Optional[int] = None
        self._oldest_match_id: Optional[int] = None
        self._search_exhausted: bool = False

        # Subscribe to message updates
        self.state.messages.subscribe(self._handle_packet_event)

        # Subscribe to settings changes
        self.state.settings.subscribe(self._handle_settings_change)

    @property
    def storage(self) -> "Optional[LogStorage]":
        """Get storage from state."""
        return self.state.storage

    def _handle_packet_event(self, event_type: str, data):
        """Handle new message."""
        if event_type == "message_added" and data:
            self._render_message(data)

    def _handle_settings_change(self, event_type: str, setting: str):
        """Handle settings changes."""
        if setting == "verbose":
            if self._filter_active:
                self._rerender_filtered()
            else:
                self._rerender_all_entries()

    def _render_message(self, entry: dict):
        """Render a message entry to the log."""
        # Track entry for search functionality
        self._displayed_entries.append(entry)

        # Check if user is at bottom before adding content
        should_scroll = self.is_vertical_scroll_end

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

        self.write(header, scroll_end=should_scroll)

        # Payload details
        payload = format_payload(packet, self.state.nodes)
        if payload.plain:
            self.write(payload, scroll_end=should_scroll)

        # Verbose output
        if self.state.settings.verbose:
            verbose = format_verbose(packet)
            if verbose.plain:
                self.write(verbose, scroll_end=should_scroll)

            # Pretty print raw packet
            raw_header = Text()
            raw_header.append("  ", style="default")
            raw_header.append("--- raw packet ---", style=Colors.DIM)
            self.write(raw_header, scroll_end=should_scroll)

            json_text = Text("  ", style="default")
            json_text.append_text(pretty_print_json(packet, indent=1))
            self.write(json_text, scroll_end=should_scroll)

    def load_history(self, count: int = 100):
        """Load recent message history."""
        self._oldest_id = None
        self._history_exhausted = False
        self._displayed_entries = []  # Clear tracked entries

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
            self.post_message(self.HistoryLoaded())
            self.app.bell()
            return

        # Capture scroll state before modifying content
        old_scroll_y = self.scroll_y
        old_virtual_height = self.virtual_size.height

        # Convert to entries and update oldest_id
        new_entries = []
        for msg in messages:
            if self._oldest_id is None or msg.id < self._oldest_id:
                self._oldest_id = msg.id
            new_entries.append(msg.to_entry())

        # Prepend new entries to displayed_entries (they're older)
        self._displayed_entries = new_entries + self._displayed_entries

        # Clear and re-render all entries
        self.clear()
        for entry in self._displayed_entries:
            self._render_message_raw(entry)

        # Adjust scroll after layout refresh to maintain position
        def finish_loading():
            new_virtual_height = self.virtual_size.height
            added_height = new_virtual_height - old_virtual_height
            self.scroll_y = old_scroll_y + added_height
            self._loading_history = False
            self.post_message(self.HistoryLoaded())

        self.call_after_refresh(finish_loading)

    def action_page_up(self):
        """Handle Page Up to load more history when at top."""
        if self.scroll_y <= 0 and self.storage and not self._history_exhausted:
            self._load_more_history()
        else:
            super().action_page_up()

    def get_loaded_count(self) -> int:
        """Get the number of currently loaded entries."""
        return len(self._displayed_entries)

    def get_total_count(self) -> Optional[int]:
        """Get total message count from database."""
        if self.storage:
            return self.storage.get_stats().get('messages', 0)
        return None

    def is_history_exhausted(self) -> bool:
        """Check if all history has been loaded."""
        return self._history_exhausted

    def get_total_db_matches(self) -> Optional[int]:
        """Get total database match count for current search."""
        return self._total_db_matches

    def search(self, term: str) -> int:
        """Search and filter log to show only matches.

        When storage is available, searches the entire database.
        Otherwise, falls back to searching only loaded entries.
        """
        self._search_term = term.lower() if term else ""
        self._match_entries = []
        self._total_db_matches = None
        self._oldest_match_id = None
        self._search_exhausted = False

        if not self._search_term:
            if self._filter_active:
                self._filter_active = False
                self._rerender_all_entries()
            return 0

        if self.storage:
            # Database search
            self._total_db_matches = self.storage.count_search_results(term)
            messages = self.storage.search_packets(term, limit=self.HISTORY_PAGE_SIZE)

            self._match_entries = [msg.to_entry() for msg in messages]
            self._oldest_match_id = min((m.id for m in messages), default=None)
            self._search_exhausted = len(messages) < self.HISTORY_PAGE_SIZE

            self._filter_active = True
            self._rerender_filtered()
            return self._total_db_matches
        else:
            # In-memory fallback
            for entry in self._displayed_entries:
                if self._entry_matches(entry, self._search_term):
                    self._match_entries.append(entry)

            self._filter_active = True
            self._rerender_filtered()
            return len(self._match_entries)

    def _entry_matches(self, entry: dict, term: str) -> bool:
        """Check if an entry matches the search term (case-insensitive).

        Only searches human-readable fields:
        - Node names (shortName/longName) for from/to nodes
        - Text message content
        """
        packet = entry.get('packet', {})
        decoded = packet.get('decoded', {})

        # Search in node names via NodeStore (from node)
        from_id = packet.get('from', packet.get('fromId', ''))
        from_name = ""
        if from_id:
            node = self.state.nodes.get_node(from_id)
            if node:
                user = node.get('user', {})
                from_name = f"{user.get('shortName', '')} {user.get('longName', '')}"

        # Search in node names via NodeStore (to node)
        to_id = packet.get('to', packet.get('toId', ''))
        to_name = ""
        if to_id:
            node = self.state.nodes.get_node(to_id)
            if node:
                user = node.get('user', {})
                to_name = f"{user.get('shortName', '')} {user.get('longName', '')}"

        # Search in text content (only for text messages)
        text = decoded.get('text', '')

        # Build searchable string (all lowercase for case-insensitive search)
        searchable = f"{from_name} {to_name} {text}".lower()

        return term in searchable

    def clear_search(self):
        """Clear search and restore full log."""
        self._search_term = ""
        self._match_entries = []
        self._total_db_matches = None
        self._oldest_match_id = None
        self._search_exhausted = False
        if self._filter_active:
            self._filter_active = False
            self._rerender_all_entries()

    def load_more_search_results(self) -> bool:
        """Load more search results from the database.

        Returns:
            True if more results were loaded, False otherwise
        """
        if not self.storage or self._search_exhausted or not self._search_term:
            return False

        messages = self.storage.search_packets(
            self._search_term,
            limit=self.HISTORY_PAGE_SIZE,
            before_id=self._oldest_match_id
        )

        if not messages:
            self._search_exhausted = True
            return False

        for msg in messages:
            self._match_entries.append(msg.to_entry())

        self._oldest_match_id = min(m.id for m in messages)
        self._search_exhausted = len(messages) < self.HISTORY_PAGE_SIZE
        self._rerender_filtered()
        return True

    def _rerender_filtered(self):
        """Re-render log showing only matching entries."""
        self.clear()
        for entry in self._match_entries:
            self._render_message_raw(entry)

    def _rerender_all_entries(self):
        """Re-render all entries (restore from filter mode)."""
        self.clear()
        for entry in self._displayed_entries:
            self._render_message_raw(entry)

    def _render_message_raw(self, entry: dict, scroll_end: bool = False):
        """Render a message entry without tracking (for re-render)."""
        packet = entry['packet']

        is_tx = packet.get('_tx', False)

        from_id = packet.get('from', packet.get('fromId'))
        from_id_str = format_node_id(from_id) if from_id else None
        is_favorite = (
            self.state.settings.favorites_highlight
            and from_id_str
            and self.state.nodes.is_favorite(from_id_str)
        )

        header = format_packet(packet, self.state.nodes)

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

        self.write(header, scroll_end=scroll_end)

        payload = format_payload(packet, self.state.nodes)
        if payload.plain:
            self.write(payload, scroll_end=scroll_end)

        if self.state.settings.verbose:
            verbose = format_verbose(packet)
            if verbose.plain:
                self.write(verbose, scroll_end=scroll_end)

            raw_header = Text()
            raw_header.append("  ", style="default")
            raw_header.append("--- raw packet ---", style=Colors.DIM)
            self.write(raw_header, scroll_end=scroll_end)

            json_text = Text("  ", style="default")
            json_text.append_text(pretty_print_json(packet, indent=1))
            self.write(json_text, scroll_end=scroll_end)

    def get_match_count(self) -> int:
        """Get current number of matches."""
        return len(self._match_entries)

    def on_unmount(self):
        """Cleanup subscriptions."""
        self.state.messages.unsubscribe(self._handle_packet_event)
        self.state.settings.unsubscribe(self._handle_settings_change)
