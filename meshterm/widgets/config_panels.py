"""Configuration panels for Settings view."""

import json
from pathlib import Path
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll, Horizontal
from textual.widgets import Static, Select, Input, Switch, Button, Label
from textual.message import Message
from textual.screen import ModalScreen
from rich.text import Text

from ..formatting import Colors, lookup_postal_code, get_location_name
from ..storage import get_data_dir


# Region options (Meshtastic regions)
REGION_OPTIONS = [
    ("UNSET", 0),
    ("US", 1),
    ("EU_433", 2),
    ("EU_868", 3),
    ("CN", 4),
    ("JP", 5),
    ("ANZ", 6),
    ("KR", 7),
    ("TW", 8),
    ("RU", 9),
    ("IN", 10),
    ("NZ_865", 11),
    ("TH", 12),
    ("LORA_24", 13),
    ("UA_433", 14),
    ("UA_868", 15),
    ("MY_433", 16),
    ("MY_919", 17),
    ("SG_923", 18),
]

# Modem preset options
MODEM_PRESET_OPTIONS = [
    ("LONG_FAST", 0),
    ("LONG_SLOW", 1),
    ("VERY_LONG_SLOW", 2),
    ("MEDIUM_SLOW", 3),
    ("MEDIUM_FAST", 4),
    ("SHORT_SLOW", 5),
    ("SHORT_FAST", 6),
    ("LONG_MODERATE", 7),
    ("SHORT_TURBO", 8),
]

# GPS mode options
GPS_MODE_OPTIONS = [
    ("DISABLED", 0),
    ("ENABLED", 1),
    ("NOT_PRESENT", 2),
]

# Device role options
DEVICE_ROLE_OPTIONS = [
    ("CLIENT", 0),
    ("CLIENT_MUTE", 1),
    ("ROUTER", 2),
    ("ROUTER_CLIENT", 3),
    ("REPEATER", 4),
    ("TRACKER", 5),
    ("SENSOR", 6),
    ("TAK", 7),
    ("CLIENT_HIDDEN", 8),
    ("LOST_AND_FOUND", 9),
    ("TAK_TRACKER", 10),
]

# Rebroadcast mode options
REBROADCAST_MODE_OPTIONS = [
    ("ALL", 0),
    ("ALL_SKIP_DECODING", 1),
    ("LOCAL_ONLY", 2),
    ("KNOWN_ONLY", 3),
]

# Channel role options
CHANNEL_ROLE_OPTIONS = [
    ("DISABLED", 0),
    ("PRIMARY", 1),
    ("SECONDARY", 2),
]


class ConfigPanel(VerticalScroll):
    """Base class for config panels."""

    DEFAULT_CSS = """
    ConfigPanel {
        padding: 1 2;
    }

    ConfigPanel .form-row {
        height: auto;
        margin-bottom: 1;
    }

    ConfigPanel .form-label {
        width: 25;
        height: 3;
        content-align: left middle;
    }

    ConfigPanel .form-input {
        width: 30;
    }

    ConfigPanel .form-switch {
        width: auto;
    }

    ConfigPanel .button-row {
        height: 3;
        margin-top: 2;
    }

    ConfigPanel .save-button {
        margin-right: 2;
    }

    ConfigPanel .no-connection {
        text-style: italic;
        color: $text-muted;
    }
    """

    class ConfigSaved(Message):
        """Message sent when config is saved."""
        def __init__(self, config_type: str, success: bool, will_reboot: bool = False):
            self.config_type = config_type
            self.success = success
            self.will_reboot = will_reboot
            super().__init__()

    def __init__(self, connection, **kwargs):
        super().__init__(**kwargs)
        self.connection = connection
        self._original_values = {}

    def load_config(self, config: dict):
        """Load configuration values into the form. Override in subclasses."""
        pass

    def _save_config(self):
        """Save configuration to device. Override in subclasses."""
        pass

    def _revert_config(self):
        """Revert to original values. Override in subclasses."""
        pass


