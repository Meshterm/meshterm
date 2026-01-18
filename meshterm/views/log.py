"""Log view - streaming message log."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from ..state import AppState
from ..widgets.log_panel import LogPanel
from ..formatting import Colors


class LogView(Container):
    """Streaming log view showing all messages."""

    DEFAULT_CSS = """
    LogView {
        height: 100%;
        width: 100%;
    }

    LogView > LogPanel {
        height: 100%;
        width: 100%;
        border: solid $primary;
    }
    """

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        yield LogPanel(self.state, id="log-panel")

    def on_mount(self):
        """Load history when mounted."""
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.load_history()

    def on_show(self):
        """Called when view becomes visible."""
        pass

    def on_hide(self):
        """Called when view is hidden."""
        pass
