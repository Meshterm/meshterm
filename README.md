# README

> #     #                      #######
> ##   ## ######  ####  #    #    #    ###### #####  #    #
> # # # # #      #      #    #    #    #      #    # ##  ##
> #  #  # #####   ####  ######    #    #####  #    # # ## #
> #     # #           # #    #    #    #      #####  #    #
> #     # #      #    # #    #    #    #      #   #  #    #
> #     # ######  ####  #    #    #    ###### #    # #    #

A terminal user interface (TUI) for monitoring and interacting with Meshtastic mesh networks.

![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## Features

- **Real-time packet monitoring** - Stream all mesh traffic with color-coded packet types
- **Node discovery** - Live table of all nodes with signal strength, battery, distance, and more
- **Node details** - Deep dive into individual nodes with telemetry, position, and message history
- **IRC-style chat** - Channel-based messaging with support for channels 0-7
- **Direct messages** - Private conversations with individual nodes (PKI encrypted)
- **Reactions & replies** - React to messages with emoji and reply with threading
- **Channel management** - Create, join, and manage channels; invite nodes to channels
- **Favorites** - Mark important nodes for quick access and alerts
- **Device settings** - Configure radio, channels, GPS, and device settings
- **Advanced tools** - Config backup/restore, factory reset, and privacy features
- **Persistent storage** - Message history and node data saved to SQLite database

## Installation

### Using pipx (Recommended)

[pipx](https://pipx.pypa.io/) installs the application in an isolated environment:

```bash
pipx install meshterm
```

### Using pip

```bash
pip install meshterm
```

### From Source

```bash
# Clone the repository
git clone <repository-url>
cd meshterm

# Option 1: Install with pip (editable mode for development)
pip install -e .

# Option 2: Use the provided scripts
bin/install   # Creates venv and installs dependencies
bin/run       # Runs the application
```

### Requirements

- Python 3.8+
- A Meshtastic device connected via USB

Dependencies (installed automatically):
- `meshtastic` - Meshtastic Python SDK
- `textual` - TUI framework
- `reverse_geocoder` - Offline reverse geocoding
- `pgeocode` - Postal code lookups

## Usage

```bash
# Auto-detect device
meshterm

# Specify a port
meshterm /dev/ttyACM0

# If installed from source with bin/install
bin/run [port]
```

## Views

### Nodes View (N)

Table of all discovered nodes with key metrics. Supports searching, sorting, and quick actions.

```
+---------------------------------------------------------------------------+
| [N]odes [C]hat [L]og [S]ettings                                      [^h] |
+---------------------------------------------------------------------------+
| On? | Name          | Short | Location | Dist  | SNR  | Batt | PKI | Fav  |
|-----+---------------+-------+----------+-------+------+------+-----+------|
| * * | My Radio      | ME    | 95051    |       |      |  95% |  *  |      |
|   * | Bob's Node    | BOB   | San Jose | 2.3km |  8.5 |  72% |  *  |  *   |
|   * | Alice Mobile  | ALI   | Palo Alto| 5.1km |  4.2 |  45% |  *  |      |
|   o | Remote Site   | REM   |          | 12km  | -2.1 |  88% |     |      |
+---------------------------------------------------------------------------+
 Enter=details  /=search  f=favorite  i=invite  </>=sort  r=reverse
```

**Features:**
- **Search** (`/`) - Filter nodes by name, ID, or location
- **Favorites** (`f`) - Mark nodes as favorites for highlighting and alerts
- **Invite** (`i`) - Send channel invitations to selected node
- **Sorting** (`<`/`>`) - Cycle through sort columns; (`r`) reverse direction
- **PKI indicator** - Shows which nodes have completed key exchange

### Log View (L)

Real-time stream of all packets in the mesh network.

```
+---------------------------------------------------------------------------+
| 14:32:15 TEXT      !a1b2c3d4 -> ^all    Hello everyone!                   |
| 14:32:18 POSITION  !e5f6a7b8 -> ^all                                      |
| 14:32:21 TELEMETRY !a1b2c3d4 -> ^all    Batt: 85% Ch: 12.3%               |
| 14:32:25 NODEINFO  !c9d0e1f2 -> ^all    Bob's Radio                       |
+---------------------------------------------------------------------------+
```

### Chat View (C)

IRC-style chat interface with channel tabs and direct messaging.

```
+---------------------------------------------------------------------------+
| [0:Primary] [1:Local] [@Bob] [@Alice(2)]                             [^h] |
+---------------------------------------------------------------------------+
| [0] [14:30] <Bob> Hello everyone!                                         |
| [1] [14:31] <You> Hi Bob!                                                 |
|     [checkmark] Delivered                                                 |
| [0] [14:32] <Alice> Hey all                                               |
|     thumbsup x2  heart                                                    |
+---------------------------------------------------------------------------+
| Ch:[0]> Type message...                                                   |
+---------------------------------------------------------------------------+
```

**Features:**
- **Channels** (`0-7`) - Switch between broadcast channels
- **Direct Messages** - Private encrypted conversations (shown as @Name tabs)
- **Reactions** (`Ctrl+R`) - React to messages with emoji
- **Replies** (`Ctrl+E`) - Reply to specific messages with threading
- **Channel Manager** (`Ctrl+J`) - Manage channels and DMs, start new conversations
- **Navigation** (`Left`/`Right`) - Cycle through channels and open DMs
- **Close DM** (`x`) - Close the current DM tab

### Detail View (D)

Comprehensive information about a selected node with DM capability.

```
+--------------------------+------------------------------------------------+
| Node: Bob's Node         | [14:30] <Bob> Position update sent             |
| Short: BOB               | [14:31] <You> Got it, thanks!                  |
| ID: !a1b2c3d4            | [14:32] <Bob> Heading north now                |
| Hardware: TBEAM          |                                                |
| Seen: 2m ago             |                                                |
|                          |                                                |
| Security:                |                                                |
|   PKI: Encrypted         |                                                |
|                          |                                                |
| Telemetry:               |                                                |
|   Battery: 72%           |                                                |
|   Voltage: 3.85V         |                                                |
|   Channel Util: 15.2%    |                                                |
|                          |                                                |
| Position:                |                                                |
|   San Jose, CA           |                                                |
|   Lat: 37.123456         |                                                |
|   Lon: -122.456789       |                                                |
|   Distance: 2.3km        |                                                |
+--------------------------+------------------------------------------------+
```

**Sub-tabs:**
- **Messages** (`m`) - DM conversation with selected node
- **Info** (`i`) - Node details and telemetry

### Settings View (S)

Configure your Meshtastic device settings.

**Sub-tabs:**
- **Radio** (`r`) - LoRa settings (region, modem preset, hop limit)
- **Channels** (`h`) - Channel configuration (name, PSK, role)
- **GPS** (`g`) - Position settings and manual location
- **Device** (`d`) - Device name and role preferences
- **Advanced** (`a`) - Backup, reset, and maintenance operations

## Key Bindings

### Global

| Key | Action |
|-----|--------|
| `N` | Switch to Nodes view |
| `L` | Switch to Log view |
| `C` | Switch to Chat view |
| `S` | Switch to Settings view |
| `Left`/`Right` | Previous/next tab |
| `V` | Toggle verbose mode (show raw packet data) |
| `W` | Toggle favorites highlighting |
| `Ctrl+H` | Show context-aware help |
| `Q` | Quit |
| `Esc` | Go back / Cancel |

### Nodes View

| Key | Action |
|-----|--------|
| `/` | Search/filter nodes |
| `Enter` or `D` | View node details |
| `f` | Toggle favorite status |
| `i` | Invite node to channel |
| `<` / `>` | Sort by previous/next column |
| `r` | Reverse sort direction |
| `Up`/`Down` or `j`/`k` | Navigate table |
| `Esc` | Clear search or go back |

### Chat View

| Key | Action |
|-----|--------|
| `0-7` | Switch to channel |
| `Left`/`Right` | Previous/next channel or DM |
| `Ctrl+R` | React to a message |
| `Ctrl+E` | Reply to a message |
| `Ctrl+J` | Open channel/DM manager |
| `x` | Close current DM |
| `Enter` | Send message |
| `Esc` | Cancel reply / clear input |

### Channel Manager (Ctrl+J)

| Key | Action |
|-----|--------|
| `Up`/`Down` | Navigate list |
| `Enter` | Select channel or DM |
| `x` | Close selected DM |
| `Tab` | Move to search field |
| `Esc` | Cancel |

### Detail View

| Key | Action |
|-----|--------|
| `m` | Messages sub-tab (DM with node) |
| `i` | Info sub-tab |
| `Left`/`Right` | Previous/next sub-tab |

### Settings View

| Key | Action |
|-----|--------|
| `r` | Radio settings |
| `h` | Channels settings |
| `g` | GPS/Position settings |
| `d` | Device settings |
| `a` | Advanced settings |
| `Left`/`Right` | Previous/next sub-tab |

## Packet Types

| Type | Color | Description |
|------|-------|-------------|
| TEXT | Green | Text messages |
| POSITION | Blue | GPS position updates |
| TELEMETRY | Yellow | Device metrics (battery, etc.) |
| NODEINFO | Cyan | Node identification |
| ROUTING | Magenta | Routing protocol messages |
| NEIGHBOR | Cyan | Neighbor information |

## Data Storage

Meshterm stores data in `~/.meshterm/`:

- `meshterm.db` - SQLite database with messages, nodes, and reactions
- `meshterm.log` - Plain text log of all messages
- `config.json` - Application settings (manual location, preferences)

## Project Structure

```
meshterm/
+-- bin/
|   +-- install          # Setup script
|   +-- run              # Application launcher
+-- meshterm/
|   +-- app.py           # Main application
|   +-- state.py         # State management
|   +-- connection.py    # Meshtastic device connection
|   +-- formatting.py    # Display formatting utilities
|   +-- storage.py       # SQLite storage backend
|   +-- views/           # Application views
|   |   +-- log.py       # Packet log view
|   |   +-- nodes.py     # Node table view
|   |   +-- detail.py    # Node detail view
|   |   +-- chat.py      # Chat view
|   |   +-- settings.py  # Settings view
|   +-- widgets/         # Reusable UI components
|       +-- header_bar.py
|       +-- status_bar.py
|       +-- node_table.py
|       +-- chat_log.py
|       +-- chat_input.py
|       +-- channel_manager.py
|       +-- reaction_picker.py
|       +-- help_modal.py
|       +-- config_panels.py
+-- README.md
```

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- [Meshtastic](https://meshtastic.org/) - The mesh networking project
- [Textual](https://textual.textualize.io/) - TUI framework
- [Rich](https://rich.readthedocs.io/) - Terminal formatting library
