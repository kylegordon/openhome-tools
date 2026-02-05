###
# Script to query Linn DSM devices for now playing information using openhomedevice
# Requires openhomedevice package: https://pypi.org/project/openhomedevice/
# Install in the project's virtual environment.
# Usage:
#   .venv/bin/python now_playing.py [--debug] [--trace-songcast]
# Alternative:
#   source .venv/bin/activate && python now_playing.py [--debug] [--trace-songcast]
#
# Notes for future reference:
# - Device discovery is explicit via a static DEVICES list (ip + udn). Names are resolved at runtime.
# - We use openhomedevice async Device API: init() -> source() -> track_info(), plus product Standby.
# - Radio: we treat Info.title as the station name.
# - Songcast: when the current source looks like Songcast, we query Receiver.Sender() to find the sender.
#   Sender resolution order: Sender Uri query (room/name) -> Sender Metadata (publisher/author/title/artist)
#   -> Sender UDN from Uri path mapped to known devices (NAME_CACHE or on-demand lookup).
# - --trace-songcast prints Sender Uri and a short head of Metadata to stdout for diagnostics.
###

"""Linn DSM now-playing reporter using openhomedevice.

This module prints a single formatted line per device describing its power state,
source, and what is currently playing. For Songcast receivers, it also includes
the Songcast sender name when determinable.

Key behaviors:
- Iterates a static list of devices (DEVICES) identified by IP and UDN.
- Resolves friendly names at runtime and caches them by UDN (NAME_CACHE).
- Uses Info service metadata to display radio and track details.
- For Songcast, queries Receiver.Sender() and infers the sender via Uri/Metadata/UDN.

Usage:
    .venv/bin/python now_playing.py [--debug] [--trace-songcast]

Alternative:
    source .venv/bin/activate && python now_playing.py [--debug] [--trace-songcast]

Example:
    .venv/bin/python now_playing.py --debug

Notes:
- Install the "openhomedevice" package inside the project's virtual environment.
- Devices are loaded from a local .env file (see DEVICES parsing rules below).
"""

import argparse
import sys
import asyncio
import html
import re
import os
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict, List
from urllib.parse import urlparse, parse_qs

try:
    from openhomedevice.device import Device
    from openhomedevice import didl_lite
except Exception:
    Device = None
    didl_lite = None

def _load_env(path: str) -> Dict[str, str]:
    env: Dict[str, str] = {}
    try:
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
    except FileNotFoundError:
        raise
    return env


def load_devices_from_env(env_path: Optional[str] = None) -> List[Dict[str, str]]:
    """Load device definitions from a .env file.

    Looks for "DEVICES_JSON" (or fallback "DEVICES") containing a JSON array
    of objects like {"ip": "...", "udn": "..."}.

    The default path is .env next to this script. Can be overridden by setting
    LINN_ENV_PATH in the environment or passing env_path.
    """
    default_path = str(Path(__file__).parent / ".env")
    path = env_path or os.environ.get("LINN_ENV_PATH") or default_path
    env = _load_env(path)
    devices: List[Dict[str, str]] = []

    # Preferred: lines like DEVICE_1=172.24.32.211 4c49..., DEVICE_2=...
    kv_pairs = [(k, v) for k, v in env.items() if k == "DEVICE" or k.startswith("DEVICE_")]
    if kv_pairs:
        for _, v in sorted(kv_pairs, key=lambda kv: kv[0]):
            line = v.strip()
            if not line:
                continue
            # allow separators: space, comma, or semicolon
            parts = re.split(r"[\s,;]+", line)
            if len(parts) >= 2:
                ip, udn = parts[0], parts[1]
                if ip and udn:
                    devices.append({"ip": ip, "udn": udn})

    # Fallback: DEVICES_JSON/DEVICES JSON array
    if not devices:
        payload = env.get("DEVICES_JSON") or env.get("DEVICES")
        if payload:
            try:
                data = json.loads(payload)
            except Exception as e:
                raise ValueError(f"Invalid DEVICES_JSON content: {e}")
            if not isinstance(data, list):
                raise ValueError("DEVICES_JSON must be a JSON array")
            for item in data:
                if not isinstance(item, dict):
                    continue
                ip = item.get("ip")
                udn = item.get("udn")
                if ip and udn:
                    devices.append({"ip": ip, "udn": udn})

    if not devices:
        raise ValueError(f"No devices found in {path}. Define DEVICE entries or DEVICES_JSON.")
    return devices


