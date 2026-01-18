"""Integration tests for message flow through state and storage."""

import time

import pytest

from meshterm.state import AppState


class TestStateStorageIntegration:
    """Tests for State + Storage integration."""

    def test_message_add_persists_to_storage(self, in_memory_storage):
        """Adding message to buffer should persist to storage."""
        state = AppState(storage=in_memory_storage)
        packet = {
            "id": 1001,
            "from": 0x12345678,
            "to": 0xFFFFFFFF,
            "channel": 0,
            "decoded": {
                "portnum": "TEXT_MESSAGE_APP",
                "text": "Test message",
            },
        }

        # Add to message buffer
        db_id = state.messages.add(packet)

        # Verify persisted to storage
        stored = in_memory_storage.find_message_by_packet_id(1001)
        assert stored is not None
        assert stored.id == db_id

    def test_node_update_persists_to_storage(self, in_memory_storage):
        """Updating node should persist to storage."""
        state = AppState(storage=in_memory_storage)

        # Update node
        state.nodes.update_node(
            0x12345678,
            {
                "user": {"shortName": "TEST", "longName": "Test Node"},
            },
        )

        # Verify persisted to storage
        nodes = in_memory_storage.get_all_nodes()
        assert "!12345678" in nodes
        assert nodes["!12345678"]["user"]["shortName"] == "TEST"

    def test_load_nodes_from_storage(self, in_memory_storage):
        """Nodes should be loadable from storage."""
        # Store nodes directly in storage
        in_memory_storage.store_node(
            "!12345678",
            {
                "num": 0x12345678,
                "user": {"shortName": "STORED"},
            },
        )
        in_memory_storage.store_node(
            "!87654321",
            {
                "num": 0x87654321,
                "user": {"shortName": "OTHER"},
            },
        )

        # Create state and load from storage
        state = AppState(storage=in_memory_storage)
        state.nodes.load_from_storage()

        # Verify nodes loaded
        assert len(state.nodes.get_all_nodes()) == 2
        assert state.nodes.get_node("!12345678")["user"]["shortName"] == "STORED"


class TestObservableNotifications:
    """Tests for Observable notification flow."""

    def test_message_add_notifies_subscribers(self, in_memory_storage, event_collector):
        """Adding message should notify subscribers."""
        state = AppState(storage=in_memory_storage)
        state.messages.subscribe(event_collector.callback)

        state.messages.add(
            {
                "id": 1001,
                "from": 0x12345678,
                "to": 0xFFFFFFFF,
                "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "Test"},
            }
        )

        assert event_collector.count("message_added") == 1

    def test_node_update_notifies_subscribers(self, in_memory_storage, event_collector):
        """Updating node should notify subscribers."""
        state = AppState(storage=in_memory_storage)
        state.nodes.subscribe(event_collector.callback)

        state.nodes.update_node(0x12345678, {"user": {"shortName": "TEST"}})

        assert event_collector.count("node_updated") == 1

    def test_multiple_updates_multiple_notifications(self, in_memory_storage, event_collector):
        """Each update should generate a notification."""
        state = AppState(storage=in_memory_storage)
        state.messages.subscribe(event_collector.callback)

        for i in range(5):
            state.messages.add(
                {
                    "id": 1000 + i,
                    "from": 0x12345678,
                    "to": 0xFFFFFFFF,
                    "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": f"Test {i}"},
                }
            )

        assert event_collector.count("message_added") == 5


class TestPendingMessageFlow:
    """Tests for pending message resolution flow."""

    def test_pending_message_success_flow(self, in_memory_storage, event_collector):
        """Successful message delivery should update state and storage."""
        state = AppState(storage=in_memory_storage)
        state.messages.subscribe(event_collector.callback)

        # Add a sent message
        packet = {
            "id": 1001,
            "from": 0x12345678,
            "to": 0x87654321,
            "_tx": True,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "Hello"},
        }
        state.messages.add(packet)

        # Track as pending
        state.messages.add_pending(request_id=12345, packet=packet, packet_id=1001)

        # Resolve as success
        result = state.messages.resolve_pending(12345, success=True)

        # Verify packet updated
        assert result["_delivered"] is True

        # Verify notification sent
        assert event_collector.count("delivery_updated") == 1

    def test_pending_message_failure_flow(self, in_memory_storage, event_collector):
        """Failed message delivery should update state and storage."""
        state = AppState(storage=in_memory_storage)
        state.messages.subscribe(event_collector.callback)

        packet = {
            "id": 1001,
            "from": 0x12345678,
            "to": 0x87654321,
            "_tx": True,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "Hello"},
        }
        state.messages.add(packet)
        state.messages.add_pending(12345, packet, packet_id=1001)

        # Resolve as failure
        result = state.messages.resolve_pending(12345, success=False, error_reason="NO_ROUTE")

        assert result["_delivered"] is False
        assert result["_error_reason"] == "NO_ROUTE"

        # Verify storage updated
        stored = in_memory_storage.find_message_by_packet_id(1001)
        assert stored.delivered is False
        assert stored.error_reason == "NO_ROUTE"


