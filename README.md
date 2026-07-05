# OpenHome Tools

[![CI](https://github.com/kylegordon/openhome-tools/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/kylegordon/openhome-tools/actions/workflows/ci.yml)

A collection of Python tools for controlling and monitoring Linn DSM devices using the OpenHome protocol.

## Overview

This repository provides command-line utilities to interact with Linn DSM network audio players. The tools allow you to:

- Discover device UDNs (Unique Device Names)
- Query now-playing information across multiple devices
- Play specific Pins (favorites/presets)
- List available sources
- Create Songcast groups for multi-room audio
- Disband Songcast groups and return devices to standalone
- Reboot all devices
- Capture firmware debug logs for diagnostics

## Prerequisites

- Python 3.7 or higher
- A Linn DSM device on your network
- The following Python packages:
  - `openhomedevice` - For most tools (install via pip)
  - `requests` - For HTTP/SOAP communication
  - Standard library packages: `asyncio`, `xml.etree.ElementTree`, `argparse`

## Installation

1. Clone this repository:
```bash
git clone https://github.com/kylegordon/openhome-tools.git
cd openhome-tools
```
> **Note:** Replace the URL above with your actual repository URL if different.

2. Create a virtual environment (recommended):
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install required dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

### Device Configuration (.env file)

Several scripts support loading device configurations from a `.env` file in the repository root. This is particularly useful when working with multiple devices.

Create a `.env` file with your device information:

```bash
# Define devices
DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f
DEVICE_2=172.24.32.142 4c494e4e-0026-0f22-5661-01531488abcd
DEVICE_3=172.24.32.143 4c494e4e-0026-0f22-5661-01531488def0

# For Songcast grouping
SONGCAST_SENDER=DEVICE_1
SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3
```

Format: `DEVICE_N=<IP_ADDRESS> <UDN>`

## Tools

### 1. find_linn_udn.py

Discovers the UDN (Unique Device Name) of a Linn DSM device by connecting via telnet.

**Usage:**
```bash
python3 find_linn_udn.py <IP_ADDRESS>
```

**Example:**
```bash
python3 find_linn_udn.py 192.168.1.100
```

**Output:**
```
=== Linn DSM UDN Discovery ===
Target IP: 192.168.1.100
------------------------------
Connecting to 192.168.1.100:23...
Received: ALIVE Ds 4c494e4e-0026-0f22-5661-01531488013f

✓ Found UDN: 4c494e4e-0026-0f22-5661-01531488013f

=== Results ===
IP Address: 192.168.1.100
UDN:        4c494e4e-0026-0f22-5661-01531488013f

Use this in your scripts:
devIp  = '192.168.1.100'
devUdn = '4c494e4e-0026-0f22-5661-01531488013f'
```

**When to use:**
- First-time setup of a new device
- When you need to find the UDN for use in other scripts

### 2. now_playing.py

Queries multiple Linn DSM devices for their current status and what's playing. Displays power state, source, track information, and Songcast sender relationships.

**Usage:**
```bash
# Option 1: Using activated virtual environment
source .venv/bin/activate
python now_playing.py [--debug] [--trace-songcast]

# Option 2: Direct virtual environment invocation
.venv/bin/python now_playing.py [--debug] [--trace-songcast]
```

**Configuration:**
Requires a `.env` file with device definitions (see Configuration section above).

**Example:**
```bash
source .venv/bin/activate
python now_playing.py
```

**Output:**
```
Living Room (Radio): Power: On, Station: BBC Radio 6, Track: Song Title — Artist Name
Kitchen (Songcast): Power: On, Songcast Sender: Living Room (ohz), Track: Song Title — Artist Name
Bedroom (in standby) (Playlist): Power: Off
```

**Features:**
- Shows power state (On/Off with standby notation)
- Displays current source and track metadata
- For Radio sources, shows station name
- For Songcast receivers, identifies the sender device
- Caches device names for efficient sender lookups
- Supports `--trace-songcast` for debugging Songcast connections

**When to use:**
- Monitoring status across multiple rooms
- Checking which devices are grouped via Songcast
- Verifying what's currently playing

### 3. play_pin.py

Invokes a specific Pin (preset/favorite) on a Linn DSM device and displays its metadata.

**Usage:**
```bash
python3 play_pin.py <IP_ADDRESS> <UDN> <PIN_NUMBER>
```

**Example:**
```bash
python3 play_pin.py 172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f 2
```

**Output:**
```
=== Linn OpenHome Pin Player ===
IP:  172.24.32.211
UDN: 4c494e4e-0026-0f22-5661-01531488013f
----------------------------------------
Pin: 2

Invoking pin 2...
✓ Pin 2 invoked successfully
✓ Pin 2 has been invoked
The device should now be playing the content associated with this pin

Pin Info
----------------------------------------
Pin: 2
Title: BBC Radio 4
Description: UK speech-based radio station
Artwork: http://example.com/artwork.jpg
```

**Notes:**
- Pin numbers are 1-based indices (1, 2, 3, ...) as shown in the Linn app
- Requires the device UDN (use `find_linn_udn.py` to discover it)
- Uses OpenHome Pins:1 service via SOAP

**When to use:**
- Quickly starting playback of a favorite radio station or playlist
- Automating playback scenarios
- Switching to preset sources

### 4. query_sources.py

Lists all available sources on a Linn DSM device, showing which are visible/hidden and which is currently selected.

**Usage:**
```bash
# Option 1: Using activated virtual environment
source .venv/bin/activate
python query_sources.py <IP_ADDRESS> <UDN>

# Option 2: Direct virtual environment invocation
.venv/bin/python query_sources.py <IP_ADDRESS> <UDN>

# Option 3: System Python (if dependencies installed globally)
python3 query_sources.py <IP_ADDRESS> <UDN>
```

**Example:**
```bash
python3 query_sources.py 172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f
```

**Output:**
```
=== Linn Device Source Query ===
IP:  172.24.32.211
UDN: 4c494e4e-0026-0f22-5661-01531488013f
----------------------------------------
Total Sources: 8
Current Source: 2

Available Sources:
----------------------------------------
[0] Analog (Analog)
[1] Digital (Digital)
[2] Radio (Radio) <- CURRENT
[3] Playlist (Playlist)
[4] UPnP AV (Upnp)
[5] Songcast (Receiver)
[6] Spotify (Spotify) (HIDDEN)
[7] AirPlay (AirPlay)

========================================
Source Index Reference:
0 = Analog, 1 = Digital, 2 = Radio
3 = Playlist, 4 = UPnP, 5 = Songcast
(Indices and types may vary by device/firmware)
```

**Features:**
- Shows per-device visibility status (some sources may be hidden in device configuration)
- Highlights the currently selected source
- Displays both friendly names and system types
- Useful for understanding available inputs

**When to use:**
- Discovering which sources are available on a device
- Finding the correct source index for automation scripts
- Troubleshooting source selection issues

### 5. songcast_group.py

Creates a Songcast group with one sender and one or more receivers for synchronized multi-room audio.

**Usage with .env configuration:**
```bash
# Option 1: Using activated virtual environment
source .venv/bin/activate
python songcast_group.py [--debug]

# Option 2: Direct virtual environment invocation
.venv/bin/python songcast_group.py [--debug]
```

**Usage with command-line arguments:**
```bash
source .venv/bin/activate
python songcast_group.py \
    --sender-ip 172.24.32.211 \
    --sender-udn 4c494e4e-0026-0f22-5661-01531488013f \
    --receiver-ip 172.24.32.142 \
    --receiver-udn 4c494e4e-0026-0f22-5661-01531488abcd \
    [--debug]
```

**Configuration (.env):**
```bash
DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f
DEVICE_2=172.24.32.142 4c494e4e-0026-0f22-5661-01531488abcd
DEVICE_3=172.24.32.143 4c494e4e-0026-0f22-5661-01531488def0

SONGCAST_SENDER=DEVICE_1
SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3
```

**Output:**
```
=== Linn OpenHome Songcast Group Creator ===
Sender: Living Room (172.24.32.211)
Receiver:  172.24.32.142 (172.24.32.142)
Receiver:  172.24.32.143 (172.24.32.143)
--------------------------------------------------

1. Waking sender from standby...
✓ Living Room woken

=== Configuring receiver Kitchen (172.24.32.142) ===
2. Waking receiver from standby...
✓ Kitchen woken
3. Ensuring receiver source is Songcast...
✓ Kitchen source set to Songcast (index 5)
4. Joining receiver to sender...
✓ Receiver join attempted via Uri ohz://239.255.255.250:51972/...
5. Verifying Songcast configuration...
✓ SUCCESS: Receiver actively grouped (ohz/transport active)

==================================================
✓ SUCCESS: Songcast group configured for all receivers!

🎵 Play audio on Living Room and it should stream to receivers
```

**Features:**
- Automatically wakes devices from standby
- Switches receiver sources to Songcast
- Discovers and uses ohz:// URIs for optimal streaming
- Verifies successful grouping
- `--debug` flag for detailed troubleshooting output

**When to use:**
- Setting up synchronized multi-room audio
- Creating party mode across multiple rooms
- Automating Songcast group creation

**Notes:**
- Prefers ohz:// URIs discovered via Receiver.Senders for best compatibility
- Falls back to ohSongcast:// descriptors if ohz not available
- Uses both API calls and direct SOAP requests for reliability
- Polls briefly to verify successful grouping

### 6. songcast_disband.py

Disbands an active Songcast group and returns all devices to standalone mode. Auto-detects sender and receiver roles by probing each device's state — no manual role configuration needed.

**Usage:**
```bash
# Using .env configuration (auto-detects roles)
.venv/bin/python songcast_disband.py [--debug]

# Specify a different .env file
.venv/bin/python songcast_disband.py --env /path/to/.env
```

**Configuration (.env):**
```bash
# UDN can be explicit or auto-discovered via LPEC
DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f
DEVICE_2=172.24.32.210 4c494e4e-0026-0f22-646e-01560511013f
DEVICE_3=172.24.32.212
```

**Example Output:**
```
=== Linn OpenHome Songcast Group Disbander ===
Devices found: 3
  Study (172.24.32.211): sender
  Tin Hut (172.24.32.210): receiver
  Living Room (172.24.32.212): receiver
--------------------------------------------------

1. Disconnecting 2 receiver(s) from Songcast group...
  ✓ Tin Hut receiver cleared and stopped
  ✓ Living Room receiver cleared and stopped

2. Switching 2 receiver(s) to standalone source...
  ✓ Tin Hut switched from Songcast (idx 3) to Playlist (idx 0)
  ✓ Living Room switched from Songcast (idx 3) to Playlist (idx 0)

3. Stopping playback on sender(s)...
  ✓ Study playback stopped

4. Verifying devices are standalone...
  ✓ Tin Hut: standalone (source=Playlist, no sender URI)
  ✓ Living Room: standalone (source=Playlist, no sender URI)
  ✓ Study: sender (playback stopped)

==================================================
✓ SUCCESS: All devices returned to standalone mode
```

**Features:**
- Auto-discovers UDNs via LPEC when not provided in `.env`
- Auto-detects sender/receiver/standalone roles (no `SONGCAST_SENDER`/`SONGCAST_RECEIVERS` needed)
- Clears receiver sender URIs via `Receiver.SetSender(empty)` — fixes "zombie" receivers
- Switches receivers from Songcast source back to Playlist
- Stops sender playback via `Playlist.Stop`
- Verifies all devices return to standalone state
- `--debug` flag for detailed SOAP/LPEC output

**When to use:**
- Breaking up a multi-room Songcast group
- Returning devices to standalone before reconfiguring
- Troubleshooting stuck receivers that appear grouped but aren't playing

### 7. reboot_all.py

Reboots all Linn DSM/DS devices defined in the `.env` file using the Volkano service.

**Usage:**
```bash
.venv/bin/python reboot_all.py
```

**Configuration (.env):**
Requires `DEVICE_N=<IP> <UDN>` entries (both IP and UDN required).

**Example Output:**
```
Reboot command sent to 172.24.32.211 (4c494e4e-0026-0f22-5661-01531488013f): [200]
Reboot command sent to 172.24.32.210 (4c494e4e-0026-0f22-646e-01560511013f): [200]
```

**Notes:**
- Uses the `linn.co.uk-Volkano-1` service (NOT `Product`) for reboot
- Synchronous SOAP requests — no async/openhomedevice dependency
- Devices will restart and temporarily go offline

**When to use:**
- Applying firmware updates
- Recovering from stuck device states
- Bulk device restart

### 8. device_logs.py

Captures the firmware debug log stream from port 2323 on Linn DSM devices. Provides real-time log categorization, multi-device concurrent capture, and post-capture analysis reports.

**Usage:**
```bash
# All .env devices, default 60s
.venv/bin/python device_logs.py

# Single device
.venv/bin/python device_logs.py 172.24.32.211

# Custom duration
.venv/bin/python device_logs.py --duration 120

# Wrap a command with log capture
.venv/bin/python device_logs.py --around-command ".venv/bin/python now_playing.py --debug"

# Background daemonized capture
.venv/bin/python device_logs.py --background
.venv/bin/python device_logs.py --stop

# Filter to specific subsystems
.venv/bin/python device_logs.py --filter SONGCAST,ERROR
```

**Options:**
- `--duration` / `-d` — Capture duration in seconds (default: 60)
- `--port` — Override target port (default: 2323)
- `--output-dir` / `-o` — Output directory (default: `captures/`)
- `--max-lines` — Max lines per capture file before rotation (default: 5000)
- `--filter` / `-f` — Comma-separated subsystem filter (e.g., `HLS,ERROR,SONGCAST`)
- `--around-command` — Capture logs while running a command, then stop
- `--background` — Daemonize capture with PID file
- `--stop` — Stop a background capture
- `--debug` — Enable debug output

**Log Subsystem Categories:**
- `HLS` — HLS playlist parsing, segment fetches
- `HTTP` — URI loader requests, status codes
- `PIPELINE` — Audio pipeline state reports
- `CONTAINER` — Media container parsing (MPEG-4, MPEG-TS, ID3v2)
- `SONGCAST` — Songcast/OHM receiver/sender activity
- `CODEC` — Codec detection and decoding
- `VOLUME` — Volume/mute changes
- `TRANSPORT` — Playback transport state changes
- `ERROR` — Error conditions
- `OTHER` — Unclassified lines

**Output:**
```
captures/DEVICE_1_20260515_143022.log           # Raw timestamped capture
captures/DEVICE_1_20260515_143022_analysis.txt  # Analysis report
```

**When to use:**
- Diagnosing playback issues (HLS failures, codec problems)
- Observing firmware-level behavior during Songcast operations
- Capturing evidence for bug reports
- Correlating with LPEC state monitoring

### 9. songcast_monitor.py (tests/)

**⚡ Test Harness for Command Validation**

Monitors Songcast member devices in real-time using LPEC (Linn Protocol for Eventing and Control) subscriptions. This tool "closes the loop" by validating that commands issued by other scripts are being enacted correctly on real hardware.

**Usage:**
```bash
# Basic monitoring
.venv/bin/python tests/songcast_monitor.py

# With debug output
.venv/bin/python tests/songcast_monitor.py --debug

# With verbose event logging
.venv/bin/python tests/songcast_monitor.py --verbose
```

**Configuration (.env):**
Monitors the sender and all receivers:
```bash
DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f
DEVICE_2=172.24.32.210 4c494e4e-0026-0f22-646e-01560511013f
DEVICE_3=172.24.32.212 4c494e4e-0026-0f22-3637-01475230013f
SONGCAST_SENDER=DEVICE_1
SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3
```

**Example Output:**
```
[12:34:56.789] [DEVICE_2:172.24.32.210] EVENT: ⚡ STATE CHANGE (seq=1):
[12:34:56.789] [DEVICE_2:172.24.32.210] EVENT:   TransportState: Stopped → Buffering
[12:34:56.790] [DEVICE_2:172.24.32.210] EVENT:   Sender: None → ohz://239.255.255.250:51972/...

[12:34:58.123] [DEVICE_2:172.24.32.210] EVENT: ⚡ STATE CHANGE (seq=2):
[12:34:58.123] [DEVICE_2:172.24.32.210] EVENT:   TransportState: Buffering → Playing
```

**Features:**
- Real-time event monitoring via LPEC telnet (port 23)
- Tracks Receiver service state: TransportState, Sender URI, Status
- Timestamped events with millisecond precision
- Monitors multiple devices simultaneously
- Validates Songcast grouping commands
- Graceful reconnection handling
- Ctrl+C for clean shutdown

**When to use:**
- Testing songcast_group.py command execution
- Debugging multi-room synchronization issues
- Validating state transitions during automation
- Developing and testing new control scripts
- Observing real hardware behavior

**Test Workflow:**
1. Start monitor in one terminal: `.venv/bin/python tests/songcast_monitor.py --debug`
2. Execute command in another terminal: `.venv/bin/python songcast_group.py --debug`
3. Observe real-time state changes in monitor output
4. Verify expected states: Playing, correct Sender URI, Status=Yes

See [tests/SONGCAST_MONITOR.md](tests/SONGCAST_MONITOR.md) for detailed documentation.

## Common Workflows

### Setting Up a New Device

1. Find the device UDN:
```bash
python3 find_linn_udn.py 192.168.1.100
```

2. Add the device to your `.env` file:
```bash
echo "DEVICE_1=192.168.1.100 4c494e4e-0026-0f22-5661-01531488013f" >> .env
```

3. Query available sources:
```bash
python3 query_sources.py 192.168.1.100 4c494e4e-0026-0f22-5661-01531488013f
```

### Monitoring Multiple Rooms

1. Configure all devices in `.env`
2. Run the now playing script:
```bash
source .venv/bin/activate
python now_playing.py
```

### Creating a Multi-Room Setup

1. Configure devices in `.env`:
```bash
DEVICE_1=192.168.1.100 4c494e4e-0026-0f22-5661-01531488013f  # Living Room
DEVICE_2=192.168.1.101 4c494e4e-0026-0f22-5661-01531488abcd  # Kitchen
SONGCAST_SENDER=DEVICE_1
SONGCAST_RECEIVERS=DEVICE_2
```

2. Create the Songcast group:
```bash
source .venv/bin/activate
python songcast_group.py
```

3. Play audio on the sender device (Living Room), and it will stream to receivers (Kitchen)

### Breaking Up a Multi-Room Setup

Disband the Songcast group and return all devices to standalone:
```bash
source .venv/bin/activate
python songcast_disband.py
```

No additional configuration needed — sender/receiver roles are auto-detected.

### Capturing Firmware Logs

Wrap any command with firmware debug log capture for diagnostics:
```bash
.venv/bin/python device_logs.py --around-command ".venv/bin/python songcast_group.py --debug"
```

Or capture in the background while you work:
```bash
.venv/bin/python device_logs.py --background
# ... run commands, observe ...
.venv/bin/python device_logs.py --stop
```

## Shared Utilities

### lpec_utils.py

Shared LPEC helper functions used by `songcast_group.py` and `tests/songcast_monitor.py` for real-time device state verification.

**Functions:**
- `query_receiver_state(ip)` — Query Receiver service state via LPEC
- `wait_for_state(ip, expected, timeout)` — Poll until device reaches expected state
- `check_transport_playing(ip)` — Quick check if device is Playing/Buffering
- `check_sender_uri(ip, scheme)` — Check if sender URI matches expected scheme
- `format_state_summary(state)` — Format state dict into human-readable string

**Standalone test:**
```bash
.venv/bin/python lpec_utils.py 172.24.32.210
```

## Troubleshooting

### Device Not Found

- Verify the device is powered on and connected to the network
- Check that the IP address is correct
- Ensure your computer and the device are on the same network
- Try pinging the device: `ping 192.168.1.100`

### UDN Discovery Fails

- Check if telnet is enabled on the device (port 23)
- Try connecting manually: `telnet <IP_ADDRESS> 23`
- Some firmware versions may have telnet disabled

### Songcast Grouping Fails

- Ensure all devices are powered on (not in standby)
- Verify the sender device is playing audio
- Check that receiver devices have Songcast source available
- Try running with `--debug` flag for detailed output
- Ensure devices are on the same network subnet

### openhomedevice Import Errors

- Make sure you've activated the virtual environment: `source .venv/bin/activate`
- Install the package: `pip install openhomedevice`
- Check Python version: `python3 --version` (requires 3.7+)

### Permission Errors

- Make scripts executable: `chmod +x *.py`
- Or always run with `python3 script.py` instead of `./script.py`

## Technical Details

### OpenHome Protocol

These tools use the Linn OpenHome protocol, which is built on top of UPnP/SOAP. The main services used are:

- **Product:4** - Device product information, source selection
- **Receiver:1** - Songcast receiver control
- **Sender:1** - Songcast sender control
- **Pins:1** - Pin/preset management
- **Info** - Track metadata retrieval
- **Playlist:1** - Playlist/playback control (used to stop sender playback)
- **Volkano:1** - Linn-specific device management (reboot) — `linn.co.uk-Volkano-1`

### Communication Methods

- **SOAP over HTTP** - Primary method for control commands (port 55178)
- **LPEC (Linn Protocol for Eventing and Control)** - Telnet-based protocol for real-time state subscriptions and device discovery (port 23)
- **Firmware Debug Stream** - Read-only diagnostic log stream from internal C++ media pipeline (port 2323)
- **ohz:// protocol** - Multicast streaming for Songcast (port 51972)
- **ohSongcast:// descriptors** - Alternative Songcast connection method

### Device URL Structure

Devices are accessed via: `http://<IP>:55178/<UDN>/Upnp/device.xml`

Service control endpoints: `http://<IP>:55178/<UDN>/<service-path>/control`

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

Please refer to the repository license file for licensing information.

## Resources

- [OpenHome Wiki - Main Documentation](https://wiki.openhome.org/)
- [OpenHome Wiki - av.openhome.org Services](https://wiki.openhome.org/wiki/Av:Developer:Service)
- [OpenHome Protocol Documentation on GitHub](https://github.com/openhome)
- [openhomedevice Python Library](https://pypi.org/project/openhomedevice/)

## Credits

Developed for controlling Linn DSM network audio players using the OpenHome protocol.
