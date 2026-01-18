"""Meshtastic interface management."""

import glob
import re
from typing import Optional, Callable, Tuple
from pubsub import pub

from .state import AppState, SUPPORTED_REACTIONS
from .formatting import format_node_id

# Protocol prefixes for reactions and replies
# Reaction: [R:<packet_id>:<emoji>] - e.g., [R:123456:👍]
# Reply: [>:<packet_id>] <message text> - e.g., [>:123456] Hello!
REACTION_PATTERN = re.compile(r'^\[R:(\d+):([^\]]+)\]$')
REPLY_PATTERN = re.compile(r'^\[>:(\d+)\]\s*(.*)$', re.DOTALL)

# Settings that cause device reboot when changed
# Maps config_type -> set of field names that trigger reboot
REBOOT_CAUSING_SETTINGS = {
    'lora': {'region', 'modem_preset'},
    'device': {'role'},
    'position': {'gps_mode'},
}


class MeshtasticConnection:
    """Manages connection to Meshtastic device."""

    def __init__(self, state: AppState, on_status_change: Optional[Callable] = None):
        self.state = state
        self.interface = None
        self.port: Optional[str] = None
        self._on_status_change = on_status_change

        # Subscribe to meshtastic events
        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_connected, "meshtastic.connection.established")
        pub.subscribe(self._on_disconnected, "meshtastic.connection.lost")

    def _on_receive(self, packet, interface):
        """Handle received packets."""
        import time
        timestamp = time.time()

        # Check for incoming DMs (TEXT_MESSAGE_APP on channel 0, to=my_node_id)
        decoded = packet.get('decoded', {})
        portnum = str(decoded.get('portnum', ''))

        # Check for reaction/reply prefixes in TEXT_MESSAGE_APP
        if portnum in ('TEXT_MESSAGE_APP', '1'):
            text = decoded.get('text', '')
            from_id = format_node_id(packet.get('from', ''))

            # Check for reaction prefix: [R:<packet_id>:<emoji>]
            reaction_match = REACTION_PATTERN.match(text)
            if reaction_match:
                self._handle_reaction(packet, reaction_match, from_id, timestamp)
                return  # Don't add reaction messages to the log

            # Check for reply prefix: [>:<packet_id>] message
            reply_match = REPLY_PATTERN.match(text)
            if reply_match:
                parent_packet_id = int(reply_match.group(1))
                actual_text = reply_match.group(2)
                # Store the original text and mark as a reply
                packet['_reply_to_packet_id'] = parent_packet_id
                # Update the decoded text to the actual message (without prefix)
                decoded['text'] = actual_text
                decoded['_original_text'] = text  # Keep original for debugging

        # Add to message buffer (this also persists to SQLite)
        db_id = self.state.messages.add(packet)

        # If this is a reply, store the reply reference
        if packet.get('_reply_to_packet_id') and self.state.storage:
            parent_packet_id = packet['_reply_to_packet_id']
            if db_id:
                self.state.storage.store_reply_ref(db_id, parent_packet_id, timestamp)

        # Log to plain text file
        if self.state.text_logger:
            self.state.text_logger.log_packet(packet, timestamp)

        # Record stats
        self.state.stats.record_packet(packet)

        if portnum in ('TEXT_MESSAGE_APP', '1'):
            channel = packet.get('channel', 0)
            to_id = format_node_id(packet.get('to', ''))
            from_id = format_node_id(packet.get('from', ''))

            # Check if this is a DM to us (channel 0, to=my_node_id, from someone else)
            if channel == 0 and to_id == self.state.my_node_id and from_id != self.state.my_node_id:
                # This is an incoming DM
                self._handle_incoming_dm(packet, from_id, decoded)

        if portnum in ('ROUTING_APP', '65'):
            request_id = decoded.get('requestId')
            if request_id:
                routing = decoded.get('routing', {})
                error = routing.get('errorReason', '')
                success = (error == '' or error == 'NONE')
                self.state.messages.resolve_pending(
                    request_id,
                    success,
                    error_reason=error if not success else None
                )

        # Update node store based on packet type
        from_id = packet.get('from', packet.get('fromId'))
        if from_id:
            node_update = {}

            # Extract SNR/RSSI/Hops
            if 'rxSnr' in packet:
                node_update['snr'] = packet['rxSnr']
            if 'rxRssi' in packet:
                node_update['rssi'] = packet['rxRssi']
            # Calculate hops from hop_start - hop_limit
            hop_start = packet.get('hopStart')
            hop_limit = packet.get('hopLimit')
            if hop_start is not None and hop_limit is not None:
                node_update['hops'] = hop_start - hop_limit

            # Extract data from decoded payload
            decoded = packet.get('decoded', {})
            portnum = str(decoded.get('portnum', ''))

            if portnum in ('NODEINFO_APP', '4'):
                user = decoded.get('user', {})
                if user:
                    node_update['user'] = user

            elif portnum in ('POSITION_APP', '3'):
                position = decoded.get('position', {})
                if position:
                    node_update['position'] = position
                    # Update my_position if this is from our node
                    if format_node_id(from_id) == self.state.my_node_id:
                        lat = position.get('latitude', position.get('latitudeI', 0))
                        lon = position.get('longitude', position.get('longitudeI', 0))
                        if isinstance(lat, int) and abs(lat) > 1000:
                            lat = lat / 1e7
                            lon = lon / 1e7
                        if lat and lon:
                            self.state.set_my_position(lat, lon)

            elif portnum in ('TELEMETRY_APP', '67'):
                telemetry = decoded.get('telemetry', {})
                device = telemetry.get('deviceMetrics', {})
                if device:
                    node_update['deviceMetrics'] = device

            if node_update:
                self.state.nodes.update_node(from_id, node_update)

    def _handle_reaction(self, packet: dict, match: re.Match, from_id: str, timestamp: float):
        """Handle a reaction message: store reaction and notify UI."""
        target_packet_id = int(match.group(1))
        emoji = match.group(2)

        # Validate emoji is supported
        if emoji not in SUPPORTED_REACTIONS:
            return  # Ignore unsupported reactions

        # Find the target message in storage
        if not self.state.storage:
            return

        target_message = self.state.storage.find_message_by_packet_id(target_packet_id)
        if not target_message:
            return  # Target message not found

        # Store the reaction (handles toggle logic internally)
        added = self.state.storage.store_reaction(
            message_db_id=target_message.id,
            message_packet_id=target_packet_id,
            reactor_node=from_id,
            emoji=emoji,
            timestamp=timestamp
        )

        # Notify UI to refresh reactions display
        self.state.messages.notify("reaction_updated", {
            'message_db_id': target_message.id,
            'message_packet_id': target_packet_id,
            'emoji': emoji,
            'reactor_node': from_id,
            'added': added
        })

    def _handle_incoming_dm(self, packet: dict, from_id: str, decoded: dict):
        """Handle an incoming DM: auto-open channel, increment notifications, notify app."""
        # Get sender name from node store
        node = self.state.nodes.get_node(from_id)
        if node:
            user = node.get('user', {})
            sender_name = user.get('shortName') or user.get('longName') or from_id
        else:
            sender_name = from_id

        # Auto-open DM channel if not already open
        self.state.open_dms.open_dm(from_id, sender_name)

        # Increment notification counter
        self.state.open_dms.increment_notification(from_id)

        # Get message preview (truncate if too long)
        text = decoded.get('text', '')
        preview = text[:50] + '...' if len(text) > 50 else text

        # Notify the app about the incoming DM
        self.state.messages.notify("dm_received", {
            'from_id': from_id,
            'from_name': sender_name,
            'preview': preview,
            'packet': packet
        })

    def _on_connected(self, interface, topic=None):
        """Handle connection established."""
        info = {}

        try:
            if interface.myInfo:
                info['my_node_id'] = format_node_id(interface.myInfo.my_node_num)

            if interface.localNode and interface.localNode.localConfig:
                config = interface.localNode.localConfig
                if hasattr(config, 'lora'):
                    info['region'] = str(config.lora.region)
                    info['modem_preset'] = str(config.lora.modem_preset)

            # Extract channel names
            if interface.localNode and interface.localNode.channels:
                for ch in interface.localNode.channels:
                    if hasattr(ch, 'settings') and ch.settings.name:
                        self.state.channel_names[ch.index] = ch.settings.name

            # Import existing nodes from interface
            if interface.nodes:
                self.state.nodes.import_nodes(interface.nodes)

                # Try to get my node's position
                my_node_num = interface.myInfo.my_node_num if interface.myInfo else None
                if my_node_num and my_node_num in interface.nodes:
                    my_node = interface.nodes[my_node_num]
                    pos = my_node.get('position', {})
                    lat = pos.get('latitude', pos.get('latitudeI', 0))
                    lon = pos.get('longitude', pos.get('longitudeI', 0))
                    if isinstance(lat, int) and abs(lat) > 1000:
                        lat = lat / 1e7
                        lon = lon / 1e7
                    if lat and lon:
                        self.state.set_my_position(lat, lon)

        except Exception:
            pass

        self.state.set_connected(True, info)

        if self._on_status_change:
            self._on_status_change("connected", info)

    def _on_disconnected(self, interface, topic=None):
        """Handle disconnection."""
        self.state.set_connected(False)

        if self._on_status_change:
            self._on_status_change("disconnected", None)

    @staticmethod
    def find_ports() -> list:
        """Find available serial ports."""
        candidates = sorted(glob.glob('/dev/ttyACM*')) + sorted(glob.glob('/dev/ttyUSB*'))
        return candidates

    @staticmethod
    def auto_detect_port() -> Optional[str]:
        """Auto-detect a Meshtastic device port."""
        from meshtastic.serial_interface import SerialInterface

        candidates = MeshtasticConnection.find_ports()

        for candidate in candidates:
            try:
                # Quick test connection
                interface = SerialInterface(candidate, noProto=True)
                interface.close()
                return candidate
            except Exception:
                continue

        return None

    def connect(self, port: Optional[str] = None) -> bool:
        """Connect to Meshtastic device."""
        from meshtastic.serial_interface import SerialInterface

        if self.interface:
            self.disconnect()

        try:
            if port is None:
                port = self.auto_detect_port()

            if port is None:
                return False

            self.port = port
            self.interface = SerialInterface(port)
            return True

        except Exception:
            return False

    def disconnect(self):
        """Disconnect from device."""
        if self.interface:
            try:
                self.interface.close()
            except Exception:
                pass
            self.interface = None
            self.port = None
            self.state.set_connected(False)

    def cleanup(self):
        """Cleanup resources."""
        pub.unsubscribe(self._on_receive, "meshtastic.receive")
        pub.unsubscribe(self._on_connected, "meshtastic.connection.established")
        pub.unsubscribe(self._on_disconnected, "meshtastic.connection.lost")
        self.disconnect()

    def send_message(self, text: str, dest: int | str = "^all", channel: int = 0) -> tuple[bool, int | None]:
        """Send a text message.

        Args:
            text: Message text to send
            dest: Destination node ID or "^all" for broadcast
            channel: Channel index (0-7)

        Returns:
            Tuple of (success, request_id) - request_id is None if send failed
        """
        if not self.interface:
            return False, None
        try:
            mesh_packet = self.interface.sendText(text, destinationId=dest, channelIndex=channel, wantAck=True)
            request_id = mesh_packet.id if mesh_packet else None
            return True, request_id
        except Exception:
            return False, None

    def send_reaction(self, target_packet_id: int, emoji: str, dest: int | str = "^all", channel: int = 0) -> Tuple[bool, Optional[int]]:
        """Send a reaction to a message.

        Args:
            target_packet_id: Meshtastic packet ID of the message to react to
            emoji: Reaction emoji (must be in SUPPORTED_REACTIONS)
            dest: Destination node ID or "^all" for broadcast
            channel: Channel index (0-7)

        Returns:
            Tuple of (success, request_id)
        """
        if emoji not in SUPPORTED_REACTIONS:
            return False, None

        # Format reaction message: [R:<packet_id>:<emoji>]
        reaction_text = f"[R:{target_packet_id}:{emoji}]"
        return self.send_message(reaction_text, dest, channel)

    def send_reply(self, parent_packet_id: int, text: str, dest: int | str = "^all", channel: int = 0) -> Tuple[bool, Optional[int]]:
        """Send a reply to a message.

        Args:
            parent_packet_id: Meshtastic packet ID of the message being replied to
            text: Reply message text
            dest: Destination node ID or "^all" for broadcast
            channel: Channel index (0-7)

        Returns:
            Tuple of (success, request_id)
        """
        # Format reply message: [>:<packet_id>] <message text>
        reply_text = f"[>:{parent_packet_id}] {text}"
        return self.send_message(reply_text, dest, channel)

    def get_local_config(self) -> Optional[dict]:
        """Get local configuration from device.

        Returns:
            Dict with lora, position, device config and channels, or None if not connected
        """
        if not self.interface or not self.interface.localNode:
            return None

        try:
            node = self.interface.localNode
            config = {}

            # LoRa config
            if node.localConfig and hasattr(node.localConfig, 'lora'):
                lora = node.localConfig.lora
                config['lora'] = {
                    'region': lora.region,
                    'modem_preset': lora.modem_preset,
                    'tx_power': lora.tx_power,
                    'hop_limit': lora.hop_limit,
                    'tx_enabled': lora.tx_enabled,
                }

            # Position config
            if node.localConfig and hasattr(node.localConfig, 'position'):
                pos = node.localConfig.position
                config['position'] = {
                    'gps_mode': pos.gps_mode,
                    'position_broadcast_secs': pos.position_broadcast_secs,
                    'fixed_position': pos.fixed_position,
                }

            # Device config
            if node.localConfig and hasattr(node.localConfig, 'device'):
                dev = node.localConfig.device
                config['device'] = {
                    'role': dev.role,
                    'rebroadcast_mode': dev.rebroadcast_mode,
                    'node_info_broadcast_secs': dev.node_info_broadcast_secs,
                }

            # User/owner info (short name, long name)
            if self.state.my_node_id:
                my_node = self.state.nodes.get_node(self.state.my_node_id)
                if my_node:
                    user = my_node.get('user', {})
                    config['user'] = {
                        'short_name': user.get('shortName', ''),
                        'long_name': user.get('longName', ''),
                    }

            # Channels
            config['channels'] = []
            if node.channels:
                for ch in node.channels:
                    ch_info = {
                        'index': ch.index,
                        'role': ch.role,
                    }
                    if hasattr(ch, 'settings') and ch.settings:
                        ch_info['name'] = ch.settings.name or ''
                        ch_info['psk'] = ch.settings.psk.hex() if ch.settings.psk else ''
                        ch_info['uplink_enabled'] = ch.settings.uplink_enabled
                        ch_info['downlink_enabled'] = ch.settings.downlink_enabled
                    config['channels'].append(ch_info)

            return config

        except Exception:
            return None

    def will_cause_reboot(self, config_type: str, values: dict) -> bool:
        """Check if config changes will cause device reboot.

        Args:
            config_type: One of 'lora', 'position', 'device'
            values: Dict of config values being set

        Returns:
            True if any of the values would cause a device reboot
        """
        reboot_fields = REBOOT_CAUSING_SETTINGS.get(config_type, set())
        if not reboot_fields:
            return False

        # Check if any reboot-causing fields are being changed
        current_config = self.get_local_config()
        if not current_config:
            # Can't compare, assume reboot to be safe
            return bool(reboot_fields & set(values.keys()))

        current_section = current_config.get(config_type, {})

        for field in reboot_fields:
            if field in values:
                current_val = current_section.get(field)
                new_val = values[field]
                if current_val != new_val:
                    return True

        return False

    def write_config(self, config_type: str, values: dict) -> bool:
        """Write configuration to device.

        Args:
            config_type: One of 'lora', 'position', 'device'
            values: Dict of config values to set

        Returns:
            True if successful
        """
        if not self.interface or not self.interface.localNode:
            return False

        try:
            node = self.interface.localNode

            if config_type == 'lora':
                for key, value in values.items():
                    setattr(node.localConfig.lora, key, value)
                node.writeConfig('lora')

            elif config_type == 'position':
                for key, value in values.items():
                    setattr(node.localConfig.position, key, value)
                node.writeConfig('position')

            elif config_type == 'device':
                for key, value in values.items():
                    setattr(node.localConfig.device, key, value)
                node.writeConfig('device')

            else:
                return False

            return True

        except Exception:
            return False

    def write_owner(self, long_name: str = None, short_name: str = None) -> bool:
        """Write owner/user info (device names) to device.

        Args:
            long_name: Long name for the device (optional)
            short_name: Short name for the device (max 4 chars, optional)

        Returns:
            True if successful
        """
        if not self.interface or not self.interface.localNode:
            return False

        try:
            self.interface.localNode.setOwner(
                long_name=long_name,
                short_name=short_name
            )
            return True
        except Exception:
            return False

    def write_channel(self, index: int, settings: dict) -> bool:
        """Write channel configuration to device.

        Args:
            index: Channel index (0-7)
            settings: Dict with channel settings (name, psk, uplink_enabled, downlink_enabled, role)

        Returns:
            True if successful
        """
        if not self.interface or not self.interface.localNode:
            return False

        try:
            from meshtastic.protobuf import channel_pb2

            node = self.interface.localNode

            # Get existing channel or create new settings
            ch = channel_pb2.Channel()
            ch.index = index

            # Set role
            if 'role' in settings:
                ch.role = settings['role']

            # Set channel settings
            if 'name' in settings:
                ch.settings.name = settings['name']
            if 'psk' in settings:
                psk = settings['psk']
                if isinstance(psk, str):
                    if psk.lower() == 'default':
                        # Default Meshtastic key (AQ==)
                        ch.settings.psk = bytes([1])
                    elif psk.lower() == 'none':
                        ch.settings.psk = bytes([0])
                    elif psk.lower() == 'random':
                        import secrets
                        ch.settings.psk = secrets.token_bytes(32)
                    else:
                        # Try hex decode, then base64
                        try:
                            ch.settings.psk = bytes.fromhex(psk)
                        except ValueError:
                            import base64
                            ch.settings.psk = base64.b64decode(psk)
                else:
                    ch.settings.psk = psk
            if 'uplink_enabled' in settings:
                ch.settings.uplink_enabled = settings['uplink_enabled']
            if 'downlink_enabled' in settings:
                ch.settings.downlink_enabled = settings['downlink_enabled']

            # Write the channel
            node.channels[index] = ch
            node.writeChannel(index)

            return True

        except Exception:
            return False

    def get_shareable_channels(self) -> list[dict]:
        """Get list of channels that can be shared (have PSK set).

        Returns:
            List of channel dicts with index, name, role, psk
        """
        if not self.interface or not self.interface.localNode:
            return []

        try:
            channels = []
            node = self.interface.localNode
            if node.channels:
                for ch in node.channels:
                    # Skip disabled channels (role == 0)
                    if ch.role == 0:
                        continue
                    # Only include channels with PSK
                    if hasattr(ch, 'settings') and ch.settings and ch.settings.psk:
                        psk_hex = ch.settings.psk.hex()
                        # Skip empty/default PSK (01 = default unencrypted)
                        if psk_hex and psk_hex != '00':
                            channels.append({
                                'index': ch.index,
                                'name': ch.settings.name or '',
                                'role': ch.role,
                                'psk': psk_hex,
                                'uplink_enabled': ch.settings.uplink_enabled,
                                'downlink_enabled': ch.settings.downlink_enabled,
                            })
            return channels

        except Exception:
            return []

    def send_channel_invitation(self, target_node_num: int, channel_settings: dict) -> tuple[bool, str]:
        """Send channel config to remote node via admin message.

        Args:
            target_node_num: Destination node number (int)
            channel_settings: Dict with channel config (index, name, psk, role, etc.)

        Returns:
            Tuple of (success, message)
        """
        if not self.interface or not self.interface.localNode:
            return False, "Not connected to device"

        try:
            from meshtastic.protobuf import admin_pb2, channel_pb2, portnums_pb2

            # Build channel protobuf
            channel = channel_pb2.Channel()
            channel.index = channel_settings['index']
            channel.role = channel_settings.get('role', 1)  # SECONDARY by default

            # Set channel settings
            if channel_settings.get('name'):
                channel.settings.name = channel_settings['name']
            if channel_settings.get('psk'):
                psk = channel_settings['psk']
                if isinstance(psk, str):
                    channel.settings.psk = bytes.fromhex(psk)
                else:
                    channel.settings.psk = psk
            if 'uplink_enabled' in channel_settings:
                channel.settings.uplink_enabled = channel_settings['uplink_enabled']
            if 'downlink_enabled' in channel_settings:
                channel.settings.downlink_enabled = channel_settings['downlink_enabled']

            # Build admin message
            admin_msg = admin_pb2.AdminMessage()
            admin_msg.set_channel.CopyFrom(channel)

            # Send via admin interface
            self.interface.sendData(
                admin_msg.SerializeToString(),
                destinationId=target_node_num,
                portNum=portnums_pb2.PortNum.ADMIN_APP,
                wantAck=True,
                wantResponse=False,
            )

            return True, "Channel invitation sent"

        except Exception as e:
            return False, f"Failed to send: {str(e)}"

    # Advanced device operations

    def reboot_device(self) -> tuple[bool, str]:
        """Reboot the connected device.

        Returns:
            Tuple of (success, message)
        """
        if not self.interface or not self.interface.localNode:
            return False, "Not connected to device"

        try:
            self.interface.localNode.reboot()
            return True, "Device is rebooting"
        except Exception as e:
            return False, f"Reboot failed: {str(e)}"

    def nodedb_reset(self) -> tuple[bool, str]:
        """Reset the device's node database (clears known nodes list).

        Returns:
            Tuple of (success, message)
        """
        if not self.interface or not self.interface.localNode:
            return False, "Not connected to device"

        try:
            self.interface.localNode.resetNodeDb()
            return True, "Node database reset"
        except Exception as e:
            return False, f"NodeDB reset failed: {str(e)}"

    def factory_reset(self) -> tuple[bool, str]:
        """Factory reset the device (wipes all settings, generates new identity).

        WARNING: This will:
        - Delete all device settings
        - Clear all channel configurations
        - Generate a new node ID and keys
        - Require complete reconfiguration

        Returns:
            Tuple of (success, message)
        """
        if not self.interface or not self.interface.localNode:
            return False, "Not connected to device"

        try:
            self.interface.localNode.factoryReset()
            return True, "Factory reset initiated - device will reboot with new identity"
        except Exception as e:
            return False, f"Factory reset failed: {str(e)}"

    def export_config(self) -> tuple[bool, dict, str]:
        """Export full device configuration for backup.

        Returns:
            Tuple of (success, config_dict, message)
            config_dict contains: lora, position, device, channels, owner
        """
        if not self.interface or not self.interface.localNode:
            return False, {}, "Not connected to device"

        try:
            import base64
            node = self.interface.localNode
            config = {}

            # LoRa config
            if node.localConfig and hasattr(node.localConfig, 'lora'):
                lora = node.localConfig.lora
                config['lora'] = {
                    'region': lora.region,
                    'modem_preset': lora.modem_preset,
                    'tx_power': lora.tx_power,
                    'hop_limit': lora.hop_limit,
                    'tx_enabled': lora.tx_enabled,
                }

            # Position config
            if node.localConfig and hasattr(node.localConfig, 'position'):
                pos = node.localConfig.position
                config['position'] = {
                    'gps_mode': pos.gps_mode,
                    'position_broadcast_secs': pos.position_broadcast_secs,
                    'fixed_position': pos.fixed_position,
                }

            # Device config
            if node.localConfig and hasattr(node.localConfig, 'device'):
                dev = node.localConfig.device
                config['device'] = {
                    'role': dev.role,
                    'rebroadcast_mode': dev.rebroadcast_mode,
                    'node_info_broadcast_secs': dev.node_info_broadcast_secs,
                }

            # Owner info
            if self.interface.myInfo:
                my_node_num = self.interface.myInfo.my_node_num
                if my_node_num and self.interface.nodes and my_node_num in self.interface.nodes:
                    my_node = self.interface.nodes[my_node_num]
                    user = my_node.get('user', {})
                    config['owner'] = {
                        'long_name': user.get('longName', ''),
                        'short_name': user.get('shortName', ''),
                    }

            # Channels (with PSK as base64 for portability)
            config['channels'] = []
            if node.channels:
                for ch in node.channels:
                    ch_info = {
                        'index': ch.index,
                        'role': ch.role,
                    }
                    if hasattr(ch, 'settings') and ch.settings:
                        ch_info['name'] = ch.settings.name or ''
                        if ch.settings.psk:
                            ch_info['psk_b64'] = base64.b64encode(ch.settings.psk).decode('ascii')
                        ch_info['uplink_enabled'] = ch.settings.uplink_enabled
                        ch_info['downlink_enabled'] = ch.settings.downlink_enabled
                    config['channels'].append(ch_info)

            return True, config, "Config exported successfully"

        except Exception as e:
            return False, {}, f"Export failed: {str(e)}"

    def import_config(self, config: dict) -> tuple[bool, list, str]:
        """Import device configuration from backup.

        Args:
            config: Configuration dict from export_config()

        Returns:
            Tuple of (success, errors_list, message)
        """
        if not self.interface or not self.interface.localNode:
            return False, [], "Not connected to device"

        import base64
        errors = []

        try:
            # Restore LoRa config
            if 'lora' in config:
                try:
                    self.write_config('lora', config['lora'])
                except Exception as e:
                    errors.append(f"LoRa: {e}")

            # Restore position config
            if 'position' in config:
                try:
                    self.write_config('position', config['position'])
                except Exception as e:
                    errors.append(f"Position: {e}")

            # Restore device config
            if 'device' in config:
                try:
                    self.write_config('device', config['device'])
                except Exception as e:
                    errors.append(f"Device: {e}")

            # Restore owner info
            if 'owner' in config:
                try:
                    owner = config['owner']
                    self.write_owner(
                        long_name=owner.get('long_name'),
                        short_name=owner.get('short_name')
                    )
                except Exception as e:
                    errors.append(f"Owner: {e}")

            # Restore channels
            if 'channels' in config:
                for ch_config in config['channels']:
                    try:
                        ch_settings = {
                            'index': ch_config['index'],
                            'role': ch_config.get('role', 0),
                            'name': ch_config.get('name', ''),
                            'uplink_enabled': ch_config.get('uplink_enabled', False),
                            'downlink_enabled': ch_config.get('downlink_enabled', False),
                        }
                        # Decode PSK from base64
                        if 'psk_b64' in ch_config:
                            ch_settings['psk'] = base64.b64decode(ch_config['psk_b64'])
                        self.write_channel(ch_config['index'], ch_settings)
                    except Exception as e:
                        errors.append(f"Channel {ch_config.get('index', '?')}: {e}")

            if errors:
                return False, errors, f"Import completed with {len(errors)} errors"
            return True, [], "Config imported successfully"

        except Exception as e:
            return False, errors, f"Import failed: {str(e)}"