# Ordered list of devices to query (names are resolved automatically) loaded from .env.
#
# Tip: Keep this small and explicit. The script resolves names each run and
# caches them in NAME_CACHE so Songcast sender names can be mapped by UDN.
DEVICES = load_devices_from_env()

# Cache resolved names by UDN during a single run.
#
# Used to label Songcast senders when only their UDN is available in Sender Uri.
NAME_CACHE: Dict[str, str] = {}


def parse_didl(didl: str) -> Dict[str, Optional[str]]:
    """Parse a DIDL-Lite metadata string to a minimal dict.

    Strategy:
    1) Fast-path regex for common fields (title/artist/album/channelName).
    2) Fallback to namespace-aware XML parsing for robustness.

    Returns a dict with keys: title, artist, album, channel. Values may be None.
    """
    if not didl:
        return {"title": None, "artist": None, "album": None, "channel": None}
    didl = html.unescape(didl).strip()
    # Regex fast path
    m_title = re.search(r"<dc:title>([^<]+)</dc:title>", didl)
    m_artist = re.search(r"<upnp:artist>([^<]+)</upnp:artist>", didl)
    m_album = re.search(r"<upnp:album>([^<]+)</upnp:album>", didl)
    m_channel = re.search(r"<upnp:channelName>([^<]+)</upnp:channelName>", didl)
    if m_title or m_artist or m_album or m_channel:
        return {
            "title": m_title.group(1) if m_title else None,
            "artist": m_artist.group(1) if m_artist else None,
            "album": m_album.group(1) if m_album else None,
            "channel": (m_channel.group(1) if m_channel else (m_title.group(1) if m_title else None)),
        }
    # XML fallback
    try:
        root = ET.fromstring(didl)
    except Exception:
        return {"title": None, "artist": None, "album": None, "channel": None}
    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/",
    }
    title_el = root.find(".//dc:title", ns)
    artist_el = root.find(".//upnp:artist", ns)
    album_el = root.find(".//upnp:album", ns)
    channel_el = root.find(".//upnp:channelName", ns)
    return {
        "title": title_el.text if title_el is not None else None,
        "artist": artist_el.text if artist_el is not None else None,
        "album": album_el.text if album_el is not None else None,
        "channel": channel_el.text if channel_el is not None else None,
    }


