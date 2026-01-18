"""Sortable node table widget."""

import time
from textual.widgets import DataTable
from textual.message import Message
from textual.binding import Binding
from rich.text import Text
from rich.cells import cell_len

from ..state import AppState
from ..formatting import (
    format_time_ago, Colors, haversine_distance, format_distance, get_node_position
)


class NodeTable(DataTable):
    """Table showing all known nodes with live updates."""

    DEFAULT_CSS = """
    NodeTable > .datatable--header {
        padding: 0 0 0 1;
    }
    NodeTable .datatable--row-cell {
        padding: 0 0 0 1;
    }
    """

    BINDINGS = [
        Binding("f", "request_favorite", "Favorite", show=False),
        Binding("i", "request_invite", "Invite", show=False),
    ]

    class FavoriteRequested(Message):
        """Posted when user presses 'f' to toggle favorite."""
        def __init__(self, node_id: str):
            self.node_id = node_id
            super().__init__()

    class InviteRequested(Message):
        """Posted when user presses 'i' to invite to channel."""
        def __init__(self, node_id: str):
            self.node_id = node_id
            super().__init__()

    COLUMNS = [
        ("On?", 4),
        ("Key", 4),
        ("Name", 16),
        ("Short", 6),
        ("Hardware", 14),
        ("Hops", 5),
        ("Dist", 8),
        ("SNR", 7),
        ("RSSI", 6),
        ("Bat", 5),
        ("Seen", 6),
    ]

    # Consider "online" if heard within 15 minutes
    ONLINE_THRESHOLD = 900

    # Sort key functions - each returns a sortable value for the column
    # t = current time threshold for online check
    SORT_KEYS = {
        "on?": lambda n, t, my_pos: (n.get('lastHeard', 0) or 0) > t - 900,
        "key": lambda n, t, my_pos: 1 if n.get('has_public_key') or bool(n.get('user', {}).get('publicKey')) else 0,
        "name": lambda n, t, my_pos: str(n.get('user', {}).get('longName') or '').lower(),
        "short": lambda n, t, my_pos: str(n.get('user', {}).get('shortName') or '').lower(),
        "hardware": lambda n, t, my_pos: str(n.get('user', {}).get('hwModel') or '').lower(),
        "dist": lambda n, t, my_pos: NodeTable._calc_distance(n, my_pos),
        "hops": lambda n, t, my_pos: n.get('hops') or n.get('hopsAway') or 999,
        "snr": lambda n, t, my_pos: n.get('snr') if n.get('snr') is not None else -999,
        "rssi": lambda n, t, my_pos: n.get('rssi') if n.get('rssi') is not None else -999,
        "bat": lambda n, t, my_pos: n.get('deviceMetrics', {}).get('batteryLevel', -1),
        "seen": lambda n, t, my_pos: n.get('lastHeard', 0) or 0,
    }

    @staticmethod
    def _calc_distance(node: dict, my_pos: tuple | None) -> float:
        """Calculate distance from my node to given node."""
        if not my_pos:
            return float('inf')
        node_pos = get_node_position(node)
        if not node_pos:
            return float('inf')
        return haversine_distance(my_pos[0], my_pos[1], node_pos[0], node_pos[1])

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.can_focus = True
        self._filter = ""
        self._sort_column_idx = 0  # Index into COLUMNS, default "On?"
        self._sort_ascending = False  # Default descending (online/recent first)

        # Subscribe to node updates
        self.state.nodes.subscribe(self._handle_node_event)

    def on_mount(self):
        """Setup table when mounted."""
        # Add columns
        for name, width in self.COLUMNS:
            self.add_column(name, width=width, key=name.lower().replace(" ", "_"))

        # Show initial sort indicator
        self._update_column_headers()

        # Load existing nodes
        self._refresh_all()
        # Focus the table for keyboard navigation
        self.focus()

    def _handle_node_event(self, event_type: str, data):
        """Handle node updates."""
        if event_type in ("node_updated", "nodes_imported"):
            self.call_later(self._refresh_all)

    def set_filter(self, filter_text: str):
        """Set the filter text and refresh the table."""
        self._filter = filter_text.lower()
        self._refresh_all()

    def cycle_sort_column(self, direction: int):
        """Cycle to next/previous sort column.

        Args:
            direction: 1 for next column, -1 for previous column
        """
        num_cols = len(self.COLUMNS)
        self._sort_column_idx = (self._sort_column_idx + direction) % num_cols
        self._update_column_headers()
        self._refresh_all()
        self._scroll_sort_column_into_view()

    def toggle_sort_direction(self):
        """Toggle between ascending and descending sort order."""
        self._sort_ascending = not self._sort_ascending
        self._update_column_headers()
        self._refresh_all()

    def _update_column_headers(self):
        """Update column headers to show sort indicator on current column."""
        if not self.ordered_columns:
            return  # Columns not yet added
        indicator = "▲" if self._sort_ascending else "▼"
        for idx, col in enumerate(self.ordered_columns):
            if idx >= len(self.COLUMNS):
                break
            name = self.COLUMNS[idx][0]
            if idx == self._sort_column_idx:
                col.label = Text(f"{name}{indicator}")
            else:
                col.label = Text(name)

    def _matches_filter(self, node_id: str, node: dict) -> bool:
        """Check if a node matches the current filter."""
        if not self._filter:
            return True

        user = node.get('user', {})
        searchable = [
            node_id.lower(),
            user.get('longName', '').lower(),
            user.get('shortName', '').lower(),
            str(user.get('hwModel', '')).lower(),
        ]
        return any(self._filter in s for s in searchable)

    def _scroll_sort_column_into_view(self):
        """Scroll the current sort column into view."""
        if not self.ordered_columns or self._sort_column_idx >= len(self.ordered_columns):
            return
        try:
            region = self._get_column_region(self._sort_column_idx)
            self.scroll_to_region(region, animate=False)
        except Exception:
            pass  # Ignore scroll errors

    def _refresh_all(self):
        """Refresh all rows while preserving scroll and cursor position."""
        # Save scroll position before clearing
        saved_scroll_x = self.scroll_x
        saved_scroll_y = self.scroll_y

        # Save cursor position by node ID (not by index)
        saved_cursor_node_id = None
        if self.cursor_row is not None and self.row_count > 0:
            try:
                row_key = self.coordinate_to_cell_key((self.cursor_row, 0)).row_key
                saved_cursor_node_id = row_key.value
            except Exception:
                pass

        self.clear()

        nodes = self.state.nodes.get_all_nodes()
        my_node_id = self.state.my_node_id
        my_pos = self.state.my_position
        current_time = int(time.time())

        # Get the sort key function for current column
        col_name = self.COLUMNS[self._sort_column_idx][0].lower().replace(" ", "_")
        sort_func = self.SORT_KEYS.get(col_name)

        def sort_key(item):
            node_id, node = item
            # Own node always first (is_me = 0 means first when sorted)
            is_me = 0 if node_id == my_node_id else 1
            if sort_func:
                sort_val = sort_func(node, current_time, my_pos)
            else:
                sort_val = 0
            return (is_me, sort_val)

        sorted_nodes = sorted(nodes.items(), key=sort_key, reverse=not self._sort_ascending)

        # But we need own node always at top, so re-sort with own node priority
        # Since reverse affects everything, we handle it differently:
        # Sort others by column, then prepend own node
        own_node = None
        other_nodes = []
        for node_id, node in nodes.items():
            if node_id == my_node_id:
                own_node = (node_id, node)
            else:
                other_nodes.append((node_id, node))

        # Sort other nodes by current column
        if sort_func:
            other_nodes.sort(
                key=lambda item: sort_func(item[1], current_time, my_pos),
                reverse=not self._sort_ascending
            )

        # Build final list with own node first
        sorted_nodes = []
        if own_node:
            sorted_nodes.append(own_node)
        sorted_nodes.extend(other_nodes)

        for node_id, node in sorted_nodes:
            if self._matches_filter(node_id, node):
                self._add_node_row(node_id, node)

        # Restore scroll position after refresh
        self.scroll_x = saved_scroll_x
        self.scroll_y = saved_scroll_y

        # Restore cursor position by finding the same node ID
        if saved_cursor_node_id and self.row_count > 0:
            for idx, row_key in enumerate(self.rows.keys()):
                if row_key.value == saved_cursor_node_id:
                    self.move_cursor(row=idx)
                    break

    def _add_node_row(self, node_id: str, node: dict):
        """Add a row for a node."""
        user = node.get('user', {})
        metrics = node.get('deviceMetrics', {})
        last_heard = node.get('lastHeard')

        # Determine online status
        is_online = False
        if last_heard:
            ago = int(time.time()) - last_heard
            is_online = ago < self.ONLINE_THRESHOLD

        # Determine row style based on recency
        style = self._get_recency_style(last_heard)

        # Build row data
        name = user.get('longName', node_id)

        # Check if own node or favorite
        is_me = node_id == self.state.my_node_id
        is_favorite = node.get('is_favorite', False)
        short = user.get('shortName', '')
        hw = str(user.get('hwModel', ''))
        hops = node.get('hops') or node.get('hopsAway')
        snr = node.get('snr')
        rssi = node.get('rssi')
        battery = metrics.get('batteryLevel', node.get('batteryLevel'))

        # Online indicator
        if is_online:
            online_text = Text("[x]", style="bright_green bold")
        else:
            online_text = Text("[ ]", style=Colors.DIM)

        # PKI status
        has_key = node.get('has_public_key', False)
        if not has_key:
            has_key = bool(user.get('publicKey'))
        if has_key:
            pki_text = Text("[*]", style="bright_green")
        else:
            pki_text = Text("[ ]", style=Colors.DIM)

        # Build name text with proper cell width handling for prefixes
        name_col_width = 16  # From COLUMNS
        if is_me:
            prefix = "@ "
            prefix_style = style
        elif is_favorite:
            prefix = "★ "
            prefix_style = "bright_yellow bold"
        else:
            prefix = ""
            prefix_style = None

        if prefix:
            prefix_width = cell_len(prefix)
            name_text = Text()
            name_text.append(prefix, style=prefix_style)
            rest = Text(name, style=style)
            rest.truncate(name_col_width - prefix_width)
            name_text.append(rest)
        else:
            name_text = Text(name, style=style)
            name_text.truncate(name_col_width)

        # Truncate short name and hardware with cell-aware truncation
        short_text = Text(short or '', style=style)
        short_text.truncate(6)
        hw_text = Text(hw or '', style=Colors.DIM)
        hw_text.truncate(14)

        # Calculate distance from my node
        dist_str = ''
        my_pos = self.state.my_position
        node_pos = get_node_position(node)
        if my_pos and node_pos:
            dist_km = haversine_distance(my_pos[0], my_pos[1], node_pos[0], node_pos[1])
            dist_str = format_distance(dist_km, short=True)

        row = [
            online_text,
            pki_text,
            name_text,
            short_text,
            hw_text,
            Text(str(hops) if hops is not None else '', style="bright_cyan" if hops else Colors.DIM),
            Text(dist_str, style="bright_blue" if dist_str else Colors.DIM),
            Text(f"{snr:.1f}" if snr is not None else '', style=Colors.SNR if snr else Colors.DIM),
            Text(str(rssi) if rssi is not None else '', style=Colors.RSSI if rssi else Colors.DIM),
            Text(f"{battery}%" if battery is not None else '', style=self._get_battery_style(battery)),
            Text(format_time_ago(last_heard), style=style),
        ]

        self.add_row(*row, key=node_id)

    def _get_recency_style(self, last_heard) -> str:
        """Get style based on how recently node was seen."""
        if not last_heard:
            return Colors.DIM

        ago = int(time.time()) - last_heard

        if ago < 60:  # Less than 1 minute
            return "bright_green bold"
        if ago < 300:  # Less than 5 minutes
            return "bright_green"
        if ago < 900:  # Less than 15 minutes
            return "bright_yellow"
        if ago < 3600:  # Less than 1 hour
            return "yellow"
        return Colors.DIM

    def _get_battery_style(self, battery) -> str:
        """Get style based on battery level."""
        if battery is None:
            return Colors.DIM
        if battery <= 20:
            return "bright_red"
        if battery <= 50:
            return "bright_yellow"
        return "bright_green"

    def _get_cursor_node_id(self) -> str | None:
        """Get the node_id of the currently highlighted row."""
        if self.cursor_row is None or self.row_count == 0:
            return None
        try:
            row_key = self.coordinate_to_cell_key((self.cursor_row, 0)).row_key
            return str(row_key.value) if row_key else None
        except Exception:
            return None

    def action_request_favorite(self):
        """Handle 'f' key - request favorite toggle for current node."""
        node_id = self._get_cursor_node_id()
        if node_id:
            self.post_message(self.FavoriteRequested(node_id))

    def action_request_invite(self):
        """Handle 'i' key - request channel invite for current node."""
        node_id = self._get_cursor_node_id()
        if node_id:
            self.post_message(self.InviteRequested(node_id))

    def on_unmount(self):
        """Cleanup subscriptions."""
        self.state.nodes.unsubscribe(self._handle_node_event)
