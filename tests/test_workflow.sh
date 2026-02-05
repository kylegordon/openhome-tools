#!/bin/bash
# Test workflow demonstration for songcast_monitor.py
# 
# This script demonstrates the "closed loop" test harness workflow:
# 1. Start monitoring in background
# 2. Execute a songcast grouping command
# 3. Capture and display both outputs
# 4. Cleanup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "===================================================================="
echo "Songcast Monitor Test Workflow"
echo "===================================================================="
echo ""
echo "This demonstrates the test harness validating real hardware changes"
echo ""

# Check if .env exists
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "✗ Error: .env file not found in $PROJECT_ROOT"
    echo ""
    echo "Please create a .env file with your device configuration:"
    echo "  DEVICE_1=<IP> <UDN>"
    echo "  DEVICE_2=<IP> <UDN>"
    echo "  SONGCAST_SENDER=DEVICE_1"
    echo "  SONGCAST_RECEIVERS=DEVICE_2"
    exit 1
fi

# Check if venv exists
if [ ! -d "$PROJECT_ROOT/.venv" ]; then
    echo "✗ Error: Virtual environment not found"
    echo "Please run: python3 -m venv .venv && source .venv/bin/activate && pip install openhomedevice requests"
    exit 1
fi

PYTHON="$PROJECT_ROOT/.venv/bin/python"
MONITOR_SCRIPT="$PROJECT_ROOT/tests/songcast_monitor.py"
GROUPING_SCRIPT="$PROJECT_ROOT/songcast_group.py"

# Check if scripts exist
if [ ! -f "$MONITOR_SCRIPT" ]; then
    echo "✗ Error: Monitor script not found: $MONITOR_SCRIPT"
    exit 1
fi

if [ ! -f "$GROUPING_SCRIPT" ]; then
    echo "✗ Error: Grouping script not found: $GROUPING_SCRIPT"
    exit 1
fi

# Temporary files for output
MONITOR_LOG=$(mktemp)
GROUPING_LOG=$(mktemp)

# Cleanup function
cleanup() {
    echo ""
    echo "===================================================================="
    echo "Cleaning up..."
    echo "===================================================================="
    
    if [ -n "$MONITOR_PID" ]; then
        echo "Stopping monitor (PID: $MONITOR_PID)..."
        kill $MONITOR_PID 2>/dev/null || true
        wait $MONITOR_PID 2>/dev/null || true
    fi
    
    rm -f "$MONITOR_LOG" "$GROUPING_LOG"
    echo "✓ Cleanup complete"
}

trap cleanup EXIT INT TERM

echo "Step 1: Starting songcast_monitor in background..."
echo "--------------------------------------------------------------------"
$PYTHON "$MONITOR_SCRIPT" --debug > "$MONITOR_LOG" 2>&1 &
MONITOR_PID=$!
echo "✓ Monitor started (PID: $MONITOR_PID)"
echo "  Output logging to: $MONITOR_LOG"
echo ""

# Wait for monitor to initialize
sleep 3

echo "Step 2: Checking monitor is running..."
echo "--------------------------------------------------------------------"
if ! ps -p $MONITOR_PID > /dev/null 2>&1; then
    echo "✗ Monitor failed to start"
    echo ""
    echo "Monitor output:"
    cat "$MONITOR_LOG"
    exit 1
fi

# Show initial monitor output
echo "Initial monitor output:"
head -30 "$MONITOR_LOG"
echo ""
echo "... (monitoring active) ..."
echo ""

# Wait a moment
sleep 2

echo "Step 3: Executing songcast_group.py..."
echo "--------------------------------------------------------------------"
echo "Running: $PYTHON $GROUPING_SCRIPT --debug"
echo ""

# Execute grouping command
if $PYTHON "$GROUPING_SCRIPT" --debug > "$GROUPING_LOG" 2>&1; then
    echo "✓ Grouping command completed"
else
    echo "⚠ Grouping command returned non-zero exit code (may be normal)"
fi
echo ""

# Wait for events to propagate
sleep 3

echo "Step 4: Results - Command Execution"
echo "--------------------------------------------------------------------"
cat "$GROUPING_LOG"
echo ""

echo "Step 5: Results - Monitor Observations"
echo "--------------------------------------------------------------------"
echo "Events detected by monitor:"
grep "EVENT:" "$MONITOR_LOG" | tail -20 || echo "(No events detected)"
echo ""

echo "===================================================================="
echo "Test Complete!"
echo "===================================================================="
echo ""
echo "Analysis:"
echo "  - Review the 'Command Execution' output for what was requested"
echo "  - Review the 'Monitor Observations' for what actually happened"
echo "  - Both should show successful state transitions if working correctly"
echo ""
echo "Full logs available at:"
echo "  Monitor:  $MONITOR_LOG"
echo "  Grouping: $GROUPING_LOG"
echo ""
echo "Note: Logs will be deleted on exit (Ctrl+C or script end)"
echo "Press Enter to view full monitor log, or Ctrl+C to exit..."

read -r

echo ""
echo "===================================================================="
echo "Full Monitor Log"
echo "===================================================================="
cat "$MONITOR_LOG"
