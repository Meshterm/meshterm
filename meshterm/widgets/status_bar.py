"""Status bar widget showing connection status and network stats."""

import time
from textual.widgets import Static
from textual.reactive import reactive
from rich.text import Text

from ..state import AppState
from ..formatting import Colors


class StatusBar(Static):
    """Status bar with connection status and network statistics."""

    connected = reactive(False)
    online_count = reactive(0)
    total_count = reactive(0)
    msgs_per_min = reactive(0.0)
    channel_util = reactive(0.0)

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._last_stats_update = 0

        # Subscribe to state changes
        self.state.nodes.subscribe(self._handle_node_event)
        self.state.stats.subscribe(self._handle_stats_event)

    def on_mount(self):
        """Initialize status from state."""
        self.connected = self.state.connected
        self._update_counts()

    def _handle_node_event(self, event_type: str, data):
        """Handle node updates."""
        self._update_counts()

    def _handle_stats_event(self, event_type: str, data):
        """Handle stats updates."""
        # Throttle updates to once per second
        now = time.time()
        if now - self._last_stats_update < 1.0:
            return
        self._last_stats_update = now

        self.msgs_per_min = self.state.stats.get_msgs_per_min()
        util = self.state.stats.get_channel_util(0)
        if util is not None:
            self.channel_util = util

    def _update_counts(self):
        """Update node counts."""
        nodes = self.state.nodes.get_all_nodes()
        self.total_count = len(nodes)

        # Count online nodes (heard within 15 minutes)
        now = int(time.time())
        online = 0
        for node in nodes.values():
            last_heard = node.get('lastHeard', 0)
            if last_heard and (now - last_heard) < 900:
                online += 1
        self.online_count = online

    def set_connected(self, connected: bool):
        """Set connection status."""
        self.connected = connected

    def render(self) -> Text:
        """Render the status bar."""
        text = Text()

        # Connection status
        if self.connected:
            text.append(" CONNECTED ", style="black on bright_green")
        else:
            text.append(" DISCONNECTED ", style="black on bright_red")

        text.append(" ")

        # Node counts
        text.append("Nodes: ", style=Colors.DIM)
        text.append(f"{self.online_count}", style="bright_green")
        text.append(" online / ", style=Colors.DIM)
        text.append(f"{self.total_count}", style="bright_white")
        text.append(" total", style=Colors.DIM)

        text.append(" | ", style=Colors.DIM)

        # Messages per minute
        text.append("Msgs: ", style=Colors.DIM)
        text.append(f"{self.msgs_per_min:.1f}", style="bright_yellow")
        text.append("/min", style=Colors.DIM)

        text.append(" | ", style=Colors.DIM)

        # Channel utilization
        text.append("Ch0: ", style=Colors.DIM)
        if self.channel_util > 0:
            # Color based on utilization level
            util_style = "bright_green"
            if self.channel_util > 25:
                util_style = "bright_yellow"
            if self.channel_util > 50:
                util_style = "bright_red"
            text.append(f"{self.channel_util:.1f}%", style=util_style)
        else:
            text.append("--", style=Colors.DIM)
        text.append(" util", style=Colors.DIM)

        return text

    def on_unmount(self):
        """Cleanup subscriptions."""
        self.state.nodes.unsubscribe(self._handle_node_event)
        self.state.stats.unsubscribe(self._handle_stats_event)
