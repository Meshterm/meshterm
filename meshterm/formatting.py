"""Display formatting - colors, emoji, packet formatting."""

from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
from rich.text import Text


class Colors:
    """Color scheme for message types using Rich style names."""
    RESET = "default"
    BOLD = "bold"
    DIM = "dim white"

    # Message types
    TEXT = "bright_green"
    POSITION = "bright_blue"
    TELEMETRY = "bright_yellow"
    NODEINFO = "bright_cyan"
    ROUTING = "bright_magenta"
    ADMIN = "bright_red"
    UNKNOWN = "bright_white"

    # Metadata
    TIMESTAMP = "bright_white"
    FROM_NODE = "bright_white"
    SNR = "bright_yellow"
    RSSI = "bright_magenta"


class JsonColors:
    """Color scheme for JSON pretty printing."""
    KEY = "bright_cyan"
    STRING = "bright_green"
    NUMBER = "bright_yellow"
    BOOL = "bright_magenta"
    NULL = "bright_red"
    BRACE = "bright_white"


# Map portnum names (strings) and values to display info
PORTNUM_MAP = {
    # By string name
    'TEXT_MESSAGE_APP': ("TEXT", Colors.TEXT),
    'POSITION_APP': ("POSITION", Colors.POSITION),
    'TELEMETRY_APP': ("TELEMETRY", Colors.TELEMETRY),
    'NODEINFO_APP': ("NODEINFO", Colors.NODEINFO),
    'ROUTING_APP': ("ROUTING", Colors.ROUTING),
    'ADMIN_APP': ("ADMIN", Colors.ADMIN),
    'NEIGHBORINFO_APP': ("NEIGHBOR", Colors.NODEINFO),
    'RANGE_TEST_APP': ("RANGETEST", Colors.TELEMETRY),
    'STORE_FORWARD_APP': ("STORE_FWD", Colors.ROUTING),
    'WAYPOINT_APP': ("WAYPOINT", Colors.POSITION),
    'MAP_REPORT_APP': ("MAP_REPORT", Colors.POSITION),
    'PRIVATE_APP': ("PRIVATE", Colors.TEXT),
    'ATAK_PLUGIN': ("ATAK", Colors.POSITION),
    'ATAK_FORWARDER': ("ATAK", Colors.POSITION),
    # By integer value
    1: ("TEXT", Colors.TEXT),
    3: ("POSITION", Colors.POSITION),
    4: ("NODEINFO", Colors.NODEINFO),
    67: ("TELEMETRY", Colors.TELEMETRY),
    71: ("NEIGHBOR", Colors.NODEINFO),
    65: ("ROUTING", Colors.ROUTING),
    6: ("ADMIN", Colors.ADMIN),
}


def get_portnum_name(portnum):
    """Get human-readable name and color for port number."""
    result = PORTNUM_MAP.get(portnum)
    if result:
        return result
    if isinstance(portnum, str):
        return (portnum.replace('_APP', '')[:10], Colors.UNKNOWN)
    return (f"PORT:{portnum}", Colors.UNKNOWN)


def format_node_id(node_id):
    """Format node ID consistently."""
    if isinstance(node_id, int):
        return f"!{node_id:08x}"
    return str(node_id)


