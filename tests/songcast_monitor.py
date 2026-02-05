#!/usr/bin/env python3
"""
Songcast Monitor - LPEC Event Listener for Test Validation

Purpose:
- Monitors all Songcast member devices defined in .env using LPEC subscriptions
- Listens to Ds/Receiver service events in real-time
- Validates that commands issued by other scripts are enacted correctly
- Provides a test harness to "close the loop" with real hardware

Usage:
    .venv/bin/python tests/songcast_monitor.py [--debug] [--verbose]

Configuration (.env):
    DEVICE_1=<IP> <UDN>
    DEVICE_2=<IP> <UDN>
    DEVICE_3=<IP> <UDN>
    SONGCAST_SENDER=DEVICE_1
    SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3

Features:
- Opens persistent LPEC telnet connections (port 23) to all Songcast devices
- Subscribes to Ds/Receiver service for real-time state updates
- Monitors key state changes: TransportState, Sender URI, Status
- Displays timestamped events for validation and debugging
- Handles reconnection on connection loss
- Graceful shutdown on Ctrl+C

LPEC Protocol:
- Port: 23 (telnet)
- Subscribe command: "SUBSCRIBE Ds/Receiver"
- Events format: "EVENT <seq> <service> <variable> <value>"
- Docs: https://docs.linn.co.uk/wiki/index.php/Developer:LPEC
"""

import socket
import sys
import re
import time
import os
import threading
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# Ensure immediate flushing when redirected
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

class StateAssertion:
    """Represents an expected state change assertion"""
    def __init__(self, device_id: str, variable: str, expected_value: str, within_seconds: float = 10.0):
        self.device_id = device_id
        self.variable = variable
        self.expected_value = expected_value
        self.within_seconds = within_seconds
        self.start_time = None
        self.met = False
        self.met_time = None
        self.actual_value = None
        
    def start(self):
        """Start the assertion timer"""
        self.start_time = time.time()
        
    def check(self, device_id: str, variable: str, value: str) -> bool:
        """Check if this assertion is met by the given state change"""
        if self.met:
            return False
            
        if device_id == self.device_id and variable == self.variable and value == self.expected_value:
            self.met = True
            self.met_time = time.time()
            self.actual_value = value
            return True
        return False
        
    def is_expired(self) -> bool:
        """Check if assertion timeout has expired"""
        if not self.start_time or self.met:
            return False
        return (time.time() - self.start_time) > self.within_seconds
        
    def elapsed_time(self) -> Optional[float]:
        """Get elapsed time if met, otherwise None"""
        if self.met and self.start_time and self.met_time:
            return self.met_time - self.start_time
        return None
        
    def status_string(self) -> str:
        """Get human-readable status"""
        if self.met:
            elapsed = self.elapsed_time()
            return f"✓ PASS ({elapsed:.2f}s)"
        elif self.is_expired():
            return f"✗ FAIL (timeout {self.within_seconds}s)"
        else:
            return "⏳ PENDING"

