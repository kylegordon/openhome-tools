#!/usr/bin/env python3
"""
Linn OpenHome Songcast Group Disbander

Purpose:
- Find the Songcast sender among all devices in .env
- Stop playback on the sender
- Disconnect all receivers from the Songcast group
- Return every device to standalone mode

Usage:
    .venv/bin/python songcast_disband.py [--debug]

Configuration (.env):
    DEVICE_1=<IP>             (UDN auto-discovered via LPEC)
    DEVICE_2=<IP>
    DEVICE_3=<IP> <UDN>       (explicit UDN also accepted)

Notes:
- Device UDNs are discovered automatically via LPEC (port 23) if not
  provided in .env. Sender/receiver roles are always auto-detected by
  querying each device's Songcast state.
- Uses Receiver.Stop via SOAP to disconnect receivers.
- Uses Playlist.Stop via SOAP to stop sender playback.
- No .env sender/receiver role configuration needed; all devices are probed.
"""

import sys
import os
import re
import socket
import time
import argparse
import requests
import xml.etree.ElementTree as ET

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

DEVICE_LINE_RE = re.compile(r"^DEVICE_\d+=(\S+)(?:\s+(\S+))?")


def discover_udn(ip, port=23, timeout=3):
    """Discover the UDN of a Linn DSM device via LPEC (telnet port 23).

    Connects to the device and reads the initial ALIVE Ds message to extract the UDN.
    Returns the UDN string or None on failure.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        buffer = ""
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = sock.recv(4096).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                buffer += chunk
                for line in buffer.splitlines():
                    m = re.search(r'^ALIVE\s+Ds\s+([A-Fa-f0-9\-]+)$', line.strip())
                    if m:
                        sock.close()
                        return m.group(1)
            except socket.timeout:
                break
        sock.close()
    except Exception:
        pass
    return None


def load_devices(env_path=None, debug=False):
    """Load device IPs from the .env file and discover UDNs from the devices.

    The .env file can contain either:
        DEVICE_N=<IP> <UDN>   (UDN used directly)
        DEVICE_N=<IP>         (UDN discovered via LPEC)
    """
    path = env_path or ENV_PATH
    devices = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if '#' in line:
                line = line.split('#', 1)[0].strip()
            m = DEVICE_LINE_RE.match(line)
            if m:
                ip = m.group(1)
                udn = m.group(2)  # May be None if not provided
                if not udn:
                    if debug:
                        print(f"  [debug] Discovering UDN for {ip} via LPEC...")
                    udn = discover_udn(ip)
                    if udn:
                        if debug:
                            print(f"  [debug] {ip} -> UDN: {udn}")
                    else:
                        print(f"  ✗ Failed to discover UDN for {ip} (is device online?)")
                        continue
                devices.append({"ip": ip, "udn": udn})
    return devices


def _soap_request(ip, udn, service_path, service_urn, action, timeout=5):
    """Send a SOAP request and return the response text, or None on failure."""
    return _soap_request_with_params(ip, udn, service_path, service_urn, action, {}, timeout)


def _soap_request_with_params(ip, udn, service_path, service_urn, action, params=None, timeout=5):
    """Send a SOAP request with optional parameters."""
    url = f"http://{ip}:55178/{udn}/{service_path}/control"
    headers = {
        "SOAPACTION": f'"{service_urn}#{action}"',
        "Content-Type": 'text/xml; charset="utf-8"',
    }
    if params:
        param_xml = "".join(f"<{k}>{v}</{k}>" for k, v in params.items())
        action_xml = f'<u:{action} xmlns:u="{service_urn}">{param_xml}</u:{action}>'
    else:
        action_xml = f'<u:{action} xmlns:u="{service_urn}"/>'
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"'
        ' xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        '<s:Body>'
        f'{action_xml}'
        '</s:Body>'
        '</s:Envelope>'
    )
    resp = requests.post(url, headers=headers, data=body, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def get_device_name(ip, udn, timeout=3):
    """Fetch the friendly name from device.xml."""
    try:
        url = f"http://{ip}:55178/{udn}/Upnp/device.xml"
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        # Handle namespaced and non-namespaced device.xml
        for ns in ["{urn:schemas-upnp-org:device-1-0}", ""]:
            el = root.find(f".//{ns}friendlyName")
            if el is not None and el.text:
                return el.text.strip()
    except Exception:
        pass
    return ip


def get_receiver_transport_state(ip, udn, debug=False):
    """Query Receiver.TransportState via SOAP. Returns state string or None."""
    try:
        text = _soap_request(
            ip, udn,
            "av.openhome.org-Receiver-1",
            "urn:av-openhome-org:service:Receiver:1",
            "TransportState",
        )
        # Parse <Value>...</Value> from response
        m = re.search(r"<Value>([^<]+)</Value>", text, re.IGNORECASE)
        if not m:
            m = re.search(r"<TransportState>([^<]+)</TransportState>", text, re.IGNORECASE)
        state = m.group(1).strip() if m else None
        if debug:
            print(f"  [debug] {ip} Receiver.TransportState = {state}")
        return state
    except Exception as e:
        if debug:
            print(f"  [debug] {ip} Receiver.TransportState query failed: {e}")
        return None


def get_receiver_sender_uri(ip, udn, debug=False):
    """Query Receiver.Sender via SOAP. Returns the sender URI or None."""
    try:
        text = _soap_request(
            ip, udn,
            "av.openhome.org-Receiver-1",
            "urn:av-openhome-org:service:Receiver:1",
            "Sender",
        )
        m = re.search(r"<Uri>([^<]*)</Uri>", text, re.IGNORECASE)
        uri = m.group(1).strip() if m else None
        if debug:
            print(f"  [debug] {ip} Receiver.Sender Uri = {uri}")
        return uri
    except Exception as e:
        if debug:
            print(f"  [debug] {ip} Receiver.Sender query failed: {e}")
        return None


def is_receiver_active(ip, udn, debug=False):
    """Check if a device is actively receiving Songcast audio."""
    state = get_receiver_transport_state(ip, udn, debug)
    if state and state.lower() in ("playing", "buffering", "connecting"):
        return True
    # Also check if a sender URI is set (ohz:// or ohSongcast://)
    uri = get_receiver_sender_uri(ip, udn, debug)
    if uri and uri.strip():
        scheme = uri.split("://")[0].lower() if "://" in uri else ""
        if scheme in ("ohz", "ohsongcast"):
            return True
    return False


def clear_receiver_sender(ip, udn, debug=False):
    """Clear the Receiver's sender URI via SetSender(Uri="", Metadata="")."""
    try:
        _soap_request_with_params(
            ip, udn,
            "av.openhome.org-Receiver-1",
            "urn:av-openhome-org:service:Receiver:1",
            "SetSender",
            {"Uri": "", "Metadata": ""},
        )
        if debug:
            print(f"  [debug] {ip} Receiver.SetSender(empty) sent")
        return True
    except Exception as e:
        if debug:
            print(f"  [debug] {ip} Receiver.SetSender(empty) failed: {e}")
        return False


