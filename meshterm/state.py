"""Shared state - node store, message buffer, settings."""

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any, Optional, TYPE_CHECKING
import time

if TYPE_CHECKING:
    from .storage import LogStorage


@dataclass
class PendingMessage:
    """Track a sent message awaiting ACK."""
    request_id: int
    timestamp: float
    packet: dict  # Reference to the packet in MessageBuffer
    packet_id: Optional[int] = None  # Meshtastic packet ID for delivery tracking


@dataclass
class Reaction:
    """A reaction (tapback) on a message."""
    emoji: str
    reactor_node: str
    timestamp: float


@dataclass
class SelectionState:
    """State for message selection mode in chat."""
    active: bool = False
    mode: str = ""  # "react" or "reply"
    selected_index: int = 0


# Supported reactions with their meanings
SUPPORTED_REACTIONS = {
    '👍': 'Thumbs up',
    '👎': 'Thumbs down',
    '❤️': 'Love',
    '😂': 'Laugh',
    '❗': 'Important',
    '❓': 'Question',
}

from .formatting import format_node_id, get_node_position


class Observable:
    """Mixin for observable pattern - allows views to subscribe to updates."""

    def __init__(self):
        self._listeners: List[Callable] = []

    def subscribe(self, callback: Callable):
        """Subscribe to updates."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback: Callable):
        """Unsubscribe from updates."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def notify(self, event_type: str = "update", data: Any = None):
        """Notify all listeners of an update."""
        for callback in self._listeners:
            try:
                callback(event_type, data)
            except Exception:
                pass


@dataclass
class DMChannel:
    """Represents an open DM conversation."""
    node_id: str
    node_name: str


class OpenDMsState(Observable):
    """State for tracking open DM conversations and notifications."""

    def __init__(self):
        super().__init__()
        self._open_dms: List[DMChannel] = []
        self._notifications: Dict[str, int] = {}  # node_id -> unread count

    def get_open_dms(self) -> List[DMChannel]:
        """Get list of open DM conversations."""
        return list(self._open_dms)

    def open_dm(self, node_id: str, node_name: str) -> bool:
        """Open a DM conversation. Returns True if newly opened."""
        node_id = format_node_id(node_id)
        if not self.is_dm_open(node_id):
            self._open_dms.append(DMChannel(node_id=node_id, node_name=node_name))
            self.notify("dm_opened", node_id)
            return True
        return False

    def close_dm(self, node_id: str) -> bool:
        """Close a DM conversation. Returns True if was open."""
        node_id = format_node_id(node_id)
        for i, dm in enumerate(self._open_dms):
            if dm.node_id == node_id:
                self._open_dms.pop(i)
                # Clear notifications for this DM
                self._notifications.pop(node_id, None)
                self.notify("dm_closed", node_id)
                return True
        return False

    def is_dm_open(self, node_id: str) -> bool:
        """Check if a DM conversation is open."""
        node_id = format_node_id(node_id)
        return any(dm.node_id == node_id for dm in self._open_dms)

    def increment_notification(self, node_id: str) -> int:
        """Increment unread count for a node. Returns new count."""
        node_id = format_node_id(node_id)
        count = self._notifications.get(node_id, 0) + 1
        self._notifications[node_id] = count
        self.notify("notification_updated", {"node_id": node_id, "count": count})
        return count

    def clear_notification(self, node_id: str):
        """Clear unread count for a node."""
        node_id = format_node_id(node_id)
        if node_id in self._notifications:
            del self._notifications[node_id]
            self.notify("notification_cleared", node_id)

    def get_notification_count(self, node_id: str) -> int:
        """Get unread count for a node."""
        node_id = format_node_id(node_id)
        return self._notifications.get(node_id, 0)

    def update_dm_name(self, node_id: str, node_name: str):
        """Update the display name for an open DM."""
        node_id = format_node_id(node_id)
        for dm in self._open_dms:
            if dm.node_id == node_id:
                dm.node_name = node_name
                self.notify("dm_updated", node_id)
                break


