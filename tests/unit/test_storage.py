"""Tests for meshterm.storage module - persistence layer."""

import time


from meshterm.storage import StoredMessage


class TestLogStorageSchema:
    """Tests for LogStorage schema creation."""

    def test_creates_tables(self, in_memory_storage):
        """Should create all required tables."""
        cursor = in_memory_storage._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}

        assert "packets" in tables
        assert "nodes" in tables
        assert "reactions" in tables
        assert "reply_refs" in tables

    def test_creates_indexes(self, in_memory_storage):
        """Should create indexes for performance."""
        cursor = in_memory_storage._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        indexes = {row[0] for row in cursor.fetchall()}

        assert "idx_timestamp" in indexes
        assert "idx_channel" in indexes
        assert "idx_from_node" in indexes
        assert "idx_portnum" in indexes


class TestLogStoragePackets:
    """Tests for packet storage operations."""

    def test_store_packet_returns_id(self, in_memory_storage, text_message_packet):
        """store_packet should return database ID."""
        db_id = in_memory_storage.store_packet(text_message_packet, time.time())

        assert db_id is not None
        assert db_id > 0

    def test_store_packet_increments_id(self, in_memory_storage, text_message_packet):
        """Each stored packet should get incrementing ID."""
        id1 = in_memory_storage.store_packet(text_message_packet, time.time())
        id2 = in_memory_storage.store_packet(text_message_packet, time.time())

        assert id2 == id1 + 1

    def test_get_text_messages(self, in_memory_storage, sample_packets):
        """Should retrieve TEXT_MESSAGE_APP messages."""
        for packet in sample_packets:
            in_memory_storage.store_packet(packet, time.time())

        messages = in_memory_storage.get_text_messages()

        assert len(messages) == 2  # Two text messages in sample_packets
        assert all(isinstance(m, StoredMessage) for m in messages)
        assert all(m.portnum in ("TEXT_MESSAGE_APP", "1") for m in messages)

    def test_get_text_messages_channel_filter(self, in_memory_storage, sample_packets):
        """Should filter by channel."""
        for packet in sample_packets:
            in_memory_storage.store_packet(packet, time.time())

        messages = in_memory_storage.get_text_messages(channel=0)
        assert len(messages) == 2

        messages = in_memory_storage.get_text_messages(channel=1)
        assert len(messages) == 0

    def test_get_text_messages_broadcast_only(self, in_memory_storage, sample_packets):
        """Should filter to broadcasts only."""
        for packet in sample_packets:
            in_memory_storage.store_packet(packet, time.time())

        messages = in_memory_storage.get_text_messages(broadcast_only=True)
        assert len(messages) == 1

    def test_get_text_messages_limit(self, in_memory_storage, text_message_packet):
        """Should respect limit parameter."""
        for i in range(10):
            packet = text_message_packet.copy()
            packet["id"] = 1000 + i
            in_memory_storage.store_packet(packet, time.time())

        messages = in_memory_storage.get_text_messages(limit=5)
        assert len(messages) == 5

    def test_get_text_messages_pagination(self, in_memory_storage, text_message_packet):
        """Should support pagination with before_id."""
        ids = []
        for i in range(10):
            packet = text_message_packet.copy()
            packet["id"] = 1000 + i
            db_id = in_memory_storage.store_packet(packet, time.time())
            ids.append(db_id)

        # Get messages before ID 6 (should get IDs 1-5)
        messages = in_memory_storage.get_text_messages(before_id=ids[5], limit=10)
        assert len(messages) == 5
        assert all(m.id < ids[5] for m in messages)

    def test_get_messages_for_node(self, in_memory_storage, sample_packets):
        """Should retrieve messages for specific node."""
        for packet in sample_packets:
            in_memory_storage.store_packet(packet, time.time())

        # Messages for node !12345678
        messages = in_memory_storage.get_messages_for_node("!12345678")
        assert len(messages) >= 1

    def test_get_all_packets(self, in_memory_storage, sample_packets):
        """Should retrieve all packets."""
        for packet in sample_packets:
            in_memory_storage.store_packet(packet, time.time())

        packets = in_memory_storage.get_all_packets()
        assert len(packets) == len(sample_packets)

    def test_get_all_packets_portnum_filter(self, in_memory_storage, sample_packets):
        """Should filter by portnum."""
        for packet in sample_packets:
            in_memory_storage.store_packet(packet, time.time())

        packets = in_memory_storage.get_all_packets(portnum_filter=["POSITION_APP", "3"])
        assert len(packets) == 1
        assert packets[0].portnum in ("POSITION_APP", "3")

    def test_find_message_by_packet_id(self, in_memory_storage, text_message_packet):
        """Should find message by Meshtastic packet ID."""
        in_memory_storage.store_packet(text_message_packet, time.time())

        found = in_memory_storage.find_message_by_packet_id(text_message_packet["id"])
        assert found is not None
        assert found.packet_id == text_message_packet["id"]

    def test_find_message_by_packet_id_not_found(self, in_memory_storage):
        """Should return None for non-existent packet ID."""
        found = in_memory_storage.find_message_by_packet_id(99999)
        assert found is None

    def test_update_delivery_status(self, in_memory_storage, text_message_packet):
        """Should update delivery status for sent messages."""
        packet = text_message_packet.copy()
        packet["_tx"] = True
        in_memory_storage.store_packet(packet, time.time())

        in_memory_storage.update_delivery_status(packet["id"], delivered=True, error_reason=None)

        found = in_memory_storage.find_message_by_packet_id(packet["id"])
        assert found.delivered is True

    def test_update_delivery_status_with_error(self, in_memory_storage, text_message_packet):
        """Should store error reason for failed delivery."""
        packet = text_message_packet.copy()
        packet["_tx"] = True
        in_memory_storage.store_packet(packet, time.time())

        in_memory_storage.update_delivery_status(
            packet["id"], delivered=False, error_reason="NO_ROUTE"
        )

        found = in_memory_storage.find_message_by_packet_id(packet["id"])
        assert found.delivered is False
        assert found.error_reason == "NO_ROUTE"


