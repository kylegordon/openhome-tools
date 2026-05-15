# Tests and Validation Tools

This directory contains test harnesses and validation tools for OpenHome script development.

## Overview

The test harness provides a feedback loop between control scripts and real Linn DSM hardware, enabling:
- Real-time state validation
- Automated test assertions
- Iterative development with immediate feedback
- Regression testing

## Tools

### songcast_monitor.py

**Real-time LPEC event monitor for validating Songcast commands**

Monitors Songcast devices via LPEC (Linn Protocol for Eventing and Control) subscriptions, displaying real-time state changes and validating command execution.

**Quick Start:**
```bash
# Basic monitoring
.venv/bin/python tests/songcast_monitor.py --debug

# Test mode with assertions
.venv/bin/python tests/songcast_monitor.py --test tests/test_songcast_join.json
```

**Documentation:** [SONGCAST_MONITOR.md](SONGCAST_MONITOR.md)

### test_workflow.sh

**Automated test workflow**

Demonstrates the complete test harness workflow:
1. Starts songcast_monitor in background
2. Executes songcast_group.py
3. Captures and displays results for validation

**Usage:**
```bash
./tests/test_workflow.sh
```

### test_songcast_join.json

**Example test scenario**

JSON-based test scenario defining expected state changes after songcast grouping:
- Receivers should reach "Playing" state
- Status should change to "Yes"
- Configurable timeouts

## Documentation

- **[SONGCAST_MONITOR.md](SONGCAST_MONITOR.md)** - Detailed monitor documentation
  - Usage examples
  - Configuration
  - Test workflows
  - Troubleshooting

- **[FEEDBACK_LOOP.md](FEEDBACK_LOOP.md)** - Integration guide
  - LPEC utilities overview
  - Development workflows
  - Test scenarios
  - AI development integration

## Quick Start

### 1. Monitor Real-Time Events

Terminal 1:
```bash
.venv/bin/python tests/songcast_monitor.py --debug
```

Terminal 2:
```bash
.venv/bin/python songcast_group.py --debug
```

Observe real-time state changes in Terminal 1.

### 2. Run Automated Tests

Create a test scenario (`my_test.json`):
```json
{
  "name": "My Test",
  "assertions": [
    {
      "device": "DEVICE_2",
      "variable": "TransportState",
      "value": "Playing",
      "within_seconds": 10.0
    }
  ]
}
```

Run the test:
```bash
# Terminal 1: Start test monitor
.venv/bin/python tests/songcast_monitor.py --test tests/my_test.json

# Terminal 2: Execute command
.venv/bin/python songcast_group.py --debug
```

Monitor will show pass/fail and exit with appropriate code.

### 3. Use LPEC Verification in Scripts

The `lpec_utils.py` module (in project root) provides functions for querying device state:

```python
from lpec_utils import wait_for_state, format_state_summary

# Wait for device to reach Playing state
success, state = wait_for_state(
    "172.24.32.210",
    {'TransportState': 'Playing'},
    timeout=10.0
)

if success:
    print(f"✓ Device is playing: {format_state_summary(state)}")
else:
    print(f"✗ Device not playing")
```

## Test Scenarios

Example test scenarios included:

### test_songcast_join.json

Validates basic Songcast group join:
- DEVICE_2 reaches "Playing" within 10s
- DEVICE_3 reaches "Playing" within 10s
- Both devices show "Status=Yes" within 12s

**Run:**
```bash
.venv/bin/python tests/songcast_monitor.py --test tests/test_songcast_join.json
```

## Development Workflow

### Iterative Development

1. **Start monitor** to observe device behavior
2. **Edit code** (e.g., songcast_group.py)
3. **Run script** - see immediate feedback via LPEC verification
4. **Iterate** based on actual hardware state

### Capturing Firmware Debug Logs

Use `device_logs.py` (project root) to capture the port 2323 firmware debug stream alongside your operations:

