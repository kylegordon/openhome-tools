#!/usr/bin/env python3
"""
Linn DSM Source Query (per-device visibility)

Purpose:
- Enumerate Product:4 sources for a Linn DSM device
- Mark each source as visible/hidden for that specific device
- Highlight the currently selected source index

Usage:
    python3 query_sources.py <IP_ADDRESS> <UDN>

Example:
    python3 query_sources.py 172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f

Notes:
- Visibility is per device. Sources such as Roon Ready, Spotify, ARC, HDMI1–4,
    TOSLINK, and AirPlay may be hidden depending on device configuration.
- Hidden detection reads Product:4 "Visible" and accepts values like
    "true/false", "1/0", and "yes/no".
- Source naming prefers the "Name" tag when present; falls back to "SystemName".
- To find a device UDN: python3 find_linn_udn.py <IP_ADDRESS>
- Requires the "requests" package (install in your venv if needed).
"""

import requests
import xml.etree.ElementTree as ET
import sys

def get_source_count(ip, udn):
    """Get the total number of sources available on the device.

    Queries Product:4 "SourceCount" via SOAP at
    http://<ip>:55178/<udn>/av.openhome.org-Product-4/control.
    """
    url = f'http://{ip}:55178/{udn}/av.openhome.org-Product-4/control'
    hdrs = {'SOAPACTION': '"urn:av-openhome-org:service:Product:4#SourceCount"'}
    msg = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
   <s:Body>
      <u:SourceCount xmlns:u="urn:av-openhome-org:service:Product:4" />
   </s:Body>
</s:Envelope>"""

    try:
        resp = requests.post(url, headers=hdrs, data=msg, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            for elem in root.iter():
                if elem.tag.endswith('Value'):
                    return int(elem.text)
        else:
            print(f"Error getting source count: HTTP {resp.status_code}")
            print(f"Response: {resp.text}")
        return None
    except Exception as e:
        print(f"Error getting source count: {e}")
        return None

def get_source_details(ip, udn, source_index):
    """Get details for a specific source by index.

    Queries Product:4 "Source" for the given Index and extracts:
    - Name: prefers tag "Name"; falls back to "SystemName".
    - Type: the source type (e.g., Radio, Receiver, Hdmi).
    - Visible: per-device visibility; accepts true/false, 1/0, yes/no.
    """
    url = f'http://{ip}:55178/{udn}/av.openhome.org-Product-4/control'
    hdrs = {'SOAPACTION': '"urn:av-openhome-org:service:Product:4#Source"'}
    msg = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
   <s:Body>
      <u:Source xmlns:u="urn:av-openhome-org:service:Product:4">
         <Index>{source_index}</Index>
      </u:Source>
   </s:Body>
</s:Envelope>"""

    try:
        resp = requests.post(url, headers=hdrs, data=msg, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            source_info = {'name': 'Unknown', 'type': 'Unknown', 'visible': True}
            
            for elem in root.iter():
                # Prefer 'Name'; fall back to 'SystemName'
                if elem.tag.endswith('Name'):
                    source_info['name'] = elem.text or f'Source {source_index}'
                elif elem.tag.endswith('SystemName'):
                    source_info['name'] = elem.text or f'Source {source_index}'
                elif elem.tag.endswith('Type'):
                    source_info['type'] = elem.text or 'Unknown'
                elif elem.tag.endswith('Visible'):
                    txt = (elem.text or '').strip().lower()
                    if txt in ('true', '1', 'yes'):
                        source_info['visible'] = True
                    elif txt in ('false', '0', 'no'):
                        source_info['visible'] = False
                    else:
                        # Default to visible if value is unexpected/missing
                        source_info['visible'] = True
            
            return source_info
        else:
            print(f"Error getting source {source_index}: HTTP {resp.status_code}")
            return {'name': f'Error-{source_index}', 'type': 'Error', 'visible': False}
    except Exception as e:
        print(f"Error getting source {source_index}: {e}")
        return {'name': f'Error-{source_index}', 'type': 'Error', 'visible': False}

def get_current_source(ip, udn):
    """Get the currently selected source index.

    Queries Product:4 "SourceIndex" via SOAP and returns the active index.
    """
    url = f'http://{ip}:55178/{udn}/av.openhome.org-Product-4/control'
    hdrs = {'SOAPACTION': '"urn:av-openhome-org:service:Product:4#SourceIndex"'}
    msg = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
   <s:Body>
      <u:SourceIndex xmlns:u="urn:av-openhome-org:service:Product:4" />
   </s:Body>
</s:Envelope>"""

    try:
        resp = requests.post(url, headers=hdrs, data=msg, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            for elem in root.iter():
                if elem.tag.endswith('Value'):
                    return int(elem.text)
        return -1
    except Exception as e:
        print(f"Error getting current source: {e}")
        return -1

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 query_sources.py <ip_address> <udn>")
        print("\nExample:")
        print("python3 query_sources.py 172.24.32.141 4c494e4e-0026-0f22-5661-01531488013f")
        print("\nTo find UDN: python3 find_linn_udn.py <ip_address>")
        print("\nNotes:")
        print("- Visibility is per device; hidden sources are shown as (HIDDEN)")
        print("- Current source is marked with <- CURRENT")
        return
    
    ip = sys.argv[1]
    udn = sys.argv[2]
    
    print(f"=== Linn Device Source Query ===")
    print(f"IP:  {ip}")
    print(f"UDN: {udn}")
    print("-" * 40)
    
    # Get source count
    source_count = get_source_count(ip, udn)
    if source_count is None:
        print("Failed to get source count. Check IP and UDN.")
        return
    
    print(f"Total Sources: {source_count}")
    
    # Get current source
    current_source = get_current_source(ip, udn)
    if current_source >= 0:
        print(f"Current Source: {current_source}")
    
    print("\nAvailable Sources:")
    print("-" * 40)
    
    # Query each source
    for i in range(source_count):
        source_info = get_source_details(ip, udn, i)
        current_marker = " <- CURRENT" if i == current_source else ""
        visible_marker = "" if source_info['visible'] else " (HIDDEN)"
        
        print(f"[{i}] {source_info['name']} ({source_info['type']}){visible_marker}{current_marker}")
    
    print(f"\n" + "=" * 40)
    print("Source Index Reference:")
    print("0 = Analog, 1 = Digital, 2 = Radio")
    print("3 = Playlist, 4 = UPnP, 5 = Songcast")
    print("(Indices and types may vary by device/firmware)")

if __name__ == "__main__":
    main()