class TestLogStorageNodes:
    """Tests for node storage operations."""

    def test_store_node(self, in_memory_storage, sample_nodes):
        """Should store node data."""
        node_data = sample_nodes["!12345678"]
        in_memory_storage.store_node("!12345678", node_data)

        nodes = in_memory_storage.get_all_nodes()
        assert "!12345678" in nodes

    def test_store_node_updates(self, in_memory_storage):
        """Storing same node should update data."""
        in_memory_storage.store_node("!12345678", {"user": {"shortName": "OLD"}})
        in_memory_storage.store_node("!12345678", {"user": {"shortName": "NEW"}})

        nodes = in_memory_storage.get_all_nodes()
        assert nodes["!12345678"]["user"]["shortName"] == "NEW"

    def test_get_all_nodes(self, in_memory_storage, sample_nodes):
        """Should retrieve all stored nodes."""
        for node_id, node_data in sample_nodes.items():
            in_memory_storage.store_node(node_id, node_data)

        nodes = in_memory_storage.get_all_nodes()
        assert len(nodes) == 3

    def test_clear_nodes(self, in_memory_storage, sample_nodes):
        """Should clear all nodes."""
        for node_id, node_data in sample_nodes.items():
            in_memory_storage.store_node(node_id, node_data)

        count = in_memory_storage.clear_nodes()
        assert count == 3

        nodes = in_memory_storage.get_all_nodes()
        assert len(nodes) == 0


