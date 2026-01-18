"""Modal widget for selecting reaction emoji."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Static, Label
from rich.text import Text

from ..state import SUPPORTED_REACTIONS


class ReactionPicker(ModalScreen):
    """Modal for selecting a reaction emoji."""

    DEFAULT_CSS = """
    ReactionPicker {
        align: center middle;
    }

    ReactionPicker > Container {
        width: auto;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }

    ReactionPicker .title {
        text-align: center;
        padding-bottom: 1;
        text-style: bold;
    }

    ReactionPicker .reactions-row {
        width: auto;
        height: auto;
        padding: 0 1;
    }

    ReactionPicker .reaction-item {
        width: 6;
        height: 1;
        padding: 0 1;
        text-align: center;
    }

    ReactionPicker .hint {
        text-align: center;
        padding-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("1", "select_reaction('1')", "1", show=False, priority=True),
        Binding("2", "select_reaction('2')", "2", show=False, priority=True),
        Binding("3", "select_reaction('3')", "3", show=False, priority=True),
        Binding("4", "select_reaction('4')", "4", show=False, priority=True),
        Binding("5", "select_reaction('5')", "5", show=False, priority=True),
        Binding("6", "select_reaction('6')", "6", show=False, priority=True),
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
    ]

    class ReactionSelected(Message):
        """Posted when a reaction is selected."""
        def __init__(self, emoji: str, entry: dict):
            self.emoji = emoji
            self.entry = entry
            super().__init__()

    class Cancelled(Message):
        """Posted when picker is cancelled."""
        pass

    def __init__(self, entry: dict, sender_name: str = ""):
        """Initialize the reaction picker.

        Args:
            entry: The message entry being reacted to
            sender_name: Display name of message sender
        """
        super().__init__()
        self.entry = entry
        self.sender_name = sender_name
        self._reactions = list(SUPPORTED_REACTIONS.keys())

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(f"React to message from {self.sender_name}:", classes="title")

            # First row: 1-3
            with Horizontal(classes="reactions-row"):
                yield Static(self._format_item(1, self._reactions[0]), classes="reaction-item")
                yield Static(self._format_item(2, self._reactions[1]), classes="reaction-item")
                yield Static(self._format_item(3, self._reactions[2]), classes="reaction-item")

            # Second row: 4-6
            with Horizontal(classes="reactions-row"):
                yield Static(self._format_item(4, self._reactions[3]), classes="reaction-item")
                yield Static(self._format_item(5, self._reactions[4]), classes="reaction-item")
                yield Static(self._format_item(6, self._reactions[5]), classes="reaction-item")

            yield Label("Press 1-6 or Esc", classes="hint")

    def _format_item(self, num: int, emoji: str) -> Text:
        """Format a reaction item for display."""
        text = Text()
        text.append(f"[{num}]", style="dim")
        text.append(" ")
        text.append(emoji)
        return text

    def action_select_reaction(self, num: str):
        """Handle reaction selection by number."""
        try:
            index = int(num) - 1
            if 0 <= index < len(self._reactions):
                emoji = self._reactions[index]
                self.dismiss(emoji)
                self.post_message(self.ReactionSelected(emoji, self.entry))
        except (ValueError, IndexError):
            pass

    def action_cancel(self):
        """Cancel the picker."""
        self.dismiss(None)
        self.post_message(self.Cancelled())
