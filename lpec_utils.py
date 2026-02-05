#!/usr/bin/env python3
"""
LPEC Utility Functions

Shared functions for querying Linn DSM devices via LPEC (Linn Protocol for Eventing and Control).
Used by both songcast_monitor.py and songcast_group.py for real-time state verification.

LPEC Protocol:
- Port: 23 (telnet)
- Subscribe: "SUBSCRIBE Ds/<Service>\r\n"
- Response: "EVENT <seq> <service> <variable> "<value>" ..."

References:
- https://docs.linn.co.uk/wiki/index.php/Developer:LPEC
- https://docs.linn.co.uk/wiki/images/3/32/LPEC_V2-5.pdf
"""

import socket
import re
import time
from typing import Dict, Optional, Tuple


def query_receiver_state(ip: str, timeout: float = 3.0) -> Optional[Dict[str, str]]:
    """
    Query the current Receiver service state of a device via LPEC.
    
    Args:
        ip: Device IP address
        timeout: Connection and read timeout in seconds
        
    Returns:
        Dictionary with Receiver state variables (TransportState, Sender, Status, ProtocolInfo)
        or None if connection fails
        
    Example:
        state = query_receiver_state("172.24.32.210")
        if state and state.get('TransportState') == 'Playing':
            print("Device is playing")
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        # Connect to LPEC port
        sock.connect((ip, 23))
        
        # Read initial ALIVE messages
        buffer = ""
        start = time.time()
        while time.time() - start < 1.0:
            try:
                chunk = sock.recv(4096).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                buffer += chunk
                if 'ALIVE Ds' in buffer:
                    break
            except socket.timeout:
                break
        
        # Workaround for LPEC first-command bug
        try:
            sock.sendall("\r\n".encode('utf-8'))
            time.sleep(0.05)
        except Exception:
            pass
        
        # Subscribe to Ds/Receiver
        sock.sendall("SUBSCRIBE Ds/Receiver\r\n".encode('utf-8'))
        
        # Read initial EVENT 0 with current state
        buffer = ""
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = sock.recv(4096).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                buffer += chunk
                # Look for EVENT 0
                if re.search(r'^EVENT\s+0\s+', buffer, re.MULTILINE):
                    break
            except socket.timeout:
                break
        
        sock.close()
        
        # Parse state from EVENT 0
        state = {}
        for line in buffer.splitlines():
            line = line.strip()
            if not line.startswith("EVENT"):
                continue
            
            # Extract variables
            m = re.search(r'TransportState\s+"([^"]*)"', line)
            if m:
                state['TransportState'] = m.group(1)
            
            m = re.search(r'Sender\s+"([^"]*)"', line)
            if m:
                state['Sender'] = m.group(1)
            
            m = re.search(r'Status\s+"([^"]*)"', line)
            if m:
                state['Status'] = m.group(1)
            
            m = re.search(r'ProtocolInfo\s+"([^"]*)"', line)
            if m:
                state['ProtocolInfo'] = m.group(1)
        
        return state if state else None
        
    except socket.timeout:
        return None
    except ConnectionRefusedError:
        return None
    except Exception:
        return None


def wait_for_state(ip: str, expected_state: Dict[str, str], timeout: float = 10.0, poll_interval: float = 0.5) -> Tuple[bool, Optional[Dict[str, str]]]:
    """
    Poll device state until expected conditions are met or timeout.
    
    Args:
        ip: Device IP address
        expected_state: Dictionary of variable:value pairs to match (e.g., {'TransportState': 'Playing'})
        timeout: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds
        
    Returns:
        Tuple of (success: bool, final_state: dict or None)
        
    Example:
        success, state = wait_for_state(
            "172.24.32.210",
            {'TransportState': 'Playing', 'Status': 'Yes'},
            timeout=10.0
        )
        if success:
            print("Device reached expected state")
    """
    start = time.time()
    last_state = None
    
    while time.time() - start < timeout:
        state = query_receiver_state(ip, timeout=2.0)
        last_state = state
        
        if state:
            # Check if all expected conditions are met
            all_match = True
            for key, expected_value in expected_state.items():
                actual_value = state.get(key)
                if actual_value != expected_value:
                    all_match = False
                    break
            
            if all_match:
                return True, state
        
        time.sleep(poll_interval)
    
    # Timeout - return last known state
    return False, last_state


def check_transport_playing(ip: str, timeout: float = 3.0) -> bool:
    """
    Quick check if device TransportState is Playing or Buffering.
    
    Args:
        ip: Device IP address
        timeout: Query timeout in seconds
        
    Returns:
        True if device is Playing or Buffering, False otherwise
    """
    state = query_receiver_state(ip, timeout=timeout)
    if not state:
        return False
    
    transport = state.get('TransportState', '').lower()
    return transport in ('playing', 'buffering')


def check_sender_uri(ip: str, expected_scheme: str = 'ohz', timeout: float = 3.0) -> Tuple[bool, Optional[str]]:
    """
    Check if device's Sender URI matches expected scheme.
    
    Args:
        ip: Device IP address
        expected_scheme: Expected URI scheme ('ohz', 'ohSongcast', etc.)
        timeout: Query timeout in seconds
        
    Returns:
        Tuple of (matches: bool, actual_uri: str or None)
        
    Example:
        matches, uri = check_sender_uri("172.24.32.210", "ohz")
        if matches:
            print(f"Device using ohz protocol: {uri}")
    """
    state = query_receiver_state(ip, timeout=timeout)
    if not state:
        return False, None
    
    sender_uri = state.get('Sender', '')
    matches = sender_uri.startswith(f"{expected_scheme}://")
    
    return matches, sender_uri


def format_state_summary(state: Optional[Dict[str, str]]) -> str:
    """
    Format state dictionary into human-readable summary.
    
    Args:
        state: State dictionary from query_receiver_state()
        
    Returns:
        Formatted string summary
    """
    if not state:
        return "No state available"
    
    parts = []
    
    if 'TransportState' in state:
        parts.append(f"Transport={state['TransportState']}")
    
    if 'Sender' in state:
        sender = state['Sender']
        if sender.startswith('ohz://'):
            parts.append("Sender=ohz://...")
        elif sender.startswith('ohSongcast://'):
            parts.append("Sender=ohSongcast://...")
        elif sender:
            parts.append(f"Sender={sender[:30]}...")
        else:
            parts.append("Sender=(empty)")
    
    if 'Status' in state:
        parts.append(f"Status={state['Status']}")
    
    return ", ".join(parts) if parts else "No data"


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python3 lpec_utils.py <IP_ADDRESS>")
        print("\nQuick test of LPEC state query functions")
        sys.exit(1)
    
    ip = sys.argv[1]
    print(f"Querying Receiver state for {ip}...")
    
    state = query_receiver_state(ip)
    if state:
        print("\n✓ State retrieved:")
        print(f"  {format_state_summary(state)}")
        print("\nFull state:")
        for key, value in state.items():
            print(f"  {key}: {value}")
    else:
        print("\n✗ Failed to retrieve state")
        print("  Device may be offline or telnet disabled")
