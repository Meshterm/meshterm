"""Channel and DM manager modal dialog."""

from typing import Optional
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Static, ListView, ListItem, Label, Input
from textual.binding import Binding
from textual.message import Message
from rich.text import Text

from ..state import AppState
from ..formatting import Colors, format_node_id


class ChannelManager(ModalScreen):
    """Modal dialog for managing channels and DMs."""

    DEFAULT_CSS = """
    ChannelManager {
        align: center middle;
    }

    #manager-container {
        width: 60;
        height: auto;
        max-height: 24;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #manager-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #manager-sections {
        height: auto;
        max-height: 16;
    }

    .section-header {
        text-style: bold;
        padding: 0 0 0 0;
        color: $text-muted;
    }

    #channel-list, #dm-list {
        height: auto;
        max-height: 6;
        margin-bottom: 1;
    }

    #channel-list > ListItem, #dm-list > ListItem {
        padding: 0 1;
    }

    #channel-list > ListItem:hover, #dm-list > ListItem:hover {
        background: $primary-darken-2;
    }

    #node-search-container {
        height: auto;
        margin-bottom: 1;
    }

    #node-search-label {
        padding: 0 0 0 0;
        color: $text-muted;
    }

    #node-search {
        width: 100%;
        height: 1;
        border: none;
        background: $surface-darken-1;
    }

    #node-results {
        height: auto;
        max-height: 4;
        display: none;
    }

    #node-results.visible {
        display: block;
    }

    #node-results > ListItem {
        padding: 0 1;
    }

    #manager-footer {
        text-align: center;
        color: $text-muted;
        padding-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("x", "close_selected", "Close", show=False),
        Binding("enter", "select_item", "Select", show=False),
        Binding("tab", "next_section", "Next Section", show=False),
        Binding("shift+tab", "prev_section", "Prev Section", show=False),
    ]

    class DMOpened(Message):
        """Posted when a DM is opened."""
        def __init__(self, node_id: str, node_name: str):
            self.node_id = node_id
            self.node_name = node_name
            super().__init__()

    class ChannelSelected(Message):
        """Posted when a channel is selected."""
        def __init__(self, channel: int):
            self.channel = channel
            super().__init__()

    class DMSelected(Message):
        """Posted when a DM is selected."""
        def __init__(self, node_id: str):
            self.node_id = node_id
            super().__init__()

    class DMClosed(Message):
        """Posted when a DM is closed."""
        def __init__(self, node_id: str):
            self.node_id = node_id
            super().__init__()

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._current_section = "channels"  # channels, dms, search
        self._search_results = []

    def compose(self) -> ComposeResult:
        with Container(id="manager-container"):
            yield Static("Channel Manager", id="manager-title")
            with Vertical(id="manager-sections"):
                # Channels section
                yield Static("Channels [0-7]", classes="section-header")
                with ListView(id="channel-list"):
                    for i in range(8):
                        name = self.state.get_channel_name(i)
                        if i == 0 or name:
                            item_text = self._format_channel_item(i, name)
                            yield ListItem(Label(item_text), id=f"ch-{i}")

                # Open DMs section
                yield Static("Open DMs [x to close]", classes="section-header")
                with ListView(id="dm-list"):
                    for dm in self.state.open_dms.get_open_dms():
                        item_text = self._format_dm_item(dm.node_id, dm.node_name)
                        yield ListItem(Label(item_text), id=f"dm-{dm.node_id}")

                # New DM section
                with Container(id="node-search-container"):
                    yield Static("New DM (type to search nodes)", id="node-search-label")
                    yield Input(placeholder="Search by name or ID...", id="node-search")
                with ListView(id="node-results"):
                    pass  # Populated dynamically

            yield Static("Enter=select  x=close DM  Esc=cancel", id="manager-footer")

    def _format_channel_item(self, index: int, name: Optional[str]) -> Text:
        """Format a channel list item."""
        text = Text()
        text.append(f"[{index}] ", style="bold bright_green")
        if name:
            text.append(name, style="bright_cyan")
        else:
            text.append("Primary" if index == 0 else "(unnamed)", style=Colors.DIM)
        return text

    def _format_dm_item(self, node_id: str, node_name: str) -> Text:
        """Format a DM list item."""
        text = Text()
        text.append("@ ", style="bold bright_magenta")
        text.append(node_name or node_id[-4:], style="bright_cyan")
        text.append(f" ({node_id})", style=Colors.DIM)

        # Show notification count if any
        count = self.state.open_dms.get_notification_count(node_id)
        if count > 0:
            text.append(f" ({count})", style="bold bright_yellow")

        return text

    def _format_node_result(self, node_id: str, node: dict) -> Text:
        """Format a node search result."""
        text = Text()
        user = node.get('user', {})
        name = user.get('shortName') or user.get('longName') or node_id[-4:]

        # Already open indicator
        if self.state.open_dms.is_dm_open(node_id):
            text.append("[open] ", style="dim")

        text.append(name, style="bright_cyan")
        text.append(f" ({node_id})", style=Colors.DIM)

        # PKI status
        has_key = node.get('has_public_key') or bool(user.get('publicKey'))
        if has_key:
            text.append(" [*]", style="bright_green")
        else:
            text.append(" [!]", style="bright_red")

        return text

    def on_input_changed(self, event: Input.Changed):
        """Handle search input changes."""
        if event.input.id != "node-search":
            return

        query = event.input.value.strip().lower()
        results_list = self.query_one("#node-results", ListView)
        results_list.clear()

        if not query:
            results_list.remove_class("visible")
            self._search_results = []
            return

        # Search nodes
        matches = []
        my_node_id = self.state.my_node_id

        for node_id, node in self.state.nodes.get_all_nodes().items():
            # Skip our own node
            if node_id == my_node_id:
                continue

            user = node.get('user', {})
            short_name = (user.get('shortName') or '').lower()
            long_name = (user.get('longName') or '').lower()
            node_id_lower = node_id.lower()

            if query in short_name or query in long_name or query in node_id_lower:
                matches.append((node_id, node))

        # Limit to 5 results
        self._search_results = matches[:5]

        if self._search_results:
            results_list.add_class("visible")
            for node_id, node in self._search_results:
                item_text = self._format_node_result(node_id, node)
                results_list.append(ListItem(Label(item_text), id=f"node-{node_id}"))
        else:
            results_list.remove_class("visible")

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle list item selection."""
        item_id = event.item.id
        if not item_id:
            return

        if item_id.startswith("ch-"):
            # Channel selected
            channel = int(item_id.split("-")[1])
            self.dismiss(("channel", channel))
        elif item_id.startswith("dm-"):
            # Existing DM selected
            node_id = item_id[3:]  # Remove "dm-" prefix
            self.dismiss(("dm", node_id))
        elif item_id.startswith("node-"):
            # New DM from search
            node_id = item_id[5:]  # Remove "node-" prefix
            self._open_new_dm(node_id)

    def _open_new_dm(self, node_id: str):
        """Open a new DM with the given node."""
        node = self.state.nodes.get_node(node_id)
        if node:
            user = node.get('user', {})
            node_name = user.get('shortName') or user.get('longName') or node_id[-4:]

            # Check PKI status
            has_key = node.get('has_public_key') or bool(user.get('publicKey'))
            if not has_key:
                self.app.notify(
                    "Warning: No PKI key exchange yet. Messages may not be secure.",
                    severity="warning",
                    timeout=3
                )
        else:
            node_name = node_id[-4:]

        # Open the DM
        self.state.open_dms.open_dm(node_id, node_name)
        self.dismiss(("new_dm", node_id))

    def action_cancel(self):
        """Cancel and close the dialog."""
        self.dismiss(None)

    def action_close_selected(self):
        """Close the selected DM."""
        dm_list = self.query_one("#dm-list", ListView)
        if dm_list.highlighted_child:
            item_id = dm_list.highlighted_child.id
            if item_id and item_id.startswith("dm-"):
                node_id = item_id[3:]
                self.state.open_dms.close_dm(node_id)
                # Refresh the DM list
                self._refresh_dm_list()
                self.app.notify(f"Closed DM", timeout=2)

    def _refresh_dm_list(self):
        """Refresh the DM list after closing one."""
        dm_list = self.query_one("#dm-list", ListView)
        dm_list.clear()
        for dm in self.state.open_dms.get_open_dms():
            item_text = self._format_dm_item(dm.node_id, dm.node_name)
            dm_list.append(ListItem(Label(item_text), id=f"dm-{dm.node_id}"))

    def action_select_item(self):
        """Select the currently highlighted item."""
        # Check which list is focused/has selection
        for list_id in ["#channel-list", "#dm-list", "#node-results"]:
            try:
                list_view = self.query_one(list_id, ListView)
                if list_view.highlighted_child:
                    # Trigger the selection
                    list_view.action_select_cursor()
                    return
            except Exception:
                pass

    def action_next_section(self):
        """Move focus to next section."""
        try:
            search = self.query_one("#node-search", Input)
            search.focus()
        except Exception:
            pass

    def action_prev_section(self):
        """Move focus to previous section."""
        try:
            channel_list = self.query_one("#channel-list", ListView)
            channel_list.focus()
        except Exception:
            pass

    def on_mount(self):
        """Focus the channel list when mounted."""
        try:
            channel_list = self.query_one("#channel-list", ListView)
            channel_list.focus()
        except Exception:
            pass