class DeviceMonitor:
    """Monitor a single device via LPEC subscription"""
    
    def __init__(self, device_id: str, ip: str, udn: str, debug: bool = False, verbose: bool = False, assertions: Optional[List[StateAssertion]] = None):
        self.device_id = device_id
        self.ip = ip
        self.udn = udn
        self.debug = debug
        self.verbose = verbose
        self.sock = None
        self.running = False
        self.thread = None
        self.state = {}
        self.last_event_time = None
        self.assertions = assertions or []
        
    def log(self, msg: str, level: str = "INFO"):
        """Print timestamped log message"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        prefix = f"[{timestamp}] [{self.device_id}:{self.ip}]"
        print(f"{prefix} {level}: {msg}")
        
    def connect(self, port: int = 23, timeout: int = 5) -> bool:
        """Establish LPEC connection to device"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            
            self.log(f"Connecting to port {port}...")
            self.sock.connect((self.ip, port))
            
            # Read initial ALIVE messages
            buffer = ""
            start = time.time()
            while time.time() - start < 2:
                try:
                    chunk = self.sock.recv(4096).decode('utf-8', errors='ignore')
                    if not chunk:
                        break
                    buffer += chunk
                    if 'ALIVE Ds' in buffer:
                        break
                except socket.timeout:
                    break
                    
            if self.debug and buffer.strip():
                self.log(f"Initial response:\n{buffer.strip()}", "DEBUG")
                
            # Workaround for LPEC first-command bug
            try:
                self.sock.sendall("\r\n".encode('utf-8'))
                time.sleep(0.1)
            except Exception:
                pass
                
            self.log("Connected successfully")
            return True
            
        except socket.timeout:
            self.log(f"Connection timeout", "ERROR")
            return False
        except ConnectionRefusedError:
            self.log(f"Connection refused - device may be offline or telnet disabled", "ERROR")
            return False
        except Exception as e:
            self.log(f"Connection error: {e}", "ERROR")
            return False
            
    def subscribe(self) -> bool:
        """Subscribe to Ds/Receiver service events"""
        try:
            cmd = "SUBSCRIBE Ds/Receiver\r\n"
            self.log(f"Subscribing to Ds/Receiver...")
            self.sock.sendall(cmd.encode('utf-8'))
            
            # Read initial EVENT 0 with current state
            buffer = ""
            start = time.time()
            while time.time() - start < 3:
                try:
                    chunk = self.sock.recv(4096).decode('utf-8', errors='ignore')
                    if not chunk:
                        break
                    buffer += chunk
                    # Look for initial EVENT line
                    if re.search(r'^EVENT\s+0\s+', buffer, re.MULTILINE):
                        break
                except socket.timeout:
                    break
                    
            if not buffer.strip():
                self.log("No subscription response received", "WARNING")
                return False
                
            # Parse initial state from EVENT 0
            self._parse_initial_event(buffer)
            
            if self.debug:
                self.log(f"Subscription response:\n{buffer.strip()}", "DEBUG")
            else:
                self.log(f"Subscribed successfully - monitoring events")
                
            return True
            
        except Exception as e:
            self.log(f"Subscription error: {e}", "ERROR")
            return False
            
    def _parse_initial_event(self, buffer: str):
        """Parse initial EVENT 0 to populate current state"""
        for line in buffer.splitlines():
            line = line.strip()
            if not line.startswith("EVENT"):
                continue
                
            # Extract key state variables
            # Format: EVENT <seq> <service> <variable> <value> [<variable> <value> ...]
            
            # TransportState
            m = re.search(r'TransportState\s+"([^"]*)"', line)
            if m:
                self.state['TransportState'] = m.group(1)
                
            # Sender (URI)
            m = re.search(r'Sender\s+"([^"]*)"', line)
            if m:
                self.state['Sender'] = m.group(1)
                
            # Status
            m = re.search(r'Status\s+"([^"]*)"', line)
            if m:
                self.state['Status'] = m.group(1)
                
            # ProtocolInfo
            m = re.search(r'ProtocolInfo\s+"([^"]*)"', line)
            if m:
                self.state['ProtocolInfo'] = m.group(1)
                
        # Display initial state
        if self.state:
            self.log(f"Initial state: {self._format_state()}")
        else:
            self.log("No initial state received", "WARNING")
            
    def _format_state(self) -> str:
        """Format current state for display"""
        parts = []
        if 'TransportState' in self.state:
            parts.append(f"Transport={self.state['TransportState']}")
        if 'Sender' in self.state:
            sender = self.state['Sender']
            # Abbreviate long URIs
            if len(sender) > 50:
                if sender.startswith('ohz://'):
                    parts.append(f"Sender=ohz://...")
                elif sender.startswith('ohSongcast://'):
                    parts.append(f"Sender=ohSongcast://...")
                else:
                    parts.append(f"Sender={sender[:30]}...")
            else:
                parts.append(f"Sender={sender}")
        if 'Status' in self.state:
            parts.append(f"Status={self.state['Status']}")
        return ", ".join(parts) if parts else "No state"
        
    def listen(self):
        """Listen for LPEC events in a loop"""
        self.running = True
        buffer = ""
        
        # Set socket to blocking mode with longer timeout for event listening
        self.sock.settimeout(30)
        
        self.log("Listening for events...")
        
        while self.running:
            try:
                chunk = self.sock.recv(4096).decode('utf-8', errors='ignore')
                if not chunk:
                    self.log("Connection closed by device", "WARNING")
                    break
                    
                buffer += chunk
                
                # Process complete lines
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    
                    if not line:
                        continue
                        
                    # Process EVENT lines
                    if line.startswith("EVENT"):
                        self._process_event(line)
                    elif self.verbose:
                        self.log(f"Other: {line}", "DEBUG")
                        
            except socket.timeout:
                # Timeout is normal - just continue listening
                if self.verbose:
                    self.log("Heartbeat (no events)", "DEBUG")
                continue
            except Exception as e:
                if self.running:
                    self.log(f"Listen error: {e}", "ERROR")
                break
                
        self.running = False
        
    def _process_event(self, line: str):
        """Process a single EVENT line and update state"""
        self.last_event_time = datetime.now()
        
        # Parse event: EVENT <seq> <service> <variable> <value> [...]
        match = re.match(r'^EVENT\s+(\d+)\s+(.+)$', line)
        if not match:
            if self.verbose:
                self.log(f"Unparseable event: {line}", "DEBUG")
            return
            
        seq = match.group(1)
        rest = match.group(2)
        
        # Extract variable changes
        changes = {}
        
        # TransportState
        m = re.search(r'TransportState\s+"([^"]*)"', rest)
        if m:
            new_val = m.group(1)
            old_val = self.state.get('TransportState')
            if new_val != old_val:
                changes['TransportState'] = (old_val, new_val)
                self.state['TransportState'] = new_val
                
        # Sender
        m = re.search(r'Sender\s+"([^"]*)"', rest)
        if m:
            new_val = m.group(1)
            old_val = self.state.get('Sender')
            if new_val != old_val:
                changes['Sender'] = (old_val, new_val)
                self.state['Sender'] = new_val
                
        # Status
        m = re.search(r'Status\s+"([^"]*)"', rest)
        if m:
            new_val = m.group(1)
            old_val = self.state.get('Status')
            if new_val != old_val:
                changes['Status'] = (old_val, new_val)
                self.state['Status'] = new_val
                
        # ProtocolInfo
        m = re.search(r'ProtocolInfo\s+"([^"]*)"', rest)
        if m:
            new_val = m.group(1)
            old_val = self.state.get('ProtocolInfo')
            if new_val != old_val:
                changes['ProtocolInfo'] = (old_val, new_val)
                self.state['ProtocolInfo'] = new_val
                
        # Display changes
        if changes:
            self.log(f"⚡ STATE CHANGE (seq={seq}):", "EVENT")
            for var, (old, new) in changes.items():
                # Format output based on variable
                if var == 'Sender':
                    # Show protocol scheme and brief info
                    old_str = self._format_uri(old) if old else "None"
                    new_str = self._format_uri(new) if new else "None"
                    self.log(f"  {var}: {old_str} → {new_str}", "EVENT")
                else:
                    self.log(f"  {var}: {old} → {new}", "EVENT")
                    
                # Check assertions
                for assertion in self.assertions:
                    if assertion.check(self.device_id, var, new):
                        elapsed = assertion.elapsed_time()
                        self.log(f"  ✓ Assertion met: {var}={new} (after {elapsed:.2f}s)", "ASSERT")
                        
        elif self.verbose:
            # No changes but log the event in verbose mode
            self.log(f"Event #{seq} (no changes)", "DEBUG")
            
    def _format_uri(self, uri: str) -> str:
        """Format URI for compact display"""
        if not uri:
            return "None"
        if uri.startswith('ohz://'):
            # Extract multicast address if present
            m = re.search(r'ohz://([^/]+)', uri)
            if m:
                return f"ohz://{m.group(1)}/..."
            return "ohz://..."
        elif uri.startswith('ohSongcast://'):
            # Extract room/name if present
            m = re.search(r'room=([^&]+)', uri)
            room = m.group(1) if m else "?"
            return f"ohSongcast://[{room}]"
        elif len(uri) > 60:
            return uri[:60] + "..."
        return uri
        
    def start(self) -> bool:
        """Start monitoring in background thread"""
        if not self.connect():
            return False
            
        if not self.subscribe():
            self.close()
            return False
            
        self.thread = threading.Thread(target=self.listen, daemon=True)
        self.thread.start()
        return True
        
    def stop(self):
        """Stop monitoring and close connection"""
        self.log("Stopping monitor...")
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.close()
        
    def close(self):
        """Close socket connection"""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None