class NodeStore(Observable):
    """Store for node information with auto-updates."""

    def __init__(self, storage: "Optional[LogStorage]" = None):
        super().__init__()
        self._nodes: Dict[str, dict] = {}
        self._storage = storage

    def set_storage(self, storage: "LogStorage"):
        """Set the storage backend."""
        self._storage = storage

    def load_from_storage(self):
        """Load nodes from persistent storage into memory."""
        if self._storage:
            stored_nodes = self._storage.get_all_nodes()
            for node_id, node_data in stored_nodes.items():
                if node_id not in self._nodes:
                    self._nodes[node_id] = node_data
            if stored_nodes:
                self.notify("nodes_imported", None)

    def update_node(self, node_id, data: dict):
        """Update a node's data (merges with existing)."""
        node_id_str = format_node_id(node_id)

        if node_id_str not in self._nodes:
            self._nodes[node_id_str] = {'num': node_id}

        node = self._nodes[node_id_str]

        # Merge data
        for key, value in data.items():
            if isinstance(value, dict) and key in node and isinstance(node[key], dict):
                node[key].update(value)
            else:
                node[key] = value

        # Extract PKI status from user data if present
        user = data.get('user', {})
        if 'publicKey' in user:
            node['has_public_key'] = bool(user.get('publicKey'))

        # Update last seen
        node['lastHeard'] = int(time.time())

        # Persist to storage
        if self._storage:
            self._storage.store_node(node_id_str, node)

        self.notify("node_updated", node_id_str)

    def get_node(self, node_id) -> Optional[dict]:
        """Get node by ID."""
        node_id_str = format_node_id(node_id)
        return self._nodes.get(node_id_str)

    def get_all_nodes(self) -> Dict[str, dict]:
        """Get all nodes."""
        return self._nodes.copy()

    def import_nodes(self, nodes: dict):
        """Import nodes from interface (initial population)."""
        for node_id, node_data in nodes.items():
            node_id_str = format_node_id(node_data.get('num', node_id))
            node_copy = node_data.copy()
            # Convert isFavorite from Meshtastic lib to is_favorite
            if 'isFavorite' in node_copy:
                node_copy['is_favorite'] = node_copy.pop('isFavorite')
            # Extract PKI status from user data
            user = node_copy.get('user', {})
            if 'publicKey' in user:
                node_copy['has_public_key'] = bool(user.get('publicKey'))
            self._nodes[node_id_str] = node_copy
        self.notify("nodes_imported", None)

    def clear(self):
        """Clear all nodes."""
        self._nodes.clear()
        self.notify("cleared", None)

    def is_favorite(self, node_id) -> bool:
        """Check if a node is marked as favorite."""
        node_id_str = format_node_id(node_id)
        node = self._nodes.get(node_id_str)
        if node:
            return node.get('is_favorite', False)
        return False

    def set_favorite(self, node_id, is_favorite: bool):
        """Set the favorite status for a node."""
        node_id_str = format_node_id(node_id)
        if node_id_str in self._nodes:
            self._nodes[node_id_str]['is_favorite'] = is_favorite
            self.notify("node_updated", node_id_str)


