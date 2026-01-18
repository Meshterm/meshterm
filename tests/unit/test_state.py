"""Tests for meshterm.state module - state management classes."""

import time


from meshterm.state import (
    Observable,
    DMChannel,
    PendingMessage,
    Reaction,
    SelectionState,
    SUPPORTED_REACTIONS,
)


class TestObservable:
    """Tests for Observable mixin class."""

    def test_subscribe_callback(self, event_collector):
        """Subscribers should receive notifications."""
        obs = Observable()
        obs.subscribe(event_collector.callback)

        obs.notify("test_event", {"data": "value"})

        assert event_collector.count() == 1
        event_type, data = event_collector.events[0]
        assert event_type == "test_event"
        assert data == {"data": "value"}

    def test_multiple_subscribers(self, event_collector):
        """Multiple subscribers should all receive notifications."""
        obs = Observable()
        collector2 = type(event_collector)()

        obs.subscribe(event_collector.callback)
        obs.subscribe(collector2.callback)

        obs.notify("event", "data")

        assert event_collector.count() == 1
        assert collector2.count() == 1

    def test_unsubscribe(self, event_collector):
        """Unsubscribed callbacks should not receive notifications."""
        obs = Observable()
        obs.subscribe(event_collector.callback)
        obs.unsubscribe(event_collector.callback)

        obs.notify("event", None)

        assert event_collector.count() == 0

    def test_duplicate_subscribe(self, event_collector):
        """Same callback should not be added twice."""
        obs = Observable()
        obs.subscribe(event_collector.callback)
        obs.subscribe(event_collector.callback)

        obs.notify("event", None)

        # Should only be called once
        assert event_collector.count() == 1

    def test_unsubscribe_nonexistent(self, event_collector):
        """Unsubscribing non-existent callback should not raise."""
        obs = Observable()
        obs.unsubscribe(event_collector.callback)  # Should not raise

    def test_callback_exception_handled(self):
        """Callback exceptions should not stop other callbacks."""
        obs = Observable()
        calls = []

        def failing_callback(event_type, data):
            raise ValueError("Test error")

        def working_callback(event_type, data):
            calls.append((event_type, data))

        obs.subscribe(failing_callback)
        obs.subscribe(working_callback)

        obs.notify("event", "data")

        # Working callback should still be called
        assert len(calls) == 1


class TestNodeStore:
    """Tests for NodeStore class."""

    def test_update_and_get_node(self, node_store):
        """Should be able to store and retrieve nodes."""
        node_store.update_node(0x12345678, {"user": {"shortName": "TEST"}})

        node = node_store.get_node(0x12345678)
        assert node is not None
        assert node["user"]["shortName"] == "TEST"

    def test_update_merges_data(self, node_store):
        """Updates should merge with existing data."""
        node_store.update_node(0x12345678, {"user": {"shortName": "TEST"}})
        node_store.update_node(0x12345678, {"position": {"latitude": 37.0}})

        node = node_store.get_node(0x12345678)
        assert node["user"]["shortName"] == "TEST"
        assert node["position"]["latitude"] == 37.0

    def test_update_sets_last_heard(self, node_store):
        """Updates should set lastHeard timestamp."""
        before = int(time.time())
        node_store.update_node(0x12345678, {"user": {"shortName": "TEST"}})
        after = int(time.time())

        node = node_store.get_node(0x12345678)
        assert before <= node["lastHeard"] <= after

    def test_get_nonexistent_node(self, node_store):
        """Getting non-existent node should return None."""
        assert node_store.get_node(0x99999999) is None

    def test_get_all_nodes(self, node_store):
        """Should return all stored nodes."""
        node_store.update_node(0x11111111, {"user": {"shortName": "ONE"}})
        node_store.update_node(0x22222222, {"user": {"shortName": "TWO"}})

        all_nodes = node_store.get_all_nodes()
        assert len(all_nodes) == 2
        assert "!11111111" in all_nodes
        assert "!22222222" in all_nodes

    def test_import_nodes(self, node_store, sample_nodes, event_collector):
        """Should import multiple nodes and notify."""
        node_store.subscribe(event_collector.callback)
        node_store.import_nodes(sample_nodes)

        assert len(node_store.get_all_nodes()) == 3
        assert event_collector.count("nodes_imported") == 1

    def test_clear(self, node_store, event_collector):
        """Clear should remove all nodes and notify."""
        node_store.update_node(0x12345678, {"user": {"shortName": "TEST"}})
        node_store.subscribe(event_collector.callback)

        node_store.clear()

        assert len(node_store.get_all_nodes()) == 0
        assert event_collector.count("cleared") == 1

    def test_favorites(self, node_store):
        """Should track favorite status."""
        node_store.update_node(0x12345678, {"user": {"shortName": "TEST"}})

        assert not node_store.is_favorite(0x12345678)

        node_store.set_favorite(0x12345678, True)
        assert node_store.is_favorite(0x12345678)

        node_store.set_favorite(0x12345678, False)
        assert not node_store.is_favorite(0x12345678)

    def test_is_favorite_nonexistent(self, node_store):
        """is_favorite should return False for non-existent nodes."""
        assert not node_store.is_favorite(0x99999999)

    def test_notify_on_update(self, node_store, event_collector):
        """Should notify subscribers on node update."""
        node_store.subscribe(event_collector.callback)
        node_store.update_node(0x12345678, {"user": {"shortName": "TEST"}})

        assert event_collector.count("node_updated") == 1
        _, data = event_collector.get_events("node_updated")[0]
        assert data == "!12345678"


