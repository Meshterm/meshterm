"""Generate screenshots of meshterm for documentation.

Runs the app headlessly with rich demo data and captures SVG screenshots
of each major view. No Meshtastic device or display server needed.

Usage:
    python scripts/screenshots.py
    python -m scripts.screenshots
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

from meshterm.app import MeshtermApp
from meshterm.connection import MeshtasticConnection
from meshterm.state import AppState
from meshterm.storage import LogStorage

SCREENSHOT_SIZE = (120, 36)
OUTPUT_DIR = Path(__file__).parent.parent / "screenshots"

# Our node
MY_NODE_NUM = 0xA1B2C3D4
MY_NODE_ID = "!a1b2c3d4"

NODES = {
    MY_NODE_ID: {
        "num": MY_NODE_NUM,
        "user": {
            "id": MY_NODE_ID,
            "longName": "Base Station",
            "shortName": "BASE",
            "hwModel": "TBEAM",
            "publicKey": "abc123",
        },
        "position": {
            "latitude": 37.7749,
            "longitude": -122.4194,
            "altitude": 15,
            "satsInView": 12,
        },
        "lastHeard": int(time.time()) - 30,
        "snr": 10.0,
        "rssi": -65,
        "hops": 0,
    },
    "!b2c3d4e5": {
        "num": 0xB2C3D4E5,
        "user": {
            "id": "!b2c3d4e5",
            "longName": "Mountain Relay",
            "shortName": "MTRL",
            "hwModel": "RAK4631",
            "publicKey": "def456",
        },
        "position": {
            "latitude": 37.8044,
            "longitude": -122.2712,
            "altitude": 450,
            "satsInView": 9,
        },
        "lastHeard": int(time.time()) - 120,
        "snr": 8.5,
        "rssi": -78,
        "hops": 1,
        "is_favorite": True,
    },
    "!c3d4e5f6": {
        "num": 0xC3D4E5F6,
        "user": {
            "id": "!c3d4e5f6",
            "longName": "Downtown Node",
            "shortName": "DWTN",
            "hwModel": "HELTEC_V3",
        },
        "position": {
            "latitude": 37.7849,
            "longitude": -122.4094,
            "altitude": 5,
        },
        "lastHeard": int(time.time()) - 300,
        "snr": 6.0,
        "rssi": -92,
        "hops": 1,
    },
    "!d4e5f6a7": {
        "num": 0xD4E5F6A7,
        "user": {
            "id": "!d4e5f6a7",
            "longName": "Park Ranger",
            "shortName": "RNGR",
            "hwModel": "TBEAM",
            "publicKey": "ghi789",
        },
        "position": {
            "latitude": 37.7694,
            "longitude": -122.4862,
            "altitude": 60,
            "satsInView": 7,
        },
        "lastHeard": int(time.time()) - 600,
        "snr": 4.5,
        "rssi": -98,
        "hops": 2,
        "is_favorite": True,
    },
    "!e5f6a7b8": {
        "num": 0xE5F6A7B8,
        "user": {
            "id": "!e5f6a7b8",
            "longName": "Harbor Monitor",
            "shortName": "HRBR",
            "hwModel": "RAK4631",
        },
        "position": {
            "latitude": 37.8085,
            "longitude": -122.4099,
            "altitude": 3,
            "satsInView": 11,
        },
        "lastHeard": int(time.time()) - 45,
        "snr": 9.0,
        "rssi": -72,
        "hops": 1,
    },
    "!f6a7b8c9": {
        "num": 0xF6A7B8C9,
        "user": {
            "id": "!f6a7b8c9",
            "longName": "Hilltop Solar",
            "shortName": "HTSP",
            "hwModel": "HELTEC_V3",
            "publicKey": "jkl012",
        },
        "lastHeard": int(time.time()) - 1800,
        "snr": 3.0,
        "rssi": -105,
        "hops": 3,
    },
    "!a7b8c9d0": {
        "num": 0xA7B8C9D0,
        "user": {
            "id": "!a7b8c9d0",
            "longName": "Mobile Unit 7",
            "shortName": "MU07",
            "hwModel": "TBEAM",
        },
        "position": {
            "latitude": 37.7599,
            "longitude": -122.4369,
            "altitude": 20,
        },
        "lastHeard": int(time.time()) - 90,
        "snr": 7.5,
        "rssi": -85,
        "hops": 1,
    },
    "!b8c9d0e1": {
        "num": 0xB8C9D0E1,
        "user": {
            "id": "!b8c9d0e1",
            "longName": "Weather Station",
            "shortName": "WXSN",
            "hwModel": "RAK4631",
            "publicKey": "mno345",
        },
        "position": {
            "latitude": 37.7950,
            "longitude": -122.3930,
            "altitude": 80,
            "satsInView": 10,
        },
        "lastHeard": int(time.time()) - 200,
        "snr": 5.5,
        "rssi": -88,
        "hops": 2,
        "is_favorite": True,
    },
}


def build_packets():
    """Build a rich set of demo packets."""
    t = int(time.time())
    packets = []

    # --- Chat messages (broadcast on channel 0) ---
    chat_messages = [
        (0xB2C3D4E5, "Good morning mesh! Mountain relay checking in."),
        (0xE5F6A7B8, "Harbor monitor online. Winds 12kt NW, vis good."),
        (MY_NODE_NUM, "Thanks for the report. Anyone seeing traffic on the bridge?"),
        (0xC3D4E5F6, "Confirmed, light traffic downtown. All clear here."),
        (0xD4E5F6A7, "Park ranger here. Trail conditions are good today."),
        (0xA7B8C9D0, "Mobile unit 7 heading to marina, will relay from there."),
        (0xB8C9D0E1, "WX update: temp 18C, humidity 65%, barometer 1013hPa."),
        (0xB2C3D4E5, "Nice! Perfect weather for mesh testing."),
        (MY_NODE_NUM, "Agreed. Let's do a range test this afternoon."),
        (0xF6A7B8C9, "Hilltop solar here. Battery at 92%, good signal."),
        (0xE5F6A7B8, "Just saw a cargo ship pass under the bridge. Cool view!"),
        (0xD4E5F6A7, "Anyone up for a group hike next weekend? 🏔️"),
        (MY_NODE_NUM, "Count me in! Let's plan on the Saturday morning."),
        (0xC3D4E5F6, "I can relay from Twin Peaks if you need coverage."),
        (0xA7B8C9D0, "At marina now. Signal is 3 hops to mountain relay."),
    ]

    for i, (from_node, text) in enumerate(chat_messages):
        is_tx = from_node == MY_NODE_NUM
        pkt = {
            "id": 2001 + i,
            "from": from_node,
            "to": 0xFFFFFFFF,
            "channel": 0,
            "decoded": {
                "portnum": "TEXT_MESSAGE_APP",
                "text": text,
            },
            "rxTime": t - (len(chat_messages) - i) * 45,
        }
        if is_tx:
            pkt["_tx"] = True
            pkt["_delivered"] = True
        else:
            pkt["rxSnr"] = 6.0 + (i % 5)
            pkt["rxRssi"] = -75 - (i % 20)
            pkt["hopLimit"] = 3
            pkt["hopStart"] = 3
        packets.append(pkt)

    # --- DM ---
    packets.append({
        "id": 2050,
        "from": 0xD4E5F6A7,
        "to": MY_NODE_NUM,
        "channel": 0,
        "decoded": {
            "portnum": "TEXT_MESSAGE_APP",
            "text": "Hey, can you check the repeater config on node MTRL?",
        },
        "rxSnr": 5.0,
        "rxRssi": -95,
        "hopLimit": 2,
        "hopStart": 3,
        "rxTime": t - 180,
    })

    # --- Position updates ---
    for node_id, node in NODES.items():
        pos = node.get("position")
        if pos:
            packets.append({
                "id": 3001 + node["num"] % 100,
                "from": node["num"],
                "to": 0xFFFFFFFF,
                "channel": 0,
                "decoded": {
                    "portnum": "POSITION_APP",
                    "position": pos,
                },
                "rxSnr": node.get("snr", 5.0),
                "rxRssi": node.get("rssi", -90),
                "hopLimit": 3,
                "hopStart": 3,
                "rxTime": t - 60,
            })

    # --- Telemetry ---
    telem_data = [
        (MY_NODE_NUM, {"batteryLevel": 95, "voltage": 4.18, "channelUtilization": 3.2, "airUtilTx": 0.8}),
        (0xB2C3D4E5, {"batteryLevel": 78, "voltage": 3.95, "channelUtilization": 5.1, "airUtilTx": 1.5}),
        (0xB8C9D0E1, {"batteryLevel": 100, "voltage": 4.20, "channelUtilization": 2.8, "airUtilTx": 0.5}),
        (0xF6A7B8C9, {"batteryLevel": 92, "voltage": 4.10, "channelUtilization": 1.2, "airUtilTx": 0.3}),
        (0xE5F6A7B8, {"batteryLevel": 64, "voltage": 3.78, "channelUtilization": 4.5, "airUtilTx": 1.1}),
    ]
    for i, (from_node, metrics) in enumerate(telem_data):
        packets.append({
            "id": 4001 + i,
            "from": from_node,
            "to": 0xFFFFFFFF,
            "channel": 0,
            "decoded": {
                "portnum": "TELEMETRY_APP",
                "telemetry": {"deviceMetrics": metrics},
            },
            "rxSnr": 7.0,
            "rxRssi": -82,
            "hopLimit": 3,
            "hopStart": 3,
            "rxTime": t - 20 + i,
        })

    # --- Node info ---
    packets.append({
        "id": 5001,
        "from": 0xA7B8C9D0,
        "to": 0xFFFFFFFF,
        "channel": 0,
        "decoded": {
            "portnum": "NODEINFO_APP",
            "user": NODES["!a7b8c9d0"]["user"],
        },
        "rxSnr": 7.5,
        "rxRssi": -85,
        "hopLimit": 3,
        "hopStart": 3,
        "rxTime": t - 10,
    })

    return packets


def create_demo_state():
    """Build a richly populated state for screenshots."""
    storage = LogStorage(db_path=Path(":memory:"))
    state = AppState(storage=storage)

    state.nodes.import_nodes(NODES)
    for node_id, node_data in NODES.items():
        storage.store_node(node_id, node_data)

    for packet in build_packets():
        state.messages.add(packet)
        state.stats.record_packet(packet)

    state.set_connected(True, {
        "my_node_id": MY_NODE_ID,
        "port": "/dev/ttyUSB0",
        "firmware": "2.3.0",
        "region": "US",
    })

    state.channel_names = {0: "LongFast", 1: "Admin", 2: "Emergency"}

    return state, storage


def create_mock_connection(state):
    """Create a mock connection matching the real interface."""
    conn = MagicMock(spec=MeshtasticConnection)
    conn.interface = MagicMock()
    conn.port = "/dev/ttyUSB0"
    conn.state = state
    conn._on_status_change = None

    # Mock localNode config for settings view
    conn.interface.myInfo = MagicMock()
    conn.interface.myInfo.my_node_num = MY_NODE_NUM
    conn.interface.localNode = MagicMock()
    conn.interface.localNode.localConfig = MagicMock()
    conn.interface.localNode.localConfig.lora = MagicMock()
    conn.interface.localNode.localConfig.lora.region = 3  # US
    conn.interface.localNode.localConfig.lora.modem_preset = 0  # LONG_FAST
    conn.interface.localNode.localConfig.lora.hop_limit = 3
    conn.interface.localNode.localConfig.lora.tx_power = 27
    conn.interface.localNode.localConfig.lora.use_preset = True
    conn.interface.localNode.localConfig.lora.bandwidth = 0
    conn.interface.localNode.localConfig.lora.spread_factor = 0
    conn.interface.localNode.localConfig.lora.coding_rate = 0
    conn.interface.localNode.channels = []
    conn.interface.nodes = {n["num"]: n for n in NODES.values()}

    return conn


async def capture(pilot, app, name, title):
    """Capture a screenshot after letting the UI settle."""
    await pilot.pause()
    await pilot.pause()
    svg = app.export_screenshot(title=title)
    path = OUTPUT_DIR / f"{name}.svg"
    path.write_text(svg)
    print(f"  {name}.svg")


async def capture_screenshots():
    """Capture all screenshots."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    state, storage = create_demo_state()
    conn = create_mock_connection(state)
    app = MeshtermApp(state=state, connection=conn)

    print("Capturing screenshots...")

    async with app.run_test(size=SCREENSHOT_SIZE) as pilot:
        # Nodes tab (default view)
        await capture(pilot, app, "nodes", "Meshterm — Nodes")

        # Chat tab
        await pilot.press("c")
        await capture(pilot, app, "chat", "Meshterm — Chat")

        # Chat selection mode
        await pilot.press("ctrl+r")
        await pilot.pause()
        await pilot.press("up")
        await pilot.press("up")
        await capture(pilot, app, "chat_selection", "Meshterm — Message Selection")
        await pilot.press("escape")

        # Log tab
        await pilot.press("l")
        await capture(pilot, app, "log", "Meshterm — Log")

        # Settings tab
        await pilot.press("s")
        await capture(pilot, app, "settings", "Meshterm — Settings")

        # Help modal (from nodes view for clean background)
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("ctrl+h")
        await capture(pilot, app, "help", "Meshterm — Help")

    storage.close()
    print(f"\nDone! Screenshots saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    asyncio.run(capture_screenshots())
