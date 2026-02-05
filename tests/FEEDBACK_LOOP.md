# Feedback Loop Integration Guide

This guide describes how the LPEC-based feedback loop enhances development of OpenHome control scripts.

## Overview

The feedback loop consists of:
1. **lpec_utils.py** - Shared LPEC query functions
2. **songcast_monitor.py** - Real-time event listener with automated assertions
3. **songcast_group.py** - Enhanced with LPEC state verification

## Components

### 1. lpec_utils.py - Shared LPEC Library

Provides functions for querying device state via LPEC without persistent connections.

**Key Functions:**

```python
# Query current Receiver state
state = query_receiver_state("172.24.32.210", timeout=3.0)
# Returns: {'TransportState': 'Playing', 'Sender': 'ohz://...', 'Status': 'Yes'}

# Wait for specific state
success, state = wait_for_state(
    "172.24.32.210",
    {'TransportState': 'Playing', 'Status': 'Yes'},
    timeout=10.0
)

# Quick checks
is_playing = check_transport_playing("172.24.32.210")
matches_ohz, uri = check_sender_uri("172.24.32.210", "ohz")
```

**Standalone Usage:**
```bash
# Test LPEC query for a device
.venv/bin/python lpec_utils.py 172.24.32.210
```

### 2. songcast_group.py - Enhanced Verification

Now includes LPEC verification after each receiver join operation.

**What Changed:**
- Imports `lpec_utils` for state queries
- After setting receiver source, waits for "Playing" state via LPEC
- Shows both API check AND LPEC verification results
- Provides detailed state information on failure

**Example Output:**
```
5. Verifying Songcast configuration...
✓ API Check: Receiver reports grouped (ohz/transport active)
  Verifying via LPEC...
✓ LPEC Verification: Device reached Playing state
  Final state: Transport=Playing, Sender=ohz://..., Status=Yes
```

**Benefits:**
- Catches cases where API reports success but device isn't actually playing
- Shows exact state progression
- Provides diagnostic info for troubleshooting

### 3. songcast_monitor.py - Automated Assertions

**New Test Mode:**

Run monitor with test assertions from JSON file:
```bash
.venv/bin/python experimental/songcast_monitor.py --test experimental/test_songcast_join.json
```

**Test JSON Format:**
```json
{
  "name": "Songcast Group Join Test",
  "description": "Verify receivers reach Playing state",
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

**Test Output:**
```
Test Mode: Songcast Group Join Test
==================================================
Assertion: DEVICE_2.TransportState = 'Playing' within 10.0s
Assertion: DEVICE_3.TransportState = 'Playing' within 10.0s

[Monitor output...]

==================================================
Test Results
==================================================
✓ PASS (2.34s) DEVICE_2.TransportState = 'Playing'
✓ PASS (2.56s) DEVICE_3.TransportState = 'Playing'

Passed: 2/2
Failed: 0/2
```

**Exit Codes:**
- `0` - All assertions passed
- `1` - One or more assertions failed

## Development Workflows

### Workflow 1: Manual Validation

**Terminal 1 - Monitor:**
```bash
.venv/bin/python tests/songcast_monitor.py --debug
```

**Terminal 2 - Execute Command:**
```bash
.venv/bin/python songcast_group.py --debug
```

**Observe:** Real-time state changes in Terminal 1, verify command success

### Workflow 2: Automated Testing

**Create test scenario:**
```json
{
  "name": "Quick Join Test",
  "assertions": [
    {
      "device": "DEVICE_2",
      "variable": "TransportState",
      "value": "Playing",
      "within_seconds": 8.0
    }
  ]
}
```

**Run test:**
```bash
# Terminal 1: Start test monitor
.venv/bin/python tests/songcast_monitor.py --test tests/test_quick_join.json

# Terminal 2: Execute command
.venv/bin/python songcast_group.py --debug

# Terminal 1: Will show pass/fail and exit
```

**Integrate with CI/CD:**
```bash
#!/bin/bash
# Start monitor in background
.venv/bin/python tests/songcast_monitor.py --test tests/test.json &
MONITOR_PID=$!

# Wait for initialization
sleep 3

# Run command
.venv/bin/python songcast_group.py --debug

# Wait for monitor test completion
wait $MONITOR_PID
TEST_RESULT=$?

# Exit with test result
exit $TEST_RESULT
```

### Workflow 3: Iterative Development

**With LPEC verification in songcast_group.py:**

1. Edit songcast_group.py
2. Run it: `.venv/bin/python songcast_group.py --debug`
3. See immediate LPEC feedback in the output
4. Iterate based on verification results

**No separate monitor needed** - verification is built-in!

## Use Cases

### Use Case 1: Debugging Failed Joins

**Problem:** `songcast_group.py` reports success but no audio plays

**Solution:**
```bash
# Terminal 1: Monitor
.venv/bin/python experimental/songcast_monitor.py --debug

