"""Tests for protocol patterns in meshterm.connection module."""

from meshterm.connection import REACTION_PATTERN, REPLY_PATTERN
from meshterm.state import SUPPORTED_REACTIONS


class TestReactionPattern:
    """Tests for REACTION_PATTERN regex."""

    def test_valid_reaction_format(self):
        """Should match valid reaction format."""
        match = REACTION_PATTERN.match("[R:123456:👍]")

        assert match is not None
        assert match.group(1) == "123456"
        assert match.group(2) == "👍"

    def test_all_supported_reactions(self):
        """Should match all supported reaction emojis."""
        for emoji in SUPPORTED_REACTIONS.keys():
            text = f"[R:999:{emoji}]"
            match = REACTION_PATTERN.match(text)

            assert match is not None, f"Failed to match emoji: {emoji}"
            assert match.group(2) == emoji

    def test_large_packet_id(self):
        """Should match large packet IDs."""
        match = REACTION_PATTERN.match("[R:4294967295:❤️]")

        assert match is not None
        assert match.group(1) == "4294967295"

    def test_single_digit_packet_id(self):
        """Should match single digit packet IDs."""
        match = REACTION_PATTERN.match("[R:1:👍]")

        assert match is not None
        assert match.group(1) == "1"

    def test_no_match_without_brackets(self):
        """Should not match without proper brackets."""
        assert REACTION_PATTERN.match("R:123:👍") is None
        assert REACTION_PATTERN.match("[R:123:👍") is None
        assert REACTION_PATTERN.match("R:123:👍]") is None

    def test_no_match_missing_colon(self):
        """Should not match with missing colons."""
        assert REACTION_PATTERN.match("[R123:👍]") is None
        assert REACTION_PATTERN.match("[R:123👍]") is None

    def test_no_match_non_numeric_id(self):
        """Should not match non-numeric packet IDs."""
        assert REACTION_PATTERN.match("[R:abc:👍]") is None
        assert REACTION_PATTERN.match("[R:12.34:👍]") is None

    def test_no_match_empty_emoji(self):
        """Should not match empty emoji."""
        assert REACTION_PATTERN.match("[R:123:]") is None

    def test_no_match_regular_text(self):
        """Should not match regular text messages."""
        assert REACTION_PATTERN.match("Hello world!") is None
        assert REACTION_PATTERN.match("👍") is None
        assert REACTION_PATTERN.match("[123]") is None

    def test_no_match_with_trailing_text(self):
        """Should not match if there's trailing text."""
        # Pattern requires exact match (anchored at end with $)
        assert REACTION_PATTERN.match("[R:123:👍] extra text") is None

    def test_no_match_with_leading_text(self):
        """Should not match if there's leading text."""
        # Pattern requires exact match (anchored at start with ^)
        assert REACTION_PATTERN.match("prefix [R:123:👍]") is None

    def test_captures_multi_char_emoji(self):
        """Should capture multi-character emoji sequences."""
        # ❤️ is actually two characters: ❤ + variation selector
        match = REACTION_PATTERN.match("[R:123:❤️]")
        assert match is not None
        assert match.group(2) == "❤️"


