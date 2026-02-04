"""UI tests for ChatLog text wrapping on narrow screens."""

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from meshterm.app import MeshtermApp
from meshterm.state import AppState
from meshterm.storage import LogStorage
from meshterm.widgets.chat_log import ChatLog

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


@pytest.fixture
def chat_state():
    """Create AppState with a sender node for chat tests."""
    storage = LogStorage(db_path=Path(":memory:"))
    state = AppState(storage=storage)

    # Add a node to be the message sender
    state.nodes.import_nodes({
        "!12345678": {
            "num": 0x12345678,
            "user": {
                "id": "!12345678",
                "longName": "Test Sender",
                "shortName": "TEST",
                "hwModel": "TBEAM",
            },
            "lastHeard": int(time.time()),
        },
    })

    state.set_connected(True, {"my_node_id": "!aabbccdd"})
    return state


def make_text_packet(text: str, from_id: int = 0x12345678) -> dict:
    """Create a text message packet."""
    return {
        "id": int(time.time() * 1000),
        "from": from_id,
        "to": 0xFFFFFFFF,
        "channel": 0,
        "decoded": {
            "portnum": "TEXT_MESSAGE_APP",
            "text": text,
        },
        "hopLimit": 3,
        "hopStart": 3,
        "rxTime": int(time.time()),
    }


class TestChatLogWrapping:
    """Tests for ChatLog text wrapping behavior."""

    def test_scrollbar_width_constant_exists(self):
        """ChatLog should define SCROLLBAR_WIDTH constant."""
        assert hasattr(ChatLog, 'SCROLLBAR_WIDTH')
        assert ChatLog.SCROLLBAR_WIDTH == 8

    @pytest.mark.asyncio
    async def test_narrow_screen_wrapping_60_cols(self, test_app):
        """Text should wrap correctly at 60 columns (narrow screen)."""
        async with test_app.run_test(size=(60, 24)) as pilot:
            # Switch to chat tab
            await pilot.press("c")
            await pilot.pause()

            # Find the ChatLog widget
            chat_log = test_app.query_one(ChatLog)

            # Create a long message that should wrap
            long_text = "This is a test message that should wrap properly on narrow screens without hiding under scrollbar"
            entry = {
                'packet': make_text_packet(long_text),
                'timestamp': time.time(),
            }

            # Render the message
            chat_log._render_message(entry)
            await pilot.pause()

            # Verify the message was added
            assert len(chat_log._displayed_entries) == 1

    @pytest.mark.asyncio
    async def test_very_narrow_screen_48_cols(self, test_app):
        """Text should wrap correctly at 48 columns (very narrow screen)."""
        async with test_app.run_test(size=(48, 24)) as pilot:
            await pilot.press("c")
            await pilot.pause()

            chat_log = test_app.query_one(ChatLog)

            # Message that should wrap on narrow screen
            text = "A moderately long message to test narrow wrapping behavior"
            entry = {
                'packet': make_text_packet(text),
                'timestamp': time.time(),
            }

            chat_log._render_message(entry)
            await pilot.pause()

            assert len(chat_log._displayed_entries) == 1

    @pytest.mark.asyncio
    async def test_long_word_force_break(self, test_app):
        """Very long words without spaces should be force-broken."""
        async with test_app.run_test(size=(60, 24)) as pilot:
            await pilot.press("c")
            await pilot.pause()

            chat_log = test_app.query_one(ChatLog)

            # A word longer than available width
            long_word = "supercalifragilisticexpialidociousandmorecharacterstoexceedwidth"
            entry = {
                'packet': make_text_packet(long_word),
                'timestamp': time.time(),
            }

            chat_log._render_message(entry)
            await pilot.pause()

            assert len(chat_log._displayed_entries) == 1


class TestWrapTextMethod:
    """Unit tests for the _wrap_text method."""

    def test_wrap_text_normal(self, chat_state):
        """Normal text should wrap at word boundaries."""
        chat_log = ChatLog(state=chat_state)
        text = "Hello world this is a test"
        lines = chat_log._wrap_text(text, 15)

        assert len(lines) > 1
        for line in lines:
            assert len(line) <= 15

    def test_wrap_text_long_word(self, chat_state):
        """Long words should be force-broken."""
        chat_log = ChatLog(state=chat_state)
        text = "abcdefghijklmnopqrstuvwxyz"
        lines = chat_log._wrap_text(text, 10)

        assert len(lines) > 1
        for line in lines:
            assert len(line) <= 10

    def test_wrap_text_unicode_emoji(self, chat_state):
        """Unicode and emoji widths should be measured correctly."""
        chat_log = ChatLog(state=chat_state)
        # Emojis typically have cell width of 2
        text = "Hello 👋 world 🌍"
        lines = chat_log._wrap_text(text, 20)

        # Should produce valid output without crash
        assert len(lines) >= 1
        assert "👋" in " ".join(lines)
        assert "🌍" in " ".join(lines)

    def test_wrap_text_empty(self, chat_state):
        """Empty text should return empty string."""
        chat_log = ChatLog(state=chat_state)
        lines = chat_log._wrap_text("", 50)
        assert lines == ['']

    def test_wrap_text_zero_width(self, chat_state):
        """Zero or negative width should return original text."""
        chat_log = ChatLog(state=chat_state)
        text = "test message"
        lines = chat_log._wrap_text(text, 0)
        assert lines == [text]

        lines = chat_log._wrap_text(text, -5)
        assert lines == [text]

    def test_wrap_preserves_content(self, chat_state):
        """Wrapped text should preserve all content when rejoined."""
        chat_log = ChatLog(state=chat_state)
        original = "The quick brown fox jumps over the lazy dog"
        lines = chat_log._wrap_text(original, 15)

        # Rejoin and compare (removing extra spaces from line breaks)
        rejoined = " ".join(lines)
        assert rejoined == original

    def test_wrap_first_line_width(self, chat_state):
        """First line can have different width than continuation lines."""
        chat_log = ChatLog(state=chat_state)
        # First line width 10, continuation width 20
        text = "Hello world this is a longer test message"
        lines = chat_log._wrap_text(text, 20, first_line_width=10)

        # First line should be shorter
        assert len(lines) >= 2
        assert len(lines[0]) <= 10
        # Continuation lines can be longer
        for line in lines[1:]:
            assert len(line) <= 20

    def test_wrap_first_line_width_preserves_content(self, chat_state):
        """Different first line width should still preserve all content."""
        chat_log = ChatLog(state=chat_state)
        original = "The quick brown fox jumps over the lazy dog"
        lines = chat_log._wrap_text(original, 25, first_line_width=12)

        rejoined = " ".join(lines)
        assert rejoined == original
