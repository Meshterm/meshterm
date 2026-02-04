"""Unit tests for log search functionality."""

import time
from pathlib import Path

import pytest

from meshterm.storage import LogStorage
from meshterm.widgets.log_panel import LogPanel


class TestStorageSearch:
    """Tests for LogStorage search methods."""

    @pytest.fixture
    def storage_with_data(self):
        """Create storage with various searchable packets."""
        storage = LogStorage(db_path=Path(":memory:"))
        base_time = time.time()

        packets = [
            {
                "id": 1001,
                "from": 0x12345678,
                "to": 0xFFFFFFFF,
                "channel": 0,
                "decoded": {
                    "portnum": "TEXT_MESSAGE_APP",
                    "text": "Hello world!",
                },
                "rxTime": base_time - 100,
            },
            {
                "id": 1002,
                "from": 0xAABBCCDD,
                "to": 0x12345678,
                "channel": 0,
                "decoded": {
                    "portnum": "TEXT_MESSAGE_APP",
                    "text": "Private message to you",
                },
                "rxTime": base_time - 90,
            },
            {
                "id": 1003,
                "from": 0x12345678,
                "to": 0xFFFFFFFF,
                "channel": 0,
                "decoded": {
                    "portnum": "POSITION_APP",
                    "position": {"latitude": 37.7749, "longitude": -122.4194},
                },
                "rxTime": base_time - 80,
            },
            {
                "id": 1004,
                "from": 0x87654321,
                "to": 0xFFFFFFFF,
                "channel": 0,
                "decoded": {
                    "portnum": "TELEMETRY_APP",
                    "telemetry": {"deviceMetrics": {"batteryLevel": 85}},
                },
                "rxTime": base_time - 70,
            },
            {
                "id": 1005,
                "from": 0x12345678,
                "to": 0xFFFFFFFF,
                "channel": 0,
                "decoded": {
                    "portnum": "TEXT_MESSAGE_APP",
                    "text": "Another hello message",
                },
                "rxTime": base_time - 60,
            },
        ]

        for packet in packets:
            storage.store_packet(packet, packet["rxTime"])

        yield storage
        storage.close()

    def test_search_by_text_content(self, storage_with_data):
        """search_packets should find messages by text content."""
        results = storage_with_data.search_packets("hello")
        assert len(results) == 2

    def test_search_does_not_match_node_id(self, storage_with_data):
        """search_packets should NOT find messages by raw node ID (only by name)."""
        # Raw node ID search should not match - we only search human-readable fields
        results = storage_with_data.search_packets("12345678")
        assert len(results) == 0

    def test_search_does_not_match_portnum(self, storage_with_data):
        """search_packets should NOT find messages by portnum (internal field)."""
        results = storage_with_data.search_packets("TELEMETRY")
        assert len(results) == 0

    def test_search_case_insensitive(self, storage_with_data):
        """search_packets should be case-insensitive."""
        results_lower = storage_with_data.search_packets("hello")
        results_upper = storage_with_data.search_packets("HELLO")
        results_mixed = storage_with_data.search_packets("HeLLo")
        assert len(results_lower) == len(results_upper) == len(results_mixed)

    def test_search_with_limit(self, storage_with_data):
        """search_packets should respect the limit parameter."""
        # Search for "hello" which matches 2 text messages
        results = storage_with_data.search_packets("hello", limit=1)
        assert len(results) == 1

    def test_search_with_before_id(self, storage_with_data):
        """search_packets should paginate with before_id."""
        all_results = storage_with_data.search_packets("hello")
        if len(all_results) > 1:
            first_id = all_results[0].id
            paginated = storage_with_data.search_packets("hello", before_id=first_id)
            assert all(r.id < first_id for r in paginated)

    def test_search_returns_ordered_by_id_desc(self, storage_with_data):
        """search_packets should return results ordered by id DESC."""
        results = storage_with_data.search_packets("hello")
        ids = [r.id for r in results]
        assert ids == sorted(ids, reverse=True)

    def test_count_search_results(self, storage_with_data):
        """count_search_results should return correct count."""
        count = storage_with_data.count_search_results("hello")
        assert count == 2

    def test_count_search_results_no_matches(self, storage_with_data):
        """count_search_results should return 0 for no matches."""
        count = storage_with_data.count_search_results("xyznonexistent")
        assert count == 0

    def test_search_no_matches(self, storage_with_data):
        """search_packets should return empty list for no matches."""
        results = storage_with_data.search_packets("xyznonexistent")
        assert results == []

    def test_search_by_node_name(self, storage_with_data):
        """search_packets should find messages by node name."""
        # Store a node with a specific name
        storage_with_data.store_node("!12345678", {
            "user": {"shortName": "CAT", "longName": "Cat Node"}
        })

        # Search by the node name
        results = storage_with_data.search_packets("Cat")
        # Should find packets from node !12345678
        assert len(results) >= 1
        assert any("12345678" in r.from_node for r in results)

    def test_count_search_by_node_name(self, storage_with_data):
        """count_search_results should include packets matching node names."""
        # Store a node with a specific name
        storage_with_data.store_node("!aabbccdd", {
            "user": {"shortName": "DOG", "longName": "Dog Node"}
        })

        # Count should include packets from/to that node
        count = storage_with_data.count_search_results("Dog")
        assert count >= 1