class TestLogStorageReactions:
    """Tests for reaction storage operations."""

    def test_store_reaction(self, in_memory_storage, text_message_packet):
        """Should store a reaction."""
        db_id = in_memory_storage.store_packet(text_message_packet, time.time())

        added = in_memory_storage.store_reaction(
            message_db_id=db_id,
            message_packet_id=text_message_packet["id"],
            reactor_node="!87654321",
            emoji="👍",
            timestamp=time.time(),
        )

        assert added is True

    def test_store_reaction_toggle_off(self, in_memory_storage, text_message_packet):
        """Storing same reaction twice should toggle it off."""
        db_id = in_memory_storage.store_packet(text_message_packet, time.time())

        # First store
        added1 = in_memory_storage.store_reaction(
            message_db_id=db_id,
            message_packet_id=text_message_packet["id"],
            reactor_node="!87654321",
            emoji="👍",
            timestamp=time.time(),
        )
        assert added1 is True

        # Second store (same reaction) should toggle off
        added2 = in_memory_storage.store_reaction(
            message_db_id=db_id,
            message_packet_id=text_message_packet["id"],
            reactor_node="!87654321",
            emoji="👍",
            timestamp=time.time(),
        )
        assert added2 is False

        # Reaction should be removed
        reactions = in_memory_storage.get_reactions_for_message(db_id)
        assert len(reactions) == 0

    def test_get_reactions_for_message(self, in_memory_storage, text_message_packet):
        """Should retrieve reactions for a message."""
        db_id = in_memory_storage.store_packet(text_message_packet, time.time())

        in_memory_storage.store_reaction(
            db_id, text_message_packet["id"], "!11111111", "👍", time.time()
        )
        in_memory_storage.store_reaction(
            db_id, text_message_packet["id"], "!22222222", "❤️", time.time()
        )

        reactions = in_memory_storage.get_reactions_for_message(db_id)
        assert len(reactions) == 2
        emojis = {r["emoji"] for r in reactions}
        assert emojis == {"👍", "❤️"}

    def test_get_reactions_for_messages_batch(self, in_memory_storage, text_message_packet):
        """Should retrieve reactions for multiple messages efficiently."""
        ids = []
        for i in range(3):
            packet = text_message_packet.copy()
            packet["id"] = 1000 + i
            db_id = in_memory_storage.store_packet(packet, time.time())
            ids.append(db_id)
            # Add reaction to each
            in_memory_storage.store_reaction(db_id, packet["id"], "!12345678", "👍", time.time())

        reactions = in_memory_storage.get_reactions_for_messages(ids)

        assert len(reactions) == 3
        for db_id in ids:
            assert db_id in reactions
            assert len(reactions[db_id]) == 1


class TestLogStorageReplyRefs:
    """Tests for reply reference storage operations."""

    def test_store_reply_ref(self, in_memory_storage, text_message_packet):
        """Should store reply reference."""
        # Store parent message
        parent_id = in_memory_storage.store_packet(text_message_packet, time.time())

        # Store reply
        reply_packet = text_message_packet.copy()
        reply_packet["id"] = 2000
        reply_id = in_memory_storage.store_packet(reply_packet, time.time())

        # Store reference
        parent_db_id = in_memory_storage.store_reply_ref(
            reply_db_id=reply_id,
            parent_packet_id=text_message_packet["id"],
            timestamp=time.time(),
        )

        assert parent_db_id == parent_id

    def test_get_reply_ref(self, in_memory_storage, text_message_packet):
        """Should retrieve reply reference."""
        parent_id = in_memory_storage.store_packet(text_message_packet, time.time())

        reply_packet = text_message_packet.copy()
        reply_packet["id"] = 2000
        reply_id = in_memory_storage.store_packet(reply_packet, time.time())

        in_memory_storage.store_reply_ref(reply_id, text_message_packet["id"], time.time())

        ref = in_memory_storage.get_reply_ref(reply_id)
        assert ref is not None
        assert ref["parent_db_id"] == parent_id
        assert ref["parent_packet_id"] == text_message_packet["id"]

    def test_get_parent_message(self, in_memory_storage, text_message_packet):
        """Should retrieve parent message from reply."""
        parent_id = in_memory_storage.store_packet(text_message_packet, time.time())

        reply_packet = text_message_packet.copy()
        reply_packet["id"] = 2000
        reply_id = in_memory_storage.store_packet(reply_packet, time.time())

        in_memory_storage.store_reply_ref(reply_id, text_message_packet["id"], time.time())

        parent = in_memory_storage.get_parent_message(reply_id)
        assert parent is not None
        assert parent.id == parent_id


