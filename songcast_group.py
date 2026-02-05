#!/usr/bin/env python3
"""
Linn OpenHome Songcast Group Creator

Purpose:
- Create a Songcast group with one sender and one or more receivers
    using the openhomedevice library.

Usage (with .env):
    .venv/bin/python experimental/songcast_group.py [--debug]

Configuration (.env):
    # Map devices once, then run without flags
    DEVICE_1=<SENDER_IP> <SENDER_UDN>
    DEVICE_2=<RECEIVER_1_IP> <RECEIVER_1_UDN>
    DEVICE_3=<RECEIVER_2_IP> <RECEIVER_2_UDN>
    SONGCAST_SENDER=DEVICE_1
    SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3

Alternative (override .env if needed):
    source .venv/bin/activate && python experimental/songcast_group.py \
        --sender-ip <IP_ADDRESS> --sender-udn <UDN> \
        --receiver-ip <IP_ADDRESS> --receiver-udn <UDN> \
        [--debug]

Example (.env-driven, minimal):
    .venv/bin/python experimental/songcast_group.py --debug

Notes:
- Uses openhomedevice to control Product:4 and Receiver services.
- Ensures receiver source is Songcast and joins sender via Receiver.SetSender.
- Prefers ohz URIs discovered via Receiver.Senders; falls back to ohSongcast descriptor.
- Supports .env configuration: define DEVICE_n entries, SONGCAST_SENDER and SONGCAST_RECEIVERS.
- To find a device UDN: python3 find_linn_udn.py <IP_ADDRESS>
- Recommended: pipe terminal output to a file for reliable reading.
"""

import sys
import argparse
import asyncio
import xml.etree.ElementTree as ET
import requests
import os
try:
    # Ensure immediate flushing of prints when redirected
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

try:
    from openhomedevice.device import Device
except Exception:
    Device = None

def _load_env_devices(env_path):
    devices = {}
    sender_id = None
    receiver_ids = []
    try:
        with open(env_path, 'r') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                # strip inline comment
                if '#' in line:
                    line = line.split('#', 1)[0].strip()
                if not line or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip()
                if key.startswith('DEVICE'):
                    parts = val.split()
                    if len(parts) >= 2:
                        devices[key] = {"ip": parts[0], "udn": parts[1]}
                elif key == 'SONGCAST_SENDER':
                    sender_id = val.strip()
                elif key == 'SONGCAST_RECEIVERS':
                    receiver_ids = [v.strip() for v in val.split(',') if v.strip()]
    except Exception:
        pass
    return devices, sender_id, receiver_ids