def load_env_config(env_path: str = '.env') -> Tuple[Optional[Dict], Optional[List[Dict]]]:
    """
    Load device configuration from .env file
    Returns: (master_device or None, [member_devices])
    """
    devices = {}
    master_id = None
    member_ids = []
    
    if not os.path.exists(env_path):
        print(f"✗ Configuration file not found: {env_path}")
        return None, []
        
    try:
        with open(env_path, 'r') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                # Strip inline comments
                if '#' in line:
                    line = line.split('#', 1)[0].strip()
                if not line or '=' not in line:
                    continue
                    
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip()
                
                if key.startswith('DEVICE'):
                    parts = val.split()
                    if len(parts) >= 2:
                        devices[key] = {"id": key, "ip": parts[0], "udn": parts[1]}
                elif key in ('SONGCAST_MASTER', 'SONGCAST_SENDER'):
                    master_id = val.strip()
                elif key in ('SONGCAST_MEMBERS', 'SONGCAST_RECEIVERS'):
                    member_ids = [v.strip() for v in val.split(',') if v.strip()]
                    
    except Exception as e:
        print(f"✗ Error reading {env_path}: {e}")
        return None, []
        
    # Resolve master and members
    master = devices.get(master_id) if master_id else None
    members = [devices[mid] for mid in member_ids if mid in devices]
    
    # Combine master and members for monitoring (monitor all devices)
    all_devices = []
    if master:
        all_devices.append(master)
    all_devices.extend(members)
    
    return master, all_devices


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Monitor Songcast member devices via LPEC subscriptions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor all Songcast members from .env
  .venv/bin/python tests/songcast_monitor.py
  
  # Enable debug output
  .venv/bin/python tests/songcast_monitor.py --debug
  
  # Enable verbose event logging
  .venv/bin/python tests/songcast_monitor.py --verbose
  