class TestLogPanelSearch:
    """Tests for LogPanel search methods."""

    def test_search_by_text_content(self, populated_state):
        """Search should find messages by text content."""
        panel = LogPanel(populated_state)
        # Simulate loading entries
        for entry in populated_state.messages.get_all():
            panel._displayed_entries.append(entry)

        count = panel.search("Hello")
        assert count >= 1

    def test_search_by_node_name(self, populated_state):
        """Search should find messages by node name."""
        panel = LogPanel(populated_state)
        for entry in populated_state.messages.get_all():
            panel._displayed_entries.append(entry)

        # Search for a node name (ALPH is the shortName for node !12345678)
        count = panel.search("ALPH")
        assert count >= 1

    def test_search_does_not_match_portnum(self, populated_state):
        """Search should NOT find messages by portnum (internal field)."""
        panel = LogPanel(populated_state)
        for entry in populated_state.messages.get_all():
            panel._displayed_entries.append(entry)

        count = panel.search("TELEMETRY")
        assert count == 0

    def test_search_case_insensitive(self, populated_state):
        """Search MUST be case-insensitive."""
        panel = LogPanel(populated_state)
        for entry in populated_state.messages.get_all():
            panel._displayed_entries.append(entry)

        count_lower = panel.search("hello")
        count_upper = panel.search("HELLO")
        count_mixed = panel.search("HeLLo")
        assert count_lower == count_upper == count_mixed

    def test_search_empty_string_returns_zero(self, populated_state):
        """Empty search should return 0 matches."""
        panel = LogPanel(populated_state)
        count = panel.search("")
        assert count == 0

    def test_search_no_matches(self, populated_state):
        """Search for non-existent term returns 0."""
        panel = LogPanel(populated_state)
        for entry in populated_state.messages.get_all():
            panel._displayed_entries.append(entry)

        count = panel.search("xyznonexistent123")
        assert count == 0

    def test_clear_search_resets_state(self, populated_state):
        """clear_search should reset all search state."""
        panel = LogPanel(populated_state)
        for entry in populated_state.messages.get_all():
            panel._displayed_entries.append(entry)

        panel.search("Hello")
        panel.clear_search()

        assert panel.get_match_count() == 0
        assert panel._search_term == ""

    def test_get_match_count_with_no_search(self, populated_state):
        """get_match_count should return 0 when no search performed."""
        panel = LogPanel(populated_state)
        assert panel.get_match_count() == 0

    def test_search_activates_filter_mode(self, populated_state):
        """Search should activate filter mode to show only matches."""
        panel = LogPanel(populated_state)
        for entry in populated_state.messages.get_all():
            panel._displayed_entries.append(entry)

        # Search for text content that exists in sample_packets
        panel.search("Hello")

        assert panel._filter_active is True
        assert len(panel._match_entries) > 0

    def test_clear_search_deactivates_filter_mode(self, populated_state):
        """Clearing search should deactivate filter mode."""
        panel = LogPanel(populated_state)
        for entry in populated_state.messages.get_all():
            panel._displayed_entries.append(entry)

        panel.search("Hello")
        assert panel._filter_active is True

        panel.clear_search()

        assert panel._filter_active is False
        assert panel._match_entries == []

    def test_empty_search_deactivates_filter(self, populated_state):
        """Searching with empty string should deactivate filter."""
        panel = LogPanel(populated_state)
        for entry in populated_state.messages.get_all():
            panel._displayed_entries.append(entry)

        panel.search("Hello")
        assert panel._filter_active is True

        panel.search("")

        assert panel._filter_active is False


class TestLogPanelDatabaseSearch:
    """Tests for LogPanel database search integration."""

    def test_search_uses_database_when_available(self, populated_state):
        """Search should query database when storage is available."""
        panel = LogPanel(populated_state)

        count = panel.search("Hello")
        assert panel._total_db_matches is not None
        assert count == panel._total_db_matches

    def test_search_sets_oldest_match_id(self, populated_state):
        """Search should track oldest match ID for pagination."""
        panel = LogPanel(populated_state)

        panel.search("Hello")
        if panel._match_entries:
            assert panel._oldest_match_id is not None

    def test_get_total_db_matches(self, populated_state):
        """get_total_db_matches should return database match count."""
        panel = LogPanel(populated_state)

        panel.search("Hello")
        db_matches = panel.get_total_db_matches()
        assert db_matches is not None
        assert db_matches >= len(panel._match_entries)

    def test_clear_search_resets_database_state(self, populated_state):
        """clear_search should reset database search state."""
        panel = LogPanel(populated_state)

        panel.search("Hello")
        panel.clear_search()

        assert panel._total_db_matches is None
        assert panel._oldest_match_id is None
        assert panel._search_exhausted is False

    def test_get_loaded_count(self, populated_state):
        """get_loaded_count should return displayed entries count."""
        panel = LogPanel(populated_state)
        for entry in populated_state.messages.get_all():
            panel._displayed_entries.append(entry)

        assert panel.get_loaded_count() == len(populated_state.messages.get_all())

    def test_get_total_count_with_storage(self, populated_state):
        """get_total_count should return database message count."""
        panel = LogPanel(populated_state)
        total = panel.get_total_count()
        assert total is not None
        assert total >= 0

    def test_is_history_exhausted_initially_false(self, populated_state):
        """is_history_exhausted should be False initially."""
        panel = LogPanel(populated_state)
        assert panel.is_history_exhausted() is False