class LinnSongcastGrouper:
        def __init__(self, sender_ip, sender_udn, receivers, debug=False):
            self.sender_ip = sender_ip
            self.sender_udn = sender_udn
            # Sender name will be resolved from device.xml (friendly_name/Product.Name)
            self.sender_name = None
            self.receivers = receivers or []
            self.debug = debug

        def _location(self, ip, udn):
            return f"http://{ip}:55178/{udn}/Upnp/device.xml"

        async def _init_dev(self, ip, udn):
            if Device is None:
                raise RuntimeError("openhomedevice not available; install in .venv")
            dev = Device(self._location(ip, udn))
            await dev.init()
            return dev

        async def _resolve_device_name(self, dev, fallback=None):
            # Try friendly_name (from device.xml), then Product.Name()
            try:
                fn = dev.friendly_name()
                if fn:
                    return fn
            except Exception:
                pass
            try:
                nm = await dev.name()
                if nm:
                    return nm
            except Exception:
                pass
            return fallback

        async def wake_device(self, dev, name):
            print(f"Waking {name} from standby...")
            try:
                await dev.set_standby(False)
                print(f"✓ {name} woken")
                return True
            except Exception as e:
                print(f"✗ Failed to wake {name}: {e}")
                return False

        async def _find_songcast_index(self, dev):
            try:
                prod = dev.device.service_id("urn:av-openhome-org:serviceId:Product")
                if prod is None:
                    return None
                sc = await prod.action("SourceCount").async_call()
                count = int(sc.get("Value") or 8)
                for i in range(count):
                    try:
                        sres = await prod.action("Source").async_call(Index=i)
                        typ = (sres.get("Type") or "").lower()
                        name = (sres.get("Name") or sres.get("SystemName") or "").lower()
                        vis = (sres.get("Visible") or "true").strip().lower()
                        if vis in ("true", "1", "yes") and ("songcast" in name or "receiver" in typ or "songcast" in typ):
                            return i
                    except Exception:
                        continue
            except Exception:
                pass
            return None

        async def _get_current_source_info(self, dev):
            try:
                prod = dev.device.service_id("urn:av-openhome-org:serviceId:Product")
                if prod is None:
                    return None
                idx_res = await prod.action("SourceIndex").async_call()
                cur_idx = int(idx_res.get("Value") or idx_res.get("Index") or -1)
                if cur_idx < 0:
                    return None
                sres = await prod.action("Source").async_call(Index=cur_idx)
                return {
                    "index": cur_idx,
                    "type": (sres.get("Type") or "").lower(),
                    "name": (sres.get("Name") or sres.get("SystemName") or "").lower(),
                }
            except Exception:
                return None

        async def set_source_to_songcast(self, dev, name):
            print(f"Setting {name} source to Songcast...")
            try:
                prod = dev.device.service_id("urn:av-openhome-org:serviceId:Product")
                if prod is None:
                    raise RuntimeError("Product service not available")

                cur = await self._get_current_source_info(dev)
                if cur and ("songcast" in cur.get("name", "") or "receiver" in cur.get("type", "") or "songcast" in cur.get("type", "")):
                    print(f"✓ {name} already on Songcast (index {cur['index']})")
                    return True

                idx = await self._find_songcast_index(dev)
                if idx is None:
                    print(f"⚠ Songcast source not found on {name}; skipping source change")
                    return False

                try:
                    await prod.action("SetSourceIndex").async_call(aIndex=idx)
                except Exception:
                    await prod.action("SetSourceIndex").async_call(Value=idx)
                print(f"✓ {name} source set to Songcast (index {idx})")
                return True
            except Exception as e:
                print(f"✗ Failed to set {name} source: {e}")
                return False


        def _build_sender_uri(self, sender_udn, sender_name=None, sender_room=None):
            from urllib.parse import urlencode
            params = {}
            if sender_room:
                params["room"] = sender_room
            if sender_name:
                params["name"] = sender_name
            q = ("?" + urlencode(params)) if params else ""
            return f"ohSongcast://{sender_udn}{q}"

        async def _is_grouped(self, dev):
            try:
                recv = dev.device.service_id("urn:av-openhome-org:serviceId:Receiver")
                if recv is None:
                    return False
                try:
                    sres = await recv.action("Sender").async_call()
                    uri_val = (sres.get("Uri") or sres.get("uri") or "")
                    from urllib.parse import urlparse
                    if uri_val and urlparse(uri_val).scheme.lower() == "ohz":
                        return True
                except Exception:
                    pass
                try:
                    ts = await recv.action("TransportState").async_call()
                    state = (ts.get("TransportState") or ts.get("state") or "").lower()
                    return state in ("playing", "buffering", "connecting")
                except Exception:
                    return False
            except Exception:
                return False

        async def _receiver_join(self, receiver_dev, sender_dev, receiver_ip, receiver_udn, fallback_sender_udn, fallback_sender_name):
            try:
                recv = receiver_dev.device.service_id("urn:av-openhome-org:serviceId:Receiver")
                if recv is None:
                    return False
                try:
                    sender_room = await sender_dev.room()
                except Exception:
                    sender_room = None
                try:
                    sender_name = await sender_dev.name()
                except Exception:
                    sender_name = fallback_sender_name
                sender_udn = fallback_sender_udn

                candidate_uris = []
                uri = None
                metadata = None
                # Prefer sender's Sender info
                try:
                    ssvc = sender_dev.device.service_id("urn:av-openhome-org:serviceId:Sender")
                    if ssvc is not None:
                        sres = await ssvc.action("Sender").async_call()
                        uri = sres.get("Uri") or sres.get("uri")
                        metadata = sres.get("Metadata") or sres.get("metadata")
                        if uri:
                            candidate_uris.append(uri)
                except Exception:
                    uri = None
                    metadata = None
                if not uri:
                    uri = self._build_sender_uri(sender_udn, sender_name=sender_name, sender_room=sender_room)
                candidate_uris.append(uri)

                if metadata is None:
                    title = f"{sender_room or ''} - {sender_name or ''}".strip(" -")
                    metadata = (
                        "<?xml version=\"1.0\"?>"
                        "<DIDL-Lite xmlns=\"urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/\" xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:upnp=\"urn:schemas-upnp-org:metadata-1-0/upnp/\">"
                        "<item id=\"ohSongcast\" parentID=\"0\" restricted=\"true\">"
                        f"<dc:title>{title}</dc:title>"
                        "<upnp:class>object.item.audioItem</upnp:class>"
                        f"<upnp:artist>{sender_name or ''}</upnp:artist>"
                        f"<upnp:album>{sender_room or ''}</upnp:album>"
                        "<dc:publisher>OpenHome</dc:publisher>"
                        "</item>"
                        "</DIDL-Lite>"
                    )

                # Discover ohz via Receiver.Senders (short retries)
                ohz_uri = None
                for _ in range(6):
                    try:
                        slist = await recv.action("Senders").async_call()
                        raw_list = slist.get("SenderList") or slist.get("List") or slist.get("senders")
                        if isinstance(raw_list, str) and raw_list.strip():
                            root = ET.fromstring(raw_list)
                            items = [el for el in root.iter() if el.tag.endswith('item')]
                            exact = None; fallbacks = []
                            for it in items:
                                title = None
                                res_uris = []
                                for ch in it:
                                    tag = ch.tag; txt = ch.text or ''
                                    if tag.endswith('title'):
                                        title = txt.strip()
                                    elif tag.endswith('res') and txt.startswith('ohz://'):
                                        res_uris.append(txt)
                                if title and res_uris and ((sender_room and title == sender_room) or (sender_name and title == sender_name)):
                                    exact = res_uris[0]
                                    break
                                fallbacks.extend(res_uris)
                            ohz_uri = exact or (fallbacks[0] if fallbacks else None)
                        if ohz_uri:
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)
                if ohz_uri:
                    candidate_uris.insert(0, ohz_uri)
                elif sender_udn:
                    candidate_uris.insert(0, f"ohz://239.255.255.250:51972/{sender_udn}")
                print(f"Candidates: {candidate_uris}")

                # Try candidates
                ok = False
                for cand in candidate_uris:
                    try:
                        try:
                            await recv.action("Stop").async_call()
                        except Exception:
                            pass
                        if str(cand).lower().startswith("ohz://"):
                            # Prefer SOAP for ohz SetSender/Play to bypass metadata quirks
                            try:
                                url = f"http://{receiver_ip}:55178/{receiver_udn}/av.openhome.org-Receiver-1/control"
                                hdrs_set = {
                                    "SOAPACTION": '"urn:av-openhome-org:service:Receiver:1#SetSender"',
                                    "Content-Type": 'text/xml; charset="utf-8"'
                                }
                                msg_set = f"""<?xml version=\"1.0\" encoding=\"utf-8\"?>
    <s:Envelope s:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\" xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\">\n    <s:Body>\n        <u:SetSender xmlns:u=\"urn:av-openhome-org:service:Receiver:1\">\n            <Uri>{cand}</Uri>\n            <Metadata></Metadata>\n        </u:SetSender>\n    </s:Body>\n</s:Envelope>"""
                                requests.post(url, headers=hdrs_set, data=msg_set, timeout=3)
                                hdrs_play = {
                                    "SOAPACTION": '"urn:av-openhome-org:service:Receiver:1#Play"',
                                    "Content-Type": 'text/xml; charset="utf-8"'
                                }
                                msg_play = """<?xml version="1.0" encoding="utf-8"?>
    <s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
        <s:Body>
            <u:Play xmlns:u="urn:av-openhome-org:service:Receiver:1"></u:Play>
        </s:Body>
    </s:Envelope>"""
                                requests.post(url, headers=hdrs_play, data=msg_play, timeout=3)
                            except Exception:
                                # Fallback to API if SOAP fails
                                try:
                                    await recv.action("SetSender").async_call(Uri=cand, Metadata="")
                                    await recv.action("Play").async_call()
                                except Exception:
                                    pass
                        else:
                            # ohSongcast descriptor path via API
                            meta_arg = metadata or ""
                            try:
                                await recv.action("SetSender").async_call(Uri=cand, Metadata=meta_arg)
                            except Exception:
                                await recv.action("SetSender").async_call(Uri=cand, Metadata="")
                            try:
                                await recv.action("Play").async_call()
                            except Exception:
                                pass
                        # Poll briefly and only accept if grouped is truly active
                        for _ in range(8):
                            await asyncio.sleep(0.5)
                            try:
                                ts = await recv.action("TransportState").async_call()
                                state = (ts.get("TransportState") or ts.get("state") or "").lower()
                                grouped_now = await self._is_grouped(receiver_dev)
                                if self.debug:
                                    print(f"  State={state}, grouped={grouped_now}, cand={cand}")
                                if grouped_now or (str(cand).lower().startswith("ohz://") and state in ("playing", "buffering", "connecting")):
                                    ok = True
                                    uri = cand
                                    break
                            except Exception:
                                break
                        if ok:
                            break
                    except Exception:
                        continue
                print(f"✓ Receiver join attempted via Uri {uri}")
                try:
                    sres_final = await recv.action("Sender").async_call()
                    uri_final = (sres_final.get("Uri") or sres_final.get("uri") or "")
                    print(f"Final Receiver.Sender Uri: {uri_final}")
                except Exception:
                    pass
                # SOAP fallback: force ohz SetSender + Play
                try:
                    url = f"http://{receiver_ip}:55178/{receiver_udn}/av.openhome.org-Receiver-1/control"
                    default_ohz = f"ohz://239.255.255.250:51972/{sender_udn}"
                    hdrs_set = {
                        "SOAPACTION": '"urn:av-openhome-org:service:Receiver:1#SetSender"',
                        "Content-Type": 'text/xml; charset="utf-8"'
                    }
                    msg_set = f"""<?xml version=\"1.0\" encoding=\"utf-8\"?>
    <s:Envelope s:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\" xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\">\n    <s:Body>\n        <u:SetSender xmlns:u=\"urn:av-openhome-org:service:Receiver:1\">\n            <Uri>{default_ohz}</Uri>\n            <Metadata></Metadata>\n        </u:SetSender>\n    </s:Body>\n</s:Envelope>"""
                    requests.post(url, headers=hdrs_set, data=msg_set, timeout=3)
                    hdrs_play = {
                        "SOAPACTION": '"urn:av-openhome-org:service:Receiver:1#Play"',
                        "Content-Type": 'text/xml; charset="utf-8"'
                    }
                    msg_play = """<?xml version="1.0" encoding="utf-8"?>
    <s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
        <s:Body>
            <u:Play xmlns:u="urn:av-openhome-org:service:Receiver:1"></u:Play>
        </s:Body>
    </s:Envelope>"""
                    requests.post(url, headers=hdrs_play, data=msg_play, timeout=3)
                except Exception:
                    pass
                return True
            except Exception as e:
                print(f"⚠ Receiver join failed: {e}")
                return False

        async def create_songcast_group_async(self):
            print("=== Linn OpenHome Songcast Group Creator ===", flush=True)
            if not self.receivers:
                print("No receivers specified.")
                return False

            # Init sender and resolve name from device.xml
            try:
                mdev = await self._init_dev(self.sender_ip, self.sender_udn)
            except Exception as e:
                print(f"✗ Sender initialization failed: {e}")
                return False
            self.sender_name = await self._resolve_device_name(mdev, fallback=self.sender_ip)
            print(f"Sender: {self.sender_name} ({self.sender_ip})")
            for sl in self.receivers:
                print(f"Receiver:  {sl.get('ip')} ({sl.get('ip')})")
            print("-" * 50)

            # Wake sender
            print("\n1. Waking sender from standby...")
            await self.wake_device(mdev, self.sender_name)
            await asyncio.sleep(1.0)

            all_ok = True
            for sl in self.receivers:
                s_ip = sl.get("ip")
                s_udn = sl.get("udn")
                s_name = None
                try:
                    sdev = await self._init_dev(s_ip, s_udn)
                except Exception as e:
                    print(f"✗ Receiver init failed: {e}")
                    all_ok = False
                    continue


                # Resolve receiver name from device.xml; fallback to IP
                s_name = await self._resolve_device_name(sdev, fallback=s_ip)
                print(f"\n=== Configuring receiver {s_name} ({s_ip}) ===")
                print("2. Waking receiver from standby...")
                await self.wake_device(sdev, s_name)
                await asyncio.sleep(1.0)

                print("3. Ensuring receiver source is Songcast...")
                await self.set_source_to_songcast(sdev, s_name)
                await asyncio.sleep(1.0)
                # Small status line: report current source index/name
                cur_info = await self._get_current_source_info(sdev)
                if cur_info:
                    print(f"Status: {s_name} source index {cur_info['index']} ({cur_info['name']})")
                else:
                    print(f"Status: {s_name} source unknown")

                print("4. Joining receiver to sender...")
                joined = await self._receiver_join(sdev, mdev, s_ip, s_udn, self.sender_udn, self.sender_name)
                if not joined:
                    print("⚠ Receiver join did not complete; receiver UI may prompt for sender selection.")

                print("5. Verifying Songcast configuration...")
                grouped = await self._is_grouped(sdev)
                if grouped:
                    print("✓ SUCCESS: Receiver actively grouped (ohz/transport active)")
                else:
                    print("⚠ Receiver not grouped (no ohz/transport idle)")
                    all_ok = False

            print("\n" + "=" * 50)
            if all_ok:
                print("✓ SUCCESS: Songcast group configured for all receivers!")
                print(f"\n🎵 Play audio on {self.sender_name} and it should stream to receivers")
                return True
            else:
                print("⚠ Songcast group configuration incomplete for one or more receivers")
                return False