def format_packet(packet, node_store=None) -> Text:
    """Format a packet for log display. Returns Rich Text object."""
    text = Text()

    timestamp = datetime.now().strftime('%H:%M:%S')

    from_id = packet.get('fromId', packet.get('from', '?'))
    to_id = packet.get('toId', packet.get('to', '?'))

    # Get node names from store if available
    from_name = format_node_id(packet.get('from', from_id))
    to_name = format_node_id(packet.get('to', to_id))

    if node_store:
        from_node = node_store.get_node(packet.get('from', from_id))
        to_node = node_store.get_node(packet.get('to', to_id))
        if from_node:
            user = from_node.get('user', {})
            from_name = user.get('shortName') or user.get('longName') or from_name
        if to_node:
            user = to_node.get('user', {})
            to_name = user.get('shortName') or user.get('longName') or to_name

    # Get signal info
    snr = packet.get('rxSnr', None)
    rssi = packet.get('rxRssi', None)
    hop_limit = packet.get('hopLimit', None)
    hop_start = packet.get('hopStart', None)

    # Determine message type
    decoded = packet.get('decoded', {})
    portnum = decoded.get('portnum', 0)
    portname, color = get_portnum_name(portnum)

    # Build the line
    text.append(f"[{timestamp}]", style=Colors.TIMESTAMP)
    text.append(" ")
    text.append(f"[{portname:^10}]", style=f"{color} bold")
    text.append(" ")
    text.append(from_name, style=Colors.FROM_NODE)
    text.append(" -> ", style=Colors.DIM)

    to_display = "all" if to_id == "^all" or to_id == 4294967295 or str(to_id) == "!ffffffff" else to_name
    text.append(to_display, style=Colors.FROM_NODE)

    # Signal info
    if snr is not None or rssi is not None or (hop_limit is not None and hop_start is not None):
        text.append(" (", style=Colors.DIM)
        parts = []
        if snr is not None:
            parts.append((f"SNR:{snr:.1f}", Colors.SNR))
        if rssi is not None:
            parts.append((f"RSSI:{rssi}", Colors.RSSI))
        if hop_limit is not None and hop_start is not None:
            hops = hop_start - hop_limit
            parts.append((f"hops:{hops}", Colors.DIM))
        for i, (part, style) in enumerate(parts):
            if i > 0:
                text.append(" ", style=Colors.DIM)
            text.append(part, style=style)
        text.append(")", style=Colors.DIM)

    return text


def format_payload(packet, node_store=None) -> Text:
    """Format payload details for a packet. Returns Rich Text object."""
    text = Text()
    indent = "           "  # 11 spaces to align with [HH:MM:SS]

    decoded = packet.get('decoded', {})
    portnum = decoded.get('portnum', 0)
    _, color = get_portnum_name(portnum)
    portnum_str = str(portnum)

    if portnum_str in ('TEXT_MESSAGE_APP', '1'):
        msg = decoded.get('text', '')
        if msg:
            text.append(f"{indent}", style=Colors.DIM)
            text.append(f"[message] {msg}", style=color)

    elif portnum_str in ('POSITION_APP', '3'):
        pos = decoded.get('position', {})
        lat = pos.get('latitude', pos.get('latitudeI', 0))
        lon = pos.get('longitude', pos.get('longitudeI', 0))
        alt = pos.get('altitude', None)
        speed = pos.get('groundSpeed', None)
        sats = pos.get('satsInView', None)
        if isinstance(lat, int) and abs(lat) > 1000:
            lat = lat / 1e7
            lon = lon / 1e7
        if lat and lon:
            text.append(f"{indent}", style=Colors.DIM)
            parts = [f"[position] {lat:.6f}, {lon:.6f}"]
            if alt:
                parts.append(f"alt:{alt}m")
            if speed:
                parts.append(f"spd:{speed}m/s")
            if sats:
                parts.append(f"sats:{sats}")
            text.append(' '.join(parts), style=color)

    elif portnum_str in ('TELEMETRY_APP', '67'):
        telem = decoded.get('telemetry', {})
        device = telem.get('deviceMetrics', {})
        env = telem.get('environmentMetrics', {})
        power = telem.get('powerMetrics', {})
        parts = []
        if device:
            if 'batteryLevel' in device:
                parts.append(f"bat:{device['batteryLevel']}%")
            if 'voltage' in device:
                parts.append(f"v:{device['voltage']:.2f}V")
            if 'channelUtilization' in device:
                parts.append(f"ch:{device['channelUtilization']:.1f}%")
            if 'airUtilTx' in device:
                parts.append(f"tx:{device['airUtilTx']:.1f}%")
            if 'uptimeSeconds' in device:
                uptime = device['uptimeSeconds']
                hrs = uptime // 3600
                mins = (uptime % 3600) // 60
                parts.append(f"up:{hrs}h{mins}m")
        if env:
            if 'temperature' in env:
                parts.append(f"temp:{env['temperature']:.1f}C")
            if 'relativeHumidity' in env:
                parts.append(f"hum:{env['relativeHumidity']:.0f}%")
            if 'barometricPressure' in env:
                parts.append(f"pres:{env['barometricPressure']:.1f}hPa")
        if power:
            if 'ch1Voltage' in power:
                parts.append(f"ch1:{power['ch1Voltage']:.2f}V")
        if parts:
            text.append(f"{indent}", style=Colors.DIM)
            text.append(f"[telemetry] {' '.join(parts)}", style=color)

    elif portnum_str in ('NODEINFO_APP', '4'):
        user = decoded.get('user', {})
        long_name = user.get('longName', '')
        short_name = user.get('shortName', '')
        hw_model = user.get('hwModel', '')
        if long_name or short_name:
            text.append(f"{indent}", style=Colors.DIM)
            text.append(f"[nodeinfo] {long_name} ({short_name}) [{hw_model}]", style=color)

    elif portnum_str in ('ROUTING_APP', '65'):
        routing = decoded.get('routing', {})
        error = routing.get('errorReason', '')
        if error and error != 'NONE':
            text.append(f"{indent}", style=Colors.DIM)
            text.append(f"[error] {error}", style=color)
        else:
            ack = decoded.get('requestId', None)
            if ack:
                text.append(f"{indent}", style=Colors.DIM)
                text.append(f"[ack] request {ack}", style=color)

    elif portnum_str in ('NEIGHBORINFO_APP', '71'):
        neighbor = decoded.get('neighborinfo', {})
        neighbors = neighbor.get('neighbors', [])
        if neighbors:
            neighbor_list = ', '.join([format_node_id(n.get('nodeId', 0)) for n in neighbors[:5]])
            text.append(f"{indent}", style=Colors.DIM)
            text.append(f"[neighbors] {len(neighbors)}: {neighbor_list}", style=color)

    return text