```bash
# Wrap any command with firmware log capture
.venv/bin/python device_logs.py --around-command ".venv/bin/python songcast_group.py --debug"

# Background capture while you work in another terminal
.venv/bin/python device_logs.py --background
# ... run commands, observe ...
.venv/bin/python device_logs.py --stop

# Filter to specific subsystems
.venv/bin/python device_logs.py --filter SONGCAST,ERROR --duration 30
```

Output is written to `captures/` with timestamped filenames and automatic analysis reports (subsystem activity, HTTP status codes, stream URIs, errors).

**Combined workflow** (both LPEC state + firmware debug):

Terminal 1 - LPEC state monitoring:
```bash
.venv/bin/python tests/songcast_monitor.py --debug
```

Terminal 2 - Firmware log capture wrapping the command:
```bash
.venv/bin/python device_logs.py --around-command ".venv/bin/python songcast_group.py --debug"
```

This gives you LPEC-level state transitions (port 23) alongside low-level firmware pipeline diagnostics (port 2323).

### Debugging Failures

When a command reports success but doesn't work:

1. **Run with monitor** to see actual state transitions
2. **Check LPEC output** for unexpected states
3. **Review timing** - does device need more time?
4. **Verify URIs** - is the correct ohz:// URI being used?

### Regression Testing

1. **Create test scenarios** for each feature
2. **Run before release** to catch regressions
3. **Integrate with CI/CD** using exit codes

## VS Code Integration

Use the integrated tasks (Ctrl+Shift+P → Tasks: Run Task):

**Monitoring & Diagnostics:**
- **Run songcast_monitor** - Real-time LPEC state monitoring (port 23)
- **Run songcast_monitor (verbose)** - Full verbose LPEC logging
- **Capture device logs (60s)** - Firmware debug stream capture (port 2323)
- **Capture device logs (background)** - Daemonized capture until stopped
- **Stop device log capture** - Stop background capture and produce reports

**Script Execution:**
- **Run now_playing** - Quick now-playing query
- **Run songcast_group join** - Execute Songcast grouping

**Combined (capture + execute):**
- **Capture logs around now_playing** - Wraps now_playing with firmware capture
- **Capture logs around songcast_group** - Wraps songcast_group with firmware capture

## Files

- `songcast_monitor.py` - Main monitoring and test script (LPEC, port 23)
- `test_songcast_join.json` - Example test scenario
- `test_workflow.sh` - Automated test workflow script
- `SONGCAST_MONITOR.md` - Detailed documentation
- `FEEDBACK_LOOP.md` - Integration and development guide

**Project root (diagnostic tools):**
- `device_logs.py` - Firmware debug log capture & analysis (port 2323)
- `lpec_utils.py` - Shared LPEC query functions (port 23)

## Requirements

- Python 3.7+
- Virtual environment with dependencies installed
- Devices configured in `.env`
- Telnet enabled on devices (port 23)

## Troubleshooting

### Monitor Won't Connect

- Verify device IP addresses in `.env`
- Check telnet is enabled: `telnet <IP> 23`
- Ensure devices are powered on

### Tests Always Fail

- Run without test mode to see actual events
- Check device IDs in test JSON match `.env`
- Verify expected values are correct
- Increase timeout if device is slow

### No Events Received

- Device may not support Receiver service
- Check with `query_sources.py` for Songcast source
- Verify network connectivity

## References

- [LPEC Documentation](https://docs.linn.co.uk/wiki/index.php/Developer:LPEC)
- [LPEC Protocol Spec (PDF)](https://docs.linn.co.uk/wiki/images/3/32/LPEC_V2-5.pdf)
- [Receiver Service Spec](http://wiki.openhome.org/wiki/Av:Developer:Service:Receiver:1)
- [Songcast ohz Protocol](http://wiki.openhome.org/wiki/Av:Developer:Songcast:Ohz)

## License

Same as parent project (see root LICENSE file)