class MessageBuffer(Observable):
    """Circular buffer for recent packets."""

    def __init__(self, max_size: int = 1000, storage: "Optional[LogStorage]" = None):
        super().__init__()
        self._messages: deque = deque(maxlen=max_size)
        self._max_size = max_size
        self._pending: Dict[int, PendingMessage] = {}
        self._storage = storage

    def set_storage(self, storage: "LogStorage"):
        """Set the storage backend."""
        self._storage = storage

    def add_pending(self, request_id: int, packet: dict, packet_id: Optional[int] = None):
        """Track a sent message awaiting ACK."""
        self._pending[request_id] = PendingMessage(
            request_id=request_id,
            timestamp=time.time(),
            packet=packet,
            packet_id=packet_id
        )

    def resolve_pending(self, request_id: int, success: bool, error_reason: str = None) -> Optional[dict]:
        """Mark a pending message as delivered/failed. Returns the packet."""
        if request_id in self._pending:
            pending = self._pending.pop(request_id)
            pending.packet['_delivered'] = success
            if error_reason:
                pending.packet['_error_reason'] = error_reason
            # Update delivery status in storage
            if self._storage and pending.packet_id:
                self._storage.update_delivery_status(pending.packet_id, success, error_reason)
            self.notify("delivery_updated", pending.packet)
            return pending.packet
        return None

    def add(self, packet: dict) -> Optional[int]:
        """Add a packet to the buffer.

        Returns:
            Database ID of the stored packet, or None if storage failed
        """
        timestamp = time.time()
        entry = {
            'packet': packet,
            'timestamp': timestamp
        }
        db_id = None
        # Persist to storage
        if self._storage:
            try:
                db_id = self._storage.store_packet(packet, timestamp)
                entry['_db_id'] = db_id
            except Exception:
                pass  # Don't let storage errors prevent message display
        self._messages.append(entry)
        self.notify("message_added", entry)
        return db_id

    def get_all(self) -> List[dict]:
        """Get all messages."""
        return list(self._messages)

    def get_recent(self, count: int = 100) -> List[dict]:
        """Get most recent N messages."""
        return list(self._messages)[-count:]

    def get_for_node(self, node_id) -> List[dict]:
        """Get messages involving a specific node."""
        node_id_str = format_node_id(node_id)
        return [
            m for m in self._messages
            if format_node_id(m['packet'].get('from', '')) == node_id_str
            or format_node_id(m['packet'].get('to', '')) == node_id_str
        ]

    def get_text_messages(self, channel: Optional[int] = None, broadcast_only: bool = False) -> List[dict]:
        """Get TEXT_MESSAGE_APP messages, optionally filtered by channel.

        Args:
            channel: Channel to filter by (None for all channels)
            broadcast_only: If True, only return broadcasts (to="^all"), excluding DMs
        """
        result = []
        for m in self._messages:
            packet = m['packet']
            decoded = packet.get('decoded', {})
            portnum = str(decoded.get('portnum', ''))
            if portnum in ('TEXT_MESSAGE_APP', '1'):
                if channel is None or packet.get('channel', 0) == channel:
                    if broadcast_only:
                        # Only include broadcasts, exclude DMs
                        to_id = format_node_id(packet.get('to', ''))
                        if to_id not in ('^all', '!ffffffff'):
                            continue
                    result.append(m)
        return result

    def get_text_messages_for_node(self, node_id, channel: Optional[int] = 0, dm_only: bool = True) -> List[dict]:
        """Get TEXT_MESSAGE_APP messages to/from specific node.

        Args:
            node_id: Node ID to filter messages for
            channel: Channel to filter by (default 0 for DMs). Use None to get all channels.
            dm_only: If True, exclude broadcasts (to="^all"). Default True.
        """
        node_id_str = format_node_id(node_id)
        result = []
        for m in self._messages:
            packet = m['packet']
            decoded = packet.get('decoded', {})
            portnum = str(decoded.get('portnum', ''))
            if portnum in ('TEXT_MESSAGE_APP', '1'):
                # Filter by channel if specified
                if channel is not None and packet.get('channel', 0) != channel:
                    continue
                from_id = format_node_id(packet.get('from', ''))
                to_id = format_node_id(packet.get('to', ''))

                if dm_only:
                    # DMs only: messages TO this node, or FROM this node but not broadcasts
                    is_to_node = to_id == node_id_str
                    is_from_node = from_id == node_id_str
                    is_broadcast = to_id in ('^all', '!ffffffff')
                    if is_to_node or (is_from_node and not is_broadcast):
                        result.append(m)
                else:
                    if from_id == node_id_str or to_id == node_id_str:
                        result.append(m)
        return result

    def clear(self):
        """Clear all messages."""
        self._messages.clear()
        self.notify("cleared", None)

    def __len__(self):
        return len(self._messages)


class StatsTracker(Observable):
    """Track statistics about packet activity."""

    def __init__(self):
        super().__init__()
        self.packet_times: deque = deque(maxlen=100)
        self.channel_util: Dict[int, float] = {}

    def record_packet(self, packet: dict):
        """Record a packet for stats tracking."""
        self.packet_times.append(time.time())

        # Extract channel utilization from telemetry
        decoded = packet.get('decoded', {})
        portnum = str(decoded.get('portnum', ''))
        if portnum in ('TELEMETRY_APP', '67'):
            telemetry = decoded.get('telemetry', {})
            device = telemetry.get('deviceMetrics', {})
            if 'channelUtilization' in device:
                # Channel 0 by default, could extract from packet channel
                channel = packet.get('channel', 0)
                self.channel_util[channel] = device['channelUtilization']

        self.notify("stats_updated", None)

    def get_msgs_per_min(self) -> float:
        """Calculate messages per minute over the last 60 seconds."""
        now = time.time()
        recent = [t for t in self.packet_times if now - t < 60]
        return len(recent)

    def get_channel_util(self, channel: int = 0) -> Optional[float]:
        """Get channel utilization percentage."""
        return self.channel_util.get(channel)