def stop_receiver(ip, udn, debug=False):
    """Stop the Receiver service via SOAP."""
    try:
        _soap_request(
            ip, udn,
            "av.openhome.org-Receiver-1",
            "urn:av-openhome-org:service:Receiver:1",
            "Stop",
        )
        if debug:
            print(f"  [debug] {ip} Receiver.Stop sent")
        return True
    except Exception as e:
        if debug:
            print(f"  [debug] {ip} Receiver.Stop failed: {e}")
        return False


def set_source_index(ip, udn, index, debug=False):
    """Set the device source via Product.SetSourceIndex."""
    try:
        _soap_request_with_params(
            ip, udn,
            "av.openhome.org-Product-4",
            "urn:av-openhome-org:service:Product:4",
            "SetSourceIndex",
            {"Value": str(index)},
        )
        if debug:
            print(f"  [debug] {ip} Product.SetSourceIndex({index}) sent")
        return True
    except Exception as e:
        if debug:
            print(f"  [debug] {ip} Product.SetSourceIndex({index}) failed: {e}")
        return False


def stop_playlist(ip, udn, debug=False):
    """Stop the Playlist service via SOAP (stops sender playback)."""
    try:
        _soap_request(
            ip, udn,
            "av.openhome.org-Playlist-1",
            "urn:av-openhome-org:service:Playlist:1",
            "Stop",
        )
        if debug:
            print(f"  [debug] {ip} Playlist.Stop sent")
        return True
    except Exception as e:
        if debug:
            print(f"  [debug] {ip} Playlist.Stop failed: {e}")
        return False


