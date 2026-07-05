#!/usr/bin/env python3
"""
Capture utility for port 2323 on a Linn DSM device.

Connects to the specified device on port 2323 and dumps all received data
to stdout and optionally to a file, for protocol identification.

Usage:
    python3 capture_port_2323.py <IP_ADDRESS> [--output capture.txt] [--duration 30]
"""

import socket
import sys
import time
import argparse


def capture(ip: str, port: int = 2323, duration: float = 30.0, output_file: str = None):
    """Connect to device and capture all data received."""
    print(f"=== Port {port} Capture ===")
    print(f"Target: {ip}:{port}")
    print(f"Duration: {duration}s")
    print(f"Output file: {output_file or '(stdout only)'}")
    print("-" * 50)

    fh = None
    if output_file:
        fh = open(output_file, "w")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)

        print(f"Connecting to {ip}:{port}...")
        sock.connect((ip, port))
        print("Connected! Capturing data...\n")

        # Use a shorter recv timeout so we can display data as it arrives
        sock.settimeout(1.0)

        start = time.time()
        total_bytes = 0
        line_num = 0

        while time.time() - start < duration:
            try:
                data = sock.recv(4096)
                if not data:
                    print("\n[Connection closed by remote]")
                    break

                text = data.decode("utf-8", errors="replace")
                total_bytes += len(data)

                # Print each line with a line number for analysis
                for line in text.splitlines(keepends=True):
                    line_num += 1
                    display = f"[{line_num:4d}] {line}"
                    sys.stdout.write(display)
                    if fh:
                        fh.write(display)

            except socket.timeout:
                # No data within 1s, just continue waiting
                continue
            except KeyboardInterrupt:
                print("\n[Interrupted by user]")
                break

    except ConnectionRefusedError:
        print(f"ERROR: Connection refused on {ip}:{port}")
        sys.exit(1)
    except socket.timeout:
        print(f"ERROR: Connection timed out to {ip}:{port}")
        sys.exit(1)
    except OSError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        sock.close()
        if fh:
            fh.close()

    elapsed = time.time() - start
    print(f"\n{'=' * 50}")
    print(f"Capture complete: {total_bytes} bytes, {line_num} lines in {elapsed:.1f}s")

    # Now try to send some probe commands to see if the protocol is interactive
    print(f"\n=== Probing for interactive protocol ===")
    probe_commands = [
        b"\r\n",           # Empty line (many text protocols respond to this)
        b"HELP\r\n",      # Common command
        b"help\r\n",
        b"?\r\n",         # Common help shortcut
        b"VERSION\r\n",   # Common info command
        b"INFO\r\n",
    ]

    for cmd in probe_commands:
        try:
            sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock2.settimeout(3.0)
            sock2.connect((ip, port))

            # Consume initial data
            initial = b""
            try:
                while True:
                    chunk = sock2.recv(4096)
                    if not chunk:
                        break
                    initial += chunk
            except socket.timeout:
                pass

            # Send probe
            sock2.sendall(cmd)
            time.sleep(0.5)

            # Read response
            response = b""
            try:
                while True:
                    chunk = sock2.recv(4096)
                    if not chunk:
                        break
                    response += chunk
            except socket.timeout:
                pass

            sock2.close()

            cmd_display = cmd.decode().strip()
            if response:
                resp_text = response.decode("utf-8", errors="replace").strip()
                print(f"\nSent: {cmd_display!r}")
                print(f"Response ({len(response)} bytes):")
                for line in resp_text.splitlines()[:10]:
                    print(f"  {line}")
            else:
                print(f"\nSent: {cmd_display!r} -> No response")

        except (ConnectionRefusedError, socket.timeout, OSError):
            print(f"\nSent: {cmd.decode().strip()!r} -> Connection failed")
            break


def main():
    parser = argparse.ArgumentParser(description="Capture data from port 2323 on a Linn DSM device")
    parser.add_argument("ip", help="Device IP address")
    parser.add_argument("--port", type=int, default=2323, help="Port to connect to (default: 2323)")
    parser.add_argument("--output", "-o", help="Save capture to file")
    parser.add_argument("--duration", "-d", type=float, default=30.0,
                        help="Capture duration in seconds (default: 30)")
    args = parser.parse_args()

    capture(args.ip, args.port, args.duration, args.output)


if __name__ == "__main__":
    main()