class TestReplyPattern:
    """Tests for REPLY_PATTERN regex."""

    def test_valid_reply_format(self):
        """Should match valid reply format."""
        match = REPLY_PATTERN.match("[>:123456] Hello, this is a reply!")

        assert match is not None
        assert match.group(1) == "123456"
        assert match.group(2) == "Hello, this is a reply!"

    def test_large_packet_id(self):
        """Should match large packet IDs."""
        match = REPLY_PATTERN.match("[>:4294967295] Reply text")

        assert match is not None
        assert match.group(1) == "4294967295"

    def test_empty_message(self):
        """Should match with empty message."""
        match = REPLY_PATTERN.match("[>:123] ")

        assert match is not None
        assert match.group(1) == "123"
        assert match.group(2) == ""

    def test_multiline_message(self):
        """Should match multiline messages (DOTALL flag)."""
        text = "[>:123] First line\nSecond line\nThird line"
        match = REPLY_PATTERN.match(text)

        assert match is not None
        assert match.group(1) == "123"
        assert "First line" in match.group(2)
        assert "Second line" in match.group(2)
        assert "Third line" in match.group(2)

    def test_message_with_emoji(self):
        """Should match messages containing emoji."""
        match = REPLY_PATTERN.match("[>:123] I agree 👍")

        assert match is not None
        assert match.group(2) == "I agree 👍"

    def test_message_with_special_chars(self):
        """Should match messages with special characters."""
        match = REPLY_PATTERN.match("[>:123] Test [brackets] and (parens)!")

        assert match is not None
        assert match.group(2) == "Test [brackets] and (parens)!"

    def test_no_match_without_brackets(self):
        """Should not match without proper brackets."""
        assert REPLY_PATTERN.match(">:123 text") is None
        assert REPLY_PATTERN.match("[>:123 text") is None

    def test_no_match_missing_colon(self):
        """Should not match with missing colon."""
        assert REPLY_PATTERN.match("[>123] text") is None

    def test_no_match_non_numeric_id(self):
        """Should not match non-numeric packet IDs."""
        assert REPLY_PATTERN.match("[>:abc] text") is None

    def test_no_match_regular_text(self):
        """Should not match regular text messages."""
        assert REPLY_PATTERN.match("Hello world!") is None
        assert REPLY_PATTERN.match("Just some text") is None

    def test_no_match_reaction_format(self):
        """Should not match reaction format."""
        assert REPLY_PATTERN.match("[R:123:👍]") is None

    def test_preserves_leading_whitespace_in_message(self):
        """Leading whitespace after bracket is consumed by regex."""
        match = REPLY_PATTERN.match("[>:123]    multiple spaces")

        assert match is not None
        # The regex uses \s* which consumes leading whitespace
        assert match.group(2) == "multiple spaces"

    def test_no_space_between_bracket_and_message(self):
        """Should work without space between bracket and message."""
        match = REPLY_PATTERN.match("[>:123]NoSpace")

        assert match is not None
        assert match.group(2) == "NoSpace"


class TestPatternInteraction:
    """Tests for interaction between patterns."""

    def test_reaction_not_matched_by_reply(self):
        """Reaction format should not match reply pattern."""
        text = "[R:123:👍]"

        reaction_match = REACTION_PATTERN.match(text)
        reply_match = REPLY_PATTERN.match(text)

        assert reaction_match is not None
        assert reply_match is None

    def test_reply_not_matched_by_reaction(self):
        """Reply format should not match reaction pattern."""
        text = "[>:123] Hello"

        reaction_match = REACTION_PATTERN.match(text)
        reply_match = REPLY_PATTERN.match(text)

        assert reaction_match is None
        assert reply_match is not None

    def test_regular_message_matches_neither(self):
        """Regular messages should match neither pattern."""
        texts = [
            "Hello everyone!",
            "Meeting at 3pm",
            "[status] online",
            "Node !12345678 is back",
        ]

        for text in texts:
            assert REACTION_PATTERN.match(text) is None
            assert REPLY_PATTERN.match(text) is None


class TestPatternEdgeCases:
    """Edge case tests for protocol patterns."""

    def test_reaction_zero_packet_id(self):
        """Should match zero packet ID."""
        match = REACTION_PATTERN.match("[R:0:👍]")

        assert match is not None
        assert match.group(1) == "0"

    def test_reply_zero_packet_id(self):
        """Should match zero packet ID in reply."""
        match = REPLY_PATTERN.match("[>:0] text")

        assert match is not None
        assert match.group(1) == "0"

    def test_reaction_with_spaces_in_emoji(self):
        """Emoji with variation selectors should work."""
        # Some emoji have invisible variation selectors
        match = REACTION_PATTERN.match("[R:123:❗]")
        assert match is not None

    def test_reply_with_reaction_text(self):
        """Reply containing reaction-like text should work."""
        match = REPLY_PATTERN.match("[>:123] Check out this reaction [R:456:👍]")

        assert match is not None
        assert "[R:456:👍]" in match.group(2)

    def test_unicode_in_reply(self):
        """Reply with various unicode should work."""
        match = REPLY_PATTERN.match("[>:123] 你好世界 🌍 مرحبا")

        assert match is not None
        assert "你好世界" in match.group(2)
        assert "🌍" in match.group(2)
