"""DM input widget for direct messages to a specific node."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static, Input
from textual.message import Message
from rich.text import Text

from ..state import AppState
from ..formatting import Colors


class DMInput(Horizontal):
    """Inline input widget for DMs (direct messages)."""

    DEFAULT_CSS = """
    DMInput {
        height: 1;
        width: 100%;
        background: $surface;
    }

    DMInput .dm-indicator {
        width: auto;
        padding: 0 1;
    }

    DMInput .dm-input-field {
        width: 1fr;
        border: none;
        height: 1;
        padding: 0;
    }
    """

    class MessageSubmitted(Message):
        """Posted when a DM is submitted."""

        def __init__(self, text: str, dest_node_id: str):
            self.text = text
            self.dest_node_id = dest_node_id
            super().__init__()

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        yield Static(self._format_indicator(), classes="dm-indicator", id="dm-indicator")
        yield Input(placeholder="Type message...", classes="dm-input-field", id="dm-input-field")

    def _format_indicator(self) -> Text:
        """Format DM indicator: DM >"""
        text = Text()
        text.append("DM", style="bold bright_magenta")
        text.append(" >", style=Colors.DIM)
        return text

    def on_input_submitted(self, event: Input.Submitted):
        """Handle Enter key in input."""
        if event.input.id == "dm-input-field":
            text = event.input.value.strip()
            dest_node_id = self.state.settings.selected_node
            if not dest_node_id:
                self.app.notify("No node selected for DM", severity="error", timeout=3)
                return

            # Check PKI status before sending
            node = self.state.nodes.get_node(dest_node_id)
            if node:
                has_key = node.get('has_public_key', False)
                if not has_key:
                    has_key = bool(node.get('user', {}).get('publicKey'))

                if not has_key:
                    self.app.notify(
                        "Cannot send DM: No public key. Wait for key exchange.",
                        severity="warning",
                        timeout=5
                    )
                    return

                # Check if node is unmessagable
                if node.get('user', {}).get('isUnmessagable'):
                    self.app.notify(
                        "Cannot send DM: Node is marked as unmessagable",
                        severity="warning",
                        timeout=5
                    )
                    return

            if text:
                self.post_message(self.MessageSubmitted(text, dest_node_id))
                event.input.value = ""

    def focus_input(self):
        """Focus the input field."""
        self.query_one("#dm-input-field", Input).focus()
