"""Regression tests for the findings in the meshterm security/code review.

Every test encodes the DESIRED behaviour after the fixes. They are expected to
fail on a tree that still has the reviewed bug and pass once it is fixed.
All tests are deterministic and hardware-free: Meshtastic interfaces are fakes,
Textual is driven with Pilot, and files live under the repo's ``.test-tmp``.
"""

import asyncio
import base64
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from meshtastic.protobuf import channel_pb2, config_pb2, localonly_pb2
from textual.app import App
from textual.widgets import Button, Input, ListView, Select, Static, Switch
from textual.widgets._toast import Toast

from meshterm.app import MeshtermApp
from meshterm.connection import MeshtasticConnection
from meshterm import formatting
from meshterm.formatting import format_packet, format_payload
from meshterm.state import AppState
from meshterm.storage import LogStorage, get_data_dir, save_config
from meshterm.widgets.channel_manager import ChannelManager
from meshterm.widgets.chat_log import ChatLog
from meshterm.widgets.config_panels import (
    AdvancedPanel,
    DevicePanel,
    PositionPanel,
    RadioConfigPanel,
)
from meshterm.widgets.dialogs import ChannelSelectDialog, InviteConfirmDialog
from meshterm.widgets.message_action_menu import MessageActionMenu
from meshterm.widgets.reaction_picker import ReactionPicker
from meshterm.widgets.reconnecting_modal import ReconnectingModal

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "meshterm"

MARKUP_BAIT = "[/]"
ESC_PAYLOAD = "\x1b[2J"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class WidgetHost(App):
    """Minimal app that hosts pre-built widgets."""

    def __init__(self, *widgets, **kwargs):
        super().__init__(**kwargs)
        self._widgets = widgets

    def compose(self):
        yield from self._widgets


def make_state(storage=None) -> AppState:
    if storage is None:
        storage = LogStorage(db_path=Path(":memory:"))
    return AppState(storage=storage)


def make_meshterm_app():
    state = make_state()
    connection = MagicMock()
    connection.interface = None
    connection.port = "/dev/ttyFAKE0"
    connection.state = state
    return MeshtermApp(state=state, connection=connection)


async def wait_until(pilot, predicate, timeout=5.0, step=0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await pilot.pause(step)
    return predicate()


async def settle(pilot, rounds=3):
    for _ in range(rounds):
        await pilot.pause()


def screen_texts(screen) -> str:
    """Plain rendered text of every Static/Label on a screen."""
    return "\n".join(str(w.render()) for w in screen.query(Static))


def text_packet(packet_id, text, channel=0, frm=0x11111111, to=0xFFFFFFFF, **extra):
    packet = {
        "id": packet_id,
        "from": frm,
        "to": to,
        "channel": channel,
        "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": text},
    }
    packet.update(extra)
    return packet