class TestMessageBuffer:
    """Tests for MessageBuffer class."""

    def test_add_message(self, message_buffer, text_message_packet):
        """Should add messages to buffer."""
        message_buffer.add(text_message_packet)

        assert len(message_buffer) == 1

    def test_get_all_messages(self, message_buffer, sample_packets):
        """Should return all messages."""
        for packet in sample_packets:
            message_buffer.add(packet)

        all_msgs = message_buffer.get_all()
        assert len(all_msgs) == len(sample_packets)

    def test_get_recent(self, message_buffer, sample_packets):
        """Should return most recent N messages."""
        for packet in sample_packets:
            message_buffer.add(packet)

        recent = message_buffer.get_recent(2)
        assert len(recent) == 2

    def test_get_text_messages(self, message_buffer, sample_packets):
        """Should filter to TEXT_MESSAGE_APP only."""
        for packet in sample_packets:
            message_buffer.add(packet)

        text_msgs = message_buffer.get_text_messages()
        assert len(text_msgs) == 2  # Two text messages in sample_packets

    def test_get_text_messages_channel_filter(self, message_buffer, sample_packets):
        """Should filter by channel."""
        for packet in sample_packets:
            message_buffer.add(packet)

        # All sample packets are channel 0
        text_msgs = message_buffer.get_text_messages(channel=0)
        assert len(text_msgs) == 2

        text_msgs = message_buffer.get_text_messages(channel=1)
        assert len(text_msgs) == 0

    def test_get_text_messages_broadcast_only(self, message_buffer, sample_packets):
        """Should filter to broadcasts only."""
        for packet in sample_packets:
            message_buffer.add(packet)

        # One broadcast text message in sample_packets
        text_msgs = message_buffer.get_text_messages(broadcast_only=True)
        assert len(text_msgs) == 1

    def test_get_for_node(self, message_buffer, sample_packets):
        """Should return messages involving specific node."""
        for packet in sample_packets:
            message_buffer.add(packet)

        # Messages involving node !12345678
        node_msgs = message_buffer.get_for_node(0x12345678)
        # 3 messages: text broadcast, DM received, telemetry
        assert len(node_msgs) >= 2

    def test_pending_message_tracking(self, message_buffer, text_message_packet):
        """Should track pending messages."""
        message_buffer.add(text_message_packet)
        message_buffer.add_pending(12345, text_message_packet, packet_id=9999)

        # Resolve as success
        result = message_buffer.resolve_pending(12345, True)
        assert result is not None
        assert result["_delivered"] is True

    def test_pending_message_failure(self, message_buffer, text_message_packet):
        """Should track failed delivery."""
        message_buffer.add(text_message_packet)
        message_buffer.add_pending(12345, text_message_packet, packet_id=9999)

        result = message_buffer.resolve_pending(12345, False, error_reason="NO_ROUTE")
        assert result is not None
        assert result["_delivered"] is False
        assert result["_error_reason"] == "NO_ROUTE"

    def test_resolve_nonexistent_pending(self, message_buffer):
        """Resolving non-existent pending should return None."""
        result = message_buffer.resolve_pending(99999, True)
        assert result is None

    def test_clear(self, message_buffer, sample_packets, event_collector):
        """Clear should remove all messages."""
        for packet in sample_packets:
            message_buffer.add(packet)

        message_buffer.subscribe(event_collector.callback)
        message_buffer.clear()

        assert len(message_buffer) == 0
        assert event_collector.count("cleared") == 1

    def test_notify_on_add(self, message_buffer, text_message_packet, event_collector):
        """Should notify on message add."""
        message_buffer.subscribe(event_collector.callback)
        message_buffer.add(text_message_packet)

        assert event_collector.count("message_added") == 1


