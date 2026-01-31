# OpenHome Tools

A collection of Python tools for controlling and monitoring Linn DSM devices using the OpenHome protocol.

## Overview

This repository provides command-line utilities to interact with Linn DSM network audio players. The tools allow you to:

- Discover device UDNs (Unique Device Names)
- Query now-playing information across multiple devices
- Play specific Pins (favorites/presets)
- List available sources
- Create Songcast groups for multi-room audio

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
pip install openhomedevice requests
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
SONGCAST_MASTER=DEVICE_1
SONGCAST_MEMBERS=DEVICE_2,DEVICE_3
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

Queries multiple Linn DSM devices for their current status and what's playing. Displays power state, source, track information, and Songcast leader relationships.

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
Kitchen (Songcast): Power: On, Songcast Leader: Living Room (ohz), Track: Song Title — Artist Name
Bedroom (in standby) (Playlist): Power: Off
```

**Features:**
- Shows power state (On/Off with standby notation)
- Displays current source and track metadata
- For Radio sources, shows station name
- For Songcast followers, identifies the leader device
- Caches device names for efficient leader lookups
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

Creates a Songcast group with one leader (sender) and one or more followers (receivers) for synchronized multi-room audio.

**Usage with .env configuration:**
```bash
# Option 1: Using activated virtual environment
source .venv/bin/activate
python songcast_group.py [--leader-songcast] [--debug]

# Option 2: Direct virtual environment invocation
.venv/bin/python songcast_group.py [--leader-songcast] [--debug]
```

**Usage with command-line arguments:**
```bash
source .venv/bin/activate
python songcast_group.py \
    --master-ip 172.24.32.211 \
    --master-udn 4c494e4e-0026-0f22-5661-01531488013f \
    --slave-ip 172.24.32.142 \
    --slave-udn 4c494e4e-0026-0f22-5661-01531488abcd \
    [--leader-songcast] [--debug]
```

**Configuration (.env):**
```bash
DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f
DEVICE_2=172.24.32.142 4c494e4e-0026-0f22-5661-01531488abcd
DEVICE_3=172.24.32.143 4c494e4e-0026-0f22-5661-01531488def0

SONGCAST_MASTER=DEVICE_1
SONGCAST_MEMBERS=DEVICE_2,DEVICE_3
```

**Output:**
```
=== Linn OpenHome Songcast Group Creator ===
Leader: Living Room (172.24.32.211)
Follower:  172.24.32.142 (172.24.32.142)
Follower:  172.24.32.143 (172.24.32.143)
--------------------------------------------------

1. Waking leader from standby...
✓ Living Room woken

=== Configuring follower Kitchen (172.24.32.142) ===
2. Waking follower from standby...
✓ Kitchen woken
3. Ensuring follower source is Songcast...
✓ Kitchen source set to Songcast (index 5)
4. Joining follower to leader...
✓ Receiver join attempted via Uri ohz://239.255.255.250:51972/...
5. Verifying Songcast configuration...
✓ SUCCESS: Follower actively grouped (ohz/transport active)

==================================================
✓ SUCCESS: Songcast group configured for all followers!

🎵 Play audio on Living Room and it should stream to followers
```

**Features:**
- Automatically wakes devices from standby
- Switches follower sources to Songcast
- Discovers and uses ohz:// URIs for optimal streaming
- Verifies successful grouping
- Supports `--leader-songcast` flag to switch leader to Songcast Sender mode
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
SONGCAST_MASTER=DEVICE_1
SONGCAST_MEMBERS=DEVICE_2
```

2. Create the Songcast group:
```bash
source .venv/bin/activate
python songcast_group.py
```

3. Play audio on the leader device (Living Room), and it will stream to followers (Kitchen)

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
- Verify the leader device is playing audio
- Check that follower devices have Songcast source available
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
- **Receiver:1** - Songcast receiver control (followers)
- **Sender:1** - Songcast sender control (leaders)
- **Pins:1** - Pin/preset management
- **Info** - Track metadata retrieval

### Communication Methods

- **SOAP over HTTP** - Primary method for control commands (port 55178)
- **Telnet** - Used for UDN discovery (port 23)
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
