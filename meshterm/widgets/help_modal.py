"""Context-aware help modal."""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Vertical
from textual.widgets import Static
from textual.binding import Binding
from rich.text import Text

from ..formatting import Colors


# Help content organized by context
HELP_CONTENT = {
    "global": {
        "title": "Global",
        "keys": [
            ("n", "Nodes view"),
            ("l", "Log view"),
            ("c", "Chat view"),
            ("s", "Settings view"),
            ("v", "Toggle verbose"),
            ("w", "Toggle favorites highlight"),
            ("q", "Quit"),
            ("Esc", "Go back"),
            ("^h", "This help"),
        ]
    },
    "nodes": {
        "title": "Nodes",
        "keys": [
            ("/", "Search nodes"),
            ("Enter", "View details"),
            ("f", "Toggle favorite"),
            ("i", "Invite to channel"),
            ("< / >", "Change sort column"),
            ("r", "Reverse sort"),
            ("j/k", "Navigate up/down"),
        ]
    },
    "chat": {
        "title": "Chat",
        "keys": [
            ("0-7", "Switch channel"),
            ("<- / ->", "Prev/next channel"),
            ("^r", "React to message"),
            ("^e", "Reply to message"),
            ("^j", "Channel manager"),
            ("x", "Close DM"),
            ("PgUp/Dn", "Scroll history"),
        ]
    },
    "detail": {
        "title": "Detail",
        "keys": [
            ("m", "Messages tab"),
            ("i", "Info tab"),
            ("<- / ->", "Prev/next tab"),
        ]
    },
    "settings": {
        "title": "Settings",
        "keys": [
            ("r", "Radio config"),
            ("h", "Channels config"),
            ("g", "GPS config"),
            ("e", "Device config"),
            ("<- / ->", "Prev/next tab"),
        ]
    },
    "log": {
        "title": "Log",
        "keys": [
            ("/", "Search log"),
            ("PgUp/Dn", "Scroll"),
        ]
    },
}


class HelpModal(ModalScreen):
    """Context-aware help modal showing keyboard shortcuts."""

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }

    #help-container {
        width: 70;
        height: auto;
        max-height: 22;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #help-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #help-content {
        height: auto;
    }

    .help-section {
        height: auto;
        margin-bottom: 1;
    }

    .help-section-title {
        text-style: bold;
        color: $text;
    }

    .help-keys {
        padding-left: 2;
    }

    #help-footer {
        text-align: center;
        color: $text-muted;
        padding-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
        Binding("ctrl+h", "close", "Close", show=False),
    ]

    def __init__(self, context: str = "global", **kwargs):
        """Initialize help modal.

        Args:
            context: Current view context (nodes, chat, detail, settings, log)
        """
        super().__init__(**kwargs)
        self.context = context

    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            yield Static("Keyboard Shortcuts", id="help-title")
            with Vertical(id="help-content"):
                # Show context-specific help first, then global
                if self.context in HELP_CONTENT and self.context != "global":
                    yield self._render_section(HELP_CONTENT[self.context])
                yield self._render_section(HELP_CONTENT["global"])
            yield Static("Press Esc or ^h to close", id="help-footer")

    def _render_section(self, section: dict) -> Static:
        """Render a help section."""
        text = Text()
        text.append(f"{section['title']}\n", style="bold bright_cyan")

        for key, desc in section["keys"]:
            text.append(f"  {key:12}", style="bold bright_green")
            text.append(f" {desc}\n", style=Colors.TEXT)

        return Static(text, classes="help-section")

    def action_close(self):
        """Close the help modal."""
        self.dismiss()
