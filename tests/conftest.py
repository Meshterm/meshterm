"""Core test fixtures for meshterm tests."""

import time
from pathlib import Path
from typing import Any, List, Tuple
from unittest.mock import MagicMock

import pytest

from meshterm.storage import LogStorage
from meshterm.state import AppState, NodeStore, MessageBuffer, OpenDMsState, Settings

# ============================================================================
# Storage Fixtures
# ============================================================================


@pytest.fixture
def in_memory_storage():
    """Create an in-memory SQLite storage for testing."""
    storage = LogStorage(db_path=Path(":memory:"))
    yield storage
    storage.close()


# ============================================================================
# State Fixtures
# ============================================================================


@pytest.fixture
def empty_state(in_memory_storage):
    """Create an empty AppState with in-memory storage."""
    state = AppState(storage=in_memory_storage)
    return state


@pytest.fixture
def populated_state(in_memory_storage, sample_nodes, sample_packets):
    """Create an AppState pre-populated with sample data."""
    state = AppState(storage=in_memory_storage)

    # Import sample nodes
    state.nodes.import_nodes(sample_nodes)

    # Add sample packets
    for packet in sample_packets:
        state.messages.add(packet)

    # Set connection info
    state.set_connected(True, {"my_node_id": "!12345678"})

    return state


@pytest.fixture
def node_store(in_memory_storage):
    """Create an isolated NodeStore for testing."""
    return NodeStore(storage=in_memory_storage)


@pytest.fixture
def message_buffer(in_memory_storage):
    """Create an isolated MessageBuffer for testing."""
    return MessageBuffer(storage=in_memory_storage)


@pytest.fixture
def open_dms_state():
    """Create an isolated OpenDMsState for testing."""
    return OpenDMsState()


@pytest.fixture
def settings():
    """Create fresh Settings instance (does not load from disk)."""
    return Settings()


# ============================================================================
# Sample Data Fixtures
# ============================================================================


@pytest.fixture
def sample_nodes():
    """Sample node data for testing."""
    return {
        "!12345678": {
            "num": 0x12345678,
            "user": {
                "id": "!12345678",
                "longName": "Test Node Alpha",
                "shortName": "ALPH",
                "hwModel": "TBEAM",
            },
            "position": {
                "latitude": 37.7749,
                "longitude": -122.4194,
                "altitude": 10,
            },
            "lastHeard": int(time.time()) - 60,
        },
        "!87654321": {
            "num": 0x87654321,
            "user": {
                "id": "!87654321",
                "longName": "Test Node Beta",
                "shortName": "BETA",
                "hwModel": "HELTEC_V3",
            },
            "position": {
                "latitude": 37.8044,
                "longitude": -122.2712,
                "altitude": 50,
            },
            "lastHeard": int(time.time()) - 300,
        },
        "!aabbccdd": {
            "num": 0xAABBCCDD,
            "user": {
                "id": "!aabbccdd",
                "longName": "Test Node Gamma",
                "shortName": "GAMM",
                "hwModel": "RAK4631",
            },
            "lastHeard": int(time.time()) - 3600,
        },
    }


