"""Nodes view - table of all known nodes."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static, Input
from textual.message import Message
from textual.binding import Binding

from ..state import AppState
from ..widgets.node_table import NodeTable


class NodesView(Container):
    """Table view showing all known nodes."""

    DEFAULT_CSS = """
    NodesView {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    NodesView > .search-bar {
        height: 1;
        display: none;
        background: $surface;
    }

    NodesView > .search-bar.visible {
        display: block;
    }

    NodesView > .search-bar Input {
        width: 100%;
        border: none;
        background: $surface;
    }

    NodesView > NodeTable {
        height: 1fr;
        width: 100%;
        border: solid $primary;
    }

    NodesView > .nodes-footer {
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("/", "start_search", "Search", show=False),
        Binding("escape", "handle_escape", "Back", show=False, priority=True),
        Binding("<", "prev_sort_column", "Sort ←", show=False),
        Binding(">", "next_sort_column", "Sort →", show=False),
        Binding("r", "toggle_sort_direction", "Reverse", show=False, priority=True),
    ]

    class NodeSelected(Message):
        """Message sent when a node is selected."""

        def __init__(self, node_id: str):
            self.node_id = node_id
            super().__init__()

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._search_active = False

    def compose(self) -> ComposeResult:
        with Container(classes="search-bar"):
            yield Input(placeholder="Search nodes...", id="search-input", disabled=True)
        yield NodeTable(self.state, id="node-table")
        yield Static("Enter=details  /=search  f=favorite  i=invite  </>=sort  r=reverse  Esc=back", classes="nodes-footer")

    def action_start_search(self):
        """Activate search mode."""
        search_bar = self.query_one(".search-bar")
        search_bar.add_class("visible")
        search_input = self.query_one("#search-input", Input)
        search_input.disabled = False  # Enable Input when showing
        search_input.focus()
        self._search_active = True

    def on_input_changed(self, event: Input.Changed):
        """Handle search input changes."""
        if event.input.id == "search-input":
            table = self.query_one("#node-table", NodeTable)
            table.set_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted):
        """Handle search input submission (Enter key) - select first match."""
        if event.input.id == "search-input":
            table = self.query_one("#node-table", NodeTable)
            # If there are rows, select the first one
            if table.row_count > 0:
                # Get the first row's key
                first_row_key = table.get_row_at(0)
                if first_row_key:
                    # The row key is stored when we add_row with key=node_id
                    # get_row_at returns the row data, we need to get the key differently
                    # Use the cursor to select and trigger
                    table.cursor_coordinate = (0, 0)
                    node_id = self._get_first_row_node_id(table)
                    if node_id:
                        self.state.settings.set_selected_node(node_id)
                        self._close_search_keep_filter()
                        self.post_message(self.NodeSelected(node_id))
                        return
            self._close_search()

    def _get_first_row_node_id(self, table: NodeTable) -> str | None:
        """Get the node_id of the first row in the table."""
        # Access the internal row keys
        if table.rows:
            first_key = next(iter(table.rows.keys()))
            return str(first_key.value)
        return None

    def _close_search_keep_filter(self):
        """Close search bar but keep the filter active."""
        search_bar = self.query_one(".search-bar")
        search_bar.remove_class("visible")
        self._search_active = False

    def action_handle_escape(self):
        """Handle ESC key - clear search if active, otherwise bubble up."""
        if self._search_active:
            self._close_search()
        elif self._has_active_filter():
            # Clear filter even if search bar is hidden (e.g., after Enter selection)
            self._close_search()
        else:
            # Let the app handle it (go back to log)
            self.app.action_go_back()

    def _has_active_filter(self) -> bool:
        """Check if there's an active filter on the table."""
        table = self.query_one("#node-table", NodeTable)
        return bool(table._filter)

    def _close_search(self, refocus_table: bool = True):
        """Close search and optionally return focus to table."""
        search_bar = self.query_one(".search-bar")
        search_bar.remove_class("visible")
        search_input = self.query_one("#search-input", Input)
        search_input.value = ""
        search_input.disabled = True  # Disable Input when hidden
        table = self.query_one("#node-table", NodeTable)
        table.set_filter("")
        if refocus_table:
            table.focus()
        self._search_active = False

    def on_data_table_row_selected(self, event):
        """Handle row selection."""
        # Get node_id directly from the event's row_key
        node_id = str(event.row_key.value) if event.row_key else None
        if node_id:
            self.state.settings.set_selected_node(node_id)
            self.post_message(self.NodeSelected(node_id))

    def on_node_table_favorite_requested(self, event: NodeTable.FavoriteRequested):
        """Handle favorite toggle request from NodeTable."""
        self._toggle_favorite_for_node(event.node_id)

    def on_node_table_invite_requested(self, event: NodeTable.InviteRequested):
        """Handle invite request from NodeTable."""
        self._invite_node_to_channel(event.node_id)

    def _toggle_favorite_for_node(self, node_id: str):
        """Toggle favorite status for the specified node."""
        # Get node name for notification
        node = self.state.nodes.get_node(node_id)
        name = node_id
        if node:
            user = node.get('user', {})
            name = user.get('shortName') or user.get('longName') or node_id

        # Check current favorite status
        is_fav = self.state.nodes.is_favorite(node_id)

        # Toggle via Meshtastic API if available
        try:
            interface = self.app.connection.interface
            if interface and interface.localNode:
                # Convert node_id to int for Meshtastic API
                node_num = node.get('num') if node else None
                if node_num:
                    if is_fav:
                        interface.localNode.removeFavorite(node_num)
                    else:
                        interface.localNode.setFavorite(node_num)
        except Exception:
            pass

        # Update local state
        self.state.nodes.set_favorite(node_id, not is_fav)

        if not is_fav:
            self.app.notify(f"Favorited: {name}", timeout=2)
        else:
            self.app.notify(f"Unfavorited: {name}", timeout=2)

    def _invite_node_to_channel(self, node_id: str):
        """Invite the specified node to a channel."""
        from ..widgets.dialogs import ChannelSelectDialog, InviteConfirmDialog

        # Validate not inviting self
        if node_id == self.state.my_node_id:
            self.app.notify("Cannot invite yourself", severity="warning", timeout=2)
            return

        # Get shareable channels
        channels = self.app.connection.get_shareable_channels()
        if not channels:
            self.app.notify("No channels with PSK configured", severity="warning", timeout=2)
            return

        # Get node info for display
        node = self.state.nodes.get_node(node_id)
        if node:
            user = node.get('user', {})
            target_name = user.get('shortName') or user.get('longName') or node_id
            target_num = node.get('num')
        else:
            target_name = node_id
            target_num = None

        if not target_num:
            self.app.notify("Cannot get node number", severity="error", timeout=2)
            return

        def on_channel_selected(channel: dict | None):
            if channel is None:
                return

            def on_confirm(confirmed: bool):
                if not confirmed:
                    return

                success, message = self.app.connection.send_channel_invitation(
                    target_num, channel
                )
                if success:
                    ch_name = channel.get('name') or f"Ch{channel['index']}"
                    self.app.notify(f"Invited {target_name} to {ch_name}", timeout=3)
                else:
                    self.app.notify(f"Failed: {message}", severity="error", timeout=3)

            # Show confirmation dialog
            self.app.push_screen(
                InviteConfirmDialog(target_name, node_id, channel),
                on_confirm
            )

        # Show channel selection dialog
        self.app.push_screen(ChannelSelectDialog(channels), on_channel_selected)

    def action_prev_sort_column(self):
        """Sort by previous column."""
        self.query_one("#node-table", NodeTable).cycle_sort_column(-1)

    def action_next_sort_column(self):
        """Sort by next column."""
        self.query_one("#node-table", NodeTable).cycle_sort_column(1)

    def action_toggle_sort_direction(self):
        """Toggle sort direction (ascending/descending)."""
        self.query_one("#node-table", NodeTable).toggle_sort_direction()

    def on_show(self):
        """Called when view becomes visible."""
        # Refresh the table when shown
        table = self.query_one("#node-table", NodeTable)
        table._refresh_all()
        table.focus()

    def on_hide(self):
        """Called when view is hidden."""
        # Close search if active, but don't refocus since we're leaving
        if self._search_active:
            self._close_search(refocus_table=False)
