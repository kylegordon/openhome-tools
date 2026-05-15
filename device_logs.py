#!/usr/bin/env python3
"""
Linn DSM Firmware Diagnostic Log Capture & Analysis Tool

Connects to port 2323 on Linn DSM devices and captures the firmware debug log
stream. Supports multi-device concurrent capture, real-time log categorization,
and post-capture analysis reports.

Port 2323 is a read-only firmware debug stream that emits internal C++ media
pipeline diagnostics: HLS segment fetches, container recognition, playback
timing, and error conditions.

Captured output is saved as per-device timestamped files suitable for attachment
to AI prompts for development and debugging assistance.

Usage:
    .venv/bin/python device_logs.py                          # All .env devices, 60s
    .venv/bin/python device_logs.py 172.24.32.211            # Single device
    .venv/bin/python device_logs.py --duration 120           # Custom duration
    .venv/bin/python device_logs.py --around-command ".venv/bin/python now_playing.py"
    .venv/bin/python device_logs.py --background             # Daemonize, write PID file
    .venv/bin/python device_logs.py --stop                   # Stop background capture

Output:
    captures/DEVICE_1_20260515_143022.log           # Raw timestamped capture
    captures/DEVICE_1_20260515_143022_analysis.txt  # Summary report
"""

import socket
import sys
import os
import re
import time
import json
import signal
import threading
import subprocess
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple


# --- Configuration Loading (reused pattern from now_playing.py) ---

def _load_env(path: str) -> Dict[str, str]:
    env: Dict[str, str] = {}
    with open(path, "r") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, val = line.partition("=")
            if not sep:
                continue
            key = key.strip()
            val = val.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            env[key] = val
    return env


def load_devices_from_env(env_path: Optional[str] = None) -> List[Dict[str, str]]:
    """Load device definitions from .env file."""
    default_path = str(Path(__file__).parent / ".env")
    path = env_path or os.environ.get("LINN_ENV_PATH") or default_path
    env = _load_env(path)
    devices: List[Dict[str, str]] = []

    kv_pairs = [(k, v) for k, v in env.items() if k == "DEVICE" or k.startswith("DEVICE_")]
    if kv_pairs:
        for key, v in sorted(kv_pairs, key=lambda kv: kv[0]):
            line = v.strip()
            if not line:
                continue
            parts = re.split(r"[\s,;]+", line)
            if len(parts) >= 2:
                ip, udn = parts[0], parts[1]
                if ip and udn:
                    device_id = key  # e.g. DEVICE_1
                    devices.append({"id": device_id, "ip": ip, "udn": udn})

    if not devices:
        payload = env.get("DEVICES_JSON") or env.get("DEVICES")
        if payload:
            data = json.loads(payload)
            if isinstance(data, list):
                for i, item in enumerate(data, 1):
                    if isinstance(item, dict):
                        ip = item.get("ip")
                        udn = item.get("udn")
                        if ip and udn:
                            devices.append({"id": f"DEVICE_{i}", "ip": ip, "udn": udn})

    return devices


# --- Log Line Parsing & Categorization ---

# Subsystem patterns derived from observed firmware debug output
SUBSYSTEM_PATTERNS = [
    ("HLS", re.compile(r"(Hls|HlsPlaylistParser|HlsM3uReader|HlsReloadTimer|PlaylistProvider)")),
    ("HTTP", re.compile(r"UriLoader::")),
    ("PIPELINE", re.compile(r"Pipeline report property")),
    ("CONTAINER", re.compile(r"(Id3v2|Mpeg4Container|MpegTs|SegmentStreamer)")),
    ("SONGCAST", re.compile(r"(Songcast|OhmReceiver|Ohm|Ohz|Sender|Receiver)")),
    ("CODEC", re.compile(r"(Codec|Decoder|Flac|Alac|Pcm|Dsd|Vorbis|Aac|Mp3)")),
    ("VOLUME", re.compile(r"(Volume|Mute)")),
    ("TRANSPORT", re.compile(r"(Transport|Track|Seek|Pause|Play|Stop)")),
]

# Error detection patterns
ERROR_PATTERNS = re.compile(
    r"(error|exception|fail|timeout|refused|disconnect|abort|panic|assert)",
    re.IGNORECASE
)

# HTTP status code extraction
HTTP_STATUS_RE = re.compile(r"(?:code|status)[:\s]+(\d{3})")
HTTP_URI_RE = re.compile(r"aUri:\s+(\S+)")


def classify_line(line: str) -> str:
    """Classify a log line into a subsystem category."""
    # Check for errors first (highest priority)
    if ERROR_PATTERNS.search(line):
        # But not if it's a normal "no more segments" type message
        if "HlsNoMoreSegments" in line:
            return "HLS"
        return "ERROR"

    for subsystem, pattern in SUBSYSTEM_PATTERNS:
        if pattern.search(line):
            return subsystem

    return "OTHER"


def extract_http_status(line: str) -> Optional[int]:
    """Extract HTTP status code from a UriLoader line."""
    m = HTTP_STATUS_RE.search(line)
    if m:
        return int(m.group(1))
    return None


def extract_uri(line: str) -> Optional[str]:
    """Extract a stream URI from a UriLoader line."""
    m = HTTP_URI_RE.search(line)
    if m:
        return m.group(1)
    return None


# --- Per-Device Capture Thread ---

class DeviceLogCapture:
    """Captures firmware debug log stream from a single device on port 2323."""

    def __init__(self, device_id: str, ip: str, udn: str, port: int = 2323,
                 captures_dir: str = "captures", max_lines: int = 5000,
                 debug: bool = False, filter_subsystems: Optional[List[str]] = None):
        self.device_id = device_id
        self.ip = ip
        self.udn = udn
        self.port = port
        self.captures_dir = captures_dir
        self.max_lines = max_lines
        self.debug = debug
        self.filter_subsystems = [s.upper() for s in filter_subsystems] if filter_subsystems else None

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.sock: Optional[socket.socket] = None

        # Capture state
        self.lines: List[Tuple[str, str, str]] = []  # (timestamp, subsystem, raw_line)
        self.total_bytes = 0
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.connected = False
        self.connection_error: Optional[str] = None

        # Analysis accumulators
        self.subsystem_counts: Dict[str, int] = {}
        self.http_status_counts: Dict[int, int] = {}
        self.stream_uris: List[str] = []
        self.error_lines: List[Tuple[str, str]] = []  # (timestamp, line)

        # Output file
        self._file_handle = None
        self._file_path: Optional[str] = None
        self._file_num = 1
        self._lines_in_file = 0

    def log(self, msg: str, level: str = "INFO"):
        """Print timestamped status message."""
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [{self.device_id}:{self.ip}] {level}: {msg}")

    def _open_capture_file(self):
        """Open a new capture file for writing."""
        os.makedirs(self.captures_dir, exist_ok=True)
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        suffix = f"_part{self._file_num}" if self._file_num > 1 else ""
        filename = f"{self.device_id}_{timestamp}{suffix}.log"
        self._file_path = os.path.join(self.captures_dir, filename)
        self._file_handle = open(self._file_path, "w")
        self._lines_in_file = 0

        # Write header
        header = (
            f"# Linn DSM Firmware Debug Log Capture\n"
            f"# Device: {self.device_id}\n"
            f"# IP: {self.ip}\n"
            f"# UDN: {self.udn}\n"
            f"# Port: {self.port}\n"
            f"# Capture Start: {self.start_time.isoformat()}\n"
            f"# Filter: {', '.join(self.filter_subsystems) if self.filter_subsystems else 'ALL'}\n"
            f"#\n"
            f"# Subsystem Tags: HLS, HTTP, PIPELINE, CONTAINER, SONGCAST, CODEC, VOLUME, TRANSPORT, ERROR, OTHER\n"
            f"# Format: [TIMESTAMP] [SUBSYSTEM] raw_log_line\n"
            f"{'#' * 70}\n\n"
        )
        self._file_handle.write(header)

    def _rotate_file(self):
        """Rotate to a new capture file when max_lines reached."""
        if self._file_handle:
            self._file_handle.close()
        self._file_num += 1
        self._open_capture_file()
        self.log(f"Rotated to part {self._file_num} ({self._file_path})")

    def _write_line(self, timestamp: str, subsystem: str, raw_line: str):
        """Write a categorized line to the capture file."""
        if self.filter_subsystems and subsystem not in self.filter_subsystems:
            return

        formatted = f"[{timestamp}] [{subsystem:<10}] {raw_line}\n"

        if self._file_handle:
            self._file_handle.write(formatted)
            self._lines_in_file += 1

            if self.max_lines and self._lines_in_file >= self.max_lines:
                self._rotate_file()

    def start(self):
        """Start capture in a background thread."""
        self.running = True
        self.start_time = datetime.now()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Signal capture to stop and wait for thread to finish."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.end_time = datetime.now()
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None

    def _capture_loop(self):
        """Main capture loop - connects and reads data."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)

            self.log(f"Connecting to port {self.port}...")
            self.sock.connect((self.ip, self.port))
            self.connected = True
            self.log("Connected, capturing firmware debug stream")

            self._open_capture_file()
            self.sock.settimeout(1.0)

            while self.running:
                try:
                    data = self.sock.recv(4096)
                    if not data:
                        self.log("Connection closed by device", "WARNING")
                        break

                    self.total_bytes += len(data)
                    text = data.decode("utf-8", errors="replace")

                    for line in text.splitlines():
                        line = line.strip()
                        if not line:
                            continue

                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        subsystem = classify_line(line)

                        # Accumulate for analysis
                        self.subsystem_counts[subsystem] = self.subsystem_counts.get(subsystem, 0) + 1

                        if subsystem == "HTTP":
                            status = extract_http_status(line)
                            if status:
                                self.http_status_counts[status] = self.http_status_counts.get(status, 0) + 1
                            uri = extract_uri(line)
                            if uri and uri not in self.stream_uris:
                                self.stream_uris.append(uri)

                        if subsystem == "ERROR":
                            self.error_lines.append((timestamp, line))

                        # Store and write
                        self.lines.append((timestamp, subsystem, line))
                        self._write_line(timestamp, subsystem, line)

                except socket.timeout:
                    continue

        except ConnectionRefusedError:
            self.connection_error = f"Connection refused on {self.ip}:{self.port}"
            self.log(self.connection_error, "ERROR")
        except socket.timeout:
            self.connection_error = f"Connection timed out to {self.ip}:{self.port}"
            self.log(self.connection_error, "ERROR")
        except OSError as e:
            if self.running:  # Only report if not an intentional stop
                self.connection_error = str(e)
                self.log(f"Socket error: {e}", "ERROR")
        finally:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass

    def get_capture_path(self) -> Optional[str]:
        """Return the path to the main capture file."""
        return self._file_path

    def generate_analysis(self) -> str:
        """Generate analysis report text."""
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        total_lines = len(self.lines)

        report = []
        report.append(f"{'=' * 70}")
        report.append(f"ANALYSIS REPORT: {self.device_id} ({self.ip})")
        report.append(f"{'=' * 70}")
        report.append(f"Capture Duration: {duration:.1f}s")
        report.append(f"Total Bytes: {self.total_bytes}")
        report.append(f"Total Lines: {total_lines}")
        report.append(f"Connected: {'Yes' if self.connected else 'No'}")
        if self.connection_error:
            report.append(f"Connection Error: {self.connection_error}")
        report.append("")

        # Subsystem activity
        report.append(f"--- Subsystem Activity ---")
        if self.subsystem_counts:
            max_count = max(self.subsystem_counts.values())
            bar_width = 40
            for subsystem, count in sorted(self.subsystem_counts.items(), key=lambda x: -x[1]):
                bar_len = int((count / max_count) * bar_width) if max_count > 0 else 0
                bar = "█" * bar_len
                pct = (count / total_lines * 100) if total_lines > 0 else 0
                report.append(f"  {subsystem:<12} {count:5d} ({pct:5.1f}%) {bar}")
        else:
            report.append("  No data captured")
        report.append("")

        # HTTP status codes
        report.append(f"--- HTTP Status Codes ---")
        if self.http_status_counts:
            for code, count in sorted(self.http_status_counts.items()):
                marker = "  " if 200 <= code < 300 else "⚠ "
                report.append(f"  {marker}{code}: {count} requests")
        else:
            report.append("  No HTTP requests observed")
        report.append("")

        # Stream URIs
        report.append(f"--- Stream URIs Identified ---")
        if self.stream_uris:
            for uri in self.stream_uris:
                # Truncate very long URIs for readability
                display = uri if len(uri) <= 100 else uri[:97] + "..."
                report.append(f"  {display}")
        else:
            report.append("  No stream URIs observed")
        report.append("")

        # Errors
        report.append(f"--- Errors ({len(self.error_lines)}) ---")
        if self.error_lines:
            for ts, line in self.error_lines[:50]:  # Cap at 50 errors
                report.append(f"  [{ts}] {line}")
            if len(self.error_lines) > 50:
                report.append(f"  ... and {len(self.error_lines) - 50} more")
        else:
            report.append("  No errors detected")
        report.append("")

        return "\n".join(report)

    def write_analysis(self) -> Optional[str]:
        """Write analysis report to file and return the path."""
        if not self.start_time:
            return None

        os.makedirs(self.captures_dir, exist_ok=True)
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        filename = f"{self.device_id}_{timestamp}_analysis.txt"
        path = os.path.join(self.captures_dir, filename)

        report = self.generate_analysis()
        with open(path, "w") as f:
            f.write(report)

        return path


# --- Multi-Device Capture Orchestrator ---

class CaptureSession:
    """Orchestrates concurrent capture from multiple devices."""

    def __init__(self, devices: List[Dict[str, str]], port: int = 2323,
                 captures_dir: str = "captures", max_lines: int = 5000,
                 debug: bool = False, filter_subsystems: Optional[List[str]] = None):
        self.devices = devices
        self.captures_dir = captures_dir
        self.debug = debug
        self.captors: List[DeviceLogCapture] = []

        for dev in devices:
            captor = DeviceLogCapture(
                device_id=dev["id"],
                ip=dev["ip"],
                udn=dev["udn"],
                port=port,
                captures_dir=captures_dir,
                max_lines=max_lines,
                debug=debug,
                filter_subsystems=filter_subsystems,
            )
            self.captors.append(captor)

    def start(self):
        """Start all device captures."""
        print(f"=== Linn DSM Diagnostic Log Capture ===")
        print(f"Devices: {len(self.captors)}")
        print(f"Output: {self.captures_dir}/")
        print(f"{'-' * 50}")

        for captor in self.captors:
            captor.start()

    def stop(self):
        """Stop all captures and generate reports."""
        print(f"\n{'=' * 50}")
        print("Stopping captures...")

        for captor in self.captors:
            captor.stop()

    def generate_reports(self) -> List[str]:
        """Generate analysis reports for all devices. Returns list of report paths."""
        paths = []
        print(f"\n{'=' * 50}")
        print("CAPTURE SESSION SUMMARY")
        print(f"{'=' * 50}\n")

        for captor in self.captors:
            # Print summary to stdout
            report = captor.generate_analysis()
            print(report)

            # Write analysis file
            analysis_path = captor.write_analysis()
            if analysis_path:
                paths.append(analysis_path)

            capture_path = captor.get_capture_path()
            if capture_path:
                paths.append(capture_path)

        # Print file listing
        print(f"\n{'=' * 50}")
        print("OUTPUT FILES:")
        for p in sorted(paths):
            size = os.path.getsize(p) if os.path.exists(p) else 0
            print(f"  {p} ({size} bytes)")

        return paths

    def wait(self, duration: Optional[float] = None):
        """Wait for specified duration or until interrupted."""
        try:
            if duration:
                print(f"\nCapturing for {duration}s (Ctrl+C to stop early)...\n")
                time.sleep(duration)
            else:
                print(f"\nCapturing indefinitely (Ctrl+C to stop)...\n")
                while True:
                    time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Interrupted by user]")


# --- Integration API (importable by other scripts) ---

_active_session: Optional[CaptureSession] = None


def start_capture(devices: Optional[List[Dict[str, str]]] = None,
                  port: int = 2323, captures_dir: str = "captures",
                  max_lines: int = 5000,
                  filter_subsystems: Optional[List[str]] = None) -> CaptureSession:
    """Start diagnostic capture for use by other scripts.

    Usage from another script:
        from device_logs import start_capture, stop_capture
        session = start_capture()
        # ... do your operation ...
        report_paths = stop_capture(session)
    """
    global _active_session

    if devices is None:
        devices = load_devices_from_env()

    session = CaptureSession(
        devices=devices,
        port=port,
        captures_dir=captures_dir,
        max_lines=max_lines,
        filter_subsystems=filter_subsystems,
    )
    session.start()
    _active_session = session
    # Allow a brief connection window
    time.sleep(1)
    return session


def stop_capture(session: Optional[CaptureSession] = None) -> List[str]:
    """Stop a capture session and return list of output file paths."""
    global _active_session
    s = session or _active_session
    if not s:
        return []

    s.stop()
    paths = s.generate_reports()
    _active_session = None
    return paths


# --- Background Mode (PID file based) ---

PID_FILE = "captures/.device_logs.pid"


def _write_pid():
    """Write current PID to control file."""
    os.makedirs("captures", exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _read_pid() -> Optional[int]:
    """Read PID from control file."""
    try:
        with open(PID_FILE, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _remove_pid():
    """Remove PID file."""
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def stop_background():
    """Send SIGTERM to a running background capture."""
    pid = _read_pid()
    if pid is None:
        print("No background capture running (no PID file found)")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent stop signal to background capture (PID {pid})")
        # Wait briefly for cleanup
        time.sleep(1)
        _remove_pid()
    except ProcessLookupError:
        print(f"Background capture (PID {pid}) is not running, cleaning up")
        _remove_pid()


# --- Around-Command Mode ---

def run_around_command(command: str, devices: List[Dict[str, str]], port: int = 2323,
                      captures_dir: str = "captures", max_lines: int = 5000,
                      filter_subsystems: Optional[List[str]] = None):
    """Start capture, run a command, stop capture, produce report."""
    print(f"=== Capture Around Command ===")
    print(f"Command: {command}")
    print(f"{'-' * 50}")

    session = CaptureSession(
        devices=devices,
        port=port,
        captures_dir=captures_dir,
        max_lines=max_lines,
        filter_subsystems=filter_subsystems,
    )
    session.start()

    # Allow connections to establish
    time.sleep(1)

    # Run the command
    print(f"\n--- Running command ---")
    print(f"$ {command}\n")

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=False,
        )
        print(f"\n--- Command exited with code {result.returncode} ---")
    except KeyboardInterrupt:
        print("\n[Command interrupted]")
    except Exception as e:
        print(f"\n--- Command failed: {e} ---")

    # Brief post-command capture window for trailing diagnostics
    print("\nCapturing trailing diagnostics (2s)...")
    time.sleep(2)

    session.stop()
    session.generate_reports()


# --- CLI Entry Point ---

def main():
    parser = argparse.ArgumentParser(
        description="Capture firmware debug logs from Linn DSM devices (port 2323)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              Capture all .env devices for 60s
  %(prog)s 172.24.32.211                Capture single device for 60s
  %(prog)s --duration 120               Capture for 2 minutes
  %(prog)s --filter HLS,ERROR           Only capture HLS and error lines
  %(prog)s --around-command ".venv/bin/python now_playing.py"
  %(prog)s --background                 Start background capture
  %(prog)s --stop                       Stop background capture
""")
    parser.add_argument("ip", nargs="?", help="Single device IP address (otherwise uses .env)")
    parser.add_argument("--port", type=int, default=2323, help="Port to capture from (default: 2323)")
    parser.add_argument("--duration", "-d", type=float, default=60.0,
                        help="Capture duration in seconds (default: 60, 0=unlimited)")
    parser.add_argument("--output-dir", "-o", default="captures",
                        help="Output directory for capture files (default: captures/)")
    parser.add_argument("--max-lines", type=int, default=5000,
                        help="Max lines per capture file before rotation (default: 5000, 0=unlimited)")
    parser.add_argument("--filter", "-f", type=str, default=None,
                        help="Comma-separated subsystem filter (e.g. HLS,ERROR,HTTP)")
    parser.add_argument("--around-command", type=str, default=None,
                        help="Run capture around a shell command")
    parser.add_argument("--background", action="store_true",
                        help="Run capture in background (write PID file)")
    parser.add_argument("--stop", action="store_true",
                        help="Stop a running background capture")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug output")

    args = parser.parse_args()

    # Handle --stop
    if args.stop:
        stop_background()
        return

    # Resolve devices
    if args.ip:
        devices = [{"id": "DEVICE", "ip": args.ip, "udn": "unknown"}]
    else:
        try:
            devices = load_devices_from_env()
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR: Could not load devices from .env: {e}")
            print("Provide an IP address argument or configure .env")
            sys.exit(1)

    # Parse filter
    filter_subs = [s.strip() for s in args.filter.split(",")] if args.filter else None

    # Handle --around-command
    if args.around_command:
        run_around_command(
            command=args.around_command,
            devices=devices,
            port=args.port,
            captures_dir=args.output_dir,
            max_lines=args.max_lines if args.max_lines > 0 else None,
            filter_subsystems=filter_subs,
        )
        return

    # Handle --background
    if args.background:
        _write_pid()
        # Register signal handler for graceful stop
        session = CaptureSession(
            devices=devices,
            port=args.port,
            captures_dir=args.output_dir,
            max_lines=args.max_lines if args.max_lines > 0 else None,
            debug=args.debug,
            filter_subsystems=filter_subs,
        )

        def handle_term(signum, frame):
            session.stop()
            session.generate_reports()
            _remove_pid()
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_term)
        signal.signal(signal.SIGINT, handle_term)

        session.start()
        print(f"Background capture started (PID {os.getpid()})")
        print(f"Stop with: .venv/bin/python device_logs.py --stop")

        # Run indefinitely until signaled
        session.wait(duration=None)
        return

    # Standard capture mode
    session = CaptureSession(
        devices=devices,
        port=args.port,
        captures_dir=args.output_dir,
        max_lines=args.max_lines if args.max_lines > 0 else None,
        debug=args.debug,
        filter_subsystems=filter_subs,
    )

    session.start()
    duration = args.duration if args.duration > 0 else None
    session.wait(duration=duration)
    session.stop()
    session.generate_reports()


if __name__ == "__main__":
    main()
