#!/usr/bin/env python3
"""
Script to discover the UDN (Unique Device Name) of a Linn DSM device
Usage: python3 find_linn_udn.py <IP_ADDRESS>

The protocol used on the telnet port is called LPEC (Linn Protocol for Eventing and Control)
and is documented here: https://docs.linn.co.uk/wiki/index.php/Developer:LPEC
"""

import socket
import sys
import time
import re

def discover_linn_udn(ip_address, port=23, timeout=5):
    """
    Connect to a Linn DSM device via telnet and extract the UDN
    from the 'ALIVE Ds' message
    """
    try:
        # Create socket connection
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        print(f"Connecting to {ip_address}:{port}...")
        sock.connect((ip_address, port))
        
        # Read initial data - Linn devices typically send ALIVE message on connect
        data = sock.recv(1024).decode('utf-8', errors='ignore')
        
        print(f"Received: {data.strip()}")
        
        # Look for UDN pattern in ALIVE message
        # Pattern: "ALIVE Ds <UDN>"
        udn_match = re.search(r'ALIVE\s+Ds\s+([a-f0-9\-]+)', data, re.IGNORECASE)
        
        if udn_match:
            udn = udn_match.group(1)
            print(f"\n✓ Found UDN: {udn}")
            return udn
        else:
            print("\n✗ No UDN found in ALIVE message")
            print("Raw data received:")
            print(repr(data))
            return None
            
    except socket.timeout:
        print(f"✗ Timeout connecting to {ip_address}:{port}")
        return None
    except ConnectionRefused:
        print(f"✗ Connection refused to {ip_address}:{port}")
        print("  Device may not have telnet enabled or may be offline")
        return None
    except Exception as e:
        print(f"✗ Error connecting to {ip_address}: {e}")
        return None
    finally:
        try:
            sock.close()
        except:
            pass

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 find_linn_udn.py <IP_ADDRESS>")
        print("\nExample: python3 find_linn_udn.py 192.168.78.12")
        sys.exit(1)
    
    ip_address = sys.argv[1]
    
    # Validate IP address format (basic check)
    parts = ip_address.split('.')
    if len(parts) != 4 or not all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
        print(f"✗ Invalid IP address format: {ip_address}")
        sys.exit(1)
    
    print(f"=== Linn DSM UDN Discovery ===")
    print(f"Target IP: {ip_address}")
    print("-" * 30)
    
    udn = discover_linn_udn(ip_address)
    
    if udn:
        print(f"\n=== Results ===")
        print(f"IP Address: {ip_address}")
        print(f"UDN:        {udn}")
        print(f"\nUse this in your scripts:")
        print(f"devIp  = '{ip_address}'")
        print(f"devUdn = '{udn}'")
    else:
        print(f"\n✗ Failed to discover UDN for {ip_address}")
        print("\nTroubleshooting:")
        print("- Ensure the device is powered on and connected to network")
        print("- Check if the IP address is correct")
        print("- Verify the device has telnet enabled")
        print("- Try connecting manually: telnet <IP_ADDRESS>")

if __name__ == "__main__":
    main()