@pytest.fixture
def sample_packets():
    """Sample packet data for testing."""
    base_time = int(time.time())
    return [
        # Text message (broadcast)
        {
            "id": 1001,
            "from": 0x12345678,
            "to": 0xFFFFFFFF,
            "channel": 0,
            "decoded": {
                "portnum": "TEXT_MESSAGE_APP",
                "text": "Hello mesh!",
            },
            "rxSnr": 8.5,
            "rxRssi": -85,
            "hopLimit": 3,
            "hopStart": 3,
            "rxTime": base_time - 120,
        },
        # Text message (DM)
        {
            "id": 1002,
            "from": 0x87654321,
            "to": 0x12345678,
            "channel": 0,
            "decoded": {
                "portnum": "TEXT_MESSAGE_APP",
                "text": "Private message",
            },
            "rxSnr": 6.0,
            "rxRssi": -92,
            "hopLimit": 2,
            "hopStart": 3,
            "rxTime": base_time - 60,
        },
        # Position update
        {
            "id": 1003,
            "from": 0xAABBCCDD,
            "to": 0xFFFFFFFF,
            "channel": 0,
            "decoded": {
                "portnum": "POSITION_APP",
                "position": {
                    "latitude": 37.7749,
                    "longitude": -122.4194,
                    "altitude": 25,
                    "satsInView": 8,
                },
            },
            "rxSnr": 10.0,
            "rxRssi": -78,
            "hopLimit": 3,
            "hopStart": 3,
            "rxTime": base_time - 30,
        },
        # Telemetry
        {
            "id": 1004,
            "from": 0x12345678,
            "to": 0xFFFFFFFF,
            "channel": 0,
            "decoded": {
                "portnum": "TELEMETRY_APP",
                "telemetry": {
                    "deviceMetrics": {
                        "batteryLevel": 85,
                        "voltage": 4.1,
                        "channelUtilization": 5.2,
                        "airUtilTx": 1.3,
                    },
                },
            },
            "rxSnr": 9.0,
            "rxRssi": -80,
            "hopLimit": 3,
            "hopStart": 3,
            "rxTime": base_time - 15,
        },
        # Node info
        {
            "id": 1005,
            "from": 0x87654321,
            "to": 0xFFFFFFFF,
            "channel": 0,
            "decoded": {
                "portnum": "NODEINFO_APP",
                "user": {
                    "id": "!87654321",
                    "longName": "Test Node Beta Updated",
                    "shortName": "BTAU",
                    "hwModel": "HELTEC_V3",
                },
            },
            "rxSnr": 7.5,
            "rxRssi": -88,
            "hopLimit": 3,
            "hopStart": 3,
            "rxTime": base_time - 5,
        },
    ]


@pytest.fixture
def text_message_packet():
    """A single text message packet for focused testing."""
    return {
        "id": 9999,
        "from": 0x12345678,
        "to": 0xFFFFFFFF,
        "channel": 0,
        "decoded": {
            "portnum": "TEXT_MESSAGE_APP",
            "text": "Test message",
        },
        "rxSnr": 8.0,
        "rxRssi": -85,
        "hopLimit": 3,
        "hopStart": 3,
        "rxTime": int(time.time()),
    }


# ============================================================================
# Event Collector Fixture
# ============================================================================


class EventCollector:
    """Collects events from Observable objects for testing."""

    def __init__(self):
        self.events: List[Tuple[str, Any]] = []

    def callback(self, event_type: str, data: Any = None):
        """Callback to register with Observable.subscribe()."""
        self.events.append((event_type, data))

    def clear(self):
        """Clear collected events."""
        self.events.clear()

    def get_events(self, event_type: str = None) -> List[Tuple[str, Any]]:
        """Get events, optionally filtered by type."""
        if event_type is None:
            return list(self.events)
        return [(t, d) for t, d in self.events if t == event_type]

    def count(self, event_type: str = None) -> int:
        """Count events, optionally filtered by type."""
        return len(self.get_events(event_type))


@pytest.fixture
def event_collector():
    """Create an event collector for testing Observable notifications."""
    return EventCollector()


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_serial_interface():
    """Create a mock Meshtastic SerialInterface."""
    interface = MagicMock()

    # Mock myInfo
    interface.myInfo = MagicMock()
    interface.myInfo.my_node_num = 0x12345678

    # Mock localNode
    interface.localNode = MagicMock()
    interface.localNode.localConfig = MagicMock()
    interface.localNode.localConfig.lora = MagicMock()
    interface.localNode.localConfig.lora.region = "US"
    interface.localNode.localConfig.lora.modem_preset = "LONG_FAST"

    # Mock channels
    interface.localNode.channels = []

    # Mock nodes dict
    interface.nodes = {
        0x12345678: {
            "num": 0x12345678,
            "user": {
                "id": "!12345678",
                "longName": "My Node",
                "shortName": "MINE",
            },
        },
    }

    # Mock sendText method
    def mock_send_text(text, destinationId="^all", channelIndex=0, wantAck=True):
        mock_packet = MagicMock()
        mock_packet.id = 12345
        return mock_packet

    interface.sendText = MagicMock(side_effect=mock_send_text)

    return interface
