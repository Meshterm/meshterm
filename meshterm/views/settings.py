"""Settings view - LoRa radio configuration."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import ContentSwitcher
from textual.binding import Binding

from ..state import AppState
from ..connection import MeshtasticConnection
from ..widgets.config_panels import (
    RadioConfigPanel, ChannelsPanel, PositionPanel, DevicePanel, AdvancedPanel, ConfigPanel
)
from ..widgets.reconnecting_modal import ReconnectingModal


class SettingsView(Container):
    """Settings view for LoRa radio configuration with sub-tabs."""

    DEFAULT_CSS = """
    SettingsView {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    SettingsView > .settings-content {
        height: 1fr;
        width: 100%;
    }

    SettingsView .config-panel {
        width: 100%;
        height: 100%;
        border: solid $primary;
    }

    SettingsView .no-connection-msg {
        padding: 2;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("r", "switch_subtab('radio')", "Radio", show=False, priority=True),
        Binding("h", "switch_subtab('channels')", "Channels", show=False, priority=True),
        Binding("g", "switch_subtab('gps')", "GPS", show=False, priority=True),
        Binding("d", "switch_subtab('device')", "Device", show=False, priority=True),
        Binding("a", "switch_subtab('advanced')", "Advanced", show=False, priority=True),
        Binding("left", "prev_subtab", "Prev Tab", show=False, priority=True),
        Binding("right", "next_subtab", "Next Tab", show=False, priority=True),
    ]

    def __init__(self, state: AppState, connection: MeshtasticConnection, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.connection = connection
        self.current_subtab = "radio"
        self._config_loaded = False

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial="radio", classes="settings-content", id="settings-switcher"):
            yield RadioConfigPanel(self.connection, classes="config-panel", id="radio")
            yield ChannelsPanel(self.connection, classes="config-panel", id="channels")
            yield PositionPanel(self.connection, state=self.state, classes="config-panel", id="gps")
            yield DevicePanel(self.connection, classes="config-panel", id="device")
            yield AdvancedPanel(self.connection, state=self.state, classes="config-panel", id="advanced")

    def action_switch_subtab(self, subtab: str):
        """Switch to a different sub-tab."""
        self.current_subtab = subtab
        self.query_one("#settings-switcher", ContentSwitcher).current = subtab

        # Update header bar
        try:
            from ..widgets.header_bar import HeaderBar
            header = self.app.query_one("#header-bar", HeaderBar)
            header.set_active_subtab(subtab)
        except Exception:
            pass

    def action_next_subtab(self):
        """Switch to next sub-tab."""
        tabs = ["radio", "channels", "gps", "device", "advanced"]
        current_idx = tabs.index(self.current_subtab)
        next_idx = (current_idx + 1) % len(tabs)
        self.action_switch_subtab(tabs[next_idx])

    def action_prev_subtab(self):
        """Switch to previous sub-tab."""
        tabs = ["radio", "channels", "gps", "device", "advanced"]
        current_idx = tabs.index(self.current_subtab)
        prev_idx = (current_idx - 1) % len(tabs)
        self.action_switch_subtab(tabs[prev_idx])

    def on_show(self):
        """Called when view becomes visible - load config from device."""
        self._load_config()

    def _load_config(self):
        """Load configuration from device."""
        config = self.connection.get_local_config()
        if not config:
            self.app.notify("No connection to device", severity="warning", timeout=3)
            return

        # Load config into each panel
        try:
            self.query_one("#radio", RadioConfigPanel).load_config(config)
            self.query_one("#channels", ChannelsPanel).load_config(config)
            self.query_one("#gps", PositionPanel).load_config(config)
            self.query_one("#device", DevicePanel).load_config(config)
            self._config_loaded = True
        except Exception:
            pass

    def on_config_panel_config_saved(self, event: ConfigPanel.ConfigSaved):
        """Handle config saved events from panels."""
        if not event.success:
            self.app.notify(f"Failed to save {event.config_type} config", severity="error", timeout=3)
            return

        if event.will_reboot:
            # Show reconnecting modal for reboot-causing changes
            self._show_reconnect_modal_for_reboot(event.config_type)
        else:
            self.app.notify(f"Saved {event.config_type} config", timeout=2)

    def _show_reconnect_modal_for_reboot(self, config_type: str):
        """Show reconnecting modal after a reboot-causing config change."""
        # Mark this as an intentional disconnect to prevent the app from
        # showing its own reconnect modal
        if hasattr(self.app, '_intentional_disconnect'):
            self.app._intentional_disconnect = True
        if hasattr(self.app, '_reconnect_modal_showing'):
            self.app._reconnect_modal_showing = True

        def on_reconnect_result(success: bool):
            # Reset flags
            if hasattr(self.app, '_intentional_disconnect'):
                self.app._intentional_disconnect = False
            if hasattr(self.app, '_reconnect_modal_showing'):
                self.app._reconnect_modal_showing = False

            if success:
                self.app.notify(f"Saved {config_type} config, device reconnected", timeout=3)
                # Reload config after reconnection
                self._load_config()
            else:
                self.app.notify("Device disconnected. Reconnect manually.", severity="warning", timeout=5)

        modal = ReconnectingModal(
            self.connection,
            reason="reboot",
            port=self.connection.port
        )
        self.app.push_screen(modal, on_reconnect_result)