@dataclass
class Settings:
    """Application settings."""
    verbose: bool = False
    filter_types: List[str] = field(default_factory=list)
    selected_node: Optional[str] = None
    favorites_highlight: bool = False  # Toggle for log highlighting + bell for favorites
    # Manual location settings (when GPS not available)
    manual_location: Optional[tuple[float, float]] = None  # (lat, lon)
    manual_location_label: str = ""  # Display label (e.g., "95051" or "Santa Clara, CA")
    use_gps: bool = True  # If True, prefer GPS; if False, use manual location

    _listeners: List[Callable] = field(default_factory=list, repr=False)

    @classmethod
    def load_from_config(cls) -> "Settings":
        """Load settings from config file."""
        from .storage import load_config
        config = load_config()
        settings = cls()
        if 'manual_location' in config and config['manual_location']:
            loc = config['manual_location']
            settings.manual_location = (loc['lat'], loc['lon'])
            settings.manual_location_label = loc.get('label', '')
        if 'use_gps' in config:
            settings.use_gps = config['use_gps']
        return settings

    def _save_to_config(self):
        """Save persistent settings to config file."""
        from .storage import load_config, save_config
        config = load_config()
        if self.manual_location:
            config['manual_location'] = {
                'lat': self.manual_location[0],
                'lon': self.manual_location[1],
                'label': self.manual_location_label
            }
        else:
            config.pop('manual_location', None)
        config['use_gps'] = self.use_gps
        save_config(config)

    def subscribe(self, callback: Callable):
        """Subscribe to settings changes."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback: Callable):
        """Unsubscribe from settings changes."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self, setting: str):
        """Notify listeners of a setting change."""
        for callback in self._listeners:
            try:
                callback("setting_changed", setting)
            except Exception:
                pass

    def toggle_verbose(self):
        """Toggle verbose mode."""
        self.verbose = not self.verbose
        self._notify("verbose")

    def set_selected_node(self, node_id: Optional[str]):
        """Set the selected node for detail view."""
        self.selected_node = node_id
        self._notify("selected_node")

    def toggle_favorites_highlight(self):
        """Toggle favorites highlighting mode."""
        self.favorites_highlight = not self.favorites_highlight
        self._notify("favorites_highlight")

    def set_manual_location(self, lat: float, lon: float, label: str = ""):
        """Set manual location coordinates."""
        self.manual_location = (lat, lon)
        self.manual_location_label = label
        self._save_to_config()
        self._notify("manual_location")

    def clear_manual_location(self):
        """Clear manual location."""
        self.manual_location = None
        self.manual_location_label = ""
        self._save_to_config()
        self._notify("manual_location")

    def set_use_gps(self, use_gps: bool):
        """Set whether to use GPS (True) or manual location (False)."""
        self.use_gps = use_gps
        self._save_to_config()
        self._notify("use_gps")


class AppState:
    """Container for all application state."""

    def __init__(self, storage: "Optional[LogStorage]" = None, text_logger=None):
        self.nodes = NodeStore(storage=storage)
        self.messages = MessageBuffer(storage=storage)
        self.settings = Settings.load_from_config()
        self.stats = StatsTracker()
        self.open_dms = OpenDMsState()  # Track open DM conversations
        self.connected = False
        self.my_node_id: Optional[str] = None
        self._my_position: Optional[tuple[float, float]] = None
        self.connection_info: dict = {}
        self.channel_names: Dict[int, str] = {}
        self._storage = storage
        self._text_logger = text_logger

    @property
    def storage(self) -> "Optional[LogStorage]":
        """Get the storage backend."""
        return self._storage

    @property
    def text_logger(self):
        """Get the plain text logger."""
        return self._text_logger

    def get_channel_name(self, index: int) -> Optional[str]:
        """Get channel name if configured."""
        return self.channel_names.get(index)

    def set_connected(self, connected: bool, info: dict = None):
        """Update connection status."""
        self.connected = connected
        if info:
            self.connection_info = info
            self.my_node_id = info.get('my_node_id')

    @property
    def my_position(self) -> Optional[tuple[float, float]]:
        """Get my node's position.

        Priority depends on use_gps setting:
        - If use_gps=True: GPS position > node stored position > manual location
        - If use_gps=False: manual location only
        """
        if self.settings.use_gps:
            # Try GPS/device position first
            if self._my_position:
                return self._my_position
            # Fall back to position from our node in the nodes dict
            if self.my_node_id:
                node = self.nodes.get_node(self.my_node_id)
                if node:
                    pos = get_node_position(node)
                    if pos:
                        return pos
            # Fall back to manual location
            if self.settings.manual_location:
                return self.settings.manual_location
        else:
            # Manual location only
            if self.settings.manual_location:
                return self.settings.manual_location
        return None

    def set_my_position(self, lat: float, lon: float):
        """Update my node's position."""
        self._my_position = (lat, lon)
