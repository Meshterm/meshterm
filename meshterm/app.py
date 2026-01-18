"""Main Textual application."""

import sys
import time
import threading
import logging
import logging.handlers
import os
from typing import Optional

from textual.app import App, ComposeResult
from textual import on

# Set up file-based error logging
_log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tmp')
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, 'error.log')

_file_handler = logging.handlers.RotatingFileHandler(
    _log_file,
    maxBytes=1024 * 1024,  # 1 MB
    backupCount=3,
)
_file_handler.setLevel(logging.ERROR)
_file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logging.getLogger().addHandler(_file_handler)
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual.widgets import TabbedContent, TabPane

from .state import AppState
from .connection import MeshtasticConnection
from .storage import LogStorage, PlainTextLogger
from .views import LogView, NodesView, DetailView, ChatView, SettingsView
from .widgets.status_bar import StatusBar
from .widgets.header_bar import HeaderBar
from .widgets.chat_input import ChatInput
from .widgets.dm_input import DMInput
from .widgets.help_modal import HelpModal
from .widgets.reconnecting_modal import ReconnectingModal


# ASCII art logo
LOGO = r"""
#     #                      #######
##   ## ######  ####  #    #    #    ###### #####  #    #
# # # # #      #      #    #    #    #      #    # ##  ##
#  #  # #####   ####  ######    #    #####  #    # # ## #
#     # #           # #    #    #    #      #####  #    #
#     # #      #    # #    #    #    #      #   #  #    #
#     # ######  ####  #    #    #    ###### #    # #    #
"""