async def query_device(ip: str, udn: str, name: Optional[str] = None, debug: bool = False, trace_songcast: bool = False) -> Dict[str, Optional[str]]:
    """Query a single device for current status and now-playing info.

    - Resolves the device's display name (friendly_name or Product.Name) and caches it by UDN.
    - Reads current Product source and Info track metadata.
    - Derives radio station from Info.title when on Radio.
    - If the source looks like Songcast, queries Receiver.Sender() to infer the sender name
      via Uri query params, DIDL metadata, or UDN mapping through NAME_CACHE/DEVICES.

    Args:
        ip: Device IP address
        udn: Device UDN (used to build the device.xml URL and for sender mapping)
        name: Optional override for display name (usually left None)
        debug: Unused here (kept for parity)
        trace_songcast: When True, prints Sender Uri and Metadata head for diagnostics

    Returns:
        Dict of fields consumed by format_result().
    """
    if Device is None:
        raise RuntimeError("openhomedevice not available; please install it.")
    location = f"http://{ip}:55178/{udn}/Upnp/device.xml"
    dev = Device(location)
    await dev.init()

    # Resolve device display name if not provided
    device_name = name
    try:
        fn = dev.friendly_name()
        if fn:
            device_name = fn
    except Exception:
        pass
    if not device_name:
        try:
            device_name = await dev.name()
        except Exception:
            device_name = name or ip
    # Cache resolved name for later sender lookup
    try:
        if device_name:
            NAME_CACHE[udn] = device_name
    except Exception:
        pass

    # Source info
    src = await dev.source()
    src_name = src.get("name") or src.get("Name")
    src_type = src.get("type") or src.get("Type")
    # Standby state
    try:
        standby = await dev.is_in_standby()
    except Exception:
        standby = None

    # Track via Info service
    track = await dev.track_info()
    title = track.get("title")
    artist = track.get("artist")
    album = track.get("albumTitle")

    # For radio, title typically is the station name
    station = None
    if (src_type or "").lower() == "radio" or (src_name or "").lower() == "radio":
        station = title

    # Songcast sender (Receiver service -> Sender()) only when on Songcast source
    sender = None
    sender_uri_dbg = None
    sender_meta_head_dbg = None
    # Detect when the selected source is Songcast, and separately determine if the
    # device is actually grouped (actively receiving from a Sender).
    is_songcast_source = ("songcast" in (src_type or "").lower()) or ("songcast" in (src_name or "").lower())
    is_songcast_grouped = False
    songcast_transport_state = None
    songcast_status = None
    songcast_sender_scheme = None
    if is_songcast_source:
        try:
            recv = dev.device.service_id("urn:av-openhome-org:serviceId:Receiver")
            if recv is not None:
                async def _get_sender():
                    return await recv.action("Sender").async_call()
                async def _get_transport_state():
                    return await recv.action("TransportState").async_call()
                async def _get_status():
                    return await recv.action("Status").async_call()
                try:
                    # Query transport state first to infer active receiver status
                    try:
                        ts_res = await asyncio.wait_for(_get_transport_state(), timeout=2.0)
                        if isinstance(ts_res, dict):
                            songcast_transport_state = (
                                ts_res.get("TransportState")
                                or ts_res.get("transportState")
                                or ts_res.get("state")
                            )
                    except Exception:
                        songcast_transport_state = None
                    # Query status for additional context (not used for grouping decision)
                    try:
                        st_res = await asyncio.wait_for(_get_status(), timeout=2.0)
                        if isinstance(st_res, dict):
                            songcast_status = (
                                st_res.get("Status")
                                or st_res.get("status")
                            )
                    except Exception:
                        songcast_status = None

                    sender_res = await asyncio.wait_for(_get_sender(), timeout=2.0)
                    if trace_songcast and isinstance(sender_res, dict):
                        uri_dbg = sender_res.get("Uri") or sender_res.get("uri") or ""
                        meta_dbg = sender_res.get("Metadata") or sender_res.get("metadata") or ""
                        try:
                            print(f"[TRACE] {device_name}: Receiver.Sender Uri: {uri_dbg}")
                        except Exception:
                            pass
                        try:
                            head = html.unescape(meta_dbg)[:400]
                            print(f"[TRACE] {device_name}: Receiver.Sender Metadata head: {head}")
                        except Exception:
                            pass
                        # also keep in-result for formatted fallback
                        sender_uri_dbg = uri_dbg or None
                        sender_meta_head_dbg = head or None
                    if isinstance(sender_res, dict):
                        # Consider grouped if TransportState indicates active playback and Uri is present
                        uri_val = sender_res.get("Uri") or sender_res.get("uri")
                        uri_present = bool(uri_val)
                        ts = (songcast_transport_state or "").lower()
                        # Heuristic:
                        # - ohz:// indicates active Songcast zone distribution -> grouped
                        # - ohSongcast:// is a sender descriptor; only grouped when transport active
                        scheme = None
                        try:
                            if uri_val:
                                scheme = urlparse(uri_val).scheme.lower()
                        except Exception:
                            scheme = None
                        is_songcast_grouped = (
                            (scheme == "ohz") or (
                                uri_present and scheme == "ohsongcast" and ts in ("playing", "buffering", "connecting")
                            )
                        )
                        songcast_sender_scheme = scheme
                        # Prefer extracting from Sender Uri query params (room/name)
                        uri = sender_res.get("Uri") or sender_res.get("uri")
                        if uri:
                            try:
                                u = urlparse(uri)
                                qs = {k.lower(): v for k, v in parse_qs(u.query).items()}
                                sender_udn = u.path.strip("/") if u and u.path else None
                                # common keys seen: room, name
                                for key in ("room", "name"):
                                    if key in qs and qs[key]:
                                        sender = qs[key][0]
                                        break
                                # If still unknown, try to resolve from sender UDN
                                if not sender and sender_udn:
                                    # Check cache
                                    sender = NAME_CACHE.get(sender_udn)
                                    if not sender:
                                        # Find matching device IP from known devices
                                        sender_ip = None
                                        for dd in DEVICES:
                                            if dd.get("udn") == sender_udn:
                                                sender_ip = dd.get("ip")
                                                break
                                        if sender_ip:
                                            try:
                                                ldev = Device(f"http://{sender_ip}:55178/{sender_udn}/Upnp/device.xml")
                                                await asyncio.wait_for(ldev.init(), timeout=2.0)
                                                try:
                                                    lname = ldev.friendly_name()
                                                except Exception:
                                                    lname = None
                                                if not lname:
                                                    try:
                                                        lname = await asyncio.wait_for(ldev.name(), timeout=2.0)
                                                    except Exception:
                                                        lname = None
                                                if lname:
                                                    sender = lname
                                                    NAME_CACHE[sender_udn] = lname
                                            except Exception:
                                                pass
                            except Exception:
                                pass
                        if not sender:
                            meta = sender_res.get("Metadata") or sender_res.get("metadata")
                            if meta:
                                details = didl_lite.parse(meta) if didl_lite else {}
                                sender = details.get("publisher") or details.get("author") or details.get("title") or details.get("artist") or None
                except Exception:
                    pass
        except Exception:
            pass

    return {
        "device": device_name,
        "source_name": src_name,
        "source_type": src_type,
        "title": title,
        "artist": artist,
        "album": album,
        "station": station,
        "is_songcast": is_songcast_source,
        "is_songcast_grouped": is_songcast_grouped,
        "songcast_transport_state": songcast_transport_state,
        "songcast_sender": sender,
        "songcast_sender_uri": sender_uri_dbg,
        "songcast_sender_meta_head": sender_meta_head_dbg,
        "songcast_status": songcast_status,
        "songcast_sender_scheme": songcast_sender_scheme,
        "standby": standby,
    }


