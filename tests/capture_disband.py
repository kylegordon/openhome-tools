#!/usr/bin/env python3
"""
Songcast Disband Capture Tool

Monitors ALL Songcast-relevant LPEC events on every device in .env while you
manually disband a Songcast group using the Linn App. Captures the exact
sequence of state changes so we can replicate it programmatically.

Subscribes to: Ds/Product, Ds/Receiver, Ds/Sender, Ds/Playlist, Ds/Transport

Usage:
    .venv/bin/python tests/capture_disband.py [--debug]

Then disband the group using the Linn App. Press Ctrl+C when done.
The captured event log is saved to captures/disband_<timestamp>.json.
"""

import socket
import sys
import re
import time
import os
import threading
import json
from datetime import datetime
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# Services to subscribe to for full disband capture
SERVICES = [
    "Ds/Product",
    "Ds/Receiver",
    "Ds/Sender",
    "Ds/Playlist",
    "Ds/Transport",
]

# Variables of interest per service (for focused display; all are captured)
KEY_VARIABLES = {
    "TransportState", "Sender", "Status", "ProtocolInfo",
    "SourceIndex", "SourceType", "SourceName", "Standby",
    "Repeat", "Shuffle", "Id", "Uri", "Metadata",
}


class EventCapture:
    """Captures and stores all LPEC events from a device."""

    def __init__(self, device_id: str, ip: str, udn: str, debug: bool = False):
        self.device_id = device_id
        self.ip = ip
        self.udn = udn
        self.debug = debug
        self.sock = None
        self.running = False
        self.thread = None
        self.events: List[Dict] = []
        self.state: Dict[str, Dict[str, str]] = {}  # service -> {var: val}
        self._lock = threading.Lock()
        self._start_time = None

    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [{self.device_id}:{self.ip}] {level}: {msg}")

    def connect(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.ip, 23))

            # Drain ALIVE messages
            buf = ""
            t0 = time.time()
            while time.time() - t0 < 2:
                try:
                    chunk = self.sock.recv(4096).decode("utf-8", errors="ignore")
                    if not chunk:
                        break
                    buf += chunk
                    if "ALIVE Ds" in buf:
                        break
                except socket.timeout:
                    break

            if self.debug and buf.strip():
                for line in buf.strip().splitlines():
                    self.log(f"  << {line}", "ALIVE")

            # LPEC first-command workaround
            self.sock.sendall(b"\r\n")
            time.sleep(0.1)

            self.log("Connected")
            return True
        except Exception as e:
            self.log(f"Connection failed: {e}", "ERROR")
            return False

    def subscribe_all(self) -> bool:
        ok = True
        for svc in SERVICES:
            try:
                self.sock.sendall(f"SUBSCRIBE {svc}\r\n".encode("utf-8"))
                time.sleep(0.15)
                # Drain initial EVENT for this service
                try:
                    self.sock.settimeout(1.0)
                    chunk = self.sock.recv(8192).decode("utf-8", errors="ignore")
                    if chunk.strip():
                        self._process_raw(chunk, initial=True)
                except socket.timeout:
                    pass
                self.log(f"Subscribed to {svc}")
            except Exception as e:
                self.log(f"Subscribe {svc} failed: {e}", "ERROR")
                ok = False
        return ok

    def _process_raw(self, data: str, initial: bool = False):
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("EVENT"):
                self._process_event(line, initial=initial)
            elif self.debug:
                self.log(f"  << {line}", "RAW")

    def _process_event(self, line: str, initial: bool = False):
        m = re.match(r"^EVENT\s+(\d+)\s+(.+)$", line)
        if not m:
            return
        seq = int(m.group(1))
        rest = m.group(2)

        # Determine which service this event is from
        service = "unknown"
        for svc in SERVICES:
            svc_short = svc.split("/", 1)[1] if "/" in svc else svc
            if svc_short.lower() in rest[:40].lower():
                service = svc_short
                break

        # Extract all quoted variable-value pairs: VarName "value"
        pairs = re.findall(r'(\w+)\s+"([^"]*)"', rest)
        changes = {}
        for var, val in pairs:
            svc_key = service
            old = None
            with self._lock:
                if svc_key not in self.state:
                    self.state[svc_key] = {}
                old = self.state[svc_key].get(var)
                self.state[svc_key][var] = val

            if old != val or initial:
                changes[var] = {"old": old, "new": val}

        if not changes:
            return

        elapsed = time.time() - self._start_time if self._start_time else 0.0
        event_record = {
            "t": round(elapsed, 3),
            "ts": datetime.now().isoformat(),
            "device": self.device_id,
            "ip": self.ip,
            "seq": seq,
            "service": service,
            "initial": initial,
            "changes": {k: v for k, v in changes.items()},
        }

        with self._lock:
            self.events.append(event_record)

        # Display notable changes
        if not initial:
            for var, delta in changes.items():
                old_str = _short(delta["old"])
                new_str = _short(delta["new"])
                marker = "⚡" if var in KEY_VARIABLES else " "
                self.log(f"{marker} {service}.{var}: {old_str} → {new_str}", "EVENT")
        elif self.debug:
            summary = ", ".join(f"{v}={_short(c['new'])}" for v, c in changes.items() if v in KEY_VARIABLES)
            if summary:
                self.log(f"  Initial {service}: {summary}", "INIT")

    def listen(self):
        self.running = True
        self.sock.settimeout(30)
        buf = ""
        while self.running:
            try:
                chunk = self.sock.recv(4096).decode("utf-8", errors="ignore")
                if not chunk:
                    self.log("Connection closed by device", "WARN")
                    break
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line.startswith("EVENT"):
                        self._process_event(line)
                    elif line and self.debug:
                        self.log(f"  << {line}", "RAW")
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.log(f"Listen error: {e}", "ERROR")
                break
        self.running = False

    def start(self, start_time: float) -> bool:
        self._start_time = start_time
        if not self.connect():
            return False
        if not self.subscribe_all():
            self.close()
            return False
        self.thread = threading.Thread(target=self.listen, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.close()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def get_events(self) -> List[Dict]:
        with self._lock:
            return list(self.events)

    def get_final_state(self) -> Dict[str, Dict[str, str]]:
        with self._lock:
            return {svc: dict(vals) for svc, vals in self.state.items()}


def _short(val: Optional[str], maxlen: int = 60) -> str:
    if val is None:
        return "(none)"
    if not val:
        return "(empty)"
    if len(val) <= maxlen:
        return val
    if val.startswith("ohz://"):
        return "ohz://..."
    if val.startswith("ohSongcast://"):
        return "ohSongcast://..."
    return val[:maxlen] + "..."


def load_all_devices(env_path: str = ".env") -> List[Dict[str, str]]:
    devices = []
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", env_path)
    if not os.path.exists(path):
        path = env_path
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if "#" in line:
                line = line.split("#", 1)[0].strip()
            m = re.match(r"^(DEVICE_\d+)=(\S+)\s+(\S+)", line)
            if m:
                devices.append({"id": m.group(1), "ip": m.group(2), "udn": m.group(3)})
    return devices


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Capture LPEC events during a Songcast disband for analysis"
    )
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--env", default=".env")
    parser.add_argument(
        "--output-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "captures"),
    )
    args = parser.parse_args()

    devices = load_all_devices(args.env)
    if not devices:
        print("No devices found in .env")
        sys.exit(1)

    print("=" * 70)
    print("Songcast Disband Capture Tool")
    print("=" * 70)
    print()
    print(f"Devices: {len(devices)}")
    for d in devices:
        print(f"  {d['id']} ({d['ip']})")
    print()
    print(f"Subscribing to: {', '.join(SERVICES)}")
    print()

    start_time = time.time()
    captures: List[EventCapture] = []
    for d in devices:
        cap = EventCapture(d["id"], d["ip"], d["udn"], debug=args.debug)
        if cap.start(start_time):
            captures.append(cap)
        else:
            print(f"✗ Failed to connect to {d['id']} ({d['ip']})")

    if not captures:
        print("✗ No devices connected")
        sys.exit(1)

    print()
    print("-" * 70)
    print("✓ Capturing events on all devices.")
    print()
    print(">>> NOW DISBAND THE SONGCAST GROUP USING THE LINN APP <<<")
    print()
    print("Press Ctrl+C when done.")
    print("-" * 70)
    print()

    try:
        while True:
            time.sleep(1)
            if not any(c.running for c in captures):
                print("\nAll connections lost.")
                break
    except KeyboardInterrupt:
        print("\n")

    # Collect results
    print("=" * 70)
    print("Stopping captures...")
    all_events = []
    final_states = {}
    for cap in captures:
        cap.stop()
        evts = cap.get_events()
        all_events.extend(evts)
        final_states[cap.device_id] = cap.get_final_state()

    # Sort by timestamp
    all_events.sort(key=lambda e: e["t"])

    # Filter to non-initial events for the summary
    runtime_events = [e for e in all_events if not e.get("initial")]

    print()
    print(f"Captured {len(all_events)} total events ({len(runtime_events)} during disband)")
    print()

    # Print summary
    if runtime_events:
        print("=" * 70)
        print("Event Timeline (non-initial)")
        print("=" * 70)
        for evt in runtime_events:
            t = evt["t"]
            dev = evt["device"]
            svc = evt["service"]
            for var, delta in evt["changes"].items():
                old_s = _short(delta["old"], 40)
                new_s = _short(delta["new"], 40)
                print(f"  +{t:7.3f}s  {dev:10s}  {svc}.{var}: {old_s} → {new_s}")
        print()

    # Print final states
    print("=" * 70)
    print("Final Device States")
    print("=" * 70)
    for dev_id, svcs in sorted(final_states.items()):
        print(f"\n  {dev_id}:")
        for svc, vals in sorted(svcs.items()):
            interesting = {k: v for k, v in vals.items() if k in KEY_VARIABLES}
            if interesting:
                parts = ", ".join(f"{k}={_short(v, 30)}" for k, v in sorted(interesting.items()))
                print(f"    {svc}: {parts}")

    # Save to file
    os.makedirs(args.output_dir, exist_ok=True)
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(args.output_dir, f"disband_{ts_str}.json")
    output = {
        "captured_at": datetime.now().isoformat(),
        "devices": devices,
        "services_subscribed": SERVICES,
        "total_events": len(all_events),
        "runtime_events": len(runtime_events),
        "events": all_events,
        "final_states": final_states,
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nCapture saved to: {out_path}")

    # Also save a human-readable summary
    summary_path = os.path.join(args.output_dir, f"disband_{ts_str}_summary.txt")
    with open(summary_path, "w") as f:
        f.write(f"Songcast Disband Capture - {datetime.now().isoformat()}\n")
        f.write(f"Devices: {len(devices)}\n")
        for d in devices:
            f.write(f"  {d['id']} ({d['ip']})\n")
        f.write(f"\nEvents captured: {len(runtime_events)} (non-initial)\n\n")
        f.write("Timeline:\n")
        for evt in runtime_events:
            t = evt["t"]
            dev = evt["device"]
            svc = evt["service"]
            for var, delta in evt["changes"].items():
                f.write(f"  +{t:7.3f}s  {dev:10s}  {svc}.{var}: {delta['old']} → {delta['new']}\n")
        f.write(f"\nFinal States:\n")
        for dev_id, svcs in sorted(final_states.items()):
            f.write(f"\n  {dev_id}:\n")
            for svc, vals in sorted(svcs.items()):
                for k, v in sorted(vals.items()):
                    f.write(f"    {svc}.{k} = {v}\n")
    print(f"Summary saved to: {summary_path}")
    print()
    print("✓ Done. Use the captured data to update songcast_disband.py.")


if __name__ == "__main__":
    main()
