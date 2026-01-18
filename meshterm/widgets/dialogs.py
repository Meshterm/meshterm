"""Modal dialogs for channel invitation."""

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Static, Button, ListView, ListItem, Label
from textual.binding import Binding
from rich.text import Text

from ..formatting import Colors


class ChannelSelectDialog(ModalScreen[dict | None]):
    """Dialog for selecting a channel to share."""

    DEFAULT_CSS = """
    ChannelSelectDialog {
        align: center middle;
    }

    #channel-dialog-container {
        width: 50;
        height: auto;
        max-height: 20;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #channel-dialog-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #channel-list {
        height: auto;
        max-height: 12;
        border: solid $primary-darken-2;
        margin-bottom: 1;
    }

    #channel-list > ListItem {
        padding: 0 1;
    }

    #channel-list > ListItem:hover {
        background: $primary-darken-2;
    }

    #channel-dialog-footer {
        text-align: center;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    def __init__(self, channels: list[dict], **kwargs):
        """Initialize dialog with list of shareable channels.

        Args:
            channels: List of channel dicts with index, name, role, psk
        """
        super().__init__(**kwargs)
        self.channels = channels

    def compose(self) -> ComposeResult:
        with Container(id="channel-dialog-container"):
            yield Static("Select Channel to Share", id="channel-dialog-title")
            with ListView(id="channel-list"):
                for ch in self.channels:
                    name = ch.get('name') or f"Channel {ch['index']}"
                    role = str(ch.get('role', '')).replace('Channel.Role.', '')
                    psk_len = len(ch.get('psk', '')) // 2  # hex to bytes
                    item_text = Text()
                    item_text.append(f"[{ch['index']}] ", style=Colors.DIM)
                    item_text.append(name, style="bold bright_cyan")
                    item_text.append(f" ({role}, {psk_len}B key)", style=Colors.DIM)
                    yield ListItem(Label(item_text), id=f"ch-{ch['index']}")
            yield Static("Enter=select  Esc=cancel", id="channel-dialog-footer")

    def action_cancel(self):
        """Cancel the dialog."""
        self.dismiss(None)

    def action_select(self):
        """Select the highlighted channel."""
        list_view = self.query_one("#channel-list", ListView)
        if list_view.highlighted_child:
            item_id = list_view.highlighted_child.id
            if item_id and item_id.startswith("ch-"):
                index = int(item_id.split("-")[1])
                for ch in self.channels:
                    if ch['index'] == index:
                        self.dismiss(ch)
                        return
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle list item selection."""
        item_id = event.item.id
        if item_id and item_id.startswith("ch-"):
            index = int(item_id.split("-")[1])
            for ch in self.channels:
                if ch['index'] == index:
                    self.dismiss(ch)
                    return


class InviteConfirmDialog(ModalScreen[bool]):
    """Confirmation dialog before sending channel invitation."""

    DEFAULT_CSS = """
    InviteConfirmDialog {
        align: center middle;
    }

    #confirm-dialog-container {
        width: 55;
        height: auto;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #confirm-dialog-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #confirm-dialog-details {
        padding: 1 0;
    }

    .confirm-row {
        height: 1;
    }

    .confirm-label {
        width: 15;
        color: $text-muted;
    }

    .confirm-value {
        width: 1fr;
    }

    #confirm-dialog-buttons {
        padding-top: 1;
        align: center middle;
        height: 3;
    }

    #confirm-dialog-buttons Button {
        margin: 0 1;
    }

    #confirm-dialog-footer {
        text-align: center;
        color: $text-muted;
        padding-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "confirm", "Confirm", show=False),
    ]

    def __init__(self, target_name: str, target_id: str, channel: dict, **kwargs):
        """Initialize confirmation dialog.

        Args:
            target_name: Display name of target node
            target_id: Node ID of target
            channel: Channel dict with index, name, psk, role
        """
        super().__init__(**kwargs)
        self.target_name = target_name
        self.target_id = target_id
        self.channel = channel

    def compose(self) -> ComposeResult:
        ch_name = self.channel.get('name') or f"Channel {self.channel['index']}"
        psk_len = len(self.channel.get('psk', '')) // 2
        role = str(self.channel.get('role', '')).replace('Channel.Role.', '')

        with Container(id="confirm-dialog-container"):
            yield Static("Confirm Channel Invitation", id="confirm-dialog-title")
            with Vertical(id="confirm-dialog-details"):
                with Horizontal(classes="confirm-row"):
                    yield Static("Target:", classes="confirm-label")
                    yield Static(f"{self.target_name} ({self.target_id})", classes="confirm-value")
                with Horizontal(classes="confirm-row"):
                    yield Static("Channel:", classes="confirm-label")
                    yield Static(f"[{self.channel['index']}] {ch_name}", classes="confirm-value")
                with Horizontal(classes="confirm-row"):
                    yield Static("Role:", classes="confirm-label")
                    yield Static(role, classes="confirm-value")
                with Horizontal(classes="confirm-row"):
                    yield Static("PSK:", classes="confirm-label")
                    yield Static(f"{psk_len} bytes (encrypted)", classes="confirm-value")
            with Horizontal(id="confirm-dialog-buttons"):
                yield Button("Confirm", variant="primary", id="btn-confirm")
                yield Button("Cancel", variant="default", id="btn-cancel")
            yield Static("Enter=confirm  Esc=cancel", id="confirm-dialog-footer")

    def action_cancel(self):
        """Cancel the invitation."""
        self.dismiss(False)

    def action_confirm(self):
        """Confirm the invitation."""
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses."""
        if event.button.id == "btn-confirm":
            self.dismiss(True)
        elif event.button.id == "btn-cancel":
            self.dismiss(False)
