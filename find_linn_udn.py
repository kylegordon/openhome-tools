#!/usr/bin/env python3
"""
Script to discover the UDN (Unique Device Name) and Product Name of a Linn DSM device
Usage: python3 find_linn_udn.py <IP_ADDRESS>

Uses LPEC (Linn Protocol for Eventing and Control) over the device's telnet port (23).
Docs: https://docs.linn.co.uk/wiki/index.php/Developer:LPEC
"""

import socket
import sys
import re
import time

def discover_linn_udn(ip_address, port=23, timeout=5):
    """
    Connect to a Linn DSM device via LPEC (telnet port 23) and extract:
      - UDN from the initial 'ALIVE Ds' message
      - ProductRoom and ProductName via SUBSCRIBE Ds/Product initial EVENT

    Returns a tuple: (udn or None, product_room or None, product_name or None)
    """
    try:
        # Create socket connection
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        print(f"Connecting to {ip_address}:{port}...")
        sock.connect((ip_address, port))

        # Read initial data - device sends one or more ALIVE messages on connect
        buffer = ""
        start = time.time()
        udn = None
        while time.time() - start < timeout:
            try:
                chunk = sock.recv(4096).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                buffer += chunk
                # Search for ALIVE Ds line(s)
                for line in buffer.splitlines():
                    # Example: ALIVE Ds 4c494e4e-...013f
                    m = re.search(r'^ALIVE\s+Ds\s+([A-Fa-f0-9\-]+)$', line.strip())
                    if m:
                        udn = m.group(1)
                # If we've seen ALIVE Ds, we can proceed
                if udn:
                    break
            except socket.timeout:
                break
        if buffer.strip():
            print(f"Received:\n{buffer.strip()}")

        if not udn:
            print("\n✗ No UDN found in ALIVE message(s)")
            print("Raw data received:")
            print(repr(buffer))
            # We will still attempt to subscribe for Product info below
        else:
            print(f"\n✓ Found UDN: {udn}")

        # Workaround for first-command LPEC bug: send blank line
        try:
            sock.sendall("\r\n".encode('utf-8'))
        except Exception:
            pass

        # Subscribe to Ds/Product to get ProductRoom / ProductName via initial EVENT
        product_room = None
        product_name = None
        try:
            cmd = "SUBSCRIBE Ds/Product\r\n".encode('utf-8')
            sock.sendall(cmd)

            buffer2 = ""
            start2 = time.time()
            while time.time() - start2 < timeout:
                try:
                    chunk = sock.recv(4096).decode('utf-8', errors='ignore')
                    if not chunk:
                        break
                    buffer2 += chunk
                    # Parse lines as they arrive
                    for line in buffer2.splitlines():
                        line_s = line.strip()
                        # Look for initial EVENT 0 with ProductName/ProductRoom
                        if line_s.startswith("EVENT "):
                            # Extract regardless of order
                            name_m = re.search(r'ProductName\s+"([^"]*)"', line_s)
                            room_m = re.search(r'ProductRoom\s+"([^"]*)"', line_s)
                            if name_m:
                                product_name = name_m.group(1)
                            if room_m:
                                product_room = room_m.group(1)
                            if product_name or product_room:
                                break
                    if product_name or product_room:
                        break
                except socket.timeout:
                    break
            if buffer2.strip():
                print(f"LPEC Subscribe Response:\n{buffer2.strip()}")
        except Exception as e:
            print(f"✗ Error subscribing to Ds/Product: {e}")

        return udn, product_room, product_name

    except socket.timeout:
        print(f"✗ Timeout connecting to {ip_address}:{port}")
        return None, None, None
    except ConnectionRefusedError:
        print(f"✗ Connection refused to {ip_address}:{port}")
        print("  Device may not have telnet enabled or may be offline")
        return None, None, None
    except Exception as e:
        print(f"✗ Error connecting to {ip_address}: {e}")
        return None, None, None
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

    udn, product_room, product_name = discover_linn_udn(ip_address)

    if udn or (product_room or product_name):
        print(f"\n=== Results ===")
        print(f"IP Address: {ip_address}")
        if udn:
            print(f"UDN:        {udn}")
        if product_room is not None:
            print(f"Room:       {product_room}")
        if product_name is not None:
            print(f"Name:       {product_name}")
        if product_room or product_name:
            display = None
            if product_room and product_name:
                display = f"{product_room}: {product_name}"
            elif product_name:
                display = product_name
            elif product_room:
                display = product_room
            if display:
                print(f"Display:    {display}")
        print(f"\nUse this in your scripts:")
        print(f"devIp   = '{ip_address}'")
        if udn:
            print(f"devUdn  = '{udn}'")
        if product_room is not None:
            print(f"devRoom = '{product_room}'")
        if product_name is not None:
            print(f"devName = '{product_name}'")
    else:
        print(f"\n✗ Failed to discover UDN for {ip_address}")
        print("\nTroubleshooting:")
        print("- Ensure the device is powered on and connected to network")
        print("- Check if the IP address is correct")
        print("- Verify the device has telnet enabled")
        print("- Try connecting manually: telnet <IP_ADDRESS>")

if __name__ == "__main__":
    main()