Configuration (.env):
  DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f
  DEVICE_2=172.24.32.210 4c494e4e-0026-0f22-646e-01560511013f
  DEVICE_3=172.24.32.212 4c494e4e-0026-0f22-3637-01475230013f
  SONGCAST_SENDER=DEVICE_1
  SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3
  
Notes:
  - Monitors Receiver service events for sender and all receivers
  - Displays real-time state changes (TransportState, Sender URI, Status)
  - Validates commands issued by songcast_group.py and other scripts
  - Press Ctrl+C to stop monitoring
        """
    )
    
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug output (connection details, raw LPEC)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging (all events, heartbeats)')
    parser.add_argument('--env', default='.env',
                       help='Path to .env configuration file (default: .env)')
    parser.add_argument('--test', metavar='JSON_FILE',
                       help='Run in test mode with assertions from JSON file')
    
    args = parser.parse_args()
    
    # Load test assertions if in test mode
    assertions = []
    test_mode = False
    if args.test:
        test_mode = True
        try:
            with open(args.test, 'r') as f:
                test_config = json.load(f)
                
            print("=" * 70)
            print(f"Test Mode: {test_config.get('name', 'Unnamed Test')}")
            print("=" * 70)
            if 'description' in test_config:
                print(f"Description: {test_config['description']}")
            print()
            
            # Parse assertions
            for assertion_def in test_config.get('assertions', []):
                assertion = StateAssertion(
                    device_id=assertion_def['device'],
                    variable=assertion_def['variable'],
                    expected_value=assertion_def['value'],
                    within_seconds=assertion_def.get('within_seconds', 10.0)
                )
                assertions.append(assertion)
                print(f"Assertion: {assertion.device_id}.{assertion.variable} = '{assertion.expected_value}' within {assertion.within_seconds}s")
            
            print()
        except Exception as e:
            print(f"✗ Error loading test file: {e}")
            sys.exit(1)
    else:
        print("=" * 70)
        print("Songcast Monitor - LPEC Event Listener")
        print("=" * 70)
        print()
    
    # Load configuration
    master, all_devices = load_env_config(args.env)
    
    if not all_devices:
        print("✗ No Songcast devices configured in .env")
        print("\nPlease configure SONGCAST_SENDER and SONGCAST_RECEIVERS in your .env file:")
        print("  SONGCAST_SENDER=DEVICE_1")
        print("  SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3")
        sys.exit(1)
        
    print(f"Configuration loaded from: {args.env}")
    if master:
        print(f"  Sender:   {master['id']} ({master['ip']})")
    receiver_count = len(all_devices) - (1 if master else 0)
    print(f"  Monitoring: {len(all_devices)} device(s) total")
    for m in all_devices:
        device_type = "sender" if master and m['id'] == master['id'] else "receiver"
        print(f"    - {m['id']} ({m['ip']}) [{device_type}]")
    print()
    
    # Create monitors for each device (sender + receivers)
    monitors = []
    for device in all_devices:
        # Filter assertions for this device
        device_assertions = [a for a in assertions if a.device_id == device['id']]
        
        mon = DeviceMonitor(
            device_id=device['id'],
            ip=device['ip'],
            udn=device['udn'],
            debug=args.debug,
            verbose=args.verbose,
            assertions=device_assertions
        )
        monitors.append(mon)
        
    # Start all monitors
    print("Starting monitors...")
    print("-" * 70)
    print()
    
    active_monitors = []
    for mon in monitors:
        if mon.start():
            active_monitors.append(mon)
        else:
            print(f"✗ Failed to start monitor for {mon.device_id}")
            
    if not active_monitors:
        print("\n✗ No monitors started successfully")
        sys.exit(1)
    
    # Start assertion timers if in test mode
    if test_mode and assertions:
        for assertion in assertions:
            assertion.start()
        print()
        print("⏱️  Assertion timers started")
        
    print()
    print(f"✓ Monitoring {len(active_monitors)} device(s)")
    if test_mode:
        print(f"  Test mode: {len(assertions)} assertion(s) active")
    print("  Press Ctrl+C to stop")
    print("=" * 70)
    print()
    
    # Keep main thread alive
    try:
        if test_mode:
            # In test mode, wait for all assertions to complete or timeout
            while assertions:
                time.sleep(0.5)
                # Check if all assertions are met or expired
                all_done = all(a.met or a.is_expired() for a in assertions)
                if all_done:
                    break
                # Check if any monitors have stopped
                if not any(m.running for m in active_monitors):
                    print("\n✗ All monitors have stopped")
                    break
            
            # Test complete - show results
            print("\n")
            print("=" * 70)
            print("Test Results")
            print("=" * 70)
            passed = 0
            failed = 0
            for assertion in assertions:
                status = assertion.status_string()
                print(f"{status} {assertion.device_id}.{assertion.variable} = '{assertion.expected_value}'")
                if assertion.met:
                    passed += 1
                else:
                    failed += 1
            
            print()
            print(f"Passed: {passed}/{len(assertions)}")
            print(f"Failed: {failed}/{len(assertions)}")
            
            exit_code = 0 if failed == 0 else 1
        else:
            # Normal monitoring mode
            while True:
                time.sleep(1)
                # Check if any monitors have stopped
                if not any(m.running for m in active_monitors):
                    print("\n✗ All monitors have stopped")
                    break
            
            exit_code = 0
    except KeyboardInterrupt:
        print("\n")
        print("=" * 70)
        print("Shutting down...")
        print("-" * 70)
        exit_code = 0
        
    # Stop all monitors
    for mon in active_monitors:
        mon.stop()
        
    print()
    print("✓ Shutdown complete")
    
    if test_mode:
        sys.exit(exit_code)
    

if __name__ == "__main__":
    main()
