"""UI tests for log search navigation."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from meshterm.app import MeshtermApp
from meshterm.state import AppState
from meshterm.storage import LogStorage

pytestmark = pytest.mark.ui


@pytest.fixture
def test_app_with_messages(sample_packets):
    """Create app with some messages in the log."""
    storage = LogStorage(db_path=Path(":memory:"))
    state = AppState(storage=storage)

    for packet in sample_packets:
        state.messages.add(packet)

    connection = MagicMock()
    connection.interface = None
    connection.port = None
    connection.state = state

    app = MeshtermApp(state=state, connection=connection)
    return app


class TestLogSearchUI:
    """Tests for log search UI behavior."""

    @pytest.mark.asyncio
    async def test_search_bar_opens_on_slash(self, test_app_with_messages):
        """Pressing / on log view should open search bar."""
        async with test_app_with_messages.run_test() as pilot:
            # Switch to log view
            await pilot.press("l")
            await pilot.pause()

            # Press / to open search
            await pilot.press("/")
            await pilot.pause()

            # Search bar should be visible
            from meshterm.views.log import LogView
            log_view = test_app_with_messages.query_one(LogView)
            search_bar = log_view.query_one(".search-bar")
            assert "visible" in search_bar.classes

    @pytest.mark.asyncio
    async def test_escape_closes_search(self, test_app_with_messages):
        """Escape should close search bar."""
        async with test_app_with_messages.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            await pilot.press("/")
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            from meshterm.views.log import LogView
            log_view = test_app_with_messages.query_one(LogView)
            search_bar = log_view.query_one(".search-bar")
            assert "visible" not in search_bar.classes

    @pytest.mark.asyncio
    async def test_typing_triggers_search(self, test_app_with_messages):
        """Typing in search input should trigger live search."""
        async with test_app_with_messages.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            await pilot.press("/")
            await pilot.pause()

            # Type a search term
            await pilot.press("h", "e", "l", "l", "o")
            await pilot.pause()

            # LogPanel should have search active
            log_panel = test_app_with_messages.query_one("#log-panel")
            assert log_panel._search_term == "hello"

    @pytest.mark.asyncio
    async def test_search_is_case_insensitive(self, test_app_with_messages):
        """Search should be case-insensitive."""
        async with test_app_with_messages.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            # Open search and type uppercase
            await pilot.press("/")
            await pilot.pause()

            await pilot.press("H", "E", "L", "L", "O")
            await pilot.pause()

            # Should still find lowercase "hello" in messages
            log_panel = test_app_with_messages.query_one("#log-panel")
            # The search term is stored lowercase
            assert log_panel._search_term == "hello"

    @pytest.mark.asyncio
    async def test_enter_focuses_log_panel(self, test_app_with_messages):
        """After Enter in search, log panel should be focused for n/N."""
        async with test_app_with_messages.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            await pilot.press("/")
            await pilot.pause()

            await pilot.press("h", "e", "l", "l", "o")
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()

            log_panel = test_app_with_messages.query_one("#log-panel")
            assert test_app_with_messages.focused == log_panel

    @pytest.mark.asyncio
    async def test_search_activates_filter_mode(self, test_app_with_messages):
        """Typing a search term should activate filter mode."""
        async with test_app_with_messages.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            await pilot.press("/")
            await pilot.pause()

            await pilot.press("h", "e", "l", "l", "o")
            await pilot.pause()

            log_panel = test_app_with_messages.query_one("#log-panel")
            assert log_panel._filter_active is True

    @pytest.mark.asyncio
    async def test_escape_clears_filter_mode(self, test_app_with_messages):
        """Escape should clear filter mode and restore full log."""
        async with test_app_with_messages.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            await pilot.press("/")
            await pilot.pause()

            await pilot.press("h", "e", "l", "l", "o")
            await pilot.pause()

            log_panel = test_app_with_messages.query_one("#log-panel")
            assert log_panel._filter_active is True

            await pilot.press("escape")
            await pilot.pause()

            assert log_panel._filter_active is False
