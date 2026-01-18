"""Reconnecting modal for device reconnection with auto-retry."""

import threading
import time
from enum import Enum
from typing import Optional

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Horizontal
from textual.widgets import Static, Button, ProgressBar
from textual.binding import Binding

from ..formatting import Colors


class ReconnectState(Enum):
    """States for reconnection process."""
    WAITING_REBOOT = "waiting_reboot"
    OPENING_PORT = "opening_port"
    WAITING_DEVICE = "waiting_device"
    CONNECTING = "connecting"
    SUCCESS = "success"
    FAILED = "failed"


class ReconnectingModal(ModalScreen[bool]):
    """Modal for reconnecting to a Meshtastic device.

    Shows progress, auto-retries with backoff, and allows manual retry on failure.
    Returns True if reconnection succeeded, False if cancelled.
    """

    DEFAULT_CSS = """
    ReconnectingModal {
        align: center middle;
    }

    #reconnect-container {
        width: 55;
        height: auto;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #reconnect-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #spinner-container {
        align: center middle;
        height: 3;
    }

    #spinner {
        text-align: center;
    }

    #status-text {
        text-align: center;
        padding: 1 0;
    }

    #detail-text {
        text-align: center;
        color: $text-muted;
        padding-bottom: 1;
    }

    #progress-container {
        height: 1;
        padding: 0 2;
        margin-bottom: 1;
    }

    #reconnect-buttons {
        align: center middle;
        height: 3;
    }

    #reconnect-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    # Reconnection settings
    MAX_ATTEMPTS = 5
    REBOOT_DELAY = 3.0  # Seconds to wait for device reboot
    RETRY_DELAY = 2.0   # Seconds between retry attempts
    CONNECT_TIMEOUT = 10.0  # Seconds to wait for connection

    def __init__(
        self,
        connection,
        reason: str = "reconnect",
        port: Optional[str] = None,
        **kwargs
    ):
        """Initialize the reconnecting modal.

        Args:
            connection: MeshtasticConnection instance
            reason: "reboot" for reboot-aware save, "reconnect" for unexpected disconnect
            port: Port to reconnect to (uses last known port if None)
        """
        super().__init__(**kwargs)
        self.connection = connection
        self.reason = reason
        self.port = port or connection.port

        # State tracking
        self._state = ReconnectState.WAITING_REBOOT if reason == "reboot" else ReconnectState.OPENING_PORT
        self._attempt = 0
        self._cancel_requested = False
        self._reconnect_thread: Optional[threading.Thread] = None
        self._spinner_frame = 0
        self._spinner_timer = None

    def compose(self) -> ComposeResult:
        title = "Device Rebooting..." if self.reason == "reboot" else "Reconnecting..."

        with Container(id="reconnect-container"):
            yield Static(title, id="reconnect-title")
            with Container(id="spinner-container"):
                yield Static(self.SPINNER_FRAMES[0], id="spinner")
            yield Static("Initializing...", id="status-text")
            yield Static(f"Port: {self.port}", id="detail-text")
            with Container(id="progress-container"):
                yield ProgressBar(total=self.MAX_ATTEMPTS, show_eta=False, id="progress-bar")
            with Horizontal(id="reconnect-buttons"):
                yield Button("Cancel", variant="default", id="cancel-btn")
                yield Button("Retry", variant="primary", id="retry-btn", disabled=True)

    def on_mount(self):
        """Start the reconnection process when modal is mounted."""
        self._start_spinner()
        self._start_reconnect()

    def on_unmount(self):
        """Clean up when modal is unmounted."""
        self._cancel_requested = True
        if self._spinner_timer:
            self._spinner_timer.stop()

    def _start_spinner(self):
        """Start the spinner animation."""
        self._spinner_timer = self.set_interval(0.1, self._animate_spinner)

    def _animate_spinner(self):
        """Update the spinner animation frame."""
        if self._state in (ReconnectState.SUCCESS, ReconnectState.FAILED):
            return

        self._spinner_frame = (self._spinner_frame + 1) % len(self.SPINNER_FRAMES)
        try:
            spinner = self.query_one("#spinner", Static)
            spinner.update(self.SPINNER_FRAMES[self._spinner_frame])
        except Exception:
            pass

    def _start_reconnect(self):
        """Start the reconnection thread."""
        self._cancel_requested = False
        self._reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
        self._reconnect_thread.start()

    def _reconnect_loop(self):
        """Main reconnection loop running in background thread."""
        try:
            # If this is a reboot, wait for device to restart
            if self.reason == "reboot":
                self._update_state(ReconnectState.WAITING_REBOOT)
                self._update_status("Waiting for device to reboot...")
                self._update_detail(f"Please wait...")

                # Wait for reboot delay
                for _ in range(int(self.REBOOT_DELAY * 10)):
                    if self._cancel_requested:
                        return
                    time.sleep(0.1)

            # Retry loop
            for attempt in range(1, self.MAX_ATTEMPTS + 1):
                if self._cancel_requested:
                    return

                self._attempt = attempt
                self._update_progress(attempt)
                self._update_detail(f"Attempt {attempt} of {self.MAX_ATTEMPTS}")

                # Try to reconnect
                if self._try_reconnect():
                    self._update_state(ReconnectState.SUCCESS)
                    self._update_status("Connected!")
                    self._update_spinner_symbol("✓")
                    time.sleep(0.5)  # Brief pause to show success
                    self.app.call_from_thread(self._on_success)
                    return

                # Wait before next attempt (unless this was the last one)
                if attempt < self.MAX_ATTEMPTS and not self._cancel_requested:
                    self._update_status("Connection failed, retrying...")
                    for _ in range(int(self.RETRY_DELAY * 10)):
                        if self._cancel_requested:
                            return
                        time.sleep(0.1)

            # All attempts failed
            self._update_state(ReconnectState.FAILED)
            self._update_status("Reconnection failed")
            self._update_spinner_symbol("✗")
            self._update_detail("Click Retry to try again")
            self.app.call_from_thread(self._enable_retry)

        except Exception as e:
            self._update_state(ReconnectState.FAILED)
            self._update_status(f"Error: {str(e)[:30]}")
            self._update_spinner_symbol("✗")
            self.app.call_from_thread(self._enable_retry)

    def _try_reconnect(self) -> bool:
        """Attempt to reconnect to the device.

        Returns:
            True if connection succeeded, False otherwise
        """
        from meshtastic.serial_interface import SerialInterface

        # Phase 1: Check if port exists
        self._update_state(ReconnectState.OPENING_PORT)
        self._update_status(f"Opening {self.port}...")

        if self._cancel_requested:
            return False

        # Disconnect any existing connection
        try:
            if self.connection.interface:
                self.connection.interface.close()
                self.connection.interface = None
        except Exception:
            pass

        # Phase 2: Try to open the port and connect
        self._update_state(ReconnectState.CONNECTING)
        self._update_status("Connecting to device...")

        try:
            # Create new interface with timeout
            interface = SerialInterface(self.port)

            if self._cancel_requested:
                try:
                    interface.close()
                except Exception:
                    pass
                return False

            # Success - update connection object
            self.connection.interface = interface
            self.connection.port = self.port

            # Trigger connection handler to repopulate state
            self.connection._on_connected(interface)

            return True

        except Exception:
            return False

    def _update_state(self, state: ReconnectState):
        """Update the current state."""
        self._state = state

    def _update_status(self, text: str):
        """Update the status text (thread-safe)."""
        def update():
            try:
                status = self.query_one("#status-text", Static)
                status.update(text)
            except Exception:
                pass
        self.app.call_from_thread(update)

    def _update_detail(self, text: str):
        """Update the detail text (thread-safe)."""
        def update():
            try:
                detail = self.query_one("#detail-text", Static)
                detail.update(text)
            except Exception:
                pass
        self.app.call_from_thread(update)

    def _update_progress(self, value: int):
        """Update the progress bar (thread-safe)."""
        def update():
            try:
                progress = self.query_one("#progress-bar", ProgressBar)
                progress.progress = value
            except Exception:
                pass
        self.app.call_from_thread(update)

    def _update_spinner_symbol(self, symbol: str):
        """Update the spinner to show a final symbol (thread-safe)."""
        def update():
            try:
                spinner = self.query_one("#spinner", Static)
                spinner.update(symbol)
            except Exception:
                pass
        self.app.call_from_thread(update)

    def _enable_retry(self):
        """Enable the retry button."""
        try:
            retry_btn = self.query_one("#retry-btn", Button)
            retry_btn.disabled = False
        except Exception:
            pass

    def _on_success(self):
        """Called when reconnection succeeds."""
        self.dismiss(True)

    def action_cancel(self):
        """Cancel the reconnection."""
        self._cancel_requested = True
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses."""
        if event.button.id == "cancel-btn":
            self.action_cancel()
        elif event.button.id == "retry-btn":
            # Reset and retry
            event.button.disabled = True
            self._attempt = 0
            self._update_progress(0)
            self._start_reconnect()
