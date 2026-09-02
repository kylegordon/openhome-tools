#!/usr/bin/env python3
"""
LPEC Utility Functions

Shared functions for querying Linn DSM devices via LPEC (Linn Protocol for Eventing and Control).
Used by both songcast_monitor.py and songcast_group.py for real-time state verification.

LPEC Protocol (verified against Linn DSM firmware, not inferred):
- Port: 23 (telnet)
- Subscribe: "SUBSCRIBE Ds/<Service>\r\n"  ->  "SUBSCRIBE <subscription-id>"
- Event:     "EVENT <subscription-id> <seq> <variable> "<value>" ..."

Note the service name does NOT appear on an event line; it is only implied by
the subscription id returned from SUBSCRIBE. The subscription id is a per-device
counter and is not 0.

References:
- https://docs.linn.co.uk/wiki/index.php/Developer:LPEC
- https://docs.linn.co.uk/wiki/images/3/32/LPEC_V2-5.pdf
"""

import socket
import re
import time
from typing import Dict, Optional, Tuple

# --- Handling device-supplied text --------------------------------------------
#
# Everything read back over LPEC or SOAP is remote input: whatever some box on
# the network chose to say about itself. Bound it before it influences a
# decision, and sanitise it before printing it. Shared by lpec_utils itself,
# songcast_disband.py and tests/songcast_monitor.py.

MAX_FIELD_CHARS = 128  # longest device string used in matching
DISPLAY_CHARS = 48  # longest device string echoed to the terminal

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


# --- LPEC wire format --------------------------------------------------------
#
# Captured live from Linn DSM firmware (port 23):
#
#   ALIVE Ds 4c494e4e-...
#   SUBSCRIBE 82
#   EVENT 82 0 Uri "" Metadata "" TransportState "Stopped" ProtocolInfo "ohz:*:*:*,..."
#
# So an event line is:  EVENT <subscription-id> <seq> <var> "<value>" ...
# The subscription id is a per-device counter, NOT 0, and the service name never
# appears on the wire — it is only implied by the SUBSCRIBE reply.
#
# Ds/Receiver publishes exactly these four variables. There is no "Sender" and
# no "Status" variable: the receiver's bound sender is reported as **Uri**.
# (Status/Status2 belong to Ds/Sender, on the sending device.)
RECEIVER_EVENT_VARIABLES = ("Uri", "Metadata", "TransportState", "ProtocolInfo")

EVENT_LINE_RE = re.compile(r'^EVENT\s+\d+\s+\d+\s', re.MULTILINE)


def parse_event_variables(buffer: str) -> Dict[str, str]:
    """Extract `Name "value"` pairs from any EVENT lines in *buffer*.

    Each name is matched at a token boundary. An unanchored search would let a
    longer variable satisfy a shorter name — `SenderStatus "x"` would be
    harvested as `Status`, and a name appearing inside another variable's
    quoted value (Metadata carries whole DIDL documents) would be picked up too.
    """
    state: Dict[str, str] = {}
    for line in buffer.splitlines():
        line = line.strip()
        if not line.startswith("EVENT"):
            continue
        for var in RECEIVER_EVENT_VARIABLES:
            m = re.search(r'(?:^|\s)' + var + r'\s+"([^"]*)"', line)
            if m:
                state[var] = m.group(1)
    return state


def bounded(value: Optional[str], limit: int = MAX_FIELD_CHARS) -> str:
    """Cap a device-supplied string before it is compared or substring-matched."""
    return (value or "")[:limit]


def safe_for_display(value, limit: int = DISPLAY_CHARS) -> str:
    """Make a device-supplied string safe to print.

    Device names, source names and transport states are echoed to the terminal,
    so a device returning ANSI escapes could reposition the cursor or overwrite
    lines — enough to make a failed run read as a successful one in a log
    someone later pastes into an issue. Strip control characters, collapse
    whitespace, truncate. Display only: comparisons use the raw value.
    """
    if value is None:
        return ""
    s = _CONTROL_CHARS.sub("", str(value))
    s = " ".join(s.split())
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return s


def query_receiver_state(ip: str, timeout: float = 3.0) -> Optional[Dict[str, str]]:
    """
    Query the current Receiver service state of a device via LPEC.
    
    Args:
        ip: Device IP address
        timeout: Connection and read timeout in seconds
        
    Returns:
        Dictionary with Receiver state variables (Uri, Metadata, TransportState,
        ProtocolInfo) or None if connection fails. "Uri" is the sender the
        receiver is bound to — Ds/Receiver publishes no "Sender" or "Status"
        variable.
        
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
        
        # Read the initial EVENT carrying current state.
        buffer = ""
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = sock.recv(4096).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                buffer += chunk
                if EVENT_LINE_RE.search(buffer):
                    break
            except socket.timeout:
                break

        sock.close()

        state = parse_event_variables(buffer)
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
    Check whether the receiver's bound sender URI matches the expected scheme.

    The URI is published by Ds/Receiver as the **Uri** variable. This used to
    read a "Sender" variable, which the firmware never emits, so the function
    returned (False, '') no matter what the device was bound to.
    
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
    
    sender_uri = state.get('Uri', '')
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
        parts.append(f"Transport={safe_for_display(state['TransportState'])}")

    if 'Uri' in state:
        sender = state['Uri']
        if sender.startswith('ohz://'):
            parts.append("Sender=ohz://...")
        elif sender.startswith('ohSongcast://'):
            parts.append("Sender=ohSongcast://...")
        elif sender:
            parts.append(f"Sender={safe_for_display(sender, 30)}...")
        else:
            parts.append("Sender=(empty)")

    if 'Status' in state:
        parts.append(f"Status={safe_for_display(state['Status'])}")
    
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
            print(f"  {key}: {safe_for_display(value, 120)}")
    else:
        print("\n✗ Failed to retrieve state")
        print("  Device may be offline or telnet disabled")