def get_current_source(ip, udn, debug=False):
    """Get the current source type/name via Product service."""
    try:
        # Get current source index
        text = _soap_request(
            ip, udn,
            "av.openhome.org-Product-4",
            "urn:av-openhome-org:service:Product:4",
            "SourceIndex",
        )
        m = re.search(r"<Value>(\d+)</Value>", text, re.IGNORECASE)
        if not m:
            return None
        idx = int(m.group(1))

        # Get source details for that index
        url = f"http://{ip}:55178/{udn}/av.openhome.org-Product-4/control"
        headers = {
            "SOAPACTION": '"urn:av-openhome-org:service:Product:4#Source"',
            "Content-Type": 'text/xml; charset="utf-8"',
        }
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"'
            ' xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            '<s:Body>'
            '<u:Source xmlns:u="urn:av-openhome-org:service:Product:4">'
            f'<Index>{idx}</Index>'
            '</u:Source>'
            '</s:Body>'
            '</s:Envelope>'
        )
        resp = requests.post(url, headers=headers, data=body, timeout=5)
        resp.raise_for_status()

        m_type = re.search(r"<Type>([^<]*)</Type>", resp.text, re.IGNORECASE)
        m_name = re.search(r"<Name>([^<]*)</Name>", resp.text, re.IGNORECASE)
        source_type = m_type.group(1).strip() if m_type else ""
        source_name = m_name.group(1).strip() if m_name else ""
        if debug:
            print(f"  [debug] {ip} current source: idx={idx} type={source_type} name={source_name}")
        return {"index": idx, "type": source_type, "name": source_name}
    except Exception as e:
        if debug:
            print(f"  [debug] {ip} get_current_source failed: {e}")
        return None


def classify_devices(devices, debug=False):
    """Classify each device as 'receiver', 'sender', or 'standalone'.

    Returns a list of dicts with keys: ip, udn, name, role, source.
    """
    results = []
    for dev in devices:
        ip, udn = dev["ip"], dev["udn"]
        name = get_device_name(ip, udn)
        source = get_current_source(ip, udn, debug)
        role = "standalone"

        if source:
            src_type = source["type"].lower()
            src_name = source["name"].lower()
            if "receiver" in src_type or "songcast" in src_name:
                # On Songcast source - check if actively receiving
                if is_receiver_active(ip, udn, debug):
                    role = "receiver"
                else:
                    role = "receiver-idle"
            elif "sender" in src_type:
                role = "sender"

        # If not identified as receiver by source, check if this device has
        # an active Sender service (it's the sender/leader)
        if role == "standalone":
            try:
                text = _soap_request(
                    ip, udn,
                    "av.openhome.org-Sender-1",
                    "urn:av-openhome-org:service:Sender:1",
                    "Status",
                )
                m = re.search(r"<Value>([^<]+)</Value>", text, re.IGNORECASE)
                status = m.group(1).strip().lower() if m else ""
                if debug:
                    print(f"  [debug] {ip} Sender.Status = {status}")
                if status == "enabled":
                    role = "sender"
            except Exception as e:
                if debug:
                    print(f"  [debug] {ip} Sender.Status query failed: {e}")

        results.append({
            "ip": ip,
            "udn": udn,
            "name": name,
            "role": role,
            "source": source,
        })
    return results


