#!/usr/bin/env python3
"""
Linn OpenHome Songcast Group Creator

Purpose:
- Create a Songcast group with one leader (sender) and one or more followers (receivers)
    using the openhomedevice library.

Usage (with .env):
    .venv/bin/python experimental/songcast_group.py [--leader-songcast] [--debug]

Configuration (.env):
    # Map devices once, then run without flags
    DEVICE_1=<MASTER_IP> <MASTER_UDN>
    DEVICE_2=<MEMBER_1_IP> <MEMBER_1_UDN>
    DEVICE_3=<MEMBER_2_IP> <MEMBER_2_UDN>
    SONGCAST_MASTER=DEVICE_1
    SONGCAST_MEMBERS=DEVICE_2,DEVICE_3

Alternative (override .env if needed):
    source .venv/bin/activate && python experimental/songcast_group.py \
        --master-ip <IP_ADDRESS> --master-udn <UDN> \
        --slave-ip <IP_ADDRESS> --slave-udn <UDN> \
        [--leader-songcast] [--debug]

Example (.env-driven, minimal):
    .venv/bin/python experimental/songcast_group.py --leader-songcast --debug

Notes:
- Uses openhomedevice to control Product:4 and Receiver services.
- Ensures follower source is Songcast and joins leader via Receiver.SetSender.
- Prefers ohz URIs discovered via Receiver.Senders; falls back to ohSongcast descriptor.
- Supports .env configuration: define DEVICE_n entries, SONGCAST_MASTER and SONGCAST_MEMBERS.
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
    master_id = None
    member_ids = []
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
                elif key == 'SONGCAST_MASTER':
                    master_id = val.strip()
                elif key == 'SONGCAST_MEMBERS':
                    member_ids = [v.strip() for v in val.split(',') if v.strip()]
    except Exception:
        pass
    return devices, master_id, member_ids

class LinnSongcastGrouper:
        def __init__(self, master_ip, master_udn, slaves, debug=False):
            self.master_ip = master_ip
            self.master_udn = master_udn
            # Master name will be resolved from device.xml (friendly_name/Product.Name)
            self.master_name = None
            self.slaves = slaves or []
            self.debug = debug
            self.force_leader_songcast = False

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

        async def set_leader_to_songcast_sender(self, dev, name):
            print(f"Setting {name} source to Songcast Sender...")
            try:
                prod = dev.device.service_id("urn:av-openhome-org:serviceId:Product")
                if prod is None:
                    raise RuntimeError("Product service not available")
                sc = await prod.action("SourceCount").async_call()
                count = int(sc.get("Value") or 8)
                sender_idx = None
                for i in range(count):
                    try:
                        sres = await prod.action("Source").async_call(Index=i)
                        typ = (sres.get("Type") or "").lower()
                        name_s = (sres.get("Name") or sres.get("SystemName") or "").lower()
                        vis = (sres.get("Visible") or "true").strip().lower()
                        if vis in ("true", "1", "yes") and ("sender" in typ or ("songcast" in name_s and "sender" in name_s)):
                            sender_idx = i
                            break
                    except Exception:
                        continue
                if sender_idx is None:
                    print("⚠ Could not find Songcast Sender source; leaving leader source unchanged")
                    return False
                try:
                    await prod.action("SetSourceIndex").async_call(aIndex=sender_idx)
                except Exception:
                    await prod.action("SetSourceIndex").async_call(Value=sender_idx)
                print(f"✓ {name} source set to Songcast Sender (index {sender_idx})")
                return True
            except Exception as e:
                print(f"✗ Failed to set {name} to Songcast Sender: {e}")
                return False

        def _build_sender_uri(self, leader_udn, leader_name=None, leader_room=None):
            from urllib.parse import urlencode
            params = {}
            if leader_room:
                params["room"] = leader_room
            if leader_name:
                params["name"] = leader_name
            q = ("?" + urlencode(params)) if params else ""
            return f"ohSongcast://{leader_udn}{q}"

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

        async def _receiver_join(self, follower_dev, leader_dev, follower_ip, follower_udn, fallback_leader_udn, fallback_leader_name):
            try:
                recv = follower_dev.device.service_id("urn:av-openhome-org:serviceId:Receiver")
                if recv is None:
                    return False
                try:
                    leader_room = await leader_dev.room()
                except Exception:
                    leader_room = None
                try:
                    leader_name = await leader_dev.name()
                except Exception:
                    leader_name = fallback_leader_name
                leader_udn = fallback_leader_udn

                candidate_uris = []
                uri = None
                metadata = None
                # Prefer leader's Sender info
                try:
                    ssvc = leader_dev.device.service_id("urn:av-openhome-org:serviceId:Sender")
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
                    uri = self._build_sender_uri(leader_udn, leader_name=leader_name, leader_room=leader_room)
                candidate_uris.append(uri)

                if metadata is None:
                    title = f"{leader_room or ''} - {leader_name or ''}".strip(" -")
                    metadata = (
                        "<?xml version=\"1.0\"?>"
                        "<DIDL-Lite xmlns=\"urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/\" xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:upnp=\"urn:schemas-upnp-org:metadata-1-0/upnp/\">"
                        "<item id=\"ohSongcast\" parentID=\"0\" restricted=\"true\">"
                        f"<dc:title>{title}</dc:title>"
                        "<upnp:class>object.item.audioItem</upnp:class>"
                        f"<upnp:artist>{leader_name or ''}</upnp:artist>"
                        f"<upnp:album>{leader_room or ''}</upnp:album>"
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
                                if title and res_uris and ((leader_room and title == leader_room) or (leader_name and title == leader_name)):
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
                elif leader_udn:
                    candidate_uris.insert(0, f"ohz://239.255.255.250:51972/{leader_udn}")
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
                                url = f"http://{follower_ip}:55178/{follower_udn}/av.openhome.org-Receiver-1/control"
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
                                grouped_now = await self._is_grouped(follower_dev)
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
                    url = f"http://{follower_ip}:55178/{follower_udn}/av.openhome.org-Receiver-1/control"
                    default_ohz = f"ohz://239.255.255.250:51972/{leader_udn}"
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
            if not self.slaves:
                print("No followers specified.")
                return False

            # Init leader and resolve name from device.xml
            try:
                mdev = await self._init_dev(self.master_ip, self.master_udn)
            except Exception as e:
                print(f"✗ Leader initialization failed: {e}")
                return False
            self.master_name = await self._resolve_device_name(mdev, fallback=self.master_ip)
            print(f"Leader: {self.master_name} ({self.master_ip})")
            for sl in self.slaves:
                print(f"Follower:  {sl.get('ip')} ({sl.get('ip')})")
            print("-" * 50)

            # Wake leader
            print("\n1. Waking leader from standby...")
            await self.wake_device(mdev, self.master_name)
            await asyncio.sleep(1.0)

            # Optionally switch leader to Songcast Sender
            if self.force_leader_songcast:
                print("1b. Switching leader to Songcast Sender...")
                await self.set_leader_to_songcast_sender(mdev, self.master_name)
                await asyncio.sleep(1.0)

            all_ok = True
            for sl in self.slaves:
                s_ip = sl.get("ip")
                s_udn = sl.get("udn")
                s_name = None
                try:
                    sdev = await self._init_dev(s_ip, s_udn)
                except Exception as e:
                    print(f"✗ Follower init failed: {e}")
                    all_ok = False
                    continue


                # Resolve follower name from device.xml; fallback to IP
                s_name = await self._resolve_device_name(sdev, fallback=s_ip)
                print(f"\n=== Configuring follower {s_name} ({s_ip}) ===")
                print("2. Waking follower from standby...")
                await self.wake_device(sdev, s_name)
                await asyncio.sleep(1.0)

                print("3. Ensuring follower source is Songcast...")
                await self.set_source_to_songcast(sdev, s_name)
                await asyncio.sleep(1.0)
                # Small status line: report current source index/name
                cur_info = await self._get_current_source_info(sdev)
                if cur_info:
                    print(f"Status: {s_name} source index {cur_info['index']} ({cur_info['name']})")
                else:
                    print(f"Status: {s_name} source unknown")

                print("4. Joining follower to leader...")
                joined = await self._receiver_join(sdev, mdev, s_ip, s_udn, self.master_udn, self.master_name)
                if not joined:
                    print("⚠ Receiver join did not complete; follower UI may prompt for leader selection.")

                print("5. Verifying Songcast configuration...")
                grouped = await self._is_grouped(sdev)
                if grouped:
                    print("✓ SUCCESS: Follower actively grouped (ohz/transport active)")
                else:
                    print("⚠ Follower not grouped (no ohz/transport idle)")
                    all_ok = False

            print("\n" + "=" * 50)
            if all_ok:
                print("✓ SUCCESS: Songcast group configured for all followers!")
                print(f"\n🎵 Play audio on {self.master_name} and it should stream to followers")
                return True
            else:
                print("⚠ Songcast group configuration incomplete for one or more followers")
                return False

def main():
    parser = argparse.ArgumentParser(description='Create Linn OpenHome Songcast group')
    parser.add_argument('--master-ip', default=None)
    parser.add_argument('--master-udn', default=None)
    parser.add_argument('--slave-ip', action='append', default=None)
    parser.add_argument('--slave-udn', action='append', default=None)
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--leader-songcast', action='store_true', help='Switch leader to Songcast Sender before joining')
    args = parser.parse_args()

    # Load .env configuration
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
    devices_map, env_master_id, env_member_ids = _load_env_devices(env_path)

    # Resolve master from args or env
    master_ip = args.master_ip
    master_udn = args.master_udn
    if (not master_ip or not master_udn) and env_master_id:
        dev = devices_map.get(env_master_id)
        if dev:
            master_ip = master_ip or dev.get('ip')
            master_udn = master_udn or dev.get('udn')

    # Resolve members from args or env
    slave_ips = args.slave_ip or []
    slave_udns = args.slave_udn or []
    slaves = []
    if slave_ips:
        # Pair with provided UDNs (pad missing with last-known or None)
        for i, ip in enumerate(slave_ips):
            udn = slave_udns[i] if (slave_udns and i < len(slave_udns)) else (slave_udns[-1] if slave_udns else None)
            slaves.append({"ip": ip, "udn": udn})
    elif env_member_ids:
        for mid in env_member_ids:
            dev = devices_map.get(mid)
            if dev:
                slaves.append({"ip": dev.get('ip'), "udn": dev.get('udn')})

    # Validate master presence
    if not master_ip or not master_udn:
        print("✗ Missing master IP/UDN. Provide --master-ip/--master-udn or set SONGCAST_MASTER in .env")
        sys.exit(2)

    grouper = LinnSongcastGrouper(master_ip, master_udn, slaves, args.debug)
    grouper.force_leader_songcast = bool(args.leader_songcast)
    success = asyncio.run(grouper.create_songcast_group_async())
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()