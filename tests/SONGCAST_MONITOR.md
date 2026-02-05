# Songcast Monitor - Test Harness

A real-time event listener for validating Songcast commands against live hardware.

## Purpose

The `songcast_monitor.py` script provides a test harness that "closes the loop" between AI-developed scripts and real Linn DSM hardware by:

- **Monitoring live device state** via LPEC (Linn Protocol for Eventing and Control)
- **Validating command execution** by observing real-time state changes
- **Debugging integration issues** with detailed event logging
- **Tracking multi-room grouping** by monitoring Receiver service events

## How It Works

1. **LPEC Subscriptions**: Opens persistent telnet connections (port 23) to all Songcast member devices
2. **Event Stream**: Subscribes to `Ds/Receiver` service to receive real-time state updates
3. **State Tracking**: Monitors key variables:
   - `TransportState` - Playing, stopped, buffering states
   - `Sender` - Current sender URI (ohz:// or ohSongcast://)
   - `Status` - Receiver status messages
   - `ProtocolInfo` - Protocol capabilities

4. **Change Detection**: Displays only state changes with timestamps for easy validation

## Usage

### Basic Monitoring

Monitor all Songcast members configured in `.env`:

```bash
.venv/bin/python tests/songcast_monitor.py
```

### Debug Mode

See connection details and raw LPEC protocol messages:

```bash
.venv/bin/python tests/songcast_monitor.py --debug
```

### Verbose Mode

Log all events including heartbeats (useful for troubleshooting):

```bash
.venv/bin/python tests/songcast_monitor.py --verbose
```

### VS Code Tasks

Use the integrated tasks:
- **Run songcast_monitor** - Basic monitoring with debug output
- **Run songcast_monitor (verbose)** - Full verbose logging

Press `Ctrl+Shift+P` → `Tasks: Run Task` → Select task

## Configuration

Requires `.env` file with device definitions and Songcast members:

```bash
# Device definitions
DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f # Study
DEVICE_2=172.24.32.210 4c494e4e-0026-0f22-646e-01560511013f # Tin Hut
DEVICE_3=172.24.32.212 4c494e4e-0026-0f22-3637-01475230013f # Living Room

# Songcast configuration
SONGCAST_SENDER=DEVICE_1
SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3
```

The script monitors the sender and all receivers.

## Test Workflow Example

### 1. Start the Monitor

In one terminal:
```bash
.venv/bin/python tests/songcast_monitor.py --debug
```

You'll see initial state for all members:
```
[12:34:56.789] [DEVICE_2:172.24.32.210] INFO: Initial state: Transport=Stopped, Sender=, Status=No
[12:34:56.790] [DEVICE_3:172.24.32.212] INFO: Initial state: Transport=Stopped, Sender=, Status=No
```

### 2. Execute Songcast Command

In another terminal, run your songcast grouping script:
```bash
.venv/bin/python songcast_group.py --debug
```

### 3. Observe State Changes

The monitor will display real-time changes:
```
[12:35:01.234] [DEVICE_2:172.24.32.210] EVENT: ⚡ STATE CHANGE (seq=1):
[12:35:01.234] [DEVICE_2:172.24.32.210] EVENT:   TransportState: Stopped → Buffering
[12:35:01.235] [DEVICE_2:172.24.32.210] EVENT:   Sender: None → ohz://239.255.255.250:51972/...

[12:35:02.456] [DEVICE_2:172.24.32.210] EVENT: ⚡ STATE CHANGE (seq=2):
[12:35:02.456] [DEVICE_2:172.24.32.210] EVENT:   TransportState: Buffering → Playing
[12:35:02.456] [DEVICE_2:172.24.32.210] EVENT:   Status: No → Yes
```

### 4. Validate Success

Confirm that:
- ✅ `TransportState` transitions to `Playing` or `Buffering`
- ✅ `Sender` URI is set to expected `ohz://` or `ohSongcast://` URI
- ✅ `Status` changes to `Yes` when successfully connected
- ✅ All member devices show the same sender URI

### 5. Stop Monitoring

Press `Ctrl+C` to gracefully shut down all monitors.

## Event Format

Events are displayed with:
- **Timestamp** - High-resolution millisecond timestamps
- **Device ID** - Device name and IP from .env
- **Event Type** - INFO, EVENT, WARNING, ERROR, DEBUG
- **State Changes** - Old value → New value

Example output:
```
[12:34:56.789] [DEVICE_2:172.24.32.210] EVENT: ⚡ STATE CHANGE (seq=1):
[12:34:56.789] [DEVICE_2:172.24.32.210] EVENT:   TransportState: Stopped → Playing
```

## Troubleshooting

### No Events Received

If you see "No subscription response received":
- Verify device is powered on and on network
- Check `.env` has correct IP addresses and UDNs
- Ensure telnet (port 23) is accessible: `telnet <IP> 23`
- Device may not support Receiver service (check with `query_sources.py`)

### Connection Refused

If connection fails:
- Device may be offline or in deep standby
- Telnet may be disabled in device settings
- Network firewall may be blocking port 23

### Monitor Stops Unexpectedly

If "All monitors have stopped":
- Device may have closed the connection (power off, reboot)
- Network interruption occurred
- Restart the monitor script

## Integration with Other Scripts

### Testing songcast_group.py

```bash
# Terminal 1: Start monitor
.venv/bin/python tests/songcast_monitor.py --debug

# Terminal 2: Execute grouping
.venv/bin/python songcast_group.py --debug

# Verify in Terminal 1 that all members show state changes
```

### Testing play_pin.py

```bash
# Terminal 1: Start monitor
.venv/bin/python tests/songcast_monitor.py

# Terminal 2: Play a Pin
.venv/bin/python play_pin.py 172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f 1

# Monitor should show source changes (if Pin triggers Songcast)
```

## Advanced Usage

### Custom .env File

Monitor devices from a different configuration:
```bash
.venv/bin/python tests/songcast_monitor.py --env /path/to/custom.env
```

### Monitoring Subset of Devices

Temporarily edit `.env` to monitor specific devices:
```bash
# Only monitor Living Room
SONGCAST_RECEIVERS=DEVICE_3
```

## Technical Details

### LPEC Protocol

- **Port**: 23 (telnet)
- **Subscribe Command**: `SUBSCRIBE Ds/Receiver\r\n`
- **Event Format**: `EVENT <seq> <service> <variable> "<value>" ...`
- **Initial State**: Sent as `EVENT 0` immediately after subscription
- **Incremental Updates**: Subsequent events only include changed variables

### Monitored Variables

From `Ds/Receiver` service:
- `TransportState` - "Stopped", "Playing", "Buffering", "Paused"
- `Sender` - URI of current sender (ohz://, ohSongcast://, or empty)
- `Status` - Connection status ("No", "Yes")
- `ProtocolInfo` - Supported streaming protocols

### Threading Model

- Main thread: Manages lifecycle and user input (Ctrl+C)
- Per-device threads: Each monitor runs in dedicated daemon thread
- Socket timeouts: 30-second read timeout allows for graceful shutdown

## References

- [LPEC Documentation](https://docs.linn.co.uk/wiki/index.php/Developer:LPEC)
- [LPEC Protocol Spec (PDF)](https://docs.linn.co.uk/wiki/images/3/32/LPEC_V2-5.pdf)
- [OpenHome Receiver Service](http://wiki.openhome.org/wiki/Av:Developer:Service:Receiver:1)
- [Songcast ohz Protocol](http://wiki.openhome.org/wiki/Av:Developer:Songcast:Ohz)

## Future Enhancements

Potential improvements:
- [ ] Monitor Product service for source changes
- [ ] Monitor Info service for track metadata
- [ ] Log events to file for post-analysis
- [ ] Web interface for remote monitoring
- [ ] Automated test scenarios with assertions
- [ ] Comparison mode: expected vs actual state
- [ ] Alert on unexpected state transitions
