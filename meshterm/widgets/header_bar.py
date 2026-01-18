"""Header bar widget showing tabs and mode indicators."""

from typing import List, Union
from textual.widgets import Static
from textual.reactive import reactive
from textual.binding import Binding
from textual.message import Message
from rich.text import Text
from rich.cells import cell_len

from ..state import AppState
from ..formatting import Colors


class HeaderBar(Static):
    """Header bar with context-aware tab indicators and mode toggles."""

    can_focus = True

    BINDINGS = [
        Binding("left", "nav_left", "Previous tab", show=False),
        Binding("right", "nav_right", "Next tab", show=False),
        Binding("enter", "select_tab", "Select tab", show=False),
        Binding("x", "close_dm", "Close DM", show=False),
    ]

    # Main level tabs
    MAIN_TABS = ["nodes", "chat", "log", "settings"]

    # Sub-tabs for each context
    DETAIL_TABS = ["messages", "info"]
    SETTINGS_TABS = ["radio", "channels", "gps", "device", "advanced"]
    # CHAT_TABS is now dynamically generated via _get_chat_tabs()

    # Tab display config: (tab_id, prefix, key, suffix)
    TAB_DISPLAY = {
        # Main tabs
        "nodes": ("", "N", "odes"),
        "log": ("", "L", "og"),
        "chat": ("", "C", "hat"),
        "settings": ("", "S", "ettings"),
        # Detail sub-tabs
        "info": ("", "I", "nfo"),
        "messages": ("", "M", "essages"),
        # Settings sub-tabs
        "radio": ("", "R", "adio"),
        "channels": ("c", "H", "annels"),
        "gps": ("", "G", "PS"),
        "device": ("", "D", "evice"),
        "advanced": ("", "A", "dvanced"),
        # Chat channel tabs (0-7)
        "0": ("", "0", ""),
        "1": ("", "1", ""),
        "2": ("", "2", ""),
        "3": ("", "3", ""),
        "4": ("", "4", ""),
        "5": ("", "5", ""),
        "6": ("", "6", ""),
        "7": ("", "7", ""),
    }

    context = reactive("main")  # "main", "detail", "settings", or "chat"
    active_tab = reactive("nodes")
    active_subtab = reactive("info")
    highlighted_idx = reactive(0)

    class TabSelected(Message):
        """Message sent when a tab is selected via Enter."""
        def __init__(self, tab_id: str):
            self.tab_id = tab_id
            super().__init__()

    class BackRequested(Message):
        """Message sent when back/Esc is selected from sub-tabs."""
        pass

    class SubTabSelected(Message):
        """Message sent when a sub-tab is selected."""
        def __init__(self, subtab_id: str):
            self.subtab_id = subtab_id
            super().__init__()

    class DMClosed(Message):
        """Message sent when a DM tab is closed."""
        def __init__(self, node_id: str):
            self.node_id = node_id
            super().__init__()

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.state.open_dms.subscribe(self._handle_dm_event)

    def _handle_dm_event(self, event_type: str, data):
        """Handle DM state changes."""
        if event_type in ("dm_opened", "dm_closed", "notification_updated", "notification_cleared"):
            self.refresh()

    def _get_chat_tabs(self) -> List[str]:
        """Get dynamic list of chat tabs based on active channels and open DMs.

        Returns:
            List of tab IDs: channel numbers ("0", "1", etc.) and DM IDs ("dm:!abcd1234")
        """
        tabs = []

        # Always include channel 0
        tabs.append("0")

        # Include channels 1-7 only if they have configured names
        for i in range(1, 8):
            if self.state.get_channel_name(i):
                tabs.append(str(i))

        # Append open DMs
        for dm in self.state.open_dms.get_open_dms():
            tabs.append(f"dm:{dm.node_id}")

        return tabs

    def _get_detail_tabs(self) -> List[str]:
        """Get tabs for detail view - excludes messages for own node."""
        if self.state.settings.selected_node == self.state.my_node_id:
            return ["info"]
        return self.DETAIL_TABS

    def _get_current_tabs(self) -> list:
        """Get the list of tabs for the current context."""
        if self.context == "detail":
            return self._get_detail_tabs()
        elif self.context == "settings":
            return self.SETTINGS_TABS
        elif self.context == "chat":
            return self._get_chat_tabs()
        else:
            return self.MAIN_TABS

    def set_context(self, context: str, subtab: str = None):
        """Set the navigation context."""
        self.context = context
        if subtab:
            self.active_subtab = subtab
        # Reset highlighted index (0 = back button for sub-contexts, 0 = first tab for main)
        self.highlighted_idx = 0 if context == "main" else 1

    def set_active_tab(self, tab_id: str):
        """Set the active main tab."""
        self.active_tab = tab_id

    def set_active_subtab(self, subtab_id: str):
        """Set the active sub-tab."""
        self.active_subtab = subtab_id
        # Update highlighted index to match
        tabs = self._get_current_tabs()
        if subtab_id in tabs:
            self.highlighted_idx = tabs.index(subtab_id) + 1  # +1 for back button

    def action_nav_left(self):
        """Navigate to previous tab."""
        tabs = self._get_current_tabs()
        if self.context == "main":
            max_idx = len(tabs) - 1
            self.highlighted_idx = (self.highlighted_idx - 1) % len(tabs)
        else:
            # Sub-context: 0 is back, 1+ are tabs
            max_idx = len(tabs)  # 0=back, 1..n=tabs
            self.highlighted_idx = (self.highlighted_idx - 1) % (max_idx + 1)

    def action_nav_right(self):
        """Navigate to next tab."""
        tabs = self._get_current_tabs()
        if self.context == "main":
            self.highlighted_idx = (self.highlighted_idx + 1) % len(tabs)
        else:
            # Sub-context: 0 is back, 1+ are tabs
            max_idx = len(tabs)
            self.highlighted_idx = (self.highlighted_idx + 1) % (max_idx + 1)

    def action_select_tab(self):
        """Select the currently highlighted tab."""
        tabs = self._get_current_tabs()

        if self.context == "main":
            tab_id = tabs[self.highlighted_idx]
            self.post_message(self.TabSelected(tab_id))
        else:
            if self.highlighted_idx == 0:
                # Back button
                self.post_message(self.BackRequested())
            else:
                subtab_id = tabs[self.highlighted_idx - 1]
                self.post_message(self.SubTabSelected(subtab_id))

    def action_close_dm(self):
        """Close the currently active DM tab."""
        if self.context != "chat":
            return

        # Check if current subtab is a DM
        if self.active_subtab.startswith("dm:"):
            node_id = self.active_subtab[3:]  # Remove "dm:" prefix
            self.state.open_dms.close_dm(node_id)
            self.post_message(self.DMClosed(node_id))

    def on_focus(self):
        """When focused, sync highlighted index with active tab."""
        tabs = self._get_current_tabs()
        if self.context == "main":
            if self.active_tab in tabs:
                self.highlighted_idx = tabs.index(self.active_tab)
        else:
            if self.active_subtab in tabs:
                self.highlighted_idx = tabs.index(self.active_subtab) + 1

    def render(self) -> Text:
        """Render the header bar."""
        text = Text()
        is_focused = self.has_focus
        tabs = self._get_current_tabs()

        if self.context != "main":
            # Render back button first
            is_highlighted = is_focused and self.highlighted_idx == 0
            if is_highlighted:
                text.append("<-[", style="bold bright_yellow")
                text.append("Esc", style="bold bright_yellow reverse")
                text.append("]", style="bold bright_yellow")
            else:
                text.append("<-[", style=Colors.DIM)
                text.append("Esc", style="bright_white")
                text.append("]", style=Colors.DIM)
            text.append(" ")

        # Render tabs
        for i, tab_id in enumerate(tabs):
            # Handle DM tabs specially
            if tab_id.startswith("dm:"):
                node_id = tab_id[3:]  # Remove "dm:" prefix
                # Get DM name from open_dms state
                dm_name = None
                for dm in self.state.open_dms.get_open_dms():
                    if dm.node_id == node_id:
                        dm_name = dm.node_name
                        break
                if not dm_name:
                    dm_name = node_id[-4:]  # Last 4 chars of node ID
                # Check for notifications
                notif_count = self.state.open_dms.get_notification_count(node_id)
                notif_badge = f"({notif_count})" if notif_count > 0 else ""
                prefix = "@"
                key = dm_name[0].upper() if dm_name else "?"
                suffix = dm_name[1:] + notif_badge if dm_name else notif_badge
            else:
                display = self.TAB_DISPLAY.get(tab_id, ("", tab_id[0].upper(), tab_id[1:]))
                prefix, key, suffix = display

                # For chat context, append channel name if available
                if self.context == "chat" and tab_id.isdigit():
                    channel_name = self.state.get_channel_name(int(tab_id))
                    if channel_name:
                        suffix = f":{channel_name}"

            if self.context == "main":
                is_active = tab_id == self.active_tab
                is_highlighted = is_focused and i == self.highlighted_idx
            else:
                is_active = tab_id == self.active_subtab
                is_highlighted = is_focused and (i + 1) == self.highlighted_idx

            if is_highlighted:
                text.append(prefix, style="bold bright_yellow")
                text.append("[", style="bold bright_yellow")
                text.append(key, style="bold bright_yellow reverse")
                text.append("]", style="bold bright_yellow")
                text.append(suffix, style="bold bright_yellow")
            elif is_active:
                text.append(prefix, style="bright_cyan")
                text.append("[", style="bright_white")
                text.append(key, style="bold bright_cyan")
                text.append("]", style="bright_white")
                text.append(suffix, style="bright_cyan")
            else:
                text.append(prefix, style=Colors.DIM)
                text.append("[", style=Colors.DIM)
                text.append(key, style="bright_white")
                text.append("]", style=Colors.DIM)
                text.append(suffix, style=Colors.DIM)
            text.append(" ")

        # Calculate padding to push help hint to the right edge
        hint = "[^h]"
        try:
            available_width = self.size.width
            current_len = cell_len(text.plain)
            padding = available_width - current_len - len(hint)
            if padding > 0:
                text.append(" " * padding)
        except Exception:
            # Fallback if size not available yet
            text.append(" " * 30)

        # Help hint on the right
        text.append(hint, style=Colors.DIM)

        return text

    def on_unmount(self):
        """Cleanup subscriptions."""
        self.state.open_dms.unsubscribe(self._handle_dm_event)
