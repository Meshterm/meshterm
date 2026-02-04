"""Log view - streaming message log."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static, Input
from textual.binding import Binding
from textual import on

from ..state import AppState
from ..widgets.log_panel import LogPanel
from ..formatting import Colors


class LogView(Container):
    """Streaming log view showing all messages."""

    DEFAULT_CSS = """
    LogView {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    LogView > .search-bar {
        height: 1;
        display: none;
        background: $surface;
    }

    LogView > .search-bar.visible {
        display: block;
    }

    LogView > .search-bar Input {
        width: 100%;
        border: none;
        background: $surface;
    }

    LogView > LogPanel {
        height: 1fr;
        width: 100%;
        border: solid $primary;
    }

    LogView > .log-footer {
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("/", "start_search", "Search", show=False),
        Binding("escape", "handle_escape", "Close Search", show=False, priority=True),
        Binding("pagedown", "load_more_or_scroll", "Load more/scroll", show=False),
        Binding("pageup", "load_history_or_scroll", "Load history/scroll", show=False),
    ]

    def __init__(self, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._search_active = False

    def compose(self) -> ComposeResult:
        with Container(classes="search-bar"):
            yield Input(placeholder="Search log...", id="log-search-input", disabled=True)
        yield LogPanel(self.state, id="log-panel")
        yield Static("/=search  PgUp/Dn=scroll", classes="log-footer")

    def on_mount(self):
        """Load history when mounted."""
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.load_history()
        self._update_footer_with_counts()

    def on_show(self):
        """Called when view becomes visible."""
        # Focus the log panel so keybindings work
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.focus()

    def on_hide(self):
        """Called when view is hidden."""
        pass

    def action_start_search(self):
        """Activate search mode."""
        search_bar = self.query_one(".search-bar")
        search_bar.add_class("visible")
        search_input = self.query_one("#log-search-input", Input)
        search_input.disabled = False
        search_input.focus()
        self._search_active = True

    def on_input_changed(self, event: Input.Changed):
        """Handle search input changes - live search."""
        if event.input.id == "log-search-input":
            log_panel = self.query_one("#log-panel", LogPanel)
            count = log_panel.search(event.value)
            self._update_search_status(count)

    def on_input_submitted(self, event: Input.Submitted):
        """Handle Enter in search - close search bar, keep filter."""
        if event.input.id == "log-search-input":
            self._close_search_keep_filter()

    def action_handle_escape(self):
        """Handle escape - close search if active."""
        if self._search_active:
            self._close_search()
        else:
            self.app.action_go_back()

    def _close_search(self):
        """Close search bar and clear filter."""
        search_bar = self.query_one(".search-bar")
        search_bar.remove_class("visible")
        search_input = self.query_one("#log-search-input", Input)
        search_input.value = ""
        search_input.disabled = True
        self._search_active = False
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.clear_search()
        log_panel.focus()
        self._update_footer_default()

    def _close_search_keep_filter(self):
        """Close search bar but keep filter active."""
        search_bar = self.query_one(".search-bar")
        search_bar.remove_class("visible")
        search_input = self.query_one("#log-search-input", Input)
        search_input.disabled = True
        self._search_active = False

        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.focus()

        count = log_panel.get_match_count()
        db_total = log_panel.get_total_db_matches()
        footer = self.query_one(".log-footer", Static)

        if db_total is not None and db_total > 0:
            if count < db_total:
                footer.update(f"{count} matches (of {db_total})  PgDn=more  Esc=clear")
            else:
                footer.update(f"{db_total} matches  Esc=clear")
        elif count > 0:
            footer.update(f"{count} matches  Esc=clear")
        else:
            footer.update("No matches  Esc=clear")

    def _update_search_status(self, total_matches: int):
        """Update footer with search status."""
        log_panel = self.query_one("#log-panel", LogPanel)
        footer = self.query_one(".log-footer", Static)

        db_total = log_panel.get_total_db_matches()
        loaded_matches = log_panel.get_match_count()

        if db_total is not None and db_total > 0:
            if loaded_matches < db_total:
                footer.update(f"{loaded_matches} matches (of {db_total})  PgDn=more  Esc=close")
            else:
                footer.update(f"{db_total} matches  Esc=close")
        elif total_matches > 0:
            footer.update(f"{total_matches} matches  Esc=close")
        else:
            footer.update("No matches  Esc=close")

    def _update_footer_default(self):
        """Reset footer to default text."""
        self._update_footer_with_counts()

    def _update_footer_with_counts(self):
        """Update footer with loaded/total counts."""
        if self._search_active:
            return

        log_panel = self.query_one("#log-panel", LogPanel)
        footer = self.query_one(".log-footer", Static)

        loaded = log_panel.get_loaded_count()
        total = log_panel.get_total_count()
        exhausted = log_panel.is_history_exhausted()

        if exhausted:
            footer.update(f"/=search  (all {loaded} loaded)")
        elif total:
            footer.update(f"/=search  PgUp=more  ({loaded}/{total} loaded)")
        else:
            footer.update(f"/=search  PgUp=more  ({loaded} loaded)")

    def action_load_more_or_scroll(self):
        """Handle Page Down - load more search results or scroll."""
        log_panel = self.query_one("#log-panel", LogPanel)
        if log_panel._filter_active:
            if log_panel.load_more_search_results():
                self._update_search_status(log_panel.get_match_count())
            else:
                self.app.bell()
        else:
            log_panel.action_page_down()

    def action_load_history_or_scroll(self):
        """Handle Page Up - load more history or scroll."""
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.action_page_up()
        self._update_footer_with_counts()

    @on(LogPanel.HistoryLoaded)
    def _handle_history_loaded(self, event: LogPanel.HistoryLoaded):
        """Handle history loaded message from LogPanel."""
        self._update_footer_with_counts()