def mode_of(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def call_values(call):
    """Return (config_type, values) of a recorded write_config style call."""
    args, kwargs = call
    config_type = args[0] if args else kwargs.get("config_type")
    values = args[1] if len(args) > 1 else kwargs.get("values")
    return config_type, values


# ---------------------------------------------------------------------------
# Fake Meshtastic device
# ---------------------------------------------------------------------------


class FakeNode:
    """localNode stand-in backed by real Meshtastic protobufs."""

    def __init__(self):
        self.localConfig = localonly_pb2.LocalConfig()
        self.moduleConfig = localonly_pb2.LocalModuleConfig()
        self.channels = [
            channel_pb2.Channel(index=i, role=channel_pb2.Channel.Role.DISABLED) for i in range(8)
        ]
        self.writeConfig = MagicMock()
        self.writeChannel = MagicMock()
        self.setOwner = MagicMock()


class FakeInterface:
    OWN_NUM = 0xA1B2C3D4
    OWN_ID = "!a1b2c3d4"

    def __init__(self, node):
        self.localNode = node
        self.myInfo = SimpleNamespace(my_node_num=self.OWN_NUM)
        own = {
            "num": self.OWN_NUM,
            "user": {
                "id": self.OWN_ID,
                "longName": "Alpha Station",
                "shortName": "ALPH",
            },
        }
        # Meshtastic keys `nodes` by string id and `nodesByNum` by integer.
        self.nodes = {self.OWN_ID: own}
        self.nodesByNum = {self.OWN_NUM: own}
        self.close = MagicMock()

    def getMyNodeInfo(self):
        return self.nodesByNum[self.OWN_NUM]


@pytest.fixture
def node():
    return FakeNode()


@pytest.fixture
def connection(node):
    conn = MeshtasticConnection(make_state())
    conn.interface = FakeInterface(node)
    yield conn
    conn.cleanup()


def configure_channel(node, index=1):
    ch = node.channels[index]
    ch.role = channel_pb2.Channel.Role.SECONDARY
    ch.settings.name = "oldname"
    ch.settings.psk = bytes(range(16))
    ch.settings.uplink_enabled = True
    ch.settings.downlink_enabled = False
    ch.settings.channel_num = 5
    ch.settings.id = 77
    ch.settings.module_settings.position_precision = 13
    ch.settings.module_settings.is_muted = True
    return ch


# ===========================================================================
# 1. Untrusted markup
# ===========================================================================


class TestUntrustedMarkup:
    @pytest.mark.asyncio
    async def test_dm_notification_with_markup_in_name_and_preview(self):
        app = make_meshterm_app()
        async with app.run_test(notifications=True) as pilot:
            await settle(pilot)
            app.state.messages.notify(
                "dm_received",
                {
                    "from_id": "!11111111",
                    "from_name": MARKUP_BAIT,
                    "preview": "x [/] y [bold]z[/bold]",
                    "packet": {},
                },
            )
            await pilot.pause(0.3)
            assert app.is_running
            toasts = [str(t.render()) for t in app.screen.query(Toast)]
            assert toasts, "DM toast was not shown"
            joined = "\n".join(toasts)
            assert MARKUP_BAIT in joined
            # Sender-supplied markup must be shown literally, not interpreted.
            assert "[bold]z[/bold]" in joined

    @pytest.mark.asyncio
    async def test_channel_select_dialog_shows_hostile_channel_name_literally(self):
        channels = [{"index": 1, "name": MARKUP_BAIT, "role": "SECONDARY", "psk": "aa" * 16}]
        app = WidgetHost()
        async with app.run_test() as pilot:
            await app.push_screen(ChannelSelectDialog(channels))
            await settle(pilot)
            text = screen_texts(app.screen)
            assert MARKUP_BAIT in text

    @pytest.mark.asyncio
    async def test_invite_confirm_dialog_shows_hostile_names_literally(self):
        channel = {"index": 1, "name": MARKUP_BAIT, "role": "SECONDARY", "psk": "aa" * 16}
        app = WidgetHost()
        async with app.run_test() as pilot:
            await app.push_screen(InviteConfirmDialog(MARKUP_BAIT, "!a1b2c3d4", channel))
            await settle(pilot)
            text = screen_texts(app.screen)
            assert f"{MARKUP_BAIT} (!a1b2c3d4)" in text
            assert f"[1] {MARKUP_BAIT}" in text

    @pytest.mark.asyncio
    async def test_message_action_menu_title_with_hostile_sender(self):
        menu = MessageActionMenu(
            entry={},
            sender_name=MARKUP_BAIT,
            is_own_message=False,
            can_retransmit=False,
            show_dm=True,
        )
        app = WidgetHost()
        async with app.run_test() as pilot:
            await app.push_screen(menu)
            await settle(pilot)
            text = screen_texts(app.screen)
            assert f"Message from {MARKUP_BAIT}" in text
            assert f"DM {MARKUP_BAIT}" in text

    @pytest.mark.asyncio
    async def test_reaction_picker_title_with_hostile_sender(self):
        app = WidgetHost()
        async with app.run_test() as pilot:
            await app.push_screen(ReactionPicker(entry={}, sender_name=MARKUP_BAIT))
            await settle(pilot)
            assert f"React to message from {MARKUP_BAIT}" in screen_texts(app.screen)


# ===========================================================================
# 2. Terminal control characters
# ===========================================================================


class TestControlCharacters:
    def test_sanitizer_strips_esc_c0_c1_but_keeps_newline_tab_and_emoji(self):
        raw = "a\x1b[2Jb\x07c\x00d\x08e\x7ff\x80g\x9bh\x9fi\nj\tk😀l"
        out = formatting.sanitize_text(raw)
        assert out == "a[2Jbcdefghi\nj\tk😀l"

    def test_sanitizer_preserves_compound_emoji(self):
        raw = "👨\u200d👩\u200d👧 ❤\ufe0f 👍🏽 \x1b]52;c;AAAA\x07"
        out = formatting.sanitize_text(raw)
        assert "\x1b" not in out and "\x07" not in out
        assert out.startswith("👨\u200d👩\u200d👧 ❤\ufe0f 👍🏽 ")

    def test_sanitizer_strips_osc_terminator_sequences(self):
        out = formatting.sanitize_text("\x1b]52;c;PAYLOAD\x1b\\done")
        assert "\x1b" not in out
        assert out.endswith("done")

    def test_format_packet_and_payload_strip_escape_from_text(self):
        packet = text_packet(1, f"hello {ESC_PAYLOAD} world", rxTime=1_700_000_000)
        for rendered in (format_packet(packet), format_payload(packet)):
            assert "\x1b" not in rendered.plain
        assert "hello" in format_payload(packet).plain

    def test_format_packet_strips_escape_from_node_names(self):
        state = make_state()
        state.nodes.import_nodes(
            {
                "!11111111": {
                    "num": 0x11111111,
                    "user": {"shortName": f"A{ESC_PAYLOAD}B", "longName": f"L{ESC_PAYLOAD}N"},
                }
            }
        )
        packet = text_packet(2, "hi", rxTime=1_700_000_000)
        assert "\x1b" not in format_packet(packet, state.nodes).plain

    def test_format_payload_strips_escape_from_nodeinfo_and_routing(self):
        nodeinfo = {
            "from": 1,
            "to": 2,
            "decoded": {
                "portnum": "NODEINFO_APP",
                "user": {
                    "longName": f"Long{ESC_PAYLOAD}",
                    "shortName": f"S{ESC_PAYLOAD}",
                    "hwModel": f"HW{ESC_PAYLOAD}",
                },
            },
        }
        routing = {
            "from": 1,
            "to": 2,
            "decoded": {
                "portnum": "ROUTING_APP",
                "routing": {"errorReason": f"BAD{ESC_PAYLOAD}"},
            },
        }
        assert "\x1b" not in format_payload(nodeinfo).plain
        assert "\x1b" not in format_payload(routing).plain

    @pytest.mark.asyncio
    async def test_chat_log_never_writes_escape_bytes(self):
        state = make_state()
        state.nodes.import_nodes(
            {
                "!11111111": {
                    "num": 0x11111111,
                    "user": {"shortName": f"N{ESC_PAYLOAD}", "longName": "Name"},
                }
            }
        )
        chat = ChatLog(state)
        app = WidgetHost(chat)
        async with app.run_test() as pilot:
            await settle(pilot)
            written = []
            original_write = chat.write

            def capture(content, *args, **kwargs):
                written.append(getattr(content, "plain", str(content)))
                return original_write(content, *args, **kwargs)

            chat.write = capture
            state.messages.add(text_packet(10, f"boom {ESC_PAYLOAD} \x1b]52;c;QQ==\x07"))
            await settle(pilot)
            assert written, "chat log did not render the message"
            assert all("\x1b" not in line for line in written)


# ===========================================================================
# 3. Python metadata
# ===========================================================================


class TestPythonMetadata:
    def test_requires_python_is_at_least_3_10(self):
        text = (REPO_ROOT / "pyproject.toml").read_text()
        match = re.search(r'^requires-python\s*=\s*"([^"]+)"', text, re.MULTILINE)
        assert match, "requires-python missing"
        spec = match.group(1)
        lower = re.search(r">=\s*(\d+)\.(\d+)", spec)
        assert lower, f"unexpected requires-python spec: {spec}"
        assert (int(lower.group(1)), int(lower.group(2))) >= (3, 10)

    def test_ci_matrix_has_no_unsupported_python(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text()
        versions = []
        for match in re.finditer(r"python-version:\s*\[([^\]]*)\]", workflow):
            versions += [v.strip().strip("'\"") for v in match.group(1).split(",") if v.strip()]
        assert versions, "no python-version matrix found"
        assert "3.9" not in versions
        assert "3.8" not in versions

    def test_classifiers_do_not_advertise_unsupported_python(self):
        text = (REPO_ROOT / "pyproject.toml").read_text()
        assert "Programming Language :: Python :: 3.8" not in text
        assert "Programming Language :: Python :: 3.9" not in text


# ===========================================================================
# 4. ChannelManager widget ids
# ===========================================================================


class TestChannelManager:
    @pytest.mark.asyncio
    async def test_compose_with_open_dm_and_select_resolves_original_id(self):
        state = make_state()
        state.open_dms.open_dm("!a1b2c3d4", "Alpha")
        results = []
        app = WidgetHost()
        async with app.run_test() as pilot:
            await app.push_screen(ChannelManager(state), callback=results.append)
            await settle(pilot)
            dm_list = app.screen.query_one("#dm-list", ListView)
            assert len(dm_list.children) == 1
            dm_list.index = 0
            dm_list.action_select_cursor()
            await settle(pilot)
        assert results == [("dm", "!a1b2c3d4")]

    @pytest.mark.asyncio
    async def test_node_search_result_select_resolves_original_id(self):
        state = make_state()
        state.nodes.import_nodes(
            {
                "!a1b2c3d4": {
                    "num": 0xA1B2C3D4,
                    "user": {"id": "!a1b2c3d4", "shortName": "ALPH", "longName": "Alpha"},
                }
            }
        )
        results = []
        app = WidgetHost()
        async with app.run_test() as pilot:
            await app.push_screen(ChannelManager(state), callback=results.append)
            await settle(pilot)
            search = app.screen.query_one("#node-search", Input)
            search.value = "alph"
            await pilot.pause(0.2)
            found = app.screen.query_one("#node-results", ListView)
            assert await wait_until(pilot, lambda: len(found.children) == 1)
            found.index = 0
            found.action_select_cursor()
            await settle(pilot)
        assert results == [("new_dm", "!a1b2c3d4")]
        assert state.open_dms.is_dm_open("!a1b2c3d4")

    @pytest.mark.asyncio
    async def test_close_open_dm_with_bang_id(self):
        state = make_state()
        state.open_dms.open_dm("!a1b2c3d4", "Alpha")
        app = WidgetHost()
        async with app.run_test() as pilot:
            await app.push_screen(ChannelManager(state))
            await settle(pilot)
            dm_list = app.screen.query_one("#dm-list", ListView)
            dm_list.index = 0
            app.screen.action_close_selected()
            await settle(pilot)
        assert not state.open_dms.is_dm_open("!a1b2c3d4")


# ===========================================================================
# 5. Disconnect from a worker thread / 6. Retry button
# ===========================================================================


class TestDisconnectThreading:
    @pytest.mark.asyncio
    async def test_unexpected_disconnect_from_worker_thread_shows_modal_on_ui_thread(
        self, monkeypatch
    ):
        monkeypatch.setattr(ReconnectingModal, "_start_reconnect", lambda self: None)
        app = make_meshterm_app()
        push_threads = []
        async with app.run_test() as pilot:
            await settle(pilot)
            ui_thread = threading.get_ident()
            original_push = app.push_screen

            def recording_push(*args, **kwargs):
                push_threads.append(threading.get_ident())
                return original_push(*args, **kwargs)

            monkeypatch.setattr(app, "push_screen", recording_push)

            # Must not raise when invoked like the pubsub thread does.
            await asyncio.to_thread(app._on_connection_status, "disconnected", None)

            assert await wait_until(pilot, lambda: isinstance(app.screen, ReconnectingModal))
            assert push_threads, "reconnect modal was never pushed"
            assert set(push_threads) == {ui_thread}

    @pytest.mark.asyncio
    async def test_second_disconnect_still_shows_modal_after_worker_thread_call(self, monkeypatch):
        monkeypatch.setattr(ReconnectingModal, "_start_reconnect", lambda self: None)
        app = make_meshterm_app()
        async with app.run_test() as pilot:
            await settle(pilot)
            await asyncio.to_thread(app._on_connection_status, "disconnected", None)
            assert await wait_until(pilot, lambda: isinstance(app.screen, ReconnectingModal))
            app.screen.dismiss(False)
            assert await wait_until(pilot, lambda: not isinstance(app.screen, ReconnectingModal))
            # Let the dismiss callback (which re-arms the handler) run.
            await pilot.pause(0.3)
            await asyncio.to_thread(app._on_connection_status, "disconnected", None)
            assert await wait_until(pilot, lambda: isinstance(app.screen, ReconnectingModal))

    @pytest.mark.asyncio
    async def test_disconnect_from_ui_thread_also_shows_modal(self, monkeypatch):
        monkeypatch.setattr(ReconnectingModal, "_start_reconnect", lambda self: None)
        app = make_meshterm_app()
        async with app.run_test() as pilot:
            await settle(pilot)
            app._on_connection_status("disconnected", None)
            assert await wait_until(pilot, lambda: isinstance(app.screen, ReconnectingModal))


class TestReconnectRetryButton:
    @pytest.mark.asyncio
    async def test_retry_handler_does_not_call_from_thread_on_app_thread(self, monkeypatch):
        monkeypatch.setattr(ReconnectingModal, "MAX_ATTEMPTS", 1)
        monkeypatch.setattr(ReconnectingModal, "RETRY_DELAY", 0.0)
        monkeypatch.setattr(
            "meshtastic.serial_interface.SerialInterface",
            MagicMock(side_effect=OSError("no device")),
        )
        connection = SimpleNamespace(
            interface=None, port="/dev/ttyFAKE0", _on_connected=MagicMock()
        )
        modal = ReconnectingModal(connection, reason="reconnect", port="/dev/ttyFAKE0")
        app = WidgetHost()
        violations = []
        async with app.run_test() as pilot:
            ui_thread = threading.get_ident()
            original_call = app.call_from_thread

            def recording_call(callback, *args, **kwargs):
                if threading.get_ident() == ui_thread:
                    violations.append(getattr(callback, "__name__", repr(callback)))
                return original_call(callback, *args, **kwargs)

            monkeypatch.setattr(app, "call_from_thread", recording_call)

            await app.push_screen(modal)
            retry = modal.query_one("#retry-btn", Button)
            assert await wait_until(pilot, lambda: not retry.disabled), "retry never enabled"

            retry.press()
            await pilot.pause(0.2)
            assert violations == [], f"call_from_thread used on the app thread: {violations}"
            assert app.is_running

            # The retry thread runs to completion and re-enables the button.
            assert await wait_until(pilot, lambda: not retry.disabled), "retry stuck disabled"
            assert violations == []


# ===========================================================================
# 7. Interval dropdowns
# ===========================================================================


def select_options(select: Select):
    return [(str(prompt), value) for prompt, value in select._options]


class TestIntervals:
    @pytest.mark.asyncio
    async def test_position_and_telemetry_zero_option_is_labeled_default(self):
        connection = MagicMock()
        position = PositionPanel(connection)
        device = DevicePanel(connection)
        app = WidgetHost(position, device)
        async with app.run_test() as pilot:
            await settle(pilot)
            for panel, select_id in (
                (position, "#pos-broadcast-select"),
                (device, "#telemetry-interval-select"),
            ):
                options = select_options(panel.query_one(select_id, Select))
                labels = {value: label for label, value in options}
                assert labels[0] == "Default", f"{select_id}: {options}"
                assert "Disabled" not in labels.values()

    @pytest.mark.asyncio
    async def test_saving_unrelated_device_field_keeps_existing_600s_intervals(self):
        connection = MagicMock()
        connection.will_cause_reboot.return_value = False
        connection.write_config.return_value = True
        connection.write_module_config.return_value = True
        connection.write_owner.return_value = True
        panel = DevicePanel(connection)
        app = WidgetHost(panel)
        async with app.run_test() as pilot:
            await settle(pilot)
            panel.load_config(
                {
                    "device": {
                        "role": 0,
                        "rebroadcast_mode": 0,
                        "node_info_broadcast_secs": 600,
                    },
                    "user": {"long_name": "Old Name", "short_name": "OLD"},
                    "telemetry": {"device_update_interval": 600},
                }
            )
            await settle(pilot)
            panel.query_one("#long-name-input", Input).value = "New Name"
            await settle(pilot)
            panel.query_one("#save-btn", Button).press()
            await settle(pilot)

        for call in connection.write_config.call_args_list:
            _, values = call_values(call)
            assert values.get("node_info_broadcast_secs", 600) == 600
        for call in connection.write_module_config.call_args_list:
            _, values = call_values(call)
            assert values.get("device_update_interval", 600) == 600
        connection.write_owner.assert_called()

    @pytest.mark.asyncio
    async def test_saving_unrelated_position_field_keeps_existing_600s_interval(self):
        connection = MagicMock()
        connection.will_cause_reboot.return_value = False
        connection.write_config.return_value = True
        panel = PositionPanel(connection)
        app = WidgetHost(panel)
        async with app.run_test() as pilot:
            await settle(pilot)
            panel.load_config(
                {
                    "position": {
                        "gps_mode": 1,
                        "position_broadcast_secs": 600,
                        "fixed_position": False,
                    }
                }
            )
            await settle(pilot)
            panel.query_one("#fixed-pos-switch", Switch).value = True
            await settle(pilot)
            panel.query_one("#save-btn", Button).press()
            await settle(pilot)

        position_calls = [
            call_values(c)[1]
            for c in connection.write_config.call_args_list
            if call_values(c)[0] == "position"
        ]
        assert position_calls, "position config was not written"
        for values in position_calls:
            assert values.get("position_broadcast_secs", 600) == 600


# ===========================================================================
# 8. PSK validation
# ===========================================================================


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


VALID_PSKS = [
    pytest.param("01", b"\x01", id="hex-1-byte"),
    pytest.param(
        "00112233445566778899aabbccddeeff",
        bytes.fromhex("00112233445566778899aabbccddeeff"),
        id="hex-16-bytes",
    ),
    pytest.param("ab" * 32, bytes.fromhex("ab" * 32), id="hex-32-bytes"),
    pytest.param(_b64(b"\x07"), b"\x07", id="base64-1-byte"),
    pytest.param(_b64(bytes(range(16))), bytes(range(16)), id="base64-16-bytes"),
    pytest.param(_b64(bytes(range(32))), bytes(range(32)), id="base64-32-bytes"),
    pytest.param("default", b"\x01", id="keyword-default"),
    pytest.param("none", b"\x00", id="keyword-none"),
]

INVALID_PSKS = [
    pytest.param("!!!!", id="garbage-base64"),
    pytest.param("", id="empty"),
    pytest.param("   ", id="whitespace"),
    pytest.param("abc", id="odd-length-hex"),
    pytest.param("a" * 33, id="odd-length-long-hex"),
    pytest.param("aabbcc", id="hex-wrong-key-length"),
    pytest.param(_b64(b"\x01\x02\x03"), id="base64-wrong-key-length"),
]


class TestPskValidation:
    @pytest.mark.parametrize("psk, expected", VALID_PSKS)
    def test_valid_keys_are_written(self, connection, node, psk, expected):
        configure_channel(node, 2)
        assert connection.write_channel(2, {"name": "ch", "psk": psk}) is True
        node.writeChannel.assert_called_once()
        assert node.channels[2].settings.psk == expected

    def test_random_keyword_generates_32_byte_key(self, connection, node):
        configure_channel(node, 2)
        assert connection.write_channel(2, {"psk": "random"}) is True
        assert len(node.channels[2].settings.psk) == 32

    @pytest.mark.parametrize("psk", INVALID_PSKS)
    def test_invalid_keys_are_rejected_without_writing(self, connection, node, psk):
        configure_channel(node, 2)
        before = node.channels[2].SerializeToString()
        assert connection.write_channel(2, {"name": "ch", "psk": psk}) is False
        node.writeChannel.assert_not_called()
        assert node.channels[2].SerializeToString() == before


# ===========================================================================
# 9. Region enum
# ===========================================================================


def _schema_regions():
    return dict(config_pb2.Config.LoRaConfig.RegionCode.items())


LORA_FORM = {"modem_preset": 0, "tx_power": 17, "hop_limit": 5, "tx_enabled": True}


class TestRegion:
    @pytest.mark.asyncio
    async def test_region_options_include_every_schema_value(self):
        panel = RadioConfigPanel(MagicMock())
        app = WidgetHost(panel)
        async with app.run_test() as pilot:
            await settle(pilot)
            options = select_options(panel.query_one("#region-select", Select))
        values = {value for _, value in options}
        labels = " ".join(label for label, _ in options)
        schema = _schema_regions()
        for name in ("PH_433", "ANZ_433", "KZ_433"):
            assert schema[name] in values, f"{name} missing from region options"
            assert name in labels
        assert set(schema.values()) <= values

    @pytest.mark.asyncio
    async def test_newer_region_loads_and_saves_without_losing_other_fields(self):
        connection = MagicMock()
        connection.will_cause_reboot.return_value = False
        connection.write_config.return_value = True
        panel = RadioConfigPanel(connection)
        app = WidgetHost(panel)
        ph_433 = _schema_regions()["PH_433"]
        async with app.run_test() as pilot:
            await settle(pilot)
            panel.load_config({"lora": {"region": ph_433, **LORA_FORM}})
            await settle(pilot)
            assert panel.query_one("#region-select", Select).value == ph_433
            assert panel.query_one("#tx-power-input", Input).value == "17"
            assert panel.query_one("#hop-limit-input", Input).value == "5"
            panel.query_one("#save-btn", Button).press()
            await settle(pilot)
        connection.write_config.assert_called_once()
        _, values = call_values(connection.write_config.call_args)
        assert values["region"] == ph_433
        assert values["tx_power"] == 17
        assert values["hop_limit"] == 5

    @pytest.mark.asyncio
    async def test_unsupported_region_blocks_save(self):
        connection = MagicMock()
        connection.will_cause_reboot.return_value = False
        connection.write_config.return_value = True
        panel = RadioConfigPanel(connection)
        app = WidgetHost(panel)
        async with app.run_test() as pilot:
            await settle(pilot)
            panel.load_config({"lora": {"region": 999, **LORA_FORM}})
            await settle(pilot)
            panel.query_one("#save-btn", Button).press()
            await settle(pilot)
        connection.write_config.assert_not_called()


# ===========================================================================
# 10. Read-only install
# ===========================================================================


class TestReadOnlyInstall:
    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
    def test_import_app_from_read_only_package_parent(self, repo_tmp, isolated_xdg):
        site = repo_tmp / "site-packages"
        site.mkdir()
        shutil.copytree(
            PACKAGE_DIR, site / "meshterm", ignore=shutil.ignore_patterns("__pycache__")
        )
        env = dict(os.environ)
        env.update(
            PYTHONPATH=str(site),
            PYTHONDONTWRITEBYTECODE="1",
            XDG_DATA_HOME=str(isolated_xdg["data"]),
            XDG_STATE_HOME=str(isolated_xdg["state"]),
            HOME=str(isolated_xdg["home"]),
        )
        code = (
            "import sys, meshterm;"
            "assert meshterm.__file__.startswith(sys.argv[1]), meshterm.__file__;"
            "import meshterm.app"
        )
        try:
            os.chmod(site / "meshterm", 0o555)
            os.chmod(site, 0o555)
            result = subprocess.run(
                [sys.executable, "-c", code, str(site)],
                cwd=str(repo_tmp),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            os.chmod(site, 0o755)
            os.chmod(site / "meshterm", 0o755)
        assert result.returncode == 0, result.stderr[-2000:]


# ===========================================================================
# 11. File permissions
# ===========================================================================


@pytest.fixture
def umask_022():
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


class TestPermissions:
    def test_new_data_dir_is_private(self, umask_022, isolated_xdg):
        assert not (isolated_xdg["data"] / "meshterm").exists()
        data_dir = get_data_dir()
        assert mode_of(data_dir) == 0o700

    def test_new_database_and_config_are_private(self, umask_022, isolated_xdg):
        storage = LogStorage()
        try:
            storage.store_packet(text_packet(1, "secret dm"), time.time())
        finally:
            storage.close()
        save_config({"use_gps": False})
        data_dir = isolated_xdg["data"] / "meshterm"
        assert mode_of(data_dir) == 0o700
        assert mode_of(data_dir / "messages.db") == 0o600
        assert mode_of(data_dir / "config.json") == 0o600

    def test_existing_loose_modes_are_tightened(self, umask_022, isolated_xdg):
        data_dir = isolated_xdg["data"] / "meshterm"
        data_dir.mkdir()
        os.chmod(data_dir, 0o755)
        db_path = data_dir / "messages.db"
        db_path.touch()
        os.chmod(db_path, 0o644)
        LogStorage().close()
        assert mode_of(data_dir) == 0o700
        assert mode_of(db_path) == 0o600

    @pytest.mark.asyncio
    async def test_exported_config_is_private(self, umask_022, isolated_xdg):
        connection = MagicMock()
        connection.export_config.return_value = (
            True,
            {"channels": [{"index": 0, "psk_b64": "AQ=="}]},
            "ok",
        )
        panel = AdvancedPanel(connection, state=make_state())
        app = WidgetHost(panel)
        async with app.run_test() as pilot:
            await settle(pilot)
            panel.query_one("#export-btn", Button).press()
            await settle(pilot)
        export = isolated_xdg["data"] / "meshterm" / "meshterm_config.json"
        assert export.exists()
        assert mode_of(export) == 0o600


# ===========================================================================
# 12. Channel write copies the existing protobuf
# ===========================================================================


class TestChannelWritePreservesFields:
    def test_name_only_change_preserves_unexposed_settings(self, connection, node):
        configure_channel(node, 1)
        assert connection.write_channel(1, {"name": "renamed"}) is True
        node.writeChannel.assert_called_once()
        assert node.writeChannel.call_args.args[0] == 1
        written = node.channels[1]
        assert written.index == 1
        assert written.settings.name == "renamed"
        assert written.settings.module_settings.position_precision == 13
        assert written.settings.module_settings.is_muted is True
        assert written.settings.psk == bytes(range(16))
        assert written.settings.channel_num == 5
        assert written.settings.id == 77
        assert written.settings.uplink_enabled is True
        assert written.role == channel_pb2.Channel.Role.SECONDARY

    def test_form_style_save_preserves_unexposed_settings(self, connection, node):
        configure_channel(node, 1)
        form = {
            "index": 1,
            "role": channel_pb2.Channel.Role.SECONDARY,
            "name": "renamed",
            "psk": bytes(range(16)).hex(),
            "uplink_enabled": False,
            "downlink_enabled": True,
        }
        assert connection.write_channel(1, form) is True
        written = node.channels[1]
        assert written.settings.uplink_enabled is False
        assert written.settings.downlink_enabled is True
        assert written.settings.module_settings.position_precision == 13
        assert written.settings.module_settings.is_muted is True

    def test_other_channels_are_untouched(self, connection, node):
        configure_channel(node, 1)
        before = [c.SerializeToString() for i, c in enumerate(node.channels) if i != 1]
        connection.write_channel(1, {"name": "renamed"})
        after = [c.SerializeToString() for i, c in enumerate(node.channels) if i != 1]
        assert before == after


# ===========================================================================
# 13. Config write failure restores the cache
# ===========================================================================


class TestConfigWriteFailureRollback:
    @pytest.mark.parametrize(
        "section, values",
        [
            ("lora", {"region": 3, "hop_limit": 6, "tx_power": 20}),
            ("position", {"gps_mode": 1, "position_broadcast_secs": 900}),
            ("device", {"role": 2, "node_info_broadcast_secs": 3600}),
        ],
    )
    def test_failed_write_config_restores_local_config(self, connection, node, section, values):
        getattr(node.localConfig, section).SetInParent()
        before = node.localConfig.SerializeToString()
        node.writeConfig.side_effect = RuntimeError("serial write failed")

        assert connection.write_config(section, values) is False

        assert node.localConfig.SerializeToString() == before

    def test_invalid_value_midway_does_not_leave_partial_changes(self, connection, node):
        node.localConfig.lora.hop_limit = 3
        node.localConfig.lora.region = 1
        before = node.localConfig.SerializeToString()

        # hop_limit is applied first; the bad region type then raises.
        result = connection.write_config("lora", {"hop_limit": 6, "region": "not-an-int"})

        assert result is False
        assert node.localConfig.SerializeToString() == before
        node.writeConfig.assert_not_called()

    def test_failed_module_write_restores_module_config(self, connection, node):
        node.moduleConfig.telemetry.device_update_interval = 600
        before = node.moduleConfig.SerializeToString()
        node.writeConfig.side_effect = RuntimeError("serial write failed")

        assert (
            connection.write_module_config("telemetry", {"device_update_interval": 3600}) is False
        )

        assert node.moduleConfig.SerializeToString() == before

    def test_successful_write_keeps_new_value(self, connection, node):
        node.localConfig.lora.hop_limit = 3
        assert connection.write_config("lora", {"hop_limit": 6}) is True
        assert node.localConfig.lora.hop_limit == 6
        node.writeConfig.assert_called_once_with("lora")

    def test_will_cause_reboot_after_failed_write_compares_against_device_value(
        self, connection, node
    ):
        node.localConfig.lora.region = 1
        node.writeConfig.side_effect = RuntimeError("serial write failed")
        connection.write_config("lora", {"region": 3})
        # Device still has region 1, so asking for 3 must still need a reboot.
        assert connection.will_cause_reboot("lora", {"region": 3}) is True


# ===========================================================================
# 14. Export owner
# ===========================================================================


class TestExportOwner:
    def test_export_includes_owner_when_nodes_keyed_by_string_id(self, connection):
        ok, config, _ = connection.export_config()
        assert ok is True
        assert config.get("owner") == {"long_name": "Alpha Station", "short_name": "ALPH"}

    def test_export_owner_survives_missing_string_key_when_nodes_by_num_present(self, connection):
        # Only the integer-keyed map knows about our node.
        connection.interface.nodes = {}
        ok, config, _ = connection.export_config()
        assert ok is True
        assert config.get("owner", {}).get("long_name") == "Alpha Station"


# ===========================================================================
# 15. Clear messages clears memory too
# ===========================================================================


class TestClearMessages:
    @pytest.mark.asyncio
    async def test_clear_messages_clears_buffer_and_chat_log(self):
        storage = LogStorage(db_path=Path(":memory:"))
        state = make_state(storage)
        state.messages.add(text_packet(1, "first"))
        state.messages.add(text_packet(2, "second"))
        assert len(state.messages) == 2

        panel = AdvancedPanel(MagicMock(), state=state)
        chat = ChatLog(state)
        app = WidgetHost(panel, chat)
        async with app.run_test() as pilot:
            await settle(pilot)
            chat.load_messages()
            assert len(chat._displayed_entries) == 2

            panel.query_one("#clear-messages-btn", Button).press()
            await settle(pilot)
            dialog = app.screen
            assert dialog is not app.screen_stack[0]
            dialog.query_one("#confirm-input", Input).value = "CLEAR"
            dialog.query_one("#confirm-btn", Button).press()
            await settle(pilot)

            assert storage.get_stats()["messages"] == 0
            assert len(state.messages) == 0
            assert state.messages.get_text_messages(0) == []

            chat.load_messages()
            assert chat._displayed_entries == []


# ===========================================================================
# 16. Reply preview
# ===========================================================================


class TestReplyPreview:
    @pytest.fixture
    def thread(self):
        """Parent A <- reply B <- reply C, as stored rows."""
        storage = LogStorage(db_path=Path(":memory:"))
        now = time.time()
        a = storage.store_packet(text_packet(100, "parent-A"), now)
        b = storage.store_packet(text_packet(101, "reply-B"), now + 1)
        c = storage.store_packet(text_packet(102, "reply-C"), now + 2)
        storage.store_reply_ref(b, 100, now + 1)
        storage.store_reply_ref(c, 101, now + 2)
        return SimpleNamespace(storage=storage, a=a, b=b, c=c)

    @pytest.mark.asyncio
    async def test_ordinary_reply_previews_its_parent(self, thread):
        state = make_state(thread.storage)
        chat = ChatLog(state)
        app = WidgetHost(chat)
        async with app.run_test() as pilot:
            await settle(pilot)
            ref = thread.storage.get_reply_ref(thread.b)
            preview = chat._get_reply_preview(ref)
        assert "parent-A" in preview
        assert "msg #" not in preview

    @pytest.mark.asyncio
    async def test_nested_reply_previews_direct_parent_not_grandparent(self, thread):
        state = make_state(thread.storage)
        chat = ChatLog(state)
        app = WidgetHost(chat)
        async with app.run_test() as pilot:
            await settle(pilot)
            ref = thread.storage.get_reply_ref(thread.c)
            preview = chat._get_reply_preview(ref)
        assert "reply-B" in preview
        assert "parent-A" not in preview

    @pytest.mark.asyncio
    async def test_loaded_reply_renders_parent_preview(self, thread):
        state = make_state(thread.storage)
        chat = ChatLog(state)
        app = WidgetHost(chat)
        async with app.run_test() as pilot:
            await settle(pilot)
            written = []
            original_write = chat.write

            def capture(content, *args, **kwargs):
                written.append(getattr(content, "plain", str(content)))
                return original_write(content, *args, **kwargs)

            chat.write = capture
            chat.load_messages()
            await settle(pilot)
        reply_b_lines = [line for line in written if "reply-B" in line and "parent-A" in line]
        assert reply_b_lines, f"reply B did not show a preview of parent A: {written}"


# ===========================================================================
# 17. Reply / reaction scoping
# ===========================================================================


class TestConversationScoping:
    def test_find_message_by_packet_id_respects_channel(self):
        storage = LogStorage(db_path=Path(":memory:"))
        storage.store_packet(text_packet(500, "on-channel-1", channel=1), time.time())
        assert storage.find_message_by_packet_id(500, channel=0) is None
        found = storage.find_message_by_packet_id(500, channel=1)
        assert found is not None and found.channel == 1

    def test_duplicate_packet_ids_resolve_within_the_requested_channel(self):
        storage = LogStorage(db_path=Path(":memory:"))
        now = time.time()
        first = storage.store_packet(text_packet(900, "ch0", channel=0), now)
        second = storage.store_packet(text_packet(900, "ch1", channel=1), now + 1)
        assert storage.find_message_by_packet_id(900, channel=0).id == first
        assert storage.find_message_by_packet_id(900, channel=1).id == second

    @pytest.fixture
    def wired(self):
        state = make_state()
        conn = MeshtasticConnection(state)
        yield state, conn
        conn.cleanup()

    def test_reaction_from_other_channel_does_not_touch_message(self, wired):
        state, conn = wired
        db_id = state.messages.add(text_packet(700, "target", channel=0))
        reaction = text_packet(701, "[R:700:👍]", channel=3, frm=0x22222222)
        conn._on_receive(reaction, None)
        assert state.storage.get_reactions_for_message(db_id) == []

    def test_reaction_on_same_channel_is_still_applied(self, wired):
        state, conn = wired
        db_id = state.messages.add(text_packet(700, "target", channel=0))
        reaction = text_packet(701, "[R:700:👍]", channel=0, frm=0x22222222)
        conn._on_receive(reaction, None)
        reactions = state.storage.get_reactions_for_message(db_id)
        assert [r["emoji"] for r in reactions] == ["👍"]

    def test_reply_from_other_channel_does_not_link_to_parent(self, wired):
        state, conn = wired
        state.messages.add(text_packet(700, "target", channel=0))
        reply = text_packet(710, "[>:700] answering", channel=3, frm=0x22222222)
        conn._on_receive(reply, None)
        reply_row = state.storage.find_message_by_packet_id(710)
        assert reply_row is not None
        ref = state.storage.get_reply_ref(reply_row.id)
        assert ref is None or ref["parent_db_id"] is None

    def test_reply_on_same_channel_links_to_parent(self, wired):
        state, conn = wired
        parent_db_id = state.messages.add(text_packet(700, "target", channel=0))
        reply = text_packet(710, "[>:700] answering", channel=0, frm=0x22222222)
        conn._on_receive(reply, None)
        reply_row = state.storage.find_message_by_packet_id(710, channel=0)
        ref = state.storage.get_reply_ref(reply_row.id)
        assert ref is not None and ref["parent_db_id"] == parent_db_id


# ===========================================================================
# 18. SQLite concurrency
# ===========================================================================


class _HookedConnection:
    """Delegating proxy that runs a hook when the Nth DELETE executes."""

    def __init__(self, inner, on_delete):
        self._inner = inner
        self._on_delete = on_delete

    def execute(self, sql, *args, **kwargs):
        if sql.lstrip().upper().startswith("DELETE FROM"):
            self._on_delete()
        return self._inner.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class TestSqliteConcurrency:
    def test_storage_exposes_a_lock(self):
        storage = LogStorage(db_path=Path(":memory:"))
        lock_names = [n for n in vars(storage) if "lock" in n.lower()]
        assert lock_names, "LogStorage has no lock attribute"
        lock = getattr(storage, lock_names[0])
        assert hasattr(lock, "acquire") and hasattr(lock, "release")

    def test_clear_messages_is_atomic_against_concurrent_store_packet(self, repo_tmp):
        db_path = repo_tmp / "concurrent.db"
        storage = LogStorage(db_path=db_path)
        now = time.time()
        parent = storage.store_packet(text_packet(1, "parent"), now)
        reply = storage.store_packet(text_packet(2, "reply"), now + 1)
        storage.store_reply_ref(reply, 1, now + 1)
        storage.store_reaction(
            message_db_id=parent,
            message_packet_id=1,
            reactor_node="!22222222",
            emoji="👍",
            timestamp=now + 2,
        )

        observed = {}
        worker_errors = []
        deletes = {"n": 0}
        worker = {}

        def concurrent_insert():
            try:
                storage.store_packet(text_packet(3, "late arrival"), time.time())
            except Exception as exc:  # pragma: no cover - failure detail
                worker_errors.append(exc)

        def on_delete():
            deletes["n"] += 1
            if deletes["n"] != 2:
                return
            # A packet arrives on the receive thread in the middle of the clear.
            thread = threading.Thread(target=concurrent_insert)
            worker["thread"] = thread
            thread.start()
            thread.join(timeout=0.5)
            # What would another reader of the database see right now?
            reader = sqlite3.connect(str(db_path), timeout=1)
            try:
                observed["counts"] = tuple(
                    reader.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("reply_refs", "reactions")
                )
            finally:
                reader.close()

        storage._conn = _HookedConnection(storage._conn, on_delete)

        assert storage.clear_messages() >= 2
        thread = worker.get("thread")
        if thread is not None:
            thread.join(timeout=10)
            assert not thread.is_alive()
        assert worker_errors == []

        if "counts" in observed:
            # Nothing may be committed halfway through the clear.
            assert observed["counts"] == (1, 1), (
                "partial clear became visible to other readers: "
                f"(reply_refs, reactions) = {observed['counts']}"
            )

        orphans = storage._conn.execute(
            "SELECT (SELECT COUNT(*) FROM reply_refs WHERE reply_db_id NOT IN (SELECT id FROM packets))"
            " + (SELECT COUNT(*) FROM reactions WHERE message_db_id NOT IN (SELECT id FROM packets))"
        ).fetchone()[0]
        assert orphans == 0
        storage.close()

    def test_parallel_writers_do_not_lose_rows_or_raise(self, repo_tmp):
        storage = LogStorage(db_path=repo_tmp / "parallel.db")
        errors = []

        def writer(offset):
            try:
                for i in range(40):
                    storage.store_packet(text_packet(offset + i, f"m{offset + i}"), time.time())
            except Exception as exc:  # pragma: no cover - failure detail
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(n * 1000,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert errors == []
        assert storage.get_stats()["messages"] == 160
        storage.close()


# ===========================================================================
# 19. Early ACK racing the send / input lock
# ===========================================================================


class TestEarlyAckInputLock:
    @pytest.mark.asyncio
    async def test_synchronous_early_ack_leaves_input_unlocked(self):
        from meshterm.widgets.chat_input import ChatInput

        app = make_meshterm_app()
        request_id = 424242
        events = []

        def send_message(text, dest="^all", channel=0):
            events.append("send")
            # The ACK arrives before send_message even returns.
            app.state.messages.resolve_pending(request_id, True)
            return True, request_id

        app.connection.send_message.side_effect = send_message

        async with app.run_test() as pilot:
            await settle(pilot)
            app.action_switch_tab("chat")
            await settle(pilot)
            chat_input = app.query_one("#chat-input", ChatInput)

            original_lock = chat_input.lock_input
            original_add_pending = app.state.messages.add_pending

            def spy_lock(*args, **kwargs):
                events.append("lock")
                return original_lock(*args, **kwargs)

            def spy_add_pending(*args, **kwargs):
                events.append("add_pending")
                return original_add_pending(*args, **kwargs)

            chat_input.lock_input = spy_lock
            app.state.messages.add_pending = spy_add_pending
            app.state.messages.subscribe(
                lambda event_type, data: (
                    events.append(event_type) if event_type == "delivery_updated" else None
                )
            )

            chat_input.post_message(ChatInput.MessageSubmitted("hello mesh", 0))
            assert await wait_until(pilot, lambda: "delivery_updated" in events)
            await settle(pilot)

            assert chat_input.send_locked is False
            assert chat_input.send_locked_request_id is None
            assert "lock" in events and "add_pending" in events
            # Lock first, then reconcile: a synchronous early ACK must be able to unlock.
            assert events.index("lock") < events.index("add_pending")
            assert events.index("add_pending") < events.index("delivery_updated")
            assert not app.state.messages._pending


# ===========================================================================
# 20. DM packet-id collision scoping
# ===========================================================================


class TestDmCollisionScoping:
    PEER_A = 0xAAAA0001
    PEER_B = 0xBBBB0002
    ME = 0x0000BEEF
    PACKET_ID = 5000

    @pytest.fixture
    def collided(self):
        state = make_state()
        conn = MeshtasticConnection(state)
        now = time.time()
        row_a = state.storage.store_packet(
            text_packet(self.PACKET_ID, "from A", channel=0, frm=self.PEER_A, to=self.ME), now
        )
        row_b = state.storage.store_packet(
            text_packet(self.PACKET_ID, "from B", channel=0, frm=self.PEER_B, to=self.ME), now + 1
        )
        yield SimpleNamespace(state=state, conn=conn, row_a=row_a, row_b=row_b)
        conn.cleanup()

    def test_find_by_endpoints_returns_the_matching_peer_only(self, collided):
        storage = collided.state.storage
        a, b, me = (formatting.format_node_id(n) for n in (self.PEER_A, self.PEER_B, self.ME))

        found_a = storage.find_message_by_packet_id(self.PACKET_ID, channel=0, endpoints=(a, me))
        found_b = storage.find_message_by_packet_id(self.PACKET_ID, channel=0, endpoints=(b, me))

        assert found_a is not None and found_a.id == collided.row_a
        assert found_b is not None and found_b.id == collided.row_b
        assert found_b.id != collided.row_a

    def test_endpoints_do_not_leak_across_peers(self, collided):
        storage = collided.state.storage
        me = formatting.format_node_id(self.ME)
        stranger = "!cccc0003"
        assert (
            storage.find_message_by_packet_id(self.PACKET_ID, channel=0, endpoints=(stranger, me))
            is None
        )

    def test_reaction_from_peer_a_resolves_only_peer_a_row(self, collided):
        storage = collided.state.storage
        reaction = text_packet(
            6000, f"[R:{self.PACKET_ID}:👍]", channel=0, frm=self.PEER_A, to=self.ME
        )
        collided.conn._on_receive(reaction, None)

        assert [r["emoji"] for r in storage.get_reactions_for_message(collided.row_a)] == ["👍"]
        assert storage.get_reactions_for_message(collided.row_b) == []

    def test_reaction_from_peer_b_resolves_only_peer_b_row(self, collided):
        storage = collided.state.storage
        reaction = text_packet(
            6001, f"[R:{self.PACKET_ID}:❗]", channel=0, frm=self.PEER_B, to=self.ME
        )
        collided.conn._on_receive(reaction, None)

        assert [r["emoji"] for r in storage.get_reactions_for_message(collided.row_b)] == ["❗"]
        assert storage.get_reactions_for_message(collided.row_a) == []


# ===========================================================================
# 21. Early-ACK bounds and TTL
# ===========================================================================


class _FakeClock:
    """Stand-in for the `time` module inside meshterm.state."""

    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


class TestEarlyAckBounds:
    def test_unmatched_early_acks_are_bounded(self):
        from meshterm.state import MessageBuffer

        buffer = MessageBuffer()
        for request_id in range(1, 201):
            buffer.resolve_pending(request_id, True)
        assert len(buffer._early_acks) <= 128
        assert len(buffer._early_ack_order) <= 128

    def test_stale_early_ack_is_not_applied_but_fresh_one_is(self, monkeypatch):
        from meshterm.state import MessageBuffer

        clock = _FakeClock(1_000_000.0)
        monkeypatch.setattr("meshterm.state.time", clock)
        buffer = MessageBuffer()
        events = []
        buffer.subscribe(lambda event_type, data: events.append((event_type, data)))

        buffer.resolve_pending(11, True)  # will go stale
        clock.now += 3600  # far beyond any sane reconciliation window
        buffer.resolve_pending(22, True)  # fresh

        stale_packet = {"id": 11, "_delivered": None}
        buffer.add_pending(11, stale_packet, packet_id=11)
        assert 11 in buffer._pending, "stale early ACK must not resolve the send"
        assert stale_packet["_delivered"] is None
        assert not [e for e in events if e[0] == "delivery_updated"]

        fresh_packet = {"id": 22, "_delivered": None}
        buffer.add_pending(22, fresh_packet, packet_id=22)
        assert 22 not in buffer._pending
        assert fresh_packet["_delivered"] is True
        assert [e[1] for e in events if e[0] == "delivery_updated"] == [fresh_packet]

    def test_early_ack_within_ttl_still_reconciles(self):
        from meshterm.state import MessageBuffer

        buffer = MessageBuffer()
        buffer.resolve_pending(7, False, "NO_RESPONSE")
        packet = {"id": 7, "_delivered": None}
        buffer.add_pending(7, packet, packet_id=7)
        assert packet["_delivered"] is False
        assert packet["_error_reason"] == "NO_RESPONSE"
        assert 7 not in buffer._pending


# ===========================================================================
# 22. Channel-0 broadcast vs DM packet-id collision
# ===========================================================================


class TestBroadcastDmCollision:
    SENDER_X = 0x0000AA01
    REACTOR_Y = 0x0000BB02
    PEER_A = 0xAAAA0001
    ME = 0x0000BEEF
    PACKET_ID = 7000

    @pytest.fixture
    def collided(self):
        state = make_state()
        conn = MeshtasticConnection(state)
        now = time.time()
        broadcast_row = state.storage.store_packet(
            text_packet(self.PACKET_ID, "broadcast", channel=0, frm=self.SENDER_X, to=0xFFFFFFFF),
            now,
        )
        # The DM is stored later so a naive "latest row wins" lookup picks it.
        dm_row = state.storage.store_packet(
            text_packet(self.PACKET_ID, "dm", channel=0, frm=self.PEER_A, to=self.ME),
            now + 1,
        )
        yield SimpleNamespace(state=state, conn=conn, broadcast_row=broadcast_row, dm_row=dm_row)
        conn.cleanup()

    def test_broadcast_lookup_returns_broadcast_row(self, collided):
        found = collided.state.storage.find_message_by_packet_id(
            self.PACKET_ID, channel=0, broadcast=True
        )
        assert found is not None
        assert found.id == collided.broadcast_row
        assert found.id != collided.dm_row

    def test_dm_lookup_returns_dm_row(self, collided):
        a, me = (formatting.format_node_id(n) for n in (self.PEER_A, self.ME))
        found = collided.state.storage.find_message_by_packet_id(
            self.PACKET_ID, channel=0, endpoints=(a, me)
        )
        assert found is not None
        assert found.id == collided.dm_row

    def test_broadcast_reaction_resolves_broadcast_not_dm(self, collided):
        storage = collided.state.storage
        reaction = text_packet(
            7100, f"[R:{self.PACKET_ID}:👍]", channel=0, frm=self.REACTOR_Y, to=0xFFFFFFFF
        )
        collided.conn._on_receive(reaction, None)

        assert [r["emoji"] for r in storage.get_reactions_for_message(collided.broadcast_row)] == [
            "👍"
        ]
        assert storage.get_reactions_for_message(collided.dm_row) == []

    def test_broadcast_reply_links_to_broadcast_not_dm(self, collided):
        storage = collided.state.storage
        reply = text_packet(
            7101, f"[>:{self.PACKET_ID}] answering", channel=0, frm=self.REACTOR_Y, to=0xFFFFFFFF
        )
        collided.conn._on_receive(reply, None)

        reply_row = storage.find_message_by_packet_id(7101, channel=0, broadcast=True)
        assert reply_row is not None
        ref = storage.get_reply_ref(reply_row.id)
        assert ref is not None
        assert ref["parent_db_id"] == collided.broadcast_row