def format_verbose(packet) -> Text:
    """Format verbose packet info. Returns Rich Text object."""
    text = Text()
    indent = "  "

    decoded = packet.get('decoded', {})
    hop_limit = packet.get('hopLimit', None)

    info_parts = []
    if 'id' in packet:
        info_parts.append(f"id:{packet['id']}")
    if 'channel' in packet:
        info_parts.append(f"ch:{packet['channel']}")
    if hop_limit is not None:
        info_parts.append(f"hopLim:{hop_limit}")
    if 'rxTime' in packet:
        info_parts.append(f"rx:{datetime.fromtimestamp(packet['rxTime']).strftime('%H:%M:%S')}")
    if decoded.get('requestId'):
        info_parts.append(f"reqId:{decoded['requestId']}")

    if info_parts:
        text.append(f"{indent}[{' | '.join(info_parts)}]\n", style=Colors.DIM)

    return text


def pretty_print_json(obj, indent=0) -> Text:
    """Pretty print an object with colored JSON. Returns Rich Text object."""
    text = Text()

    def print_value(val, ind):
        spacing = "  " * ind
        if isinstance(val, dict):
            if not val:
                text.append("{}", style=JsonColors.BRACE)
            else:
                text.append("{\n", style=JsonColors.BRACE)
                items = list(val.items())
                for i, (k, v) in enumerate(items):
                    text.append(f"{spacing}  ", style="default")
                    text.append(f'"{k}"', style=JsonColors.KEY)
                    text.append(": ", style="default")
                    print_value(v, ind + 1)
                    if i < len(items) - 1:
                        text.append(",\n", style="default")
                    else:
                        text.append("\n", style="default")
                text.append(f"{spacing}", style="default")
                text.append("}", style=JsonColors.BRACE)
        elif isinstance(val, list):
            if not val:
                text.append("[]", style=JsonColors.BRACE)
            else:
                text.append("[\n", style=JsonColors.BRACE)
                for i, item in enumerate(val):
                    text.append(f"{spacing}  ", style="default")
                    print_value(item, ind + 1)
                    if i < len(val) - 1:
                        text.append(",\n", style="default")
                    else:
                        text.append("\n", style="default")
                text.append(f"{spacing}", style="default")
                text.append("]", style=JsonColors.BRACE)
        elif isinstance(val, str):
            display = val if len(val) <= 60 else val[:57] + "..."
            text.append(f'"{display}"', style=JsonColors.STRING)
        elif isinstance(val, bool):
            text.append(str(val).lower(), style=JsonColors.BOOL)
        elif isinstance(val, (int, float)):
            text.append(str(val), style=JsonColors.NUMBER)
        elif val is None:
            text.append("null", style=JsonColors.NULL)
        else:
            text.append(f'"{val}"', style=JsonColors.STRING)

    print_value(obj, indent)
    return text