class MeshtermApp(App):
    """Meshterm - TUI for Meshtastic monitoring."""

    TITLE = "Meshterm"
    CSS = """
    Screen {
        layout: vertical;
    }

    #header-bar {
        height: 1;
        background: $surface;
    }

    #main-tabs {
        height: 1fr;
    }

    #main-tabs > ContentSwitcher {
        height: 1fr;
    }

    #main-tabs Tabs {
        display: none;
    }

    TabPane {
        height: 100%;
        padding: 0;
    }

    #status-bar {
        height: 1;
        background: $surface;
    }
    """

    BINDINGS = [
        # Main tab navigation
        Binding("l", "switch_tab('log')", "Log", show=False),
        Binding("n", "switch_tab('nodes')", "Nodes", show=False),
        Binding("c", "switch_tab('chat')", "Chat", show=False),
        Binding("s", "switch_tab('settings')", "Settings", show=False),
        Binding("left", "prev_tab", "Prev Tab", show=False),
        Binding("right", "next_tab", "Next Tab", show=False),
        Binding("escape", "go_back", "Back", show=False),
        Binding("v", "toggle_verbose", "Verbose", show=False),
        Binding("w", "toggle_favorites_highlight", "Favorites Highlight", show=False),
        Binding("ctrl+h", "show_help", "Help", show=False),
        Binding("q", "quit", "Quit", show=False),
        # Detail view sub-tabs
        Binding("i", "subtab_detail('info')", show=False),
        Binding("m", "subtab_detail('messages')", show=False),
        Binding("p", "subtab_detail('position')", show=False),
        # Settings view sub-tabs
        Binding("r", "subtab_settings('radio')", show=False),
        Binding("h", "subtab_settings('channels')", show=False),
        Binding("g", "subtab_settings('gps')", show=False),
        Binding("d", "subtab_settings('device')", show=False),
        Binding("a", "subtab_settings('advanced')", show=False),
    ]

    def __init__(self, state: AppState, connection: MeshtasticConnection, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.connection = connection
        self.connection._on_status_change = self._on_connection_status
        self.current_view = "nodes"

        # Track intentional disconnects (e.g., from reconnecting modal)
        self._intentional_disconnect = False
        # Track if reconnect modal is already showing
        self._reconnect_modal_showing = False

        # Subscribe to DM notifications
        self.state.messages.subscribe(self._handle_message_event)

    def compose(self) -> ComposeResult:
        yield HeaderBar(self.state, id="header-bar")
        with TabbedContent(id="main-tabs", initial="nodes"):
            with TabPane("Nodes", id="nodes"):
                yield NodesView(self.state, id="nodes-view")
            with TabPane("Log", id="log"):
                yield LogView(self.state, id="log-view")
            with TabPane("Detail", id="detail"):
                yield DetailView(self.state, id="detail-view")
            with TabPane("Chat", id="chat"):
                yield ChatView(self.state, id="chat-view")
            with TabPane("Settings", id="settings"):
                yield SettingsView(self.state, self.connection, id="settings-view")
        yield StatusBar(self.state, id="status-bar")

    def _on_connection_status(self, status: str, info: dict):
        """Handle connection status changes."""
        status_bar = self.query_one("#status-bar", StatusBar)

        if status == "connected":
            status_bar.set_connected(True)
            node_id = info.get('my_node_id', '?')
            self.notify(f"Connected: {node_id}", timeout=3)
            # Reset flags on successful connection
            self._intentional_disconnect = False
        else:
            status_bar.set_connected(False)

            # Check if this is an unexpected disconnect
            if self._intentional_disconnect or self._reconnect_modal_showing:
                # Intentional or already handling - just show toast
                self.notify("Disconnected", severity="warning", timeout=3)
            else:
                # Unexpected disconnect - show reconnecting modal
                self._show_reconnect_modal()

    def _show_reconnect_modal(self):
        """Show the reconnecting modal for unexpected disconnects."""
        if self._reconnect_modal_showing:
            return

        self._reconnect_modal_showing = True

        def on_reconnect_result(success: bool):
            self._reconnect_modal_showing = False
            if success:
                self.notify("Reconnected to device", timeout=3)
                # Update status bar
                try:
                    status_bar = self.query_one("#status-bar", StatusBar)
                    status_bar.set_connected(True)
                except Exception:
                    pass
            else:
                self.notify("Could not reconnect. Please reconnect manually.", severity="error", timeout=5)

        modal = ReconnectingModal(
            self.connection,
            reason="reconnect",
            port=self.connection.port
        )
        self.push_screen(modal, on_reconnect_result)

    def _handle_message_event(self, event_type: str, data):
        """Handle message events including DM notifications."""
        if event_type == "dm_received" and data:
            from_name = data.get('from_name', '?')
            preview = data.get('preview', '')

            # Show toast notification
            self.notify(f"DM from {from_name}: {preview}", timeout=5)

            # Audio alert
            self.bell()

            # Refresh header bar to show notification badge
            try:
                header = self.query_one("#header-bar", HeaderBar)
                header.refresh()
            except Exception:
                pass

    def action_switch_tab(self, tab_id: str):
        """Switch to a different tab."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = tab_id
        self.current_view = tab_id

        # Update header bar context and active tab
        header = self.query_one("#header-bar", HeaderBar)
        header.set_active_tab(tab_id)

        if tab_id == "detail":
            header.set_context("detail", "info")
        elif tab_id == "settings":
            header.set_context("settings", "radio")
        elif tab_id == "chat":
            header.set_context("chat", "0")
        else:
            header.set_context("main")

    def action_next_tab(self):
        """Switch to next main tab."""
        tabs = ["nodes", "log", "chat", "detail", "settings"]
        try:
            current_idx = tabs.index(self.current_view)
            next_idx = (current_idx + 1) % len(tabs)
        except ValueError:
            next_idx = 0
        self.action_switch_tab(tabs[next_idx])

    def action_prev_tab(self):
        """Switch to previous main tab."""
        tabs = ["nodes", "log", "chat", "detail", "settings"]
        try:
            current_idx = tabs.index(self.current_view)
            prev_idx = (current_idx - 1) % len(tabs)
        except ValueError:
            prev_idx = 0
        self.action_switch_tab(tabs[prev_idx])

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated):
        """Handle tab changes."""
        tab_id = event.pane.id
        self.current_view = tab_id

        # Update header bar context and active tab
        header = self.query_one("#header-bar", HeaderBar)
        header.set_active_tab(tab_id)

        if tab_id == "detail":
            header.set_context("detail", "info")
        elif tab_id == "settings":
            header.set_context("settings", "radio")
        elif tab_id == "chat":
            header.set_context("chat", "0")
        else:
            header.set_context("main")

        # Trigger on_show for the view and focus appropriate widget
        if tab_id == "log":
            view = self.query_one("#log-view", LogView)
            if hasattr(view, 'on_show'):
                view.on_show()
        elif tab_id == "nodes":
            view = self.query_one("#nodes-view", NodesView)
            if hasattr(view, 'on_show'):
                view.on_show()
            try:
                from .widgets.node_table import NodeTable
                table = view.query_one(NodeTable)
                table.focus()
            except Exception:
                pass
        elif tab_id == "detail":
            view = self.query_one("#detail-view", DetailView)
            if hasattr(view, 'on_show'):
                view.on_show()
        elif tab_id == "chat":
            view = self.query_one("#chat-view", ChatView)
            if hasattr(view, 'on_show'):
                view.on_show()
        elif tab_id == "settings":
            view = self.query_one("#settings-view", SettingsView)
            if hasattr(view, 'on_show'):
                view.on_show()

    def action_go_back(self):
        """Go back by focusing header bar, or to nodes if already in tab selection."""
        header = self.query_one("#header-bar", HeaderBar)
        if header.has_focus:
            # Already in tab selection, go back to nodes
            self.action_switch_tab("nodes")
        else:
            # Focus header bar for tab selection
            header.focus()

    def on_header_bar_tab_selected(self, event: HeaderBar.TabSelected):
        """Handle tab selection from header bar navigation."""
        self.action_switch_tab(event.tab_id)

    def on_header_bar_back_requested(self, event: HeaderBar.BackRequested):
        """Handle back button from sub-tab header."""
        self.action_go_back()

    def on_header_bar_sub_tab_selected(self, event: HeaderBar.SubTabSelected):
        """Handle sub-tab selection from header bar."""
        header = self.query_one("#header-bar", HeaderBar)
        header.set_active_subtab(event.subtab_id)

        if self.current_view == "detail":
            view = self.query_one("#detail-view", DetailView)
            view.action_switch_subtab(event.subtab_id)
        elif self.current_view == "settings":
            view = self.query_one("#settings-view", SettingsView)
            view.action_switch_subtab(event.subtab_id)
        elif self.current_view == "chat":
            view = self.query_one("#chat-view", ChatView)
            view.action_switch_channel(event.subtab_id)

    def on_header_bar_dm_closed(self, event: HeaderBar.DMClosed):
        """Handle DM closed from header bar."""
        if self.current_view == "chat":
            view = self.query_one("#chat-view", ChatView)
            # If we were on the closed DM, switch to channel 0
            if isinstance(view.current_channel, str) and view.current_channel == f"dm:{event.node_id}":
                view.action_switch_channel("0")

    def action_toggle_verbose(self):
        """Toggle verbose mode."""
        self.state.settings.toggle_verbose()
        mode = "ON" if self.state.settings.verbose else "OFF"
        self.notify(f"Verbose mode: {mode}", timeout=1)
        self.query_one("#header-bar", HeaderBar).refresh()

    def on_nodes_view_node_selected(self, event: NodesView.NodeSelected):
        """Handle node selection from nodes view."""
        self.action_switch_tab("detail")

    def action_toggle_favorites_highlight(self):
        """Toggle favorites highlighting in log."""
        self.state.settings.toggle_favorites_highlight()
        mode = "ON" if self.state.settings.favorites_highlight else "OFF"
        self.notify(f"Favorites highlight: {mode}", timeout=2)
        self.query_one("#header-bar", HeaderBar).refresh()

    def action_show_help(self):
        """Show context-aware help modal."""
        self.push_screen(HelpModal(context=self.current_view))

    def action_subtab_detail(self, subtab: str):
        """Switch detail view sub-tab if on detail view."""
        if self.current_view == "detail":
            view = self.query_one("#detail-view", DetailView)
            view.action_switch_subtab(subtab)
            header = self.query_one("#header-bar", HeaderBar)
            header.set_active_subtab(subtab)

    def action_subtab_settings(self, subtab: str):
        """Switch settings view sub-tab if on settings view."""
        if self.current_view == "settings":
            view = self.query_one("#settings-view", SettingsView)
            view.action_switch_subtab(subtab)
            header = self.query_one("#header-bar", HeaderBar)
            header.set_active_subtab(subtab)

    def on_chat_input_message_submitted(self, event: ChatInput.MessageSubmitted):
        """Handle message sent from chat input."""
        import time as time_module

        if event.dest_node_id:
            # DM mode: send to specific node on channel 0
            dest = event.dest_node_id
            channel = 0
            # Get node name for notification
            node = self.state.nodes.get_node(event.dest_node_id)
            if node:
                user = node.get('user', {})
                dest_name = user.get('shortName') or user.get('longName') or event.dest_node_id
            else:
                dest_name = event.dest_node_id

            # Ensure DM tab is open (fixes DM not appearing when user initiates)
            self.state.open_dms.open_dm(event.dest_node_id, dest_name)
        else:
            # Broadcast mode: send to all on specified channel
            dest = "^all"
            channel = event.channel
            dest_name = None

        # Check if this is a reply
        text_to_send = event.text
        if event.reply_to_packet_id:
            # Use the send_reply method which handles the prefix
            success, request_id = self.connection.send_reply(
                event.reply_to_packet_id, event.text, dest, channel
            )
            # The actual text sent includes the prefix, but we display without it
        else:
            success, request_id = self.connection.send_message(text_to_send, dest, channel)

        if success:
            # Add a TX marker to the log
            tx_packet = {
                'from': self.state.my_node_id,
                'to': dest,
                'decoded': {
                    'portnum': 'TEXT_MESSAGE_APP',
                    'text': event.text  # Display without prefix
                },
                'channel': channel,
                '_tx': True,  # Mark as transmitted
                '_delivered': None,  # None = pending, True = delivered, False = failed
                'id': request_id,  # Store packet ID for delivery tracking
            }

            # Mark as reply if applicable
            if event.reply_to_packet_id:
                tx_packet['_reply_to_packet_id'] = event.reply_to_packet_id

            timestamp = time_module.time()
            db_id = self.state.messages.add(tx_packet)

            # Store reply reference if this is a reply
            if event.reply_to_packet_id and db_id and self.state.storage:
                self.state.storage.store_reply_ref(db_id, event.reply_to_packet_id, timestamp)

            # Log to plain text file
            if self.state.text_logger:
                self.state.text_logger.log_packet(tx_packet, timestamp)

            # Track pending message for ACK
            if request_id:
                self.state.messages.add_pending(request_id, tx_packet, packet_id=request_id)
        else:
            if dest_name:
                self.notify("Failed to send DM", severity="error", timeout=3)
            else:
                self.notify("Failed to send message", severity="error", timeout=3)

    @on(DMInput.MessageSubmitted)
    def on_dm_input_message_submitted(self, event: DMInput.MessageSubmitted):
        """Handle DM sent from DM input."""
        import time as time_module
        # DMs use channel 0
        success, request_id = self.connection.send_message(event.text, event.dest_node_id, 0)

        if success:
            # Get node name for notification
            node = self.state.nodes.get_node(event.dest_node_id)
            if node:
                user = node.get('user', {})
                dest_name = user.get('shortName') or user.get('longName') or event.dest_node_id
            else:
                dest_name = event.dest_node_id

            # Ensure DM tab is open in chat view (fixes DM not appearing)
            self.state.open_dms.open_dm(event.dest_node_id, dest_name)

            # Add a TX marker to the log
            tx_packet = {
                'from': self.state.my_node_id,
                'to': event.dest_node_id,
                'decoded': {
                    'portnum': 'TEXT_MESSAGE_APP',
                    'text': event.text
                },
                'channel': 0,
                '_tx': True,  # Mark as transmitted
                '_delivered': None,  # None = pending, True = delivered, False = failed
                'id': request_id,  # Store packet ID for delivery tracking
            }
            timestamp = time_module.time()
            self.state.messages.add(tx_packet)

            # Log to plain text file
            if self.state.text_logger:
                self.state.text_logger.log_packet(tx_packet, timestamp)

            # Track pending message for ACK
            if request_id:
                self.state.messages.add_pending(request_id, tx_packet, packet_id=request_id)
        else:
            self.notify("Failed to send DM", severity="error", timeout=3)

    def on_unmount(self):
        """Cleanup when app exits."""
        self.state.messages.unsubscribe(self._handle_message_event)
        self.connection.cleanup()


def print_status(message: str, status: str = "info"):
    """Print a status message with color."""
    if status == "success":
        print(f"\033[32m✓\033[0m {message}")
    elif status == "error":
        print(f"\033[31m✗\033[0m {message}")
    else:
        print(f"\033[36m→\033[0m {message}")


class Spinner:
    """Animated spinner for long operations."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str):
        self.message = message
        self.running = False
        self.thread = None
        self.frame = 0
        self._lock = threading.Lock()

    def update(self, message: str):
        """Update the spinner message."""
        with self._lock:
            self.message = message

    def _animate(self):
        while self.running:
            with self._lock:
                msg = self.message
            frame = self.FRAMES[self.frame % len(self.FRAMES)]
            print(f"\r\033[K\033[36m{frame}\033[0m {msg}", end="", flush=True)
            self.frame += 1
            time.sleep(0.1)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()

    def stop(self, final_message: str = None, status: str = "success"):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.2)
        # Clear the spinner line
        print(f"\r\033[K", end="")
        if final_message:
            print_status(final_message, status)