class TestOpenDMsState:
    """Tests for OpenDMsState class."""

    def test_open_dm(self, open_dms_state, event_collector):
        """Should open DM and notify."""
        open_dms_state.subscribe(event_collector.callback)
        result = open_dms_state.open_dm("!12345678", "Test Node")

        assert result is True
        assert open_dms_state.is_dm_open("!12345678")
        assert event_collector.count("dm_opened") == 1

    def test_open_dm_already_open(self, open_dms_state):
        """Opening already open DM should return False."""
        open_dms_state.open_dm("!12345678", "Test Node")
        result = open_dms_state.open_dm("!12345678", "Test Node")

        assert result is False

    def test_close_dm(self, open_dms_state, event_collector):
        """Should close DM and notify."""
        open_dms_state.open_dm("!12345678", "Test Node")
        open_dms_state.subscribe(event_collector.callback)

        result = open_dms_state.close_dm("!12345678")

        assert result is True
        assert not open_dms_state.is_dm_open("!12345678")
        assert event_collector.count("dm_closed") == 1

    def test_close_dm_not_open(self, open_dms_state):
        """Closing not-open DM should return False."""
        result = open_dms_state.close_dm("!12345678")
        assert result is False

    def test_get_open_dms(self, open_dms_state):
        """Should return list of open DMs."""
        open_dms_state.open_dm("!12345678", "Node A")
        open_dms_state.open_dm("!87654321", "Node B")

        dms = open_dms_state.get_open_dms()
        assert len(dms) == 2
        assert all(isinstance(dm, DMChannel) for dm in dms)

    def test_notifications(self, open_dms_state, event_collector):
        """Should track and clear notification counts."""
        open_dms_state.open_dm("!12345678", "Test Node")
        open_dms_state.subscribe(event_collector.callback)

        # Increment
        count = open_dms_state.increment_notification("!12345678")
        assert count == 1
        count = open_dms_state.increment_notification("!12345678")
        assert count == 2

        assert open_dms_state.get_notification_count("!12345678") == 2
        assert event_collector.count("notification_updated") == 2

        # Clear
        open_dms_state.clear_notification("!12345678")
        assert open_dms_state.get_notification_count("!12345678") == 0
        assert event_collector.count("notification_cleared") == 1

    def test_close_dm_clears_notifications(self, open_dms_state):
        """Closing DM should clear its notifications."""
        open_dms_state.open_dm("!12345678", "Test Node")
        open_dms_state.increment_notification("!12345678")

        open_dms_state.close_dm("!12345678")

        assert open_dms_state.get_notification_count("!12345678") == 0

    def test_update_dm_name(self, open_dms_state, event_collector):
        """Should update DM display name."""
        open_dms_state.open_dm("!12345678", "Old Name")
        open_dms_state.subscribe(event_collector.callback)

        open_dms_state.update_dm_name("!12345678", "New Name")

        dms = open_dms_state.get_open_dms()
        assert dms[0].node_name == "New Name"
        assert event_collector.count("dm_updated") == 1


