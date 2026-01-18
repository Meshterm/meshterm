"""UI tests for application navigation using Textual Pilot.

Tests are consolidated to minimize app startup overhead - each run_test() call
takes ~0.5s, so we group related assertions into single test functions.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from meshterm.app import MeshtermApp
from meshterm.state import AppState
from meshterm.storage import LogStorage

pytestmark = pytest.mark.ui


@pytest.fixture
def test_app():
    """Create a MeshtermApp instance for testing."""
    storage = LogStorage(db_path=Path(":memory:"))
    state = AppState(storage=storage)

    connection = MagicMock()
    connection.interface = None
    connection.port = None
    connection.state = state

    app = MeshtermApp(state=state, connection=connection)
    return app


class TestAppStartupAndComponents:
    """Tests for app initialization and UI components."""

    @pytest.mark.asyncio
    async def test_app_starts_with_expected_components(self, test_app):
        """App should start with all expected UI components and state."""
        async with test_app.run_test():
            # App is running
            assert test_app.is_running

            # State is initialized
            assert test_app.state is not None
            assert test_app.state.nodes is not None
            assert test_app.state.messages is not None
            assert test_app.state.settings is not None

            # Not connected (no device)
            assert test_app.state.connected is False

            # UI components present
            assert len(test_app.query("#header-bar")) == 1
            assert len(test_app.query("#status-bar")) == 1
            assert len(test_app.query("#main-tabs")) == 1

            # Default tab is nodes
            assert test_app.query_one("#main-tabs").active == "nodes"


class TestTabNavigation:
    """Tests for tab switching via keyboard."""

    @pytest.mark.asyncio
    async def test_tab_switching_via_keys(self, test_app):
        """Tab hotkeys should switch between all tabs."""
        async with test_app.run_test() as pilot:
            tabs = test_app.query_one("#main-tabs")

            # Start at nodes (default)
            assert tabs.active == "nodes"

            # n -> nodes (no change)
            await pilot.press("n")
            assert tabs.active == "nodes"

            # l -> log
            await pilot.press("l")
            assert tabs.active == "log"

            # c -> chat
            await pilot.press("c")
            assert tabs.active == "chat"

            # escape to unfocus chat input, then s -> settings
            await pilot.press("escape")
            await pilot.press("s")
            assert tabs.active == "settings"

            # n -> back to nodes
            await pilot.press("n")
            assert tabs.active == "nodes"


class TestHelpModal:
    """Tests for help modal behavior."""

    @pytest.mark.asyncio
    async def test_help_modal_opens_and_closes(self, test_app):
        """Help modal should open via action and close via escape."""
        async with test_app.run_test() as pilot:
            from meshterm.widgets.help_modal import HelpModal

            # Initially no modal
            assert len(test_app.screen_stack) == 1

            # Open help modal
            await pilot.pause()
            test_app.action_show_help()
            await pilot.pause()

            # Modal is now on screen
            assert len(test_app.screen_stack) > 1
            assert isinstance(test_app.screen, HelpModal)

            # Close with escape
            await pilot.press("escape")
            await pilot.pause()

            # Back to main screen
            assert len(test_app.screen_stack) == 1


class TestSettingsToggles:
    """Tests for settings toggle keybindings."""

    @pytest.mark.asyncio
    async def test_verbose_and_favorites_toggles(self, test_app):
        """v and w keys should toggle their respective settings."""
        async with test_app.run_test() as pilot:
            # Verbose toggle
            initial_verbose = test_app.state.settings.verbose
            await pilot.press("v")
            assert test_app.state.settings.verbose != initial_verbose

            # Toggle back
            await pilot.press("v")
            assert test_app.state.settings.verbose == initial_verbose

            # Favorites highlight toggle
            initial_favorites = test_app.state.settings.favorites_highlight
            await pilot.press("w")
            assert test_app.state.settings.favorites_highlight != initial_favorites


class TestKeyboardBehavior:
    """Tests for other keyboard behaviors."""

    @pytest.mark.asyncio
    async def test_escape_and_quit_handling(self, test_app):
        """Escape and Ctrl+C should be handled gracefully."""
        async with test_app.run_test() as pilot:
            # Go to nodes tab and press escape (should not crash)
            await pilot.press("n")
            await pilot.press("escape")

            # App still running after escape
            assert test_app.is_running

            # Ctrl+C triggers quit
            await pilot.press("ctrl+c")
            # Test framework handles the exit gracefully
