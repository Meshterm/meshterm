"""Modal showing detailed metadata about a chat message."""

from datetime import datetime
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container
from textual.widgets import Static
from textual.binding import Binding
from rich.text import Text

from ..state import AppState
from ..formatting import Colors, format_node_id


class MessageDetailsModal(ModalScreen):
    """Modal showing packet metadata for a selected message."""

    DEFAULT_CSS = """
    MessageDetailsModal {
        align: center middle;
    }

    MessageDetailsModal > Container {
        width: 60;
        height: auto;
        max-height: 24;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }

    MessageDetailsModal .title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    MessageDetailsModal .details-content {
        height: auto;
        padding: 0 1;
    }

    MessageDetailsModal .hint {
        text-align: center;
        padding-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False, priority=True),
        Binding("q", "close", "Close", show=False, priority=True),
    ]

    def __init__(self, entry: dict, state: AppState):
        super().__init__()
        self.entry = entry
        self.state = state

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("Message Details", classes="title")
            yield Static(self._build_details(), classes="details-content")
            yield Static("Press Esc to close", classes="hint")

    def _build_details(self) -> Text:
        packet = self.entry.get('packet', {})
        decoded = packet.get('decoded', {})
        is_tx = packet.get('_tx', False)

        text = Text()

        # Message text
        msg_text = decoded.get('text', '')
        text.append("Message: ", style="bold bright_cyan")
        text.append(f"{msg_text}\n", style=Colors.TEXT)
        text.append("\n")

        # Sender
        from_id = packet.get('from', packet.get('fromId'))
        sender_name = self._get_node_display(from_id)
        text.append("From: ", style="bold bright_cyan")
        text.append(f"{sender_name}", style="bold bright_magenta" if is_tx else "bold bright_green")
        if from_id:
            text.append(f" ({format_node_id(from_id)})", style=Colors.DIM)
        text.append("\n")

        # Destination
        to_id = packet.get('to', '')
        to_display = format_node_id(to_id)
        if to_display in ('^all', '!ffffffff'):
            to_display = "Broadcast (all)"
        else:
            to_display = self._get_node_display(to_id)
        text.append("To: ", style="bold bright_cyan")
        text.append(f"{to_display}\n", style=Colors.TEXT)

        # Channel
        channel = packet.get('channel', 0)
        channel_name = self.state.get_channel_name(channel) if hasattr(self.state, 'get_channel_name') else None
        text.append("Channel: ", style="bold bright_cyan")
        text.append(f"{channel}")
        if channel_name:
            text.append(f" ({channel_name})", style=Colors.DIM)
        text.append("\n")

        # Timestamp
        timestamp = self.entry.get('timestamp', None)
        if timestamp:
            time_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            text.append("Time: ", style="bold bright_cyan")
            text.append(f"{time_str}\n", style=Colors.TEXT)

        # Packet ID
        packet_id = packet.get('id')
        if packet_id:
            text.append("Packet ID: ", style="bold bright_cyan")
            text.append(f"{packet_id}\n", style=Colors.DIM)

        text.append("\n")

        # Delivery info (TX messages)
        if is_tx:
            delivered = packet.get('_delivered')
            text.append("Delivery: ", style="bold bright_cyan")
            if delivered is None:
                text.append("Pending\n", style="bright_yellow")
            elif delivered:
                text.append("Delivered\n", style="bright_green")
            else:
                error = packet.get('_error_reason', 'Unknown')
                text.append(f"Failed ({error})\n", style="bright_red")

        # Hop info (received messages)
        if not is_tx:
            hop_start = packet.get('hopStart')
            hop_limit = packet.get('hopLimit')
            if hop_start is not None and hop_limit is not None:
                hops = hop_start - hop_limit
                text.append("Hops: ", style="bold bright_cyan")
                text.append(f"{hops}", style="bright_green")
                text.append(f" (start: {hop_start}, limit: {hop_limit})\n", style=Colors.DIM)

            # Signal info
            snr = packet.get('rxSnr')
            rssi = packet.get('rxRssi')
            if snr is not None:
                text.append("SNR: ", style="bold bright_cyan")
                text.append(f"{snr} dB\n", style=Colors.TEXT)
            if rssi is not None:
                text.append("RSSI: ", style="bold bright_cyan")
                text.append(f"{rssi} dBm\n", style=Colors.TEXT)

        # Sender node details
        if from_id:
            node = self.state.nodes.get_node(from_id)
            if node:
                text.append("\n")
                text.append("Node Info\n", style="bold bright_cyan")
                user = node.get('user', {})

                hw_model = user.get('hwModel')
                if hw_model:
                    text.append("  Hardware: ", style=Colors.DIM)
                    text.append(f"{hw_model}\n", style=Colors.TEXT)

                hops_away = node.get('hopsAway')
                if hops_away is not None:
                    text.append("  Hops away: ", style=Colors.DIM)
                    text.append(f"{hops_away}\n", style=Colors.TEXT)

                last_heard = node.get('lastHeard')
                if last_heard:
                    heard_str = datetime.fromtimestamp(last_heard).strftime('%Y-%m-%d %H:%M:%S')
                    text.append("  Last heard: ", style=Colors.DIM)
                    text.append(f"{heard_str}\n", style=Colors.TEXT)

                node_snr = node.get('snr')
                if node_snr is not None:
                    text.append("  Node SNR: ", style=Colors.DIM)
                    text.append(f"{node_snr} dB\n", style=Colors.TEXT)

        return text

    def _get_node_display(self, node_id) -> str:
        """Get display name for a node ID."""
        if not node_id:
            return "???"
        node = self.state.nodes.get_node(node_id)
        if node:
            user = node.get('user', {})
            return user.get('longName') or user.get('shortName') or format_node_id(node_id)
        return format_node_id(node_id)

    def action_close(self):
        self.dismiss()
