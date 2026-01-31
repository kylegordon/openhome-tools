###
# Script to query Linn DSM devices for now playing information using openhomedevice
# Requires openhomedevice package: https://pypi.org/project/openhomedevice/
# Usage:
#   /home/kyleg/Sync/scripts/Linn/.venv/bin/python /home/kyleg/Sync/scripts/Linn/openhome_now_playing.py [--debug] [--trace-songcast]
#
# Notes for future reference:
# - Device discovery is explicit via a static DEVICES list (ip + udn). Names are resolved at runtime.
# - We use openhomedevice async Device API: init() -> source() -> track_info(), plus product Standby.
# - Radio: we treat Info.title as the station name.
# - Songcast: when the current source looks like Songcast, we query Receiver.Sender() to find the leader.
#   Leader resolution order: Sender Uri query (room/name) -> Sender Metadata (publisher/author/title/artist)
#   -> Leader UDN from Uri path mapped to known devices (NAME_CACHE or on-demand lookup).
# - --trace-songcast prints Sender Uri and a short head of Metadata to stdout for diagnostics.
###

"""Linn DSM now-playing reporter using openhomedevice.

This module prints a single formatted line per device describing its power state,
source, and what is currently playing. For Songcast followers, it also includes
the Songcast leader name when determinable.

Key behaviors:
- Iterates a static list of devices (DEVICES) identified by IP and UDN.
- Resolves friendly names at runtime and caches them by UDN (NAME_CACHE).
- Uses Info service metadata to display radio and track details.
- For Songcast, queries Receiver.Sender() and infers the leader via Uri/Metadata/UDN.
"""

import argparse
import sys
import asyncio
import html
import re
import xml.etree.ElementTree as ET
from typing import Optional, Dict
from urllib.parse import urlparse, parse_qs

try:
    from openhomedevice.device import Device
    from openhomedevice import didl_lite
except Exception:
    Device = None
    didl_lite = None

# Ordered list of devices to query (names are resolved automatically).
#
# Tip: Keep this small and explicit. The script resolves names each run and
# caches them in NAME_CACHE so Songcast leader names can be mapped by UDN.
DEVICES = [
    {"ip": "172.24.32.211", "udn": "4c494e4e-0026-0f22-5661-01531488013f"},
    {"ip": "172.24.32.210", "udn": "4c494e4e-0026-0f22-646e-01560511013f"},
    {"ip": "172.24.32.212", "udn": "4c494e4e-0026-0f22-3637-01475230013f"},
]

# Cache resolved names by UDN during a single run.
#
# Used to label Songcast leaders when only their UDN is available in Sender Uri.
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
    - If the source looks like Songcast, queries Receiver.Sender() to infer the leader name
      via Uri query params, DIDL metadata, or UDN mapping through NAME_CACHE/DEVICES.

    Args:
        ip: Device IP address
        udn: Device UDN (used to build the device.xml URL and for leader mapping)
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
    # Cache resolved name for later leader lookup
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

    # Songcast leader (Receiver service -> Sender()) only when on Songcast source
    leader = None
    sender_uri_dbg = None
    sender_meta_head_dbg = None
    is_songcast = ("songcast" in (src_type or "").lower()) or ("songcast" in (src_name or "").lower())
    if is_songcast:
        try:
            recv = dev.device.service_id("urn:av-openhome-org:serviceId:Receiver")
            if recv is not None:
                async def _get_sender():
                    return await recv.action("Sender").async_call()
                try:
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
                        # Prefer extracting from Sender Uri query params (room/name)
                        uri = sender_res.get("Uri") or sender_res.get("uri")
                        if uri:
                            try:
                                u = urlparse(uri)
                                qs = {k.lower(): v for k, v in parse_qs(u.query).items()}
                                leader_udn = u.path.strip("/") if u and u.path else None
                                # common keys seen: room, name
                                for key in ("room", "name"):
                                    if key in qs and qs[key]:
                                        leader = qs[key][0]
                                        break
                                # If still unknown, try to resolve from leader UDN
                                if not leader and leader_udn:
                                    # Check cache
                                    leader = NAME_CACHE.get(leader_udn)
                                    if not leader:
                                        # Find matching device IP from known devices
                                        leader_ip = None
                                        for dd in DEVICES:
                                            if dd.get("udn") == leader_udn:
                                                leader_ip = dd.get("ip")
                                                break
                                        if leader_ip:
                                            try:
                                                ldev = Device(f"http://{leader_ip}:55178/{leader_udn}/Upnp/device.xml")
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
                                                    leader = lname
                                                    NAME_CACHE[leader_udn] = lname
                                            except Exception:
                                                pass
                            except Exception:
                                pass
                        if not leader:
                            meta = sender_res.get("Metadata") or sender_res.get("metadata")
                            if meta:
                                details = didl_lite.parse(meta) if didl_lite else {}
                                leader = details.get("publisher") or details.get("author") or details.get("title") or details.get("artist") or None
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
        "is_songcast": is_songcast,
        "songcast_leader": leader,
        "songcast_sender_uri": sender_uri_dbg,
        "songcast_sender_meta_head": sender_meta_head_dbg,
        "standby": standby,
    }


def format_result(r: Dict[str, Optional[str]]) -> str:
    """Render a concise, single-line summary for a device.

    Includes:
    - Power state (On/Off), with an "(in standby)" note in the device label when Off.
    - Songcast Leader when on Songcast; with optional raw Sender fields if tracing.
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
        if r.get("songcast_leader"):
            parts.append(f"Songcast Leader: {r['songcast_leader']}")
        else:
            parts.append("Songcast Leader: Unknown")
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
