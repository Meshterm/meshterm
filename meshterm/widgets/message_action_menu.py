"""Modal action menu for a selected chat message."""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Vertical
from textual.widgets import Static, Label
from textual.binding import Binding
from rich.text import Text

from ..formatting import Colors


class MessageActionMenu(ModalScreen):
    """Modal menu of actions for a selected message."""

    DEFAULT_CSS = """
    MessageActionMenu {
        align: center middle;
    }

    MessageActionMenu > Container {
        width: auto;
        min-width: 30;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }

    MessageActionMenu .title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    MessageActionMenu .actions-list {
        height: auto;
        padding: 0 1;
    }

    MessageActionMenu .action-item {
        height: 1;
        padding: 0;
    }

    MessageActionMenu .hint {
        text-align: center;
        padding-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("1", "pick('1')", show=False, priority=True),
        Binding("2", "pick('2')", show=False, priority=True),
        Binding("3", "pick('3')", show=False, priority=True),
        Binding("4", "pick('4')", show=False, priority=True),
        Binding("5", "pick('5')", show=False, priority=True),
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
    ]

    def __init__(
        self,
        entry: dict,
        sender_name: str,
        is_own_message: bool,
        can_retransmit: bool,
        show_dm: bool,
    ):
        super().__init__()
        self.entry = entry
        self.sender_name = sender_name
        self.is_own_message = is_own_message
        self.can_retransmit = can_retransmit
        self.show_dm = show_dm
        self._actions: list[tuple[str, str]] = []  # (action_key, label)

    def compose(self) -> ComposeResult:
        # Build action list based on context
        self._actions = []
        self._actions.append(("reply", "Reply"))
        self._actions.append(("react", "React"))
        self._actions.append(("details", "Details"))
        if self.show_dm:
            self._actions.append(("dm", f"DM {self.sender_name}"))
        if self.can_retransmit:
            self._actions.append(("retransmit", "Re-transmit"))

        title = "Your message" if self.is_own_message else f"Message from {self.sender_name}"

        with Container():
            yield Label(title, classes="title")
            with Vertical(classes="actions-list"):
                for i, (_, label) in enumerate(self._actions):
                    yield Static(self._format_item(i + 1, label), classes="action-item")
            yield Label(f"Press 1-{len(self._actions)} or Esc", classes="hint")

    def _format_item(self, num: int, label: str) -> Text:
        text = Text()
        text.append(f"[{num}]", style="bold bright_green")
        text.append(f" {label}", style=Colors.TEXT)
        return text

    def action_pick(self, num: str):
        try:
            index = int(num) - 1
            if 0 <= index < len(self._actions):
                action_key = self._actions[index][0]
                self.dismiss((action_key, self.entry))
        except (ValueError, IndexError):
            pass

    def action_cancel(self):
        self.dismiss(None)
