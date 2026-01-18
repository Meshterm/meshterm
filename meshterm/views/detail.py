"""Detail view - single node detail with sub-tabs."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static, ContentSwitcher
from textual.binding import Binding
from rich.text import Text

from ..state import AppState
from ..formatting import (
    format_node_id, format_time_ago, format_packet, format_payload,
    Colors, haversine_distance, format_distance, get_node_position, get_location_name
)
from ..widgets.dm_input import DMInput
from ..widgets.chat_log import ChatLog


class NodeInfoPanel(Container):
    """Two-column panel showing node information."""

    DEFAULT_CSS = """
    NodeInfoPanel {
        layout: horizontal;
        height: 100%;
        width: 100%;
    }

    NodeInfoPanel > .info-column {
        width: 1fr;
        height: 100%;
        padding: 0 1;
    }
    """

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.state.settings.subscribe(self._handle_settings_event)
        self.state.nodes.subscribe(self._handle_node_event)

    def compose(self) -> ComposeResult:
        yield Static(id="info-left", classes="info-column")
        yield Static(id="info-right", classes="info-column")

    def on_mount(self):
        self._update_content()

    def _handle_settings_event(self, event_type: str, setting: str):
        if setting == "selected_node":
            self._update_content()

    def _handle_node_event(self, event_type: str, data):
        if self.state.settings.selected_node:
            self.call_later(self._update_content)

    def _update_content(self):
        """Update both column content widgets."""
        try:
            left = self.query_one("#info-left", Static)
            right = self.query_one("#info-right", Static)
            left_text, right_text = self._render_info()
            left.update(left_text)
            right.update(right_text)
        except Exception:
            pass

    def _render_info(self) -> tuple[Text, Text]:
        node_id = self.state.settings.selected_node
        if not node_id:
            return Text("No node selected", style=Colors.DIM), Text()

        node = self.state.nodes.get_node(node_id)
        if not node:
            return Text(f"Node {node_id} not found", style=Colors.DIM), Text()

        left = Text()
        right = Text()
        user = node.get('user', {})
        metrics = node.get('deviceMetrics', {})
        last_heard = node.get('lastHeard')

        # LEFT COLUMN: Node info, Security

        left.append("Node:\n", style="bold")
        left.append(f"  {user.get('longName', node_id)}\n")
        left.append("Short:\n", style="bold")
        left.append(f"  {user.get('shortName', '?')}\n")
        left.append("ID:\n", style="bold")
        left.append(f"  {node_id}\n")
        left.append("Hardware:\n", style="bold")
        left.append(f"  {user.get('hwModel', '?')}\n")
        if user.get('macaddr'):
            left.append("MAC:\n", style="bold")
            left.append(f"  {user.get('macaddr')}\n")
        left.append("Seen:\n", style="bold")
        left.append(f"  {format_time_ago(last_heard)} ago\n")

        # Security/PKI status
        left.append("Security:\n", style="bold")
        has_key = node.get('has_public_key', False)
        if not has_key:
            has_key = bool(user.get('publicKey'))
        if has_key:
            left.append("  PKI: Encrypted\n")
        else:
            left.append("  PKI: No public key\n")
        if user.get('isUnmessagable'):
            left.append("  Status: Unmessagable\n")

        # RIGHT COLUMN: Telemetry, Signal, Position

        right.append("Telemetry:\n", style="bold")
        if metrics:
            if 'batteryLevel' in metrics:
                right.append(f"  Battery: {metrics['batteryLevel']}%\n")
            if 'voltage' in metrics:
                right.append(f"  Voltage: {metrics['voltage']:.2f}V\n")
            if 'channelUtilization' in metrics:
                right.append(f"  Channel Util: {metrics['channelUtilization']:.1f}%\n")
            if 'airUtilTx' in metrics:
                right.append(f"  Air Util TX: {metrics['airUtilTx']:.1f}%\n")
            if 'uptimeSeconds' in metrics:
                uptime = metrics['uptimeSeconds']
                hrs = uptime // 3600
                mins = (uptime % 3600) // 60
                right.append(f"  Uptime: {hrs}h {mins}m\n")
        else:
            right.append("  No telemetry data\n", style="dim")

        right.append("Signal:\n", style="bold")
        snr = node.get('snr')
        rssi = node.get('rssi')
        if snr is not None:
            right.append(f"  SNR: {snr:.1f}\n")
        if rssi is not None:
            right.append(f"  RSSI: {rssi}\n")
        if snr is None and rssi is None:
            right.append("  No signal data\n", style="dim")

        right.append("Position:\n", style="bold")
        position = node.get('position', {})
        node_pos = get_node_position(node)
        if node_pos:
            lat, lon = node_pos

            location_name = get_location_name(lat, lon)
            if location_name:
                right.append(f"  {location_name}\n")

            right.append(f"  Lat: {lat:.6f}\n")
            right.append(f"  Lon: {lon:.6f}\n")

            my_pos = self.state.my_position
            if my_pos:
                dist_km = haversine_distance(my_pos[0], my_pos[1], lat, lon)
                right.append(f"  Distance: {format_distance(dist_km)}\n")

            if 'altitude' in position:
                right.append(f"  Altitude: {position['altitude']}m\n")
            if 'satsInView' in position:
                right.append(f"  Satellites: {position['satsInView']}\n")
            if 'groundSpeed' in position:
                right.append(f"  Speed: {position['groundSpeed']}m/s\n")
            if 'groundTrack' in position:
                right.append(f"  Heading: {position['groundTrack']}°\n")
            if 'precisionBits' in position:
                right.append(f"  Precision: {position['precisionBits']} bits\n")
            if 'time' in position:
                right.append(f"  Fix time: {format_time_ago(position['time'])} ago\n")
        else:
            right.append("  No position data\n", style="dim")

        return left, right

    def on_unmount(self):
        self.state.settings.unsubscribe(self._handle_settings_event)
        self.state.nodes.unsubscribe(self._handle_node_event)


class NodeChatPanel(Container):
    """IRC-style chat panel for DMs with the selected node."""

    DEFAULT_CSS = """
    NodeChatPanel {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    NodeChatPanel > .dm-header {
        height: 1;
        background: $surface;
        padding: 0 1;
    }

    NodeChatPanel > .dm-chat-log {
        height: 1fr;
        width: 100%;
    }

    NodeChatPanel > .dm-footer {
        height: 1;
        background: $surface;
    }
    """

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.state.settings.subscribe(self._handle_settings_event)

    def compose(self) -> ComposeResult:
        yield Static(self._format_header(), classes="dm-header", id="dm-header")
        yield ChatLog(self.state, classes="dm-chat-log", id="dm-chat-log")
        yield DMInput(self.state, classes="dm-footer", id="dm-input")

    def _format_header(self) -> Text:
        """Format the 'To: NodeName' header with PKI indicator."""
        text = Text()
        text.append("To: ", style=Colors.DIM)

        node_id = self.state.settings.selected_node
        if node_id:
            node = self.state.nodes.get_node(node_id)
            if node:
                user = node.get('user', {})
                name = user.get('shortName') or user.get('longName') or node_id
                has_key = node.get('has_public_key') or bool(user.get('publicKey'))

                text.append(name, style="bold bright_cyan")

                # PKI indicator
                if has_key:
                    text.append(" [*]", style="bright_green")
                else:
                    text.append(" [!NO KEY]", style="bright_red")
            else:
                text.append(node_id, style="bold bright_cyan")
        else:
            text.append("(no node selected)", style=Colors.DIM)

        return text

    def _handle_settings_event(self, event_type: str, setting: str):
        if setting == "selected_node":
            self._update_header()
            self._update_chat_log()

    def _update_header(self):
        """Update the header when selected node changes."""
        try:
            header = self.query_one("#dm-header", Static)
            header.update(self._format_header())
        except Exception:
            pass

    def _update_chat_log(self):
        """Update the chat log when selected node changes."""
        try:
            chat_log = self.query_one("#dm-chat-log", ChatLog)
            node_id = self.state.settings.selected_node
            chat_log.dm_node_id = node_id
            chat_log.load_messages()
        except Exception:
            pass

    def load_messages(self):
        """Load messages for the selected node."""
        try:
            chat_log = self.query_one("#dm-chat-log", ChatLog)
            node_id = self.state.settings.selected_node
            chat_log.dm_node_id = node_id
            chat_log.load_messages()
        except Exception:
            pass

    def focus_input(self):
        """Focus the DM input field."""
        try:
            dm_input = self.query_one("#dm-input", DMInput)
            dm_input.focus_input()
        except Exception:
            pass

    def on_unmount(self):
        self.state.settings.unsubscribe(self._handle_settings_event)


class DetailView(Container):
    """Detail view for a single node with sub-tabs."""

    DEFAULT_CSS = """
    DetailView {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    DetailView > .detail-content {
        height: 1fr;
        width: 100%;
    }

    DetailView .info-panel {
        width: 100%;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }

    DetailView .messages-panel {
        width: 100%;
        height: 100%;
        border: solid $secondary;
        padding: 0;
    }
    """

    BINDINGS = [
        Binding("i", "switch_subtab('info')", "Info", show=False, priority=True),
        Binding("m", "switch_subtab('messages')", "Messages", show=False, priority=True),
        Binding("left", "prev_subtab", "Prev Tab", show=False, priority=True),
        Binding("right", "next_subtab", "Next Tab", show=False, priority=True),
    ]

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.current_subtab = "messages"

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial="messages", classes="detail-content", id="detail-switcher"):
            yield NodeChatPanel(self.state, classes="messages-panel", id="messages")
            yield NodeInfoPanel(self.state, classes="info-panel", id="info")

    def _get_available_tabs(self) -> list:
        """Get available tabs for the current node context."""
        if self.state.settings.selected_node == self.state.my_node_id:
            return ["info"]
        return ["messages", "info"]

    def action_switch_subtab(self, subtab: str):
        """Switch to a different sub-tab."""
        tabs = self._get_available_tabs()

        # If requested tab not available, use first available
        if subtab not in tabs:
            subtab = tabs[0]

        self.current_subtab = subtab
        self.query_one("#detail-switcher", ContentSwitcher).current = subtab

        # Update header bar
        try:
            from ..widgets.header_bar import HeaderBar
            header = self.app.query_one("#header-bar", HeaderBar)
            header.set_active_subtab(subtab)
        except Exception:
            pass

        # Load messages and focus input if switching to messages tab
        if subtab == "messages":
            messages_panel = self.query_one("#messages", NodeChatPanel)
            messages_panel.load_messages()
            messages_panel.focus_input()

    def action_next_subtab(self):
        """Switch to next sub-tab."""
        tabs = self._get_available_tabs()
        if len(tabs) <= 1:
            return
        current_idx = tabs.index(self.current_subtab) if self.current_subtab in tabs else 0
        next_idx = (current_idx + 1) % len(tabs)
        self.action_switch_subtab(tabs[next_idx])

    def action_prev_subtab(self):
        """Switch to previous sub-tab."""
        tabs = self._get_available_tabs()
        if len(tabs) <= 1:
            return
        current_idx = tabs.index(self.current_subtab) if self.current_subtab in tabs else 0
        prev_idx = (current_idx - 1) % len(tabs)
        self.action_switch_subtab(tabs[prev_idx])

    def on_show(self):
        """Called when view becomes visible."""
        # Always default to first available tab
        tabs = self._get_available_tabs()
        self.action_switch_subtab(tabs[0])