def disband_group(devices, debug=False):
    """Disband the Songcast group: stop receivers first, then stop the sender.

    Returns True if all operations succeeded.
    """
    classified = classify_devices(devices, debug)

    receivers = [d for d in classified if d["role"] in ("receiver", "receiver-idle")]
    senders = [d for d in classified if d["role"] == "sender"]
    standalone = [d for d in classified if d["role"] == "standalone"]

    print("=== Linn OpenHome Songcast Group Disbander ===")
    print(f"Devices found: {len(classified)}")
    for d in classified:
        print(f"  {d['name']} ({d['ip']}): {d['role']}")
    print("-" * 50)

    if not receivers and not senders:
        print("No active Songcast group found. All devices are standalone.")
        return True

    all_ok = True

    # Step 1: Clear sender URI on all receivers and stop them
    if receivers:
        print(f"\n1. Disconnecting {len(receivers)} receiver(s) from Songcast group...")
        for d in receivers:
            print(f"  {d['name']} ({d['ip']})...")
            # Clear the sender URI first
            clear_receiver_sender(d["ip"], d["udn"], debug)
            # Then stop the receiver
            stop_receiver(d["ip"], d["udn"], debug)
            print(f"  ✓ {d['name']} receiver cleared and stopped")
    else:
        print("\n1. No receivers to disconnect.")

    # Step 2: Switch receivers from Songcast source to Playlist (source 0)
    if receivers:
        print(f"\n2. Switching {len(receivers)} receiver(s) to standalone source...")
        for d in receivers:
            src = d.get("source")
            if src and src["index"] != 0:
                ok = set_source_index(d["ip"], d["udn"], 0, debug)
                if ok:
                    print(f"  ✓ {d['name']} switched from {src['name']} (idx {src['index']}) to Playlist (idx 0)")
                else:
                    print(f"  ✗ Failed to switch {d['name']} source")
                    all_ok = False
            else:
                print(f"  ✓ {d['name']} already on source index 0")
    else:
        print("\n2. No receivers to switch.")

    # Step 3: Stop sender playback
    if senders:
        print(f"\n3. Stopping playback on sender(s)...")
        for d in senders:
            print(f"  Stopping {d['name']} ({d['ip']})...")
            ok = stop_playlist(d["ip"], d["udn"], debug)
            if ok:
                print(f"  ✓ {d['name']} playback stopped")
            else:
                print(f"  ✗ Failed to stop playback on {d['name']}")
                all_ok = False
    else:
        print("\n3. No sender found to stop.")

    # Step 4: Verify all devices are now standalone
    print("\n4. Verifying devices are standalone...")
    for d in classified:
        if d["role"] in ("receiver", "receiver-idle"):
            source = get_current_source(d["ip"], d["udn"], debug)
            uri = get_receiver_sender_uri(d["ip"], d["udn"], debug)
            src_ok = source and source["type"].lower() != "receiver"
            uri_ok = not uri or not uri.strip()
            if src_ok and uri_ok:
                print(f"  ✓ {d['name']}: standalone (source={source['name']}, no sender URI)")
            elif src_ok:
                print(f"  ✓ {d['name']}: source={source['name']} (sender URI still set but source changed)")
            else:
                print(f"  ⚠ {d['name']}: still on Songcast source")
                all_ok = False
        elif d["role"] == "standalone":
            print(f"  ✓ {d['name']}: already standalone")
        elif d["role"] == "sender":
            print(f"  ✓ {d['name']}: sender (playback stopped)")

    print("\n" + "=" * 50)
    if all_ok:
        print("✓ SUCCESS: All devices returned to standalone mode")
    else:
        print("⚠ Some operations did not complete successfully")
    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="Disband Linn OpenHome Songcast group and return all devices to standalone mode"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument(
        "--env", default=None, help="Path to .env file (default: .env next to script)"
    )
    args = parser.parse_args()

    env_path = args.env or ENV_PATH
    if not os.path.exists(env_path):
        print(f"✗ .env file not found at {env_path}")
        sys.exit(1)

    devices = load_devices(env_path, debug=args.debug)
    if not devices:
        print("✗ No devices found in .env (check IPs and device connectivity)")
        sys.exit(1)

    print(f"Loaded {len(devices)} device(s) from {env_path}")
    success = disband_group(devices, debug=args.debug)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
