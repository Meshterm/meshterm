"""Regression tests: device writes, SystemExit boundaries, import_config,
connection lifecycle, observers and favorites.

They encode the DESIRED behaviour. The real ``meshtastic.node.Node`` is used
where practical (its ``setOwner`` calls ``our_exit`` -> ``SystemExit`` on empty
names), with the transport (`_sendAdmin`) patched, so no hardware is needed.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from meshtastic.node import Node
from meshtastic.protobuf import channel_pb2
from pubsub import pub

from meshterm.connection import MeshtasticConnection
from meshterm.state import Observable
from meshterm.widgets.reconnecting_modal import ReconnectingModal, ReconnectState
from tests.regression.test_review_fixes import (
    FakeInterface,
    FakeNode,
    WidgetHost,
    configure_channel,
    make_meshterm_app,
    make_state,
    settle,
    text_packet,
    wait_until,
)

OWN_NUM = FakeInterface.OWN_NUM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class RealNodeInterface(FakeInterface):
    """Fake interface whose localNode is a real meshtastic Node."""

    def __init__(self):
        super().__init__(None)
        node = Node(self, OWN_NUM)
        node.channels = [
            channel_pb2.Channel(index=i, role=channel_pb2.Channel.Role.DISABLED) for i in range(8)
        ]
        self.localNode = node
        self.sendText = MagicMock(return_value=SimpleNamespace(id=1234))
        self.sendData = MagicMock()

    def _getOrCreateByNum(self, num):
        # An existing session key makes Node.ensureSessionKey a no-op.
        return {"adminSessionPassKey": b"session-key"}


def snapshot(node):
    return (
        node.localConfig.SerializeToString(),
        node.moduleConfig.SerializeToString(),
        [c.SerializeToString() for c in node.channels],
    )


@pytest.fixture
def real_conn(monkeypatch):
    """Connection bound to a real Node whose transport is mocked out."""
    transport = MagicMock(name="_sendAdmin")
    monkeypatch.setattr(Node, "_sendAdmin", transport)
    conn = MeshtasticConnection(make_state())
    conn.interface = RealNodeInterface()
    conn.transport = transport
    yield conn
    conn.cleanup()
    assert not pub.isSubscribed(conn._on_receive, "meshtastic.receive")


@pytest.fixture
def fake_conn():
    """Connection bound to the mock-based FakeNode used by other regression tests."""
    node = FakeNode()
    conn = MeshtasticConnection(make_state())
    conn.interface = FakeInterface(node)
    conn.node = node
    yield conn
    conn.cleanup()
    assert not pub.isSubscribed(conn._on_receive, "meshtastic.receive")


@pytest.fixture
def make_conn():
    """Factory for connections wired to a status recorder; always unsubscribes."""
    made = []

    def factory():
        state = make_state()
        statuses = []
        conn = MeshtasticConnection(
            state, on_status_change=lambda status, info: statuses.append(status)
        )
        made.append(conn)
        return conn, statuses

    yield factory
    for conn in made:
        conn.cleanup()
        for handler, topic in (
            (conn._on_receive, "meshtastic.receive"),
            (conn._on_connected, "meshtastic.connection.established"),
            (conn._on_disconnected, "meshtastic.connection.lost"),
        ):
            assert not pub.isSubscribed(handler, topic), f"{topic} still subscribed"


# ===========================================================================
# A. Owner and SystemExit boundaries
# ===========================================================================


class TestOwnerValidation:
    @pytest.mark.parametrize(
        "long_name, short_name",
        [("", None), ("   ", None), (None, ""), (None, "   "), ("", ""), ("Name", "")],
        ids=["empty-long", "blank-long", "empty-short", "blank-short", "both-empty", "bad-short"],
    )
    def test_empty_or_blank_names_are_rejected_without_calling_set_owner(
        self, real_conn, long_name, short_name
    ):
        node = real_conn.interface.localNode
        spy = MagicMock(side_effect=node.setOwner)  # the real setOwner would sys.exit
        node.setOwner = spy

        assert real_conn.write_owner(long_name, short_name) is False

        spy.assert_not_called()
        real_conn.transport.assert_not_called()

    def test_valid_owner_is_written(self, real_conn):
        assert real_conn.write_owner("Name", "N") is True
        real_conn.transport.assert_called_once()


WRITE_OPERATIONS = [
    pytest.param(lambda c: c.write_owner("Name", "N"), False, id="write_owner"),
    pytest.param(lambda c: c.write_config("lora", {"hop_limit": 6}), False, id="write_config"),
    pytest.param(
        lambda c: c.write_module_config("telemetry", {"device_update_interval": 3600}),
        False,
        id="write_module_config",
    ),
    pytest.param(lambda c: c.write_channel(1, {"name": "renamed"}), False, id="write_channel"),
    pytest.param(lambda c: c.send_message("x"), (False, None), id="send_message"),
]


class TestSystemExitBoundary:
    @pytest.mark.parametrize("operation, expected", WRITE_OPERATIONS)
    def test_system_exit_from_meshtastic_does_not_escape(
        self, real_conn, monkeypatch, operation, expected
    ):
        node = real_conn.interface.localNode
        node.localConfig.lora.hop_limit = 3
        node.moduleConfig.telemetry.device_update_interval = 600
        configure_channel(node, 1)
        before = snapshot(node)

        # Meshtastic calls sys.exit() on fatal protocol/validation errors.
        monkeypatch.setattr(Node, "_sendAdmin", MagicMock(side_effect=SystemExit(1)))
        real_conn.interface.sendText = MagicMock(side_effect=SystemExit(1))

        assert operation(real_conn) == expected

        assert snapshot(node) == before, "cached config/channels were not restored"

    def test_write_channel_failure_leaves_channel_byte_for_byte_unchanged(self, fake_conn):
        node = fake_conn.node
        configure_channel(node, 1)
        before = node.channels[1].SerializeToString()
        everything = [c.SerializeToString() for c in node.channels]
        node.writeChannel.side_effect = RuntimeError("serial write failed")

        assert fake_conn.write_channel(1, {"name": "renamed", "uplink_enabled": False}) is False

        assert node.channels[1].SerializeToString() == before
        assert [c.SerializeToString() for c in node.channels] == everything


# ===========================================================================
# B. import_config partial failure
# ===========================================================================


class TestImportConfigPartialFailure:
    def test_lora_failure_does_not_stop_later_sections(self, fake_conn):
        node = fake_conn.node
        configure_channel(node, 1)
        ok, config, _ = fake_conn.export_config()
        assert ok and {"lora", "position", "device", "owner", "channels"} <= set(config)

        def write_config(name):
            if name == "lora":
                raise RuntimeError("lora write failed")

        node.writeConfig.side_effect = write_config

        success, errors, message = fake_conn.import_config(config)

        assert success is False
        assert any("lora" in e.lower() for e in errors), errors
        written = [c.args[0] for c in node.writeConfig.call_args_list]
        assert "position" in written and "device" in written
        node.setOwner.assert_called_once()
        node.writeChannel.assert_called()
        # Only LoRa failed; nothing else may be reported as an error.
        assert all("lora" in e.lower() for e in errors), errors

    def test_empty_owner_short_name_is_reported_not_fatal(self, real_conn):
        config = {"owner": {"long_name": "Alpha Station", "short_name": ""}}

        success, errors, _ = real_conn.import_config(config)

        assert success is False
        assert any("owner" in e.lower() for e in errors), errors

    def test_valid_import_succeeds_with_real_node(self, real_conn):
        config = {
            "lora": {"hop_limit": 5},
            "owner": {"long_name": "Alpha Station", "short_name": "ALPH"},
        }
        success, errors, _ = real_conn.import_config(config)
        assert success is True and errors == []


# ===========================================================================
# C. Connection lifecycle
# ===========================================================================


def make_iface():
    return FakeInterface(FakeNode())


class TestInterfaceIdentity:
    def test_events_from_other_interface_are_ignored(self, make_conn):
        conn, statuses = make_conn()
        iface_a, iface_b = make_iface(), make_iface()
        conn.interface = iface_a
        conn._on_connected(iface_a)
        assert conn.state.connected is True
        assert conn.state.nodes.get_node(FakeInterface.OWN_ID) is not None
        statuses.clear()

        conn._on_receive(text_packet(1, "from the wrong device"), iface_b)
        assert len(conn.state.messages) == 0

        conn._on_disconnected(iface_b)
        assert conn.state.connected is True
        assert "disconnected" not in statuses

    def test_matching_interface_events_are_processed(self, make_conn):
        conn, statuses = make_conn()
        iface_a = make_iface()
        conn.interface = iface_a
        conn._on_connected(iface_a)

        conn._on_receive(text_packet(1, "hello"), iface_a)
        assert len(conn.state.messages) == 1

        conn._on_disconnected(iface_a)
        assert conn.state.connected is False
        assert statuses[-1] == "disconnected"

    def test_stale_disconnect_after_reconnect_is_ignored(self, make_conn):
        conn, statuses = make_conn()
        iface_a, iface_b = make_iface(), make_iface()
        conn.interface = iface_a
        conn._on_connected(iface_a)
        conn._on_disconnected(iface_a)
        assert conn.state.connected is False

        conn.interface = iface_b
        conn._on_connected(iface_b)
        assert conn.state.connected is True
        statuses.clear()

        conn._on_disconnected(iface_a)  # late event from the replaced interface

        assert conn.state.connected is True
        assert "disconnected" not in statuses

    def test_connected_is_idempotent_for_same_interface(self, make_conn):
        conn, statuses = make_conn()
        iface_a = make_iface()
        conn.interface = iface_a
        imports = []
        original_import = conn.state.nodes.import_nodes
        conn.state.nodes.import_nodes = lambda nodes: (imports.append(1), original_import(nodes))[1]

        conn._on_connected(iface_a)
        conn._on_connected(iface_a)

        assert len(imports) == 1
        assert statuses.count("connected") == 1


MALFORMED_PACKETS = [
    pytest.param({"from": 1, "to": 2, "id": 9}, id="decoded-missing"),
    pytest.param({"from": 1, "to": 2, "id": 9, "decoded": "oops"}, id="decoded-not-dict"),
    pytest.param({"from": 1, "to": 2, "id": 9, "decoded": None}, id="decoded-none"),
    pytest.param(
        {"from": 1, "to": 2, "id": 9, "decoded": {"portnum": "NOT_A_REAL_APP", "x": 1}},
        id="unknown-portnum",
    ),
    pytest.param(
        {
            "from": 1,
            "to": 2,
            "id": 9,
            "hopStart": 3,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hi"},
        },
        id="hopStart-without-hopLimit",
    ),
    pytest.param(
        {"from": 1, "to": 2, "id": 9, "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": 12345}},
        id="text-not-a-string",
    ),
    pytest.param(
        {"from": 1, "to": 2, "id": 9, "decoded": {"portnum": "POSITION_APP", "position": "bad"}},
        id="position-not-dict",
    ),
    pytest.param(
        {"from": 1, "to": 2, "id": 9, "decoded": {"portnum": "TELEMETRY_APP", "telemetry": []}},
        id="telemetry-not-dict",
    ),
]


class TestMalformedPackets:
    @pytest.mark.parametrize("packet", MALFORMED_PACKETS)
    def test_malformed_packet_does_not_raise(self, make_conn, packet):
        conn, _ = make_conn()
        iface = make_iface()
        conn.interface = iface
        conn._on_connected(iface)

        conn._on_receive(packet, iface)  # must not raise

        assert conn.state.connected is True

    def test_reaction_to_unknown_id_stores_nothing(self, make_conn):
        conn, _ = make_conn()
        iface = make_iface()
        conn.interface = iface
        conn._on_connected(iface)

        conn._on_receive(text_packet(9, "[R:123456:👍]", frm=0x22222222), iface)

        assert len(conn.state.messages) == 0
        assert conn.state.storage.get_stats()["messages"] == 0
        assert conn.state.storage.get_stats()["reactions"] == 0

    def test_reply_to_unknown_id_is_plain_message_without_parent(self, make_conn):
        conn, _ = make_conn()
        iface = make_iface()
        conn.interface = iface
        conn._on_connected(iface)

        conn._on_receive(text_packet(9, "[>:123456] hello", frm=0x22222222), iface)

        stored = conn.state.storage.find_message_by_packet_id(9)
        assert stored is not None
        assert stored.payload["text"] == "hello"  # prefix is not shown as text
        ref = conn.state.storage.get_reply_ref(stored.id)
        assert ref is None or ref["parent_db_id"] is None


class TestReconnectingModalBoundary:
    @pytest.mark.asyncio
    async def test_try_reconnect_survives_system_exit_from_meshtastic(self, monkeypatch):
        import asyncio

        monkeypatch.setattr(ReconnectingModal, "_start_reconnect", lambda self: None)
        monkeypatch.setattr(
            "meshtastic.serial_interface.SerialInterface", MagicMock(side_effect=SystemExit(1))
        )
        connection = SimpleNamespace(
            interface=None, port="/dev/ttyFAKE0", _on_connected=MagicMock()
        )
        modal = ReconnectingModal(connection, reason="reconnect", port="/dev/ttyFAKE0")
        app = WidgetHost()
        async with app.run_test() as pilot:
            await app.push_screen(modal)
            await settle(pilot)
            result = await asyncio.to_thread(modal._try_reconnect)
        assert result is False
        connection._on_connected.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconnect_loop_reaches_failed_and_enables_retry(self, monkeypatch):
        monkeypatch.setattr(ReconnectingModal, "MAX_ATTEMPTS", 1)
        monkeypatch.setattr(ReconnectingModal, "RETRY_DELAY", 0.0)
        monkeypatch.setattr(
            "meshtastic.serial_interface.SerialInterface", MagicMock(side_effect=SystemExit(1))
        )
        connection = SimpleNamespace(
            interface=None, port="/dev/ttyFAKE0", _on_connected=MagicMock()
        )
        modal = ReconnectingModal(connection, reason="reconnect", port="/dev/ttyFAKE0")
        app = WidgetHost()
        async with app.run_test() as pilot:
            await app.push_screen(modal)
            retry = modal.query_one("#retry-btn")
            assert await wait_until(
                pilot, lambda: not retry.disabled, timeout=4.0
            ), "reconnect loop died without enabling retry"
            assert modal._state == ReconnectState.FAILED


# ===========================================================================
# E. Observable isolation and favorite failures
# ===========================================================================


class TestObservableIsolation:
    def test_failing_subscriber_does_not_block_others(self):
        observable = Observable()
        seen = []

        def first(event, data):
            seen.append(("first", event, data))

        def broken(event, data):
            raise RuntimeError("subscriber bug")

        def last(event, data):
            seen.append(("last", event, data))

        for callback in (first, broken, last):
            observable.subscribe(callback)

        observable.notify("update", 42)  # must not raise
        observable.notify("again", 43)

        assert seen == [
            ("first", "update", 42),
            ("last", "update", 42),
            ("first", "again", 43),
            ("last", "again", 43),
        ]


class TestFavoriteFailure:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error", [RuntimeError("radio busy"), SystemExit(1)], ids=["runtime", "system-exit"]
    )
    @pytest.mark.parametrize("initially_favorite", [False, True], ids=["set", "unset"])
    async def test_failed_favorite_keeps_local_state_and_reports_error(
        self, error, initially_favorite
    ):
        from meshterm.views.nodes import NodesView

        app = make_meshterm_app()
        node_id = "!11111111"
        app.state.nodes.import_nodes(
            {node_id: {"num": 0x11111111, "user": {"shortName": "AAAA", "longName": "Alpha"}}}
        )
        app.state.nodes.set_favorite(node_id, initially_favorite)
        local_node = SimpleNamespace(
            setFavorite=MagicMock(side_effect=error), removeFavorite=MagicMock(side_effect=error)
        )
        app.connection.interface = SimpleNamespace(localNode=local_node)

        async with app.run_test() as pilot:
            await settle(pilot)
            view = app.query_one("#nodes-view", NodesView)

            view._toggle_favorite_for_node(node_id)  # must not raise
            await settle(pilot)

            assert app.state.nodes.is_favorite(node_id) is initially_favorite
            assert any(n.severity == "error" for n in app._notifications), [
                (n.severity, n.message) for n in app._notifications
            ]