# Terminal 2: Run grouping
.venv/bin/python songcast_group.py --debug
```

**Diagnose:** 
- Monitor shows TransportState stays "Stopped"
- Or goes "Buffering" but never "Playing"
- Or Sender URI is empty

### Use Case 2: Performance Validation

**Test JSON:**
```json
{
  "name": "Performance Test",
  "assertions": [
    {
      "device": "DEVICE_2",
      "variable": "TransportState",
      "value": "Playing",
      "within_seconds": 5.0
    }
  ]
}
```

Run multiple times, verify consistently meets 5-second target.

### Use Case 3: Regression Testing

Create test scenarios for each feature:
- `test_basic_join.json` - Simple 1-receiver join
- `test_multi_receiver.json` - Multiple receivers
- `test_sender_songcast.json` - Sender in Songcast mode

Run all tests after code changes to catch regressions.

### Use Case 4: AI Development Feedback

**AI develops new feature:**
1. AI writes code changes to songcast_group.py
2. AI runs with LPEC verification enabled
3. AI observes verification output
4. AI iterates based on actual hardware behavior

**The AI can "see" real results**, not just API responses!

## Testing Examples

### Example 1: Basic Join Test

**test_basic_join.json:**
```json
{
  "name": "Basic Songcast Join",
  "description": "Single receiver joins sender",
  "assertions": [
    {
      "device": "DEVICE_2",
      "variable": "TransportState",
      "value": "Playing",
      "within_seconds": 10.0
    },
    {
      "device": "DEVICE_2",
      "variable": "Status",
      "value": "Yes",
      "within_seconds": 10.0
    }
  ]
}
```

### Example 2: Multi-Receiver Test

**test_all_receivers.json:**
```json
{
  "name": "All Receivers Join",
  "assertions": [
    {"device": "DEVICE_2", "variable": "TransportState", "value": "Playing", "within_seconds": 10.0},
    {"device": "DEVICE_3", "variable": "TransportState", "value": "Playing", "within_seconds": 10.0},
    {"device": "DEVICE_2", "variable": "Status", "value": "Yes", "within_seconds": 12.0},
    {"device": "DEVICE_3", "variable": "Status", "value": "Yes", "within_seconds": 12.0}
  ]
}
```

### Example 3: Performance Test

**test_performance.json:**
```json
{
  "name": "Fast Join Test",
  "description": "Verify join completes within 5 seconds",
  "assertions": [
    {
      "device": "DEVICE_2",
      "variable": "TransportState",
      "value": "Playing",
      "within_seconds": 5.0
    }
  ]
}
```

## Integration with Other Scripts

### Adding LPEC Verification to New Scripts

```python
#!/usr/bin/env python3
import sys
from lpec_utils import wait_for_state, format_state_summary

def my_command(device_ip):
    # ... do your thing ...
    
    # Verify result via LPEC
    print("Verifying device state...")
    success, state = wait_for_state(
        device_ip,
        {'TransportState': 'Playing'},
        timeout=10.0
    )
    
    if success:
        print(f"✓ Verification passed: {format_state_summary(state)}")
        return 0
    else:
        print(f"✗ Verification failed")
        if state:
            print(f"  Last state: {format_state_summary(state)}")
        return 1
```

### Creating Custom Test Scenarios

**Template:**
```json
{
  "name": "Test Name",
  "description": "What this test validates",
  "assertions": [
    {
      "device": "DEVICE_ID",
      "variable": "VariableName",
      "value": "ExpectedValue",
      "within_seconds": 10.0
    }
  ]
}
```

**Supported Variables:**
- `TransportState` - "Stopped", "Playing", "Buffering", "Paused"
- `Sender` - Full URI (e.g., "ohz://239.255.255.250:51972/...")
- `Status` - "Yes" or "No"
- `ProtocolInfo` - Protocol capabilities string

## Benefits for AI Development

1. **Immediate Feedback**: AI sees real hardware state, not just API success/fail
2. **Automated Validation**: Test mode provides clear pass/fail for AI to evaluate
3. **Iterative Improvement**: AI can run tests, observe results, adjust code, repeat
4. **Debugging Context**: Detailed state information helps AI understand failures
5. **Regression Prevention**: Existing tests catch when AI changes break working features

## Troubleshooting

### LPEC Verification Shows "(lpec_utils module not available)"

**Cause:** lpec_utils.py not in Python path

**Fix:**
```bash
# Ensure lpec_utils.py is in the same directory as your script
# Or add parent directory to path in the script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```

### Test Assertions Always Timeout

**Causes:**
- Device not actually changing state
- Wrong device ID in test JSON
- Telnet (port 23) blocked
- Device offline

**Debug:**
```bash
# Test LPEC connectivity
.venv/bin/python lpec_utils.py 172.24.32.210

# Run monitor without test mode to see actual events
.venv/bin/python tests/songcast_monitor.py --debug
```

### Verification Succeeds but Audio Doesn't Play

**Cause:** Device reports "Playing" but sender not actually sending audio

**Debug:**
- Check sender device is playing audio
- Verify sender is in correct mode (Songcast Sender if needed)
- Check network multicast routing

## Future Enhancements

Potential improvements:
- [ ] HTTP API for monitor (scripts can query state via HTTP)
- [ ] WebSocket events for real-time updates
- [ ] Test report generation (HTML/JSON output)
- [ ] Performance metrics tracking
- [ ] State diff visualization
- [ ] Integration with pytest
- [ ] Mock device for offline testing

## References

- [LPEC Protocol Documentation](https://docs.linn.co.uk/wiki/index.php/Developer:LPEC)
- [Receiver Service Spec](http://wiki.openhome.org/wiki/Av:Developer:Service:Receiver:1)
- [tests/SONGCAST_MONITOR.md](SONGCAST_MONITOR.md) - Monitor detailed docs