def format_time_ago(timestamp):
    """Format a timestamp as time ago string."""
    import time
    if not timestamp:
        return "?"
    ago = int(time.time()) - timestamp
    if ago < 0:
        return "now"
    if ago < 60:
        return f"{ago}s"
    if ago < 3600:
        return f"{ago // 60}m"
    if ago < 86400:
        return f"{ago // 3600}h"
    return f"{ago // 86400}d"


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km between two lat/lon points using haversine formula."""
    R = 6371  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def _use_imperial() -> bool:
    """Check if locale uses imperial units (miles)."""
    import locale
    try:
        loc = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ''
        # US, UK, Myanmar, Liberia use miles
        return loc.startswith(('en_US', 'en_GB', 'en_LR', 'my_MM'))
    except Exception:
        return False


def format_distance(km: float, short: bool = False) -> str:
    """Format distance in human-readable form.

    Uses miles for US/UK locales, km elsewhere.
    If short=True, uses compact format for table columns.
    """
    if _use_imperial():
        miles = km * 0.621371
        if short:
            if miles < 0.1:
                return f"{int(miles * 5280)}ft"
            return f"{miles:.1f}mi"
        else:
            if miles < 0.1:
                return f"{int(miles * 5280)} ft"
            return f"{miles:.1f} mi"
    else:
        if short:
            if km < 1:
                return f"{int(km * 1000)}m"
            return f"{km:.1f}km"
        else:
            if km < 1:
                return f"{int(km * 1000)} m"
            return f"{km:.1f} km"


def get_node_position(node: dict) -> tuple[float, float] | None:
    """Extract normalized lat/lon from a node's position data."""
    if not node:
        return None
    position = node.get('position', {})
    if not position:
        return None
    lat = position.get('latitude', position.get('latitudeI', 0))
    lon = position.get('longitude', position.get('longitudeI', 0))
    if isinstance(lat, int) and abs(lat) > 1000:
        lat = lat / 1e7
        lon = lon / 1e7
    if lat and lon:
        return (lat, lon)
    return None


def lookup_postal_code(postal_code: str, country: str = 'US') -> tuple[float, float] | None:
    """Look up coordinates from a postal code.

    Returns (lat, lon) tuple or None if lookup fails.
    Fails gracefully if pgeocode not installed or lookup fails.
    """
    try:
        import pgeocode
        nomi = pgeocode.Nominatim(country)
        result = nomi.query_postal_code(postal_code)
        if result is not None and not (result.latitude != result.latitude):  # NaN check
            return (float(result.latitude), float(result.longitude))
    except ImportError:
        return None  # Library not installed
    except Exception:
        return None  # Any other error
    return None


def get_location_name(lat: float, lon: float) -> str | None:
    """Get human-readable location name from coordinates.

    Returns city name with region, or None if lookup fails.
    Fails gracefully if reverse_geocoder not installed or lookup fails.
    """
    try:
        import reverse_geocoder as rg
        result = rg.search((lat, lon))
        if result and len(result) > 0:
            r = result[0]
            city = r.get('name', '')
            admin1 = r.get('admin1', '')  # State/Province
            cc = r.get('cc', '')  # Country code
            parts = [p for p in [city, admin1, cc] if p]
            return ', '.join(parts) if parts else None
    except ImportError:
        return None  # Library not installed
    except Exception:
        return None  # Any other error
    return None