def connect_to_device(port: Optional[str] = None) -> tuple[AppState, MeshtasticConnection, LogStorage, PlainTextLogger] | None:
    """Connect to a Meshtastic device. Returns (state, connection, storage, text_logger) or None if failed."""
    from pubsub import pub
    from meshtastic.serial_interface import SerialInterface

    # Initialize persistent storage
    print_status("Initializing storage...")
    storage = LogStorage()
    text_logger = PlainTextLogger()
    print_status(f"Database: {storage.db_path}", "success")
    print_status(f"Log file: {text_logger.log_path}", "success")

    state = AppState(storage=storage, text_logger=text_logger)

    # Load previously seen nodes from storage
    state.nodes.load_from_storage()
    stored_count = len(state.nodes._nodes)
    if stored_count > 0:
        print_status(f"Loaded {stored_count} nodes from database", "success")

    print_status("Scanning for devices...")
    ports = MeshtasticConnection.find_ports()

    if not ports:
        print_status("No serial ports found", "error")
        print_status("Connect a Meshtastic device and try again")
        return None

    print_status(f"Found: {', '.join(ports)}", "success")

    # Connection state tracking
    connection_state = {
        "phase": "connecting",
        "node_count": 0,
        "my_info": None,
        "config_done": False,
        "interface": None,
        "error": None,
    }
    spinner = None

    def on_node_updated(node, interface):
        """Track nodes being received."""
        connection_state["node_count"] += 1
        if spinner:
            count = connection_state["node_count"]
            spinner.update(f"Receiving node database... ({count} nodes)")

    def on_connected(interface):
        """Track connection established."""
        connection_state["config_done"] = True
        if spinner:
            spinner.update("Finalizing connection...")

    # Subscribe to events temporarily
    pub.subscribe(on_node_updated, "meshtastic.node.updated")
    pub.subscribe(on_connected, "meshtastic.connection.established")

    ports_to_try = [port] if port else ports
    connected = False

    try:
        for p in ports_to_try:
            connection_state["phase"] = "serial"
            connection_state["node_count"] = 0
            connection_state["config_done"] = False

            spinner = Spinner(f"Opening serial port {p}...")
            spinner.start()

            def try_connect():
                try:
                    spinner.update(f"Connecting to {p} (waiting for device info...)")
                    connection_state["interface"] = SerialInterface(p)
                except Exception as e:
                    connection_state["error"] = str(e)
                    connection_state["interface"] = None

            connect_thread = threading.Thread(target=try_connect, daemon=True)
            connect_thread.start()

            # Wait for connection with progress updates
            while connect_thread.is_alive():
                time.sleep(0.1)
                iface = connection_state["interface"]
                if iface:
                    if iface.myInfo and connection_state["phase"] == "serial":
                        connection_state["phase"] = "config"
                        connection_state["my_info"] = iface.myInfo
                        spinner.update(f"Receiving configuration from {p}...")

            connect_thread.join()

            if connection_state["interface"] is not None:
                spinner.stop(f"Connected to {p}", "success")
                connected = True
                break
            else:
                err = connection_state.get("error", "")
                if "lock" in err.lower():
                    spinner.stop(f"Port {p} is busy (in use by another program)", "error")
                else:
                    spinner.stop(f"No Meshtastic device on {p}", "error" if port else "info")

    finally:
        # Unsubscribe from events
        try:
            pub.unsubscribe(on_node_updated, "meshtastic.node.updated")
            pub.unsubscribe(on_connected, "meshtastic.connection.established")
        except Exception:
            pass

    if not connected:
        print_status("No Meshtastic device found", "error")
        print_status("Check connection and try again")
        return None

    # Create our connection wrapper
    connection = MeshtasticConnection(state)
    connection.interface = connection_state["interface"]
    connection.port = ports_to_try[0] if port else connection_state["interface"].devPath

    # Trigger the connected handler manually to populate state
    connection._on_connected(connection.interface)

    # Show connection details
    if state.my_node_id:
        print_status(f"Node ID: {state.my_node_id}", "success")

    if state.connection_info:
        region = state.connection_info.get('region', '')
        modem = state.connection_info.get('modem_preset', '')
        if region:
            region = region.replace('Config.LoRaConfig.RegionCode.', '')
            modem = modem.replace('Config.LoRaConfig.ModemPreset.', '')
            print_status(f"Region: {region}, Modem: {modem}")

    node_count = len(state.nodes._nodes)
    if node_count > 0:
        print_status(f"Loaded {node_count} nodes from device", "success")

    return state, connection, storage, text_logger


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Meshterm - TUI for Meshtastic')
    parser.add_argument('port', nargs='?', help='Serial port (auto-detects if not specified)')
    args = parser.parse_args()

    # Print logo
    print("\033[36m" + LOGO + "\033[0m")
    print("  Terminal UI for Meshtastic\n")

    # Connect to device
    result = connect_to_device(args.port)
    if result is None:
        sys.exit(1)

    state, connection, storage, text_logger = result
    print_status("Starting TUI...", "success")
    print()

    # Launch the TUI
    app = MeshtermApp(state=state, connection=connection)
    try:
        app.run()
    finally:
        # Cleanup storage on exit
        storage.close()
        text_logger.close()


if __name__ == "__main__":
    main()