class RadioConfigPanel(ConfigPanel):
    """Panel for LoRa radio settings."""

    def compose(self) -> ComposeResult:
        # Region
        with Horizontal(classes="form-row"):
            yield Label("Region:", classes="form-label")
            yield Select(
                [(name, val) for name, val in REGION_OPTIONS],
                id="region-select",
                classes="form-input",
                allow_blank=False,
            )

        # Modem preset
        with Horizontal(classes="form-row"):
            yield Label("Modem Preset:", classes="form-label")
            yield Select(
                [(name, val) for name, val in MODEM_PRESET_OPTIONS],
                id="modem-preset-select",
                classes="form-input",
                allow_blank=False,
            )

        # TX Power
        with Horizontal(classes="form-row"):
            yield Label("TX Power (dBm):", classes="form-label")
            yield Input(
                placeholder="0-30",
                id="tx-power-input",
                classes="form-input",
                type="integer",
            )

        # Hop Limit
        with Horizontal(classes="form-row"):
            yield Label("Hop Limit:", classes="form-label")
            yield Input(
                placeholder="1-7",
                id="hop-limit-input",
                classes="form-input",
                type="integer",
            )

        # TX Enabled
        with Horizontal(classes="form-row"):
            yield Label("TX Enabled:", classes="form-label")
            yield Switch(id="tx-enabled-switch", classes="form-switch")

        # Buttons
        with Horizontal(classes="button-row"):
            yield Button("Save", variant="primary", id="save-btn", classes="save-button")
            yield Button("Revert", variant="default", id="revert-btn")

    def load_config(self, config: dict):
        """Load LoRa configuration values."""
        lora = config.get('lora', {})
        if not lora:
            return

        self._original_values = lora.copy()

        try:
            # Region
            region_val = lora.get('region', 0)
            self.query_one("#region-select", Select).value = region_val

            # Modem preset
            modem_val = lora.get('modem_preset', 0)
            self.query_one("#modem-preset-select", Select).value = modem_val

            # TX Power
            tx_power = lora.get('tx_power', 0)
            self.query_one("#tx-power-input", Input).value = str(tx_power)

            # Hop limit
            hop_limit = lora.get('hop_limit', 3)
            self.query_one("#hop-limit-input", Input).value = str(hop_limit)

            # TX enabled
            tx_enabled = lora.get('tx_enabled', True)
            self.query_one("#tx-enabled-switch", Switch).value = tx_enabled

        except Exception:
            pass

    def _get_form_values(self) -> dict:
        """Get current form values."""
        values = {}

        try:
            values['region'] = self.query_one("#region-select", Select).value
            values['modem_preset'] = self.query_one("#modem-preset-select", Select).value

            tx_power_str = self.query_one("#tx-power-input", Input).value
            values['tx_power'] = max(0, min(30, int(tx_power_str))) if tx_power_str else 0

            hop_limit_str = self.query_one("#hop-limit-input", Input).value
            values['hop_limit'] = max(1, min(7, int(hop_limit_str))) if hop_limit_str else 3

            values['tx_enabled'] = self.query_one("#tx-enabled-switch", Switch).value

        except Exception:
            pass

        return values

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses."""
        if event.button.id == "save-btn":
            self._save_config()
        elif event.button.id == "revert-btn":
            self._revert_config()

    def _save_config(self):
        """Save LoRa config to device."""
        values = self._get_form_values()
        will_reboot = self.connection.will_cause_reboot('lora', values)
        success = self.connection.write_config('lora', values)
        self.post_message(self.ConfigSaved('lora', success, will_reboot))

    def _revert_config(self):
        """Revert to original values."""
        if self._original_values:
            self.load_config({'lora': self._original_values})


class ChannelsPanel(ConfigPanel):
    """Panel for channel configuration."""

    DEFAULT_CSS = ConfigPanel.DEFAULT_CSS + """
    ChannelsPanel .channel-selector {
        height: 3;
        margin-bottom: 1;
    }

    ChannelsPanel .channel-btn {
        width: 5;
        min-width: 5;
        margin-right: 1;
    }

    ChannelsPanel .channel-btn-active {
        background: $primary;
    }
    """

    def __init__(self, connection, **kwargs):
        super().__init__(connection, **kwargs)
        self._current_channel = 0
        self._channels_data = []

    def compose(self) -> ComposeResult:
        # Channel selector buttons
        with Horizontal(classes="channel-selector"):
            for i in range(8):
                yield Button(str(i), id=f"ch-btn-{i}", classes="channel-btn")

        # Channel role
        with Horizontal(classes="form-row"):
            yield Label("Role:", classes="form-label")
            yield Select(
                [(name, val) for name, val in CHANNEL_ROLE_OPTIONS],
                id="channel-role-select",
                classes="form-input",
                allow_blank=False,
            )

        # Channel name
        with Horizontal(classes="form-row"):
            yield Label("Name:", classes="form-label")
            yield Input(
                placeholder="Channel name",
                id="channel-name-input",
                classes="form-input",
            )

        # PSK
        with Horizontal(classes="form-row"):
            yield Label("PSK:", classes="form-label")
            yield Input(
                placeholder="default, random, none, or key",
                id="channel-psk-input",
                classes="form-input",
            )

        # Uplink enabled
        with Horizontal(classes="form-row"):
            yield Label("Uplink (MQTT):", classes="form-label")
            yield Switch(id="channel-uplink-switch", classes="form-switch")

        # Downlink enabled
        with Horizontal(classes="form-row"):
            yield Label("Downlink (MQTT):", classes="form-label")
            yield Switch(id="channel-downlink-switch", classes="form-switch")

        # Buttons
        with Horizontal(classes="button-row"):
            yield Button("Save", variant="primary", id="save-btn", classes="save-button")
            yield Button("Revert", variant="default", id="revert-btn")

    def on_mount(self):
        """Set initial channel button style."""
        self._update_channel_buttons()

    def _update_channel_buttons(self):
        """Update channel button styles."""
        for i in range(8):
            btn = self.query_one(f"#ch-btn-{i}", Button)
            if i == self._current_channel:
                btn.add_class("channel-btn-active")
            else:
                btn.remove_class("channel-btn-active")

    def load_config(self, config: dict):
        """Load channel configuration."""
        self._channels_data = config.get('channels', [])
        self._load_channel(self._current_channel)

    def _load_channel(self, index: int):
        """Load specific channel into form."""
        if index >= len(self._channels_data):
            # No data for this channel
            try:
                self.query_one("#channel-role-select", Select).value = 0
                self.query_one("#channel-name-input", Input).value = ""
                self.query_one("#channel-psk-input", Input).value = ""
                self.query_one("#channel-uplink-switch", Switch).value = False
                self.query_one("#channel-downlink-switch", Switch).value = False
            except Exception:
                pass
            return

        ch = self._channels_data[index]
        try:
            self.query_one("#channel-role-select", Select).value = ch.get('role', 0)
            self.query_one("#channel-name-input", Input).value = ch.get('name', '')
            self.query_one("#channel-psk-input", Input).value = ch.get('psk', '')
            self.query_one("#channel-uplink-switch", Switch).value = ch.get('uplink_enabled', False)
            self.query_one("#channel-downlink-switch", Switch).value = ch.get('downlink_enabled', False)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses."""
        btn_id = event.button.id

        if btn_id and btn_id.startswith("ch-btn-"):
            # Channel selection
            ch_num = int(btn_id.split("-")[-1])
            self._current_channel = ch_num
            self._update_channel_buttons()
            self._load_channel(ch_num)

        elif btn_id == "save-btn":
            self._save_config()

        elif btn_id == "revert-btn":
            self._revert_config()

    def _get_form_values(self) -> dict:
        """Get current form values for current channel."""
        values = {'index': self._current_channel}

        try:
            values['role'] = self.query_one("#channel-role-select", Select).value
            values['name'] = self.query_one("#channel-name-input", Input).value
            values['psk'] = self.query_one("#channel-psk-input", Input).value
            values['uplink_enabled'] = self.query_one("#channel-uplink-switch", Switch).value
            values['downlink_enabled'] = self.query_one("#channel-downlink-switch", Switch).value
        except Exception:
            pass

        return values

    def _save_config(self):
        """Save current channel config to device."""
        values = self._get_form_values()
        success = self.connection.write_channel(self._current_channel, values)
        self.post_message(self.ConfigSaved('channel', success))

    def _revert_config(self):
        """Revert to original values."""
        self._load_channel(self._current_channel)


