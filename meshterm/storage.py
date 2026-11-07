"""Persistent storage for packets using SQLite and plain text logs."""

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional, Tuple

from .formatting import format_node_id, is_broadcast_destination

MAX_PACKET_ID = 0xFFFFFFFF
logger = logging.getLogger(__name__)


def _secure_dir(path: Path) -> Path:
    """Create an application-owned directory with private permissions."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _secure_file(path: Path, mode: int = 0o600):
    """Restrict an application-owned file to private permissions."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _locked(method):
    """Serialize a storage operation on the shared SQLite connection."""

    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    wrapper.__name__ = method.__name__
    return wrapper


def get_data_dir() -> Path:
    """Get XDG-compliant data directory."""
    xdg_data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))

    return _secure_dir(Path(xdg_data) / "meshterm")


def get_state_dir() -> Path:
    """Get XDG-compliant state directory for logs."""
    xdg_state = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))

    return _secure_dir(Path(xdg_state) / "meshterm" / "logs")


def get_config_path() -> Path:
    """Get path to config file."""
    return get_data_dir() / "config.json"


def load_config() -> dict:
    """Load config from disk."""
    config_path = get_config_path()
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(config: dict):
    """Save config to disk with owner-only permissions."""
    config_path = get_config_path()
    try:
        fd = os.open(str(config_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
        _secure_file(config_path)
    except Exception:
        logger.debug("Could not save config", exc_info=True)


@dataclass
class StoredMessage:
    """A message retrieved from storage."""

    id: int
    timestamp: float
    packet_id: Optional[int]
    from_node: str
    to_node: str
    channel: int
    portnum: str
    payload: dict
    raw_packet: dict
    snr: Optional[float]
    rssi: Optional[int]
    hops: Optional[int]
    is_tx: bool
    delivered: Optional[bool]
    error_reason: Optional[str] = None

    def to_entry(self) -> dict:
        """Convert to the entry format used by MessageBuffer."""
        return {"packet": self.raw_packet, "timestamp": self.timestamp, "_db_id": self.id}


class LogStorage:
    """SQLite-based persistent storage for packets."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS packets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        packet_id INTEGER,
        from_node TEXT NOT NULL,
        to_node TEXT NOT NULL,
        channel INTEGER DEFAULT 0,
        portnum TEXT NOT NULL,
        payload TEXT,
        raw_packet TEXT NOT NULL,
        snr REAL,
        rssi INTEGER,
        hops INTEGER,
        is_tx BOOLEAN DEFAULT 0,
        delivered BOOLEAN,
        error_reason TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_timestamp ON packets(timestamp);
    CREATE INDEX IF NOT EXISTS idx_channel ON packets(channel);
    CREATE INDEX IF NOT EXISTS idx_from_node ON packets(from_node);
    CREATE INDEX IF NOT EXISTS idx_portnum ON packets(portnum);
    CREATE INDEX IF NOT EXISTS idx_to_node ON packets(to_node);

    CREATE TABLE IF NOT EXISTS nodes (
        node_id TEXT PRIMARY KEY,
        data TEXT NOT NULL,
        last_updated REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_nodes_last_updated ON nodes(last_updated);

    CREATE TABLE IF NOT EXISTS reactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_db_id INTEGER NOT NULL,
        message_packet_id INTEGER,
        reactor_node TEXT NOT NULL,
        emoji TEXT NOT NULL,
        timestamp REAL NOT NULL,
        UNIQUE(message_db_id, reactor_node, emoji)
    );
    CREATE INDEX IF NOT EXISTS idx_reactions_message ON reactions(message_db_id);

    CREATE TABLE IF NOT EXISTS reply_refs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reply_db_id INTEGER NOT NULL,
        parent_db_id INTEGER,
        parent_packet_id INTEGER NOT NULL,
        timestamp REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_reply_refs_reply ON reply_refs(reply_db_id);
    CREATE INDEX IF NOT EXISTS idx_reply_refs_parent ON reply_refs(parent_db_id);
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = get_data_dir() / "messages.db"
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._init_db()

    @_locked
    def _init_db(self):
        """Initialize the database."""
        self._conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()

        # Migration: add error_reason column if it doesn't exist
        try:
            self._conn.execute("ALTER TABLE packets ADD COLUMN error_reason TEXT")
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                logger.warning("Database migration failed: %s", exc)

        if str(self.db_path) != ":memory:" and self.db_path.exists():
            _secure_file(self.db_path)

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @_locked
    def store_packet(self, packet: dict, timestamp: float) -> int:
        """Store a packet and return its database ID."""
        decoded = packet.get("decoded", {})
        if not isinstance(decoded, dict):
            decoded = {}
        portnum = str(decoded.get("portnum", ""))

        from_id = packet.get("from", packet.get("fromId", ""))
        to_id = packet.get("to", packet.get("toId", ""))

        # Calculate hops
        hops = None
        hop_start = packet.get("hopStart")
        hop_limit = packet.get("hopLimit")
        if hop_start is not None and hop_limit is not None:
            hops = hop_start - hop_limit

        # Safely serialize to JSON (handle non-serializable objects)
        def json_serializable(obj):
            """Convert object to JSON-serializable form."""
            from enum import Enum

            if isinstance(obj, dict):
                return {k: json_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [json_serializable(item) for item in obj]
            elif isinstance(obj, bytes):
                return obj.hex()
            elif isinstance(obj, Enum):
                return obj.name
            elif hasattr(obj, "__dict__") and not isinstance(obj, type):
                return json_serializable(vars(obj))
            else:
                try:
                    json.dumps(obj)
                    return obj
                except (TypeError, ValueError):
                    return str(obj)

        def safe_json(obj):
            try:
                return json.dumps(json_serializable(obj))
            except (TypeError, ValueError):
                return json.dumps(str(obj))

        cursor = self._conn.execute(
            """
            INSERT INTO packets (
                timestamp, packet_id, from_node, to_node, channel, portnum,
                payload, raw_packet, snr, rssi, hops, is_tx, delivered
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                packet.get("id"),
                format_node_id(from_id),
                format_node_id(to_id),
                packet.get("channel", 0),
                portnum,
                safe_json(decoded),
                safe_json(packet),
                packet.get("rxSnr"),
                packet.get("rxRssi"),
                hops,
                1 if packet.get("_tx") else 0,
                packet.get("_delivered"),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    @_locked
    def update_delivery_status(self, packet_id: int, delivered: bool, error_reason: str = None):
        """Update the delivery status for a packet by its Meshtastic packet ID."""
        self._conn.execute(
            "UPDATE packets SET delivered = ?, error_reason = ? WHERE packet_id = ? AND is_tx = 1",
            (1 if delivered else 0, error_reason, packet_id),
        )
        self._conn.commit()

    def _row_to_stored_message(self, row: sqlite3.Row) -> StoredMessage:
        """Convert a database row to a StoredMessage."""
        raw_packet = json.loads(row["raw_packet"])
        payload = json.loads(row["payload"]) if row["payload"] else {}

        # Restore delivery status in raw_packet for rendering
        if row["is_tx"]:
            raw_packet["_tx"] = True
            if row["delivered"] is not None:
                raw_packet["_delivered"] = bool(row["delivered"])
                if not row["delivered"] and row["error_reason"]:
                    raw_packet["_error_reason"] = row["error_reason"]

        return StoredMessage(
            id=row["id"],
            timestamp=row["timestamp"],
            packet_id=row["packet_id"],
            from_node=row["from_node"],
            to_node=row["to_node"],
            channel=row["channel"],
            portnum=row["portnum"],
            payload=payload,
            raw_packet=raw_packet,
            snr=row["snr"],
            rssi=row["rssi"],
            hops=row["hops"],
            is_tx=bool(row["is_tx"]),
            delivered=bool(row["delivered"]) if row["delivered"] is not None else None,
            error_reason=row["error_reason"] if row["is_tx"] and not row["delivered"] else None,
        )

    def get_text_messages(
        self,
        channel: Optional[int] = None,
        limit: int = 100,
        before_id: Optional[int] = None,
        broadcast_only: bool = False,
    ) -> List[StoredMessage]:
        """Get TEXT_MESSAGE_APP messages, optionally filtered by channel.

        Args:
            channel: Channel to filter by (None for all channels)
            limit: Maximum number of messages to return
            before_id: Return messages before this database ID (for pagination)
            broadcast_only: If True, only return broadcasts (to="^all"), excluding DMs
        """
        query = """
            SELECT * FROM packets
            WHERE portnum IN ('TEXT_MESSAGE_APP', '1')
        """
        params = []

        if channel is not None:
            query += " AND channel = ?"
            params.append(channel)

        if broadcast_only:
            # Only include broadcasts (to="^all" or "!ffffffff"), exclude DMs
            query += " AND to_node IN ('^all', '!ffffffff')"

        if before_id is not None:
            query += " AND id < ?"
            params.append(before_id)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()
        # Reverse to get chronological order
        return [self._row_to_stored_message(row) for row in reversed(rows)]

    def get_messages_for_node(
        self,
        node_id: str,
        limit: int = 100,
        before_id: Optional[int] = None,
        channel: Optional[int] = 0,
        dm_only: bool = True,
    ) -> List[StoredMessage]:
        """Get TEXT_MESSAGE_APP messages to/from a specific node.

        Args:
            node_id: Node ID to filter messages for
            limit: Maximum number of messages to return
            before_id: Return messages before this database ID (for pagination)
            channel: Channel to filter by (default 0 for DMs). Use None to get all channels.
            dm_only: If True, exclude broadcasts (to="^all"). Default True.
        """
        node_id_str = format_node_id(node_id)

        if dm_only:
            # DMs only: messages sent TO this node, or FROM this node TO me (not broadcasts)
            # Exclude messages where to_node is "^all" or the broadcast address
            query = """
                SELECT * FROM packets
                WHERE portnum IN ('TEXT_MESSAGE_APP', '1')
                AND (
                    to_node = ?
                    OR (from_node = ? AND to_node NOT IN ('^all', '!ffffffff'))
                )
            """
            params = [node_id_str, node_id_str]
        else:
            query = """
                SELECT * FROM packets
                WHERE portnum IN ('TEXT_MESSAGE_APP', '1')
                AND (from_node = ? OR to_node = ?)
            """
            params = [node_id_str, node_id_str]

        if channel is not None:
            query += " AND channel = ?"
            params.append(channel)

        if before_id is not None:
            query += " AND id < ?"
            params.append(before_id)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()
        return [self._row_to_stored_message(row) for row in reversed(rows)]

    def get_all_packets(
        self,
        limit: int = 100,
        before_id: Optional[int] = None,
        portnum_filter: Optional[List[str]] = None,
    ) -> List[StoredMessage]:
        """Get all packets, optionally filtered by portnum."""
        query = "SELECT * FROM packets WHERE 1=1"
        params = []

        if portnum_filter:
            placeholders = ",".join("?" for _ in portnum_filter)
            query += f" AND portnum IN ({placeholders})"
            params.extend(portnum_filter)

        if before_id is not None:
            query += " AND id < ?"
            params.append(before_id)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()
        return [self._row_to_stored_message(row) for row in reversed(rows)]

    def get_oldest_id(self) -> Optional[int]:
        """Get the oldest message ID in the database."""
        cursor = self._conn.execute("SELECT MIN(id) FROM packets")
        row = cursor.fetchone()
        return row[0] if row else None

    def _find_nodes_by_name(self, term: str) -> List[str]:
        """Find node IDs whose names match the search term.

        Searches only shortName and longName fields, not entire JSON blob.
        """
        search_pattern = f"%{term}%"
        cursor = self._conn.execute(
            """SELECT node_id FROM nodes
            WHERE json_extract(data, '$.user.shortName') LIKE ? COLLATE NOCASE
               OR json_extract(data, '$.user.longName') LIKE ? COLLATE NOCASE""",
            [search_pattern, search_pattern],
        )
        return [row[0] for row in cursor.fetchall()]

    def search_packets(
        self,
        term: str,
        limit: int = 100,
        before_id: Optional[int] = None,
    ) -> List[StoredMessage]:
        """Search packets by node names or text message content.

        Only searches human-readable fields:
        - Node shortName and longName (via nodes table)
        - Text message content (extracted from payload JSON)

        Args:
            term: Search term (case-insensitive LIKE match)
            limit: Maximum number of results to return
            before_id: Return results with id < this value (for pagination)

        Returns:
            List of matching StoredMessage objects, ordered by id DESC
        """
        search_pattern = f"%{term}%"

        # Find node IDs whose names match the search term
        matching_node_ids = self._find_nodes_by_name(term)

        # Search only text messages by content, or packets from/to matching nodes
        query = """
            SELECT * FROM packets
            WHERE (
                -- Text message content (using json_extract for SQLite)
                (portnum IN ('TEXT_MESSAGE_APP', '1')
                 AND json_extract(payload, '$.text') LIKE ? COLLATE NOCASE)
        """
        params = [search_pattern]

        # Include packets from/to nodes whose names match
        if matching_node_ids:
            placeholders = ",".join("?" for _ in matching_node_ids)
            query += f" OR from_node IN ({placeholders})"
            query += f" OR to_node IN ({placeholders})"
            params.extend(matching_node_ids)
            params.extend(matching_node_ids)

        query += ")"

        if before_id is not None:
            query += " AND id < ?"
            params.append(before_id)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, params)
        return [self._row_to_stored_message(row) for row in cursor.fetchall()]

    def count_search_results(self, term: str) -> int:
        """Count total matching packets for a search term.

        Only counts matches in human-readable fields:
        - Node shortName and longName (via nodes table)
        - Text message content (extracted from payload JSON)

        Args:
            term: Search term (case-insensitive LIKE match)

        Returns:
            Total count of matching packets
        """
        search_pattern = f"%{term}%"

        # Find node IDs whose names match the search term
        matching_node_ids = self._find_nodes_by_name(term)

        # Count only text messages by content, or packets from/to matching nodes
        query = """
            SELECT COUNT(*) FROM packets
            WHERE (
                -- Text message content (using json_extract for SQLite)
                (portnum IN ('TEXT_MESSAGE_APP', '1')
                 AND json_extract(payload, '$.text') LIKE ? COLLATE NOCASE)
        """
        params = [search_pattern]

        # Include packets from/to nodes whose names match
        if matching_node_ids:
            placeholders = ",".join("?" for _ in matching_node_ids)
            query += f" OR from_node IN ({placeholders})"
            query += f" OR to_node IN ({placeholders})"
            params.extend(matching_node_ids)
            params.extend(matching_node_ids)

        query += ")"

        cursor = self._conn.execute(query, params)
        return cursor.fetchone()[0]

    @_locked
    def store_node(self, node_id: str, data: dict):
        """Store or update a node's data as JSON."""
        node_id_str = format_node_id(node_id)
        timestamp = time.time()

        # Safely serialize to JSON
        def json_serializable(obj):
            """Convert object to JSON-serializable form."""
            from enum import Enum

            if isinstance(obj, dict):
                return {k: json_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [json_serializable(item) for item in obj]
            elif isinstance(obj, bytes):
                return obj.hex()
            elif isinstance(obj, Enum):
                return obj.name
            elif hasattr(obj, "__dict__") and not isinstance(obj, type):
                return json_serializable(vars(obj))
            else:
                try:
                    json.dumps(obj)
                    return obj
                except (TypeError, ValueError):
                    return str(obj)

        try:
            data_json = json.dumps(json_serializable(data))
            self._conn.execute(
                """
                INSERT OR REPLACE INTO nodes (node_id, data, last_updated)
                VALUES (?, ?, ?)
                """,
                (node_id_str, data_json, timestamp),
            )
            self._conn.commit()
        except Exception:
            logger.exception("Failed to persist node %s", node_id_str)

    def get_all_nodes(self) -> dict:
        """Load all nodes from the database.

        Returns:
            Dict mapping node_id to node data dict
        """
        cursor = self._conn.execute("SELECT node_id, data FROM nodes")
        rows = cursor.fetchall()
        nodes = {}
        for row in rows:
            try:
                nodes[row["node_id"]] = json.loads(row["data"])
            except (json.JSONDecodeError, KeyError):
                pass
        return nodes

    @_locked
    def delete_old_nodes(self, max_age_days: int = 30):
        """Delete nodes not seen in the specified number of days.

        Args:
            max_age_days: Maximum age in days before pruning (default 30)
        """
        cutoff = time.time() - (max_age_days * 24 * 60 * 60)
        self._conn.execute("DELETE FROM nodes WHERE last_updated < ?", (cutoff,))
        self._conn.commit()

    # Reactions methods

    @_locked
    def store_reaction(
        self,
        message_db_id: int,
        message_packet_id: Optional[int],
        reactor_node: str,
        emoji: str,
        timestamp: float,
    ) -> bool:
        """Store a reaction. Returns True if inserted, False if toggled off (removed).

        If the same reaction (same message, reactor, emoji) already exists, it is removed.
        """
        reactor_node = format_node_id(reactor_node)

        # Check if reaction already exists
        cursor = self._conn.execute(
            """
            SELECT id FROM reactions
            WHERE message_db_id = ? AND reactor_node = ? AND emoji = ?
            """,
            (message_db_id, reactor_node, emoji),
        )
        existing = cursor.fetchone()

        if existing:
            # Toggle off - remove the reaction
            self._conn.execute("DELETE FROM reactions WHERE id = ?", (existing["id"],))
            self._conn.commit()
            return False
        else:
            # Insert new reaction
            self._conn.execute(
                """
                INSERT INTO reactions (message_db_id, message_packet_id, reactor_node, emoji, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_db_id, message_packet_id, reactor_node, emoji, timestamp),
            )
            self._conn.commit()
            return True

    def get_reactions_for_message(self, message_db_id: int) -> List[dict]:
        """Get all reactions for a specific message.

        Returns:
            List of dicts with emoji, reactor_node, timestamp
        """
        cursor = self._conn.execute(
            """
            SELECT emoji, reactor_node, timestamp
            FROM reactions
            WHERE message_db_id = ?
            ORDER BY timestamp
            """,
            (message_db_id,),
        )
        return [
            {
                "emoji": row["emoji"],
                "reactor_node": row["reactor_node"],
                "timestamp": row["timestamp"],
            }
            for row in cursor.fetchall()
        ]

    def get_reactions_for_messages(self, message_db_ids: List[int]) -> dict:
        """Get reactions for multiple messages efficiently.

        Args:
            message_db_ids: List of message database IDs

        Returns:
            Dict mapping message_db_id to list of reactions
        """
        if not message_db_ids:
            return {}

        placeholders = ",".join("?" for _ in message_db_ids)
        cursor = self._conn.execute(
            f"SELECT message_db_id, emoji, reactor_node, timestamp FROM reactions WHERE message_db_id IN ({placeholders}) ORDER BY message_db_id, timestamp",  # nosec B608: placeholders are fixed '?'
            message_db_ids,
        )

        result = {db_id: [] for db_id in message_db_ids}
        for row in cursor.fetchall():
            result[row["message_db_id"]].append(
                {
                    "emoji": row["emoji"],
                    "reactor_node": row["reactor_node"],
                    "timestamp": row["timestamp"],
                }
            )
        return result

    def get_message_by_db_id(self, db_id: int) -> Optional[StoredMessage]:
        """Fetch a stored message by its database row id."""
        if not isinstance(db_id, int) or db_id <= 0:
            return None
        cursor = self._conn.execute("SELECT * FROM packets WHERE id = ?", (db_id,))
        row = cursor.fetchone()
        return self._row_to_stored_message(row) if row else None

    def find_message_by_packet_id(
        self,
        packet_id: int,
        channel: Optional[int] = None,
        endpoints: Optional[Tuple[str, str]] = None,
        broadcast: Optional[bool] = None,
    ) -> Optional[StoredMessage]:
        """Find a message by packet ID, scoped to a conversation."""
        if not isinstance(packet_id, int) or not 0 <= packet_id <= MAX_PACKET_ID:
            return None
        query = "SELECT * FROM packets WHERE packet_id = ?"
        params = [packet_id]
        if channel is not None:
            query += " AND channel = ?"
            params.append(channel)
        if endpoints:
            first, second = endpoints
            query += " AND ((from_node = ? AND to_node = ?)" " OR (from_node = ? AND to_node = ?))"
            params.extend([first, second, second, first])
        elif broadcast:
            query += " AND to_node IN ('^all', '!ffffffff')"
        query += " ORDER BY id DESC LIMIT 1"
        cursor = self._conn.execute(query, params)
        row = cursor.fetchone()
        if row:
            return self._row_to_stored_message(row)
        return None

    # Reply refs methods

    @_locked
    def store_reply_ref(
        self,
        reply_db_id: int,
        parent_packet_id: int,
        timestamp: float,
        channel: Optional[int] = None,
        endpoints: Optional[Tuple[str, str]] = None,
        broadcast: Optional[bool] = None,
    ) -> Optional[int]:
        """Store a reply reference.

        Args:
            reply_db_id: Database ID of the reply message
            parent_packet_id: Meshtastic packet ID of the parent message
            timestamp: When the reply was created

        Returns:
            The parent's database ID if found, None if parent not in DB
        """
        if not isinstance(reply_db_id, int) or not isinstance(parent_packet_id, int):
            return None
        if not 0 <= parent_packet_id <= MAX_PACKET_ID:
            return None
        # Try to find the parent message by packet ID
        parent = self.find_message_by_packet_id(
            parent_packet_id,
            channel=channel,
            endpoints=endpoints,
            broadcast=broadcast,
        )
        parent_db_id = parent.id if parent else None

        self._conn.execute(
            """
            INSERT INTO reply_refs (reply_db_id, parent_db_id, parent_packet_id, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (reply_db_id, parent_db_id, parent_packet_id, timestamp),
        )
        self._conn.commit()
        return parent_db_id

    def get_reply_ref(self, reply_db_id: int) -> Optional[dict]:
        """Get reply reference for a message.

        Returns:
            Dict with parent_db_id, parent_packet_id, timestamp or None
        """
        cursor = self._conn.execute(
            """
            SELECT parent_db_id, parent_packet_id, timestamp
            FROM reply_refs
            WHERE reply_db_id = ?
            """,
            (reply_db_id,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "parent_db_id": row["parent_db_id"],
                "parent_packet_id": row["parent_packet_id"],
                "timestamp": row["timestamp"],
            }
        return None

    def get_reply_refs_for_messages(self, message_db_ids: List[int]) -> dict:
        """Get reply refs for multiple messages efficiently.

        Args:
            message_db_ids: List of message database IDs

        Returns:
            Dict mapping reply_db_id to reply ref info
        """
        if not message_db_ids:
            return {}

        placeholders = ",".join("?" for _ in message_db_ids)
        cursor = self._conn.execute(
            f"SELECT reply_db_id, parent_db_id, parent_packet_id, timestamp FROM reply_refs WHERE reply_db_id IN ({placeholders})",  # nosec B608: placeholders are fixed '?'
            message_db_ids,
        )

        return {
            row["reply_db_id"]: {
                "parent_db_id": row["parent_db_id"],
                "parent_packet_id": row["parent_packet_id"],
                "timestamp": row["timestamp"],
            }
            for row in cursor.fetchall()
        }

    def get_parent_message(self, reply_db_id: int) -> Optional[StoredMessage]:
        """Get the parent message for a reply.

        Returns:
            StoredMessage of parent if found, None otherwise
        """
        ref = self.get_reply_ref(reply_db_id)
        if not ref:
            return None

        # Try by parent_db_id first (more reliable)
        if ref["parent_db_id"]:
            cursor = self._conn.execute(
                "SELECT * FROM packets WHERE id = ?", (ref["parent_db_id"],)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_stored_message(row)

        # Fall back to packet_id lookup, scoped to the reply's conversation.
        cursor = self._conn.execute(
            "SELECT channel, from_node, to_node FROM packets WHERE id = ?",
            (reply_db_id,),
        )
        row = cursor.fetchone()
        if row:
            channel = row["channel"]
            endpoints = None
            broadcast = False
            if channel == 0:
                if is_broadcast_destination(row["to_node"]):
                    broadcast = True
                else:
                    endpoints = (row["from_node"], row["to_node"])
            return self.find_message_by_packet_id(
                ref["parent_packet_id"],
                channel=channel,
                endpoints=endpoints,
                broadcast=broadcast,
            )
        return self.find_message_by_packet_id(ref["parent_packet_id"])

    # Data management methods

    @_locked
    def clear_messages(self) -> int:
        """Clear all messages (packets, reactions, reply_refs).

        Returns:
            Number of messages deleted
        """
        cursor = self._conn.execute("SELECT COUNT(*) FROM packets")
        count = cursor.fetchone()[0]

        self._conn.execute("DELETE FROM reply_refs")
        self._conn.execute("DELETE FROM reactions")
        self._conn.execute("DELETE FROM packets")
        self._conn.commit()

        return count

    @_locked
    def clear_nodes(self) -> int:
        """Clear all stored nodes.

        Returns:
            Number of nodes deleted
        """
        cursor = self._conn.execute("SELECT COUNT(*) FROM nodes")
        count = cursor.fetchone()[0]

        self._conn.execute("DELETE FROM nodes")
        self._conn.commit()

        return count

    @_locked
    def clear_all_data(self) -> dict:
        """Clear all data from the database.

        Returns:
            Dict with counts of deleted items
        """
        msg_count = self.clear_messages()
        node_count = self.clear_nodes()

        # Vacuum to reclaim space
        self._conn.execute("VACUUM")

        return {"messages": msg_count, "nodes": node_count}

    def get_stats(self) -> dict:
        """Get storage statistics.

        Returns:
            Dict with counts of stored items
        """
        stats = {}

        cursor = self._conn.execute("SELECT COUNT(*) FROM packets")
        stats["messages"] = cursor.fetchone()[0]

        cursor = self._conn.execute("SELECT COUNT(*) FROM nodes")
        stats["nodes"] = cursor.fetchone()[0]

        cursor = self._conn.execute("SELECT COUNT(*) FROM reactions")
        stats["reactions"] = cursor.fetchone()[0]

        # Database file size
        if self.db_path.exists():
            stats["db_size_mb"] = self.db_path.stat().st_size / (1024 * 1024)
        else:
            stats["db_size_mb"] = 0

        return stats


class PlainTextLogger:
    """Rotating plain text logs for external tool access."""

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 7,
    ):
        if log_dir is None:
            log_dir = get_state_dir()

        self.log_path = log_dir / "meshterm.log"
        self._logger = logging.getLogger("meshterm.packets")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

        # Remove existing handlers
        self._logger.handlers.clear()

        # Create rotating file handler
        handler = RotatingFileHandler(
            str(self.log_path), maxBytes=max_bytes, backupCount=backup_count
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)
        _secure_file(self.log_path)

    def log_packet(self, packet: dict, timestamp: float):
        """Log a packet to the plain text log file."""
        from datetime import datetime

        decoded = packet.get("decoded", {})
        portnum = str(decoded.get("portnum", ""))

        time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        from_id = format_node_id(packet.get("from", packet.get("fromId", "")))
        to_id = format_node_id(packet.get("to", packet.get("toId", "")))
        channel = packet.get("channel", 0)

        # Build log line
        parts = [time_str, portnum, f"from={from_id}", f"to={to_id}", f"ch={channel}"]

        # Add relevant payload info
        if portnum in ("TEXT_MESSAGE_APP", "1"):
            text = decoded.get("text", "")
            parts.append(f"text={repr(text)}")
        elif portnum in ("POSITION_APP", "3"):
            pos = decoded.get("position", {})
            lat = pos.get("latitude", pos.get("latitudeI", 0))
            lon = pos.get("longitude", pos.get("longitudeI", 0))
            if isinstance(lat, int) and abs(lat) > 1000:
                lat = lat / 1e7
                lon = lon / 1e7
            parts.append(f"lat={lat:.6f} lon={lon:.6f}")
        elif portnum in ("TELEMETRY_APP", "67"):
            telemetry = decoded.get("telemetry", {})
            device = telemetry.get("deviceMetrics", {})
            if "batteryLevel" in device:
                parts.append(f"battery={device['batteryLevel']}%")
            if "channelUtilization" in device:
                parts.append(f"chUtil={device['channelUtilization']:.1f}%")

        # Add signal info
        snr = packet.get("rxSnr")
        rssi = packet.get("rxRssi")
        if snr is not None:
            parts.append(f"snr={snr:.1f}")
        if rssi is not None:
            parts.append(f"rssi={rssi}")

        self._logger.info(" | ".join(parts))

    def close(self):
        """Close the logger handlers."""
        for handler in self._logger.handlers:
            handler.close()
        self._logger.handlers.clear()

    def clear_logs(self) -> int:
        """Clear all log files.

        Returns:
            Number of files deleted
        """
        import glob as glob_module

        # Close handlers first
        for handler in self._logger.handlers:
            handler.close()
        self._logger.handlers.clear()

        # Find and delete log files
        log_pattern = str(self.log_path) + "*"
        log_files = glob_module.glob(log_pattern)
        count = 0

        for log_file in log_files:
            try:
                Path(log_file).unlink()
                count += 1
            except Exception:
                pass

        # Reinitialize the handler
        handler = RotatingFileHandler(str(self.log_path), maxBytes=10 * 1024 * 1024, backupCount=7)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)
        _secure_file(self.log_path)

        return count

    def get_log_size(self) -> float:
        """Get total size of log files in MB."""
        import glob as glob_module

        log_pattern = str(self.log_path) + "*"
        log_files = glob_module.glob(log_pattern)
        total_size = 0

        for log_file in log_files:
            try:
                total_size += Path(log_file).stat().st_size
            except Exception:
                pass

        return total_size / (1024 * 1024)