class TestSettings:
    """Tests for Settings dataclass."""

    def test_default_values(self, settings):
        """Should have correct default values."""
        assert settings.verbose is False
        assert settings.filter_types == []
        assert settings.selected_node is None
        assert settings.favorites_highlight is False
        assert settings.use_gps is True
        assert settings.manual_location is None

    def test_toggle_verbose(self, settings):
        """Should toggle verbose mode."""
        assert settings.verbose is False
        settings.toggle_verbose()
        assert settings.verbose is True
        settings.toggle_verbose()
        assert settings.verbose is False

    def test_toggle_favorites_highlight(self, settings):
        """Should toggle favorites highlighting."""
        assert settings.favorites_highlight is False
        settings.toggle_favorites_highlight()
        assert settings.favorites_highlight is True

    def test_set_selected_node(self, settings):
        """Should set selected node."""
        settings.set_selected_node("!12345678")
        assert settings.selected_node == "!12345678"

        settings.set_selected_node(None)
        assert settings.selected_node is None

    def test_subscribe_to_changes(self, settings):
        """Should notify on settings changes."""
        changes = []

        def callback(event_type, setting):
            changes.append(setting)

        settings.subscribe(callback)
        settings.toggle_verbose()

        assert "verbose" in changes

    def test_unsubscribe(self, settings):
        """Should allow unsubscribing."""
        changes = []

        def callback(event_type, setting):
            changes.append(setting)

        settings.subscribe(callback)
        settings.unsubscribe(callback)
        settings.toggle_verbose()

        assert len(changes) == 0


class TestAppState:
    """Tests for AppState container class."""

    def test_initialization(self, empty_state):
        """Should initialize with all components."""
        assert empty_state.nodes is not None
        assert empty_state.messages is not None
        assert empty_state.settings is not None
        assert empty_state.stats is not None
        assert empty_state.open_dms is not None

    def test_set_connected(self, empty_state):
        """Should set connection status."""
        empty_state.set_connected(True, {"my_node_id": "!12345678"})

        assert empty_state.connected is True
        assert empty_state.my_node_id == "!12345678"

    def test_channel_names(self, empty_state):
        """Should track channel names."""
        empty_state.channel_names[0] = "Primary"
        empty_state.channel_names[1] = "Secondary"

        assert empty_state.get_channel_name(0) == "Primary"
        assert empty_state.get_channel_name(1) == "Secondary"
        assert empty_state.get_channel_name(2) is None

    def test_my_position_from_gps(self, empty_state):
        """Should return GPS position when use_gps is True."""
        empty_state.set_my_position(37.7749, -122.4194)

        pos = empty_state.my_position
        assert pos == (37.7749, -122.4194)

    def test_my_position_from_manual(self, empty_state):
        """Should return manual position when use_gps is False."""
        empty_state.settings.use_gps = False
        empty_state.settings.manual_location = (40.0, -74.0)

        pos = empty_state.my_position
        assert pos == (40.0, -74.0)


class TestDataclasses:
    """Tests for state dataclasses."""

    def test_pending_message(self):
        """PendingMessage should store message info."""
        pm = PendingMessage(
            request_id=123,
            timestamp=time.time(),
            packet={"id": 456},
            packet_id=789,
        )
        assert pm.request_id == 123
        assert pm.packet_id == 789

    def test_reaction(self):
        """Reaction should store reaction info."""
        r = Reaction(emoji="👍", reactor_node="!12345678", timestamp=time.time())
        assert r.emoji == "👍"
        assert r.reactor_node == "!12345678"

    def test_selection_state(self):
        """SelectionState should store selection info."""
        ss = SelectionState(active=True, mode="react", selected_index=5)
        assert ss.active is True
        assert ss.mode == "react"
        assert ss.selected_index == 5

    def test_dm_channel(self):
        """DMChannel should store channel info."""
        dm = DMChannel(node_id="!12345678", node_name="Test Node")
        assert dm.node_id == "!12345678"
        assert dm.node_name == "Test Node"


class TestSupportedReactions:
    """Tests for SUPPORTED_REACTIONS constant."""

    def test_contains_expected_emojis(self):
        """Should contain expected emoji reactions."""
        expected = ["👍", "👎", "❤️", "😂", "❗", "❓"]
        for emoji in expected:
            assert emoji in SUPPORTED_REACTIONS

    def test_each_has_description(self):
        """Each reaction should have a description."""
        for emoji, description in SUPPORTED_REACTIONS.items():
            assert isinstance(description, str)
            assert len(description) > 0