class PositionPanel(ConfigPanel):
    """Panel for GPS/position settings."""

    DEFAULT_CSS = ConfigPanel.DEFAULT_CSS + """
    PositionPanel .section-header {
        margin-top: 1;
        margin-bottom: 1;
        text-style: bold;
        color: $text;
    }

    PositionPanel .location-status {
        margin-left: 25;
        color: $success;
    }
    """

    def __init__(self, connection, state=None, **kwargs):
        super().__init__(connection, **kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        # Device GPS Settings section
        yield Static("Device GPS Settings", classes="section-header")

        # GPS Mode
        with Horizontal(classes="form-row"):
            yield Label("GPS Mode:", classes="form-label")
            yield Select(
                [(name, val) for name, val in GPS_MODE_OPTIONS],
                id="gps-mode-select",
                classes="form-input",
                allow_blank=False,
            )

        # Position broadcast interval
        with Horizontal(classes="form-row"):
            yield Label("Broadcast Secs:", classes="form-label")
            yield Input(
                placeholder="Seconds (0=disable)",
                id="pos-broadcast-input",
                classes="form-input",
                type="integer",
            )

        # Fixed position
        with Horizontal(classes="form-row"):
            yield Label("Fixed Position:", classes="form-label")
            yield Switch(id="fixed-pos-switch", classes="form-switch")

        # Buttons for device config
        with Horizontal(classes="button-row"):
            yield Button("Save to Device", variant="primary", id="save-btn", classes="save-button")
            yield Button("Revert", variant="default", id="revert-btn")

        # My Location section (app setting, not device)
        yield Static("My Location (for distance calc)", classes="section-header")

        # Use GPS toggle
        with Horizontal(classes="form-row"):
            yield Label("Use GPS if available:", classes="form-label")
            yield Switch(id="use-gps-switch", classes="form-switch", value=True)

        # Postal code input
        with Horizontal(classes="form-row"):
            yield Label("Postal/Zip Code:", classes="form-label")
            yield Input(
                placeholder="e.g., 95051",
                id="postal-code-input",
                classes="form-input",
            )

        # Country code input
        with Horizontal(classes="form-row"):
            yield Label("Country:", classes="form-label")
            yield Input(
                placeholder="US, GB, DE, etc.",
                id="country-input",
                classes="form-input",
                value="US",
            )

        # Location status display
        yield Static("", id="location-status", classes="location-status")

        # Buttons for location
        with Horizontal(classes="button-row"):
            yield Button("Look Up & Save", variant="success", id="lookup-btn", classes="save-button")
            yield Button("Clear", variant="default", id="clear-location-btn")

    def on_mount(self):
        """Initialize with current settings."""
        self._update_location_status()

    def _update_location_status(self):
        """Update the location status display."""
        try:
            status = self.query_one("#location-status", Static)
            if self.state and self.state.settings.manual_location:
                lat, lon = self.state.settings.manual_location
                label = self.state.settings.manual_location_label
                # Try to get city name
                city = get_location_name(lat, lon)
                if city:
                    status.update(f"Location: {city}")
                elif label:
                    status.update(f"Location: {label} ({lat:.4f}, {lon:.4f})")
                else:
                    status.update(f"Location: {lat:.4f}, {lon:.4f}")
            else:
                status.update("No manual location set")
        except Exception:
            pass

    def load_config(self, config: dict):
        """Load position configuration."""
        pos = config.get('position', {})
        if not pos:
            return

        self._original_values = pos.copy()

        try:
            gps_mode = pos.get('gps_mode', 0)
            self.query_one("#gps-mode-select", Select).value = gps_mode

            broadcast_secs = pos.get('position_broadcast_secs', 0)
            self.query_one("#pos-broadcast-input", Input).value = str(broadcast_secs)

            fixed_pos = pos.get('fixed_position', False)
            self.query_one("#fixed-pos-switch", Switch).value = fixed_pos

        except Exception:
            pass

        # Load app settings
        if self.state:
            try:
                self.query_one("#use-gps-switch", Switch).value = self.state.settings.use_gps
                if self.state.settings.manual_location_label:
                    # Try to extract postal code from label
                    self.query_one("#postal-code-input", Input).value = self.state.settings.manual_location_label
            except Exception:
                pass

        self._update_location_status()

    def _get_form_values(self) -> dict:
        """Get current form values."""
        values = {}

        try:
            values['gps_mode'] = self.query_one("#gps-mode-select", Select).value

            broadcast_str = self.query_one("#pos-broadcast-input", Input).value
            values['position_broadcast_secs'] = int(broadcast_str) if broadcast_str else 0

            values['fixed_position'] = self.query_one("#fixed-pos-switch", Switch).value

        except Exception:
            pass

        return values

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses."""
        if event.button.id == "save-btn":
            self._save_config()
        elif event.button.id == "revert-btn":
            self._revert_config()
        elif event.button.id == "lookup-btn":
            self._lookup_location()
        elif event.button.id == "clear-location-btn":
            self._clear_location()

    def on_switch_changed(self, event: Switch.Changed):
        """Handle switch changes."""
        if event.switch.id == "use-gps-switch" and self.state:
            self.state.settings.set_use_gps(event.value)

    def _lookup_location(self):
        """Look up postal code and save location."""
        try:
            postal_code = self.query_one("#postal-code-input", Input).value.strip()
            country = self.query_one("#country-input", Input).value.strip().upper() or "US"

            if not postal_code:
                self.app.notify("Enter a postal code", severity="warning", timeout=2)
                return

            coords = lookup_postal_code(postal_code, country)
            if coords:
                lat, lon = coords
                if self.state:
                    self.state.settings.set_manual_location(lat, lon, postal_code)
                    self._update_location_status()
                    self.app.notify(f"Location set: {lat:.4f}, {lon:.4f}", timeout=2)
            else:
                self.app.notify(f"Could not find postal code: {postal_code}", severity="error", timeout=3)

        except Exception as e:
            self.app.notify(f"Lookup failed: {e}", severity="error", timeout=3)

    def _clear_location(self):
        """Clear manual location."""
        if self.state:
            self.state.settings.clear_manual_location()
            self._update_location_status()
            self.app.notify("Manual location cleared", timeout=2)

    def _save_config(self):
        """Save position config to device."""
        values = self._get_form_values()
        will_reboot = self.connection.will_cause_reboot('position', values)
        success = self.connection.write_config('position', values)
        self.post_message(self.ConfigSaved('position', success, will_reboot))

    def _revert_config(self):
        """Revert to original values."""
        if self._original_values:
            self.load_config({'position': self._original_values})


class DevicePanel(ConfigPanel):
    """Panel for device role settings."""

    def compose(self) -> ComposeResult:
        # Long name
        with Horizontal(classes="form-row"):
            yield Label("Long Name:", classes="form-label")
            yield Input(
                placeholder="Device name",
                id="long-name-input",
                classes="form-input",
            )

        # Short name
        with Horizontal(classes="form-row"):
            yield Label("Short Name:", classes="form-label")
            yield Input(
                placeholder="4 chars max",
                id="short-name-input",
                classes="form-input",
                max_length=4,
            )

        # Device role
        with Horizontal(classes="form-row"):
            yield Label("Role:", classes="form-label")
            yield Select(
                [(name, val) for name, val in DEVICE_ROLE_OPTIONS],
                id="device-role-select",
                classes="form-input",
                allow_blank=False,
            )

        # Rebroadcast mode
        with Horizontal(classes="form-row"):
            yield Label("Rebroadcast Mode:", classes="form-label")
            yield Select(
                [(name, val) for name, val in REBROADCAST_MODE_OPTIONS],
                id="rebroadcast-mode-select",
                classes="form-input",
                allow_blank=False,
            )

        # Node info broadcast interval
        with Horizontal(classes="form-row"):
            yield Label("NodeInfo Secs:", classes="form-label")
            yield Input(
                placeholder="Seconds (0=default)",
                id="nodeinfo-broadcast-input",
                classes="form-input",
                type="integer",
            )

        # Buttons
        with Horizontal(classes="button-row"):
            yield Button("Save", variant="primary", id="save-btn", classes="save-button")
            yield Button("Revert", variant="default", id="revert-btn")

    def load_config(self, config: dict):
        """Load device configuration."""
        dev = config.get('device', {})
        user = config.get('user', {})

        self._original_values = {
            'device': dev.copy() if dev else {},
            'user': user.copy() if user else {},
        }

        try:
            # User/owner names
            long_name = user.get('long_name', '')
            self.query_one("#long-name-input", Input).value = long_name

            short_name = user.get('short_name', '')
            self.query_one("#short-name-input", Input).value = short_name

            # Device settings
            role = dev.get('role', 0)
            self.query_one("#device-role-select", Select).value = role

            rebroadcast = dev.get('rebroadcast_mode', 0)
            self.query_one("#rebroadcast-mode-select", Select).value = rebroadcast

            nodeinfo_secs = dev.get('node_info_broadcast_secs', 0)
            self.query_one("#nodeinfo-broadcast-input", Input).value = str(nodeinfo_secs)

        except Exception:
            pass

    def _get_form_values(self) -> dict:
        """Get current form values."""
        values = {'device': {}, 'user': {}}

        try:
            # User/owner names
            values['user']['long_name'] = self.query_one("#long-name-input", Input).value
            values['user']['short_name'] = self.query_one("#short-name-input", Input).value

            # Device settings
            values['device']['role'] = self.query_one("#device-role-select", Select).value
            values['device']['rebroadcast_mode'] = self.query_one("#rebroadcast-mode-select", Select).value

            nodeinfo_str = self.query_one("#nodeinfo-broadcast-input", Input).value
            values['device']['node_info_broadcast_secs'] = int(nodeinfo_str) if nodeinfo_str else 0

        except Exception:
            pass

        return values

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses."""
        if event.button.id == "save-btn":
            self._save_config()
        elif event.button.id == "revert-btn":
            self._revert_config()

    def _save_config(self):
        """Save device config and owner names."""
        values = self._get_form_values()

        # Check if device config will cause reboot
        device_values = values.get('device', {})
        will_reboot = self.connection.will_cause_reboot('device', device_values)

        # Save device config
        device_success = self.connection.write_config('device', device_values)

        # Save owner names if provided
        user_values = values.get('user', {})
        long_name = user_values.get('long_name', '').strip()
        short_name = user_values.get('short_name', '').strip()

        owner_success = True
        if long_name or short_name:
            owner_success = self.connection.write_owner(
                long_name=long_name if long_name else None,
                short_name=short_name if short_name else None
            )

        success = device_success and owner_success
        self.post_message(self.ConfigSaved('device', success, will_reboot))

    def _revert_config(self):
        """Revert to original values."""
        if self._original_values:
            self.load_config({
                'device': self._original_values.get('device', {}),
                'user': self._original_values.get('user', {}),
            })


class ConfirmDialog(ModalScreen):
    """Confirmation dialog for dangerous operations."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }

    ConfirmDialog > Container {
        width: 60;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }

    ConfirmDialog .title {
        text-align: center;
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }

    ConfirmDialog .message {
        margin-bottom: 1;
    }

    ConfirmDialog .confirm-input {
        margin-bottom: 1;
    }

    ConfirmDialog .buttons {
        height: 3;
        align: center middle;
    }

    ConfirmDialog .cancel-btn {
        margin-right: 2;
    }
    """

    def __init__(
        self,
        title: str,
        message: str,
        confirm_text: str = "CONFIRM",
        action_name: str = "confirm",
        **kwargs
    ):
        super().__init__(**kwargs)
        self.title_text = title
        self.message_text = message
        self.confirm_text = confirm_text
        self.action_name = action_name

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(self.title_text, classes="title")
            yield Static(self.message_text, classes="message")
            yield Static(f'Type "{self.confirm_text}" to confirm:', classes="message")
            yield Input(placeholder=self.confirm_text, classes="confirm-input", id="confirm-input")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", variant="default", id="cancel-btn", classes="cancel-btn")
                yield Button(self.action_name.title(), variant="error", id="confirm-btn")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(False)
        elif event.button.id == "confirm-btn":
            self._check_confirm()

    def on_input_submitted(self, event: Input.Submitted):
        self._check_confirm()

    def _check_confirm(self):
        input_value = self.query_one("#confirm-input", Input).value
        if input_value.upper() == self.confirm_text.upper():
            self.dismiss(True)
        else:
            self.app.notify("Confirmation text doesn't match", severity="error", timeout=2)


class AdvancedPanel(ConfigPanel):
    """Panel for advanced/dangerous device operations."""

    DEFAULT_CSS = ConfigPanel.DEFAULT_CSS + """
    AdvancedPanel .section-header {
        margin-top: 1;
        margin-bottom: 1;
        text-style: bold;
        color: $text;
    }

    AdvancedPanel .warning-header {
        margin-top: 1;
        margin-bottom: 1;
        text-style: bold;
        color: $error;
    }

    AdvancedPanel .description {
        color: $text-muted;
        margin-bottom: 1;
    }

    AdvancedPanel .stats-display {
        margin-bottom: 1;
        padding: 1;
        background: $surface-darken-1;
    }

    AdvancedPanel .action-row {
        height: 3;
        margin-bottom: 1;
    }

    AdvancedPanel .action-btn {
        width: 25;
        margin-right: 2;
    }

    AdvancedPanel .danger-btn {
        width: 25;
        margin-right: 2;
    }
    """

    def __init__(self, connection, state=None, **kwargs):
        super().__init__(connection, **kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        # Storage stats
        yield Static("Local Data", classes="section-header")
        yield Static("", id="storage-stats", classes="stats-display")

        # Config backup/restore
        yield Static("Configuration Backup", classes="section-header")
        yield Static("Export saves device settings to a JSON file. Import restores them.", classes="description")
        with Horizontal(classes="action-row"):
            yield Button("Export Config", variant="primary", id="export-btn", classes="action-btn")
            yield Button("Import Config", variant="primary", id="import-btn", classes="action-btn")

        # Safe operations
        yield Static("Device Operations", classes="section-header")
        with Horizontal(classes="action-row"):
            yield Button("Reboot Device", variant="warning", id="reboot-btn", classes="action-btn")
            yield Button("NodeDB Reset", variant="warning", id="nodedb-btn", classes="action-btn")

        # Local data clearing
        yield Static("Clear Local Data", classes="warning-header")
        yield Static("Clears meshterm's local message history and logs (not device data).", classes="description")
        with Horizontal(classes="action-row"):
            yield Button("Clear Messages", variant="error", id="clear-messages-btn", classes="danger-btn")
            yield Button("Clear Logs", variant="error", id="clear-logs-btn", classes="danger-btn")

        # Dangerous operations
        yield Static("Factory Reset", classes="warning-header")
        yield Static("WARNING: These operations cannot be undone!", classes="description")
        with Horizontal(classes="action-row"):
            yield Button("Factory Reset", variant="error", id="factory-btn", classes="danger-btn")
            yield Button("Total Reset", variant="error", id="total-reset-btn", classes="danger-btn")

    def on_mount(self):
        """Load initial stats."""
        self._update_stats()

    def on_show(self):
        """Update stats when panel becomes visible."""
        self._update_stats()

    def _update_stats(self):
        """Update storage statistics display."""
        stats_display = self.query_one("#storage-stats", Static)

        lines = []
        if self.state and self.state.storage:
            stats = self.state.storage.get_stats()
            lines.append(f"Messages: {stats.get('messages', 0):,}")
            lines.append(f"Nodes: {stats.get('nodes', 0):,}")
            lines.append(f"Reactions: {stats.get('reactions', 0):,}")
            lines.append(f"Database: {stats.get('db_size_mb', 0):.2f} MB")

        if self.state and self.state.text_logger:
            log_size = self.state.text_logger.get_log_size()
            lines.append(f"Log files: {log_size:.2f} MB")

        stats_display.update("\n".join(lines) if lines else "No storage data available")

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses."""
        btn_id = event.button.id

        if btn_id == "export-btn":
            self._export_config()
        elif btn_id == "import-btn":
            self._import_config()
        elif btn_id == "reboot-btn":
            self._reboot_device()
        elif btn_id == "nodedb-btn":
            self._nodedb_reset()
        elif btn_id == "clear-messages-btn":
            self._clear_messages()
        elif btn_id == "clear-logs-btn":
            self._clear_logs()
        elif btn_id == "factory-btn":
            self._factory_reset()
        elif btn_id == "total-reset-btn":
            self._total_reset()

    def _export_config(self):
        """Export device configuration to JSON file."""
        success, config, message = self.connection.export_config()
        if not success:
            self.app.notify(message, severity="error", timeout=3)
            return

        # Save to file
        export_path = get_data_dir() / "meshterm_config.json"
        try:
            with open(export_path, 'w') as f:
                json.dump(config, f, indent=2)
            self.app.notify(f"Config exported to {export_path}", timeout=3)
        except Exception as e:
            self.app.notify(f"Failed to save: {e}", severity="error", timeout=3)

    def _import_config(self):
        """Import device configuration from JSON file."""
        import_path = get_data_dir() / "meshterm_config.json"

        if not import_path.exists():
            self.app.notify(f"No config file found at {import_path}", severity="error", timeout=3)
            return

        def do_import(confirmed: bool):
            if not confirmed:
                return

            try:
                with open(import_path, 'r') as f:
                    config = json.load(f)

                success, errors, message = self.connection.import_config(config)

                if success:
                    self.app.notify("Config imported successfully", timeout=3)
                else:
                    self.app.notify(message, severity="warning", timeout=5)
                    for err in errors[:3]:  # Show first 3 errors
                        self.app.notify(err, severity="error", timeout=3)

            except Exception as e:
                self.app.notify(f"Import failed: {e}", severity="error", timeout=3)

        self.app.push_screen(
            ConfirmDialog(
                "Import Configuration",
                "This will overwrite current device settings with the backup.",
                confirm_text="IMPORT",
                action_name="Import"
            ),
            do_import
        )

    def _reboot_device(self):
        """Reboot the device."""
        def do_reboot(confirmed: bool):
            if not confirmed:
                return
            success, message = self.connection.reboot_device()
            severity = "information" if success else "error"
            self.app.notify(message, severity=severity, timeout=3)

        self.app.push_screen(
            ConfirmDialog(
                "Reboot Device",
                "The device will restart. Connection will be lost temporarily.",
                confirm_text="REBOOT",
                action_name="Reboot"
            ),
            do_reboot
        )

    def _nodedb_reset(self):
        """Reset device's node database."""
        def do_reset(confirmed: bool):
            if not confirmed:
                return
            success, message = self.connection.nodedb_reset()
            severity = "information" if success else "error"
            self.app.notify(message, severity=severity, timeout=3)

        self.app.push_screen(
            ConfirmDialog(
                "Reset Node Database",
                "This will clear the device's list of known nodes.\nYour identity and settings are preserved.",
                confirm_text="NODEDB",
                action_name="Reset"
            ),
            do_reset
        )

    def _clear_messages(self):
        """Clear local message history."""
        def do_clear(confirmed: bool):
            if not confirmed:
                return
            if self.state and self.state.storage:
                result = self.state.storage.clear_messages()
                self.app.notify(f"Cleared {result} messages", timeout=3)
                self._update_stats()
            else:
                self.app.notify("No storage available", severity="error", timeout=3)

        self.app.push_screen(
            ConfirmDialog(
                "Clear Message History",
                "This will delete all locally stored messages.\nDevice data is not affected.",
                confirm_text="CLEAR",
                action_name="Clear"
            ),
            do_clear
        )

    def _clear_logs(self):
        """Clear log files."""
        def do_clear(confirmed: bool):
            if not confirmed:
                return
            if self.state and self.state.text_logger:
                count = self.state.text_logger.clear_logs()
                self.app.notify(f"Cleared {count} log files", timeout=3)
                self._update_stats()
            else:
                self.app.notify("No logger available", severity="error", timeout=3)

        self.app.push_screen(
            ConfirmDialog(
                "Clear Log Files",
                "This will delete all meshterm log files.",
                confirm_text="LOGS",
                action_name="Clear"
            ),
            do_clear
        )

    def _factory_reset(self):
        """Factory reset the device."""
        def do_reset(confirmed: bool):
            if not confirmed:
                return
            success, message = self.connection.factory_reset()
            severity = "information" if success else "error"
            self.app.notify(message, severity=severity, timeout=5)

        self.app.push_screen(
            ConfirmDialog(
                "FACTORY RESET",
                "WARNING: This will:\n"
                "• Delete ALL device settings\n"
                "• Clear ALL channel configurations\n"
                "• Generate a NEW node ID and keys\n"
                "• Require complete reconfiguration\n\n"
                "Consider exporting your config first!",
                confirm_text="FACTORY",
                action_name="Reset"
            ),
            do_reset
        )

    def _total_reset(self):
        """Factory reset device AND clear local data."""
        def do_reset(confirmed: bool):
            if not confirmed:
                return

            # Clear local data first
            if self.state:
                if self.state.storage:
                    self.state.storage.clear_all_data()
                if self.state.text_logger:
                    self.state.text_logger.clear_logs()

            # Then factory reset device
            success, message = self.connection.factory_reset()

            if success:
                self.app.notify("Total reset complete - new identity, clean slate", timeout=5)
            else:
                self.app.notify(f"Device reset failed: {message}", severity="error", timeout=5)

        self.app.push_screen(
            ConfirmDialog(
                "TOTAL RESET",
                "WARNING: This is the nuclear option!\n\n"
                "This will:\n"
                "• Factory reset the device (new identity)\n"
                "• Delete ALL local message history\n"
                "• Delete ALL log files\n\n"
                "Your device will have a completely new identity\n"
                "and all local data will be erased.",
                confirm_text="TOTAL",
                action_name="Reset"
            ),
            do_reset
        )