class TestLogStorageDataManagement:
    """Tests for data management operations."""

    def test_clear_messages(self, in_memory_storage, sample_packets, text_message_packet):
        """Should clear all messages, reactions, and reply refs."""
        for packet in sample_packets:
            in_memory_storage.store_packet(packet, time.time())

        # Add a reaction
        db_id = in_memory_storage.store_packet(text_message_packet, time.time())
        in_memory_storage.store_reaction(
            db_id, text_message_packet["id"], "!12345678", "👍", time.time()
        )

        count = in_memory_storage.clear_messages()
        assert count == len(sample_packets) + 1

        messages = in_memory_storage.get_all_packets()
        assert len(messages) == 0

    def test_clear_all_data(self, in_memory_storage, sample_packets, sample_nodes):
        """Should clear all data."""
        for packet in sample_packets:
            in_memory_storage.store_packet(packet, time.time())
        for node_id, node_data in sample_nodes.items():
            in_memory_storage.store_node(node_id, node_data)

        result = in_memory_storage.clear_all_data()

        assert result["messages"] == len(sample_packets)
        assert result["nodes"] == len(sample_nodes)

        assert len(in_memory_storage.get_all_packets()) == 0
        assert len(in_memory_storage.get_all_nodes()) == 0

    def test_get_stats(self, in_memory_storage, sample_packets, sample_nodes, text_message_packet):
        """Should return storage statistics."""
        for packet in sample_packets:
            in_memory_storage.store_packet(packet, time.time())
        for node_id, node_data in sample_nodes.items():
            in_memory_storage.store_node(node_id, node_data)

        # Add a reaction
        db_id = in_memory_storage.store_packet(text_message_packet, time.time())
        in_memory_storage.store_reaction(
            db_id, text_message_packet["id"], "!12345678", "👍", time.time()
        )

        stats = in_memory_storage.get_stats()

        assert stats["messages"] == len(sample_packets) + 1
        assert stats["nodes"] == len(sample_nodes)
        assert stats["reactions"] == 1


class TestStoredMessage:
    """Tests for StoredMessage dataclass."""

    def test_to_entry(self, in_memory_storage, text_message_packet):
        """Should convert to MessageBuffer entry format."""
        db_id = in_memory_storage.store_packet(text_message_packet, time.time())

        found = in_memory_storage.find_message_by_packet_id(text_message_packet["id"])
        entry = found.to_entry()

        assert "packet" in entry
        assert "timestamp" in entry
        assert entry["_db_id"] == db_id

    def test_stored_message_fields(self, in_memory_storage, text_message_packet):
        """Should have all expected fields."""
        in_memory_storage.store_packet(text_message_packet, time.time())

        found = in_memory_storage.find_message_by_packet_id(text_message_packet["id"])

        assert found.id is not None
        assert found.timestamp > 0
        assert found.packet_id == text_message_packet["id"]
        assert found.from_node is not None
        assert found.to_node is not None
        assert found.channel == 0
        assert found.portnum in ("TEXT_MESSAGE_APP", "1")


class TestLogStorageEnumHandling:
    """Tests for handling enum values in packet data."""

    def test_handles_enum_in_packet(self, in_memory_storage):
        """Should serialize enum values correctly."""
        from enum import Enum

        class TestEnum(Enum):
            VALUE = "test_value"

        packet = {
            "id": 1234,
            "from": 0x12345678,
            "to": 0xFFFFFFFF,
            "channel": 0,
            "decoded": {
                "portnum": TestEnum.VALUE,
                "text": "Test",
            },
        }

        # Should not raise
        db_id = in_memory_storage.store_packet(packet, time.time())
        assert db_id is not None

    def test_handles_bytes_in_packet(self, in_memory_storage):
        """Should serialize bytes values correctly."""
        packet = {
            "id": 1234,
            "from": 0x12345678,
            "to": 0xFFFFFFFF,
            "channel": 0,
            "decoded": {
                "portnum": "TEXT_MESSAGE_APP",
                "data": b"\x00\x01\x02\x03",
            },
        }

        db_id = in_memory_storage.store_packet(packet, time.time())
        assert db_id is not None