class TestDMNotificationFlow:
    """Tests for DM notification flow."""

    def test_dm_notification_increment_and_clear(self, empty_state, event_collector):
        """DM notifications should increment and clear correctly."""
        empty_state.open_dms.subscribe(event_collector.callback)

        # Open DM
        empty_state.open_dms.open_dm("!12345678", "Test Node")

        # Simulate incoming messages
        empty_state.open_dms.increment_notification("!12345678")
        empty_state.open_dms.increment_notification("!12345678")
        empty_state.open_dms.increment_notification("!12345678")

        assert empty_state.open_dms.get_notification_count("!12345678") == 3

        # Clear (e.g., user opened DM tab)
        empty_state.open_dms.clear_notification("!12345678")

        assert empty_state.open_dms.get_notification_count("!12345678") == 0

        # Verify events
        assert event_collector.count("dm_opened") == 1
        assert event_collector.count("notification_updated") == 3
        assert event_collector.count("notification_cleared") == 1


class TestReactionStorageFlow:
    """Tests for reaction storage through state."""

    def test_reaction_stored_with_message(self, in_memory_storage):
        """Reactions should be stored and retrievable with message."""
        state = AppState(storage=in_memory_storage)

        # Add a message
        packet = {
            "id": 1001,
            "from": 0x12345678,
            "to": 0xFFFFFFFF,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "Hello!"},
        }
        db_id = state.messages.add(packet)

        # Add reaction via storage
        in_memory_storage.store_reaction(
            message_db_id=db_id,
            message_packet_id=1001,
            reactor_node="!87654321",
            emoji="👍",
            timestamp=time.time(),
        )

        # Retrieve reactions
        reactions = in_memory_storage.get_reactions_for_message(db_id)
        assert len(reactions) == 1
        assert reactions[0]["emoji"] == "👍"
        assert reactions[0]["reactor_node"] == "!87654321"


class TestStorageRoundtrip:
    """Tests for data integrity through storage roundtrip."""

    def test_packet_roundtrip(self, in_memory_storage):
        """Packet data should survive storage roundtrip."""
        original_packet = {
            "id": 1001,
            "from": 0x12345678,
            "to": 0x87654321,
            "channel": 2,
            "rxSnr": 8.5,
            "rxRssi": -85,
            "hopLimit": 2,
            "hopStart": 3,
            "decoded": {
                "portnum": "TEXT_MESSAGE_APP",
                "text": "Hello with special chars: 日本語 🎉",
            },
        }

        # Store
        timestamp = time.time()
        in_memory_storage.store_packet(original_packet, timestamp)

        # Retrieve
        stored = in_memory_storage.find_message_by_packet_id(1001)

        # Verify key fields
        assert stored.packet_id == 1001
        assert stored.from_node == "!12345678"
        assert stored.to_node == "!87654321"
        assert stored.channel == 2
        assert stored.snr == pytest.approx(8.5)
        assert stored.rssi == -85
        assert stored.hops == 1  # hopStart - hopLimit

        # Verify payload preserved
        assert "Hello with special chars" in stored.raw_packet["decoded"]["text"]
        assert "日本語" in stored.raw_packet["decoded"]["text"]

    def test_node_roundtrip(self, in_memory_storage):
        """Node data should survive storage roundtrip."""
        original_node = {
            "num": 0x12345678,
            "user": {
                "id": "!12345678",
                "longName": "Test Node with Unicode: 测试",
                "shortName": "TEST",
                "hwModel": "TBEAM",
            },
            "position": {
                "latitude": 37.7749,
                "longitude": -122.4194,
                "altitude": 100,
            },
            "deviceMetrics": {
                "batteryLevel": 85,
                "voltage": 4.1,
            },
        }

        # Store
        in_memory_storage.store_node("!12345678", original_node)

        # Retrieve
        nodes = in_memory_storage.get_all_nodes()
        stored = nodes["!12345678"]

        # Verify
        assert stored["user"]["longName"] == "Test Node with Unicode: 测试"
        assert stored["position"]["latitude"] == 37.7749
        assert stored["deviceMetrics"]["batteryLevel"] == 85