def format_result(r: Dict[str, Optional[str]]) -> str:
    """Render a concise, single-line summary for a device.

    Includes:
    - Power state (On/Off), with an "(in standby)" note in the device label when Off.
    - Songcast Sender when on Songcast; with optional raw Sender fields if tracing.
    - Station (for Radio), Title/Artist, and Album when available.
    """
    device = r.get("device") or "Device"
    src = r.get("source_name") or r.get("source_type") or "Unknown source"
    parts = []
    if r.get("standby") is not None:
        parts.append(f"Power: {'Off' if r['standby'] else 'On'}")
    # Add a clear standby note to avoid confusion
    if r.get("standby"):
        device = f"{device} (in standby)"
    if r.get("is_songcast"):
        scheme = r.get("songcast_sender_scheme") or "unknown"
        if r.get("is_songcast_grouped"):
            if r.get("songcast_sender"):
                parts.append(f"Songcast Sender: {r['songcast_sender']} ({scheme})")
            else:
                parts.append(f"Songcast: Grouped ({scheme}, sender unknown)")
                if r.get("songcast_sender_uri"):
                    parts.append(f"Sender Uri: {r['songcast_sender_uri']}")
        else:
            parts.append(f"Songcast: Not grouped ({scheme})")
            ts = r.get("songcast_transport_state")
            st = r.get("songcast_status")
            if ts:
                parts.append(f"Receiver: {ts}")
            if st:
                parts.append(f"Status: {st}")
            # When tracing, also show raw fields if present
            if r.get("songcast_sender_uri"):
                parts.append(f"Sender Uri: {r['songcast_sender_uri']}")
            if r.get("songcast_sender_meta_head"):
                parts.append(f"Sender Meta: {r['songcast_sender_meta_head']}")
    if r.get("station"):
        parts.append(f"Station: {r['station']}")
    if r.get("title") and r.get("artist"):
        parts.append(f"Track: {r['title']} — {r['artist']}")
    elif r.get("title"):
        parts.append(f"Title: {r['title']}")
    if r.get("album"):
        parts.append(f"Album: {r['album']}")
    summary = ", ".join(p for p in parts if p)
    return f"{device} ({src}): {summary if summary else 'No metadata available'}"


async def main_async():
    """CLI entry: iterate DEVICES and print a summary line per device."""
    parser = argparse.ArgumentParser(description="Query Linn DSM now playing via openhomedevice")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--trace-songcast", action="store_true", help="Trace Songcast Receiver Sender Uri/Metadata")
    args = parser.parse_args()

    for d in DEVICES:
        r = await query_device(d["ip"], d["udn"], None, debug=args.debug, trace_songcast=args.trace_songcast)
        print(format_result(r))

def main():
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main() or 0)