def main():
    parser = argparse.ArgumentParser(description='Create Linn OpenHome Songcast group')
    parser.add_argument('--sender-ip', default=None)
    parser.add_argument('--sender-udn', default=None)
    parser.add_argument('--receiver-ip', action='append', default=None)
    parser.add_argument('--receiver-udn', action='append', default=None)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    # Load .env configuration
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
    devices_map, env_sender_id, env_receiver_ids = _load_env_devices(env_path)

    # Resolve sender from args or env
    sender_ip = args.sender_ip
    sender_udn = args.sender_udn
    if (not sender_ip or not sender_udn) and env_sender_id:
        dev = devices_map.get(env_sender_id)
        if dev:
            sender_ip = sender_ip or dev.get('ip')
            sender_udn = sender_udn or dev.get('udn')

    # Resolve receivers from args or env
    receiver_ips = args.receiver_ip or []
    receiver_udns = args.receiver_udn or []
    receivers = []
    if receiver_ips:
        # Pair with provided UDNs (pad missing with last-known or None)
        for i, ip in enumerate(receiver_ips):
            udn = receiver_udns[i] if (receiver_udns and i < len(receiver_udns)) else (receiver_udns[-1] if receiver_udns else None)
            receivers.append({"ip": ip, "udn": udn})
    elif env_receiver_ids:
        for mid in env_receiver_ids:
            dev = devices_map.get(mid)
            if dev:
                receivers.append({"ip": dev.get('ip'), "udn": dev.get('udn')})

    # Validate sender presence
    if not sender_ip or not sender_udn:
        print("✗ Missing sender IP/UDN. Provide --sender-ip/--sender-udn or set SONGCAST_SENDER in .env")
        sys.exit(2)

    grouper = LinnSongcastGrouper(sender_ip, sender_udn, receivers, args.debug)
    success = asyncio.run(grouper.create_songcast_group_async())
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()