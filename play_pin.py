#!/usr/bin/env python3
"""
Linn OpenHome Pin Player

Description:
- Invokes a specified Pin (by 1-based index) on a Linn DSM.
- Retrieves and prints Pin metadata (title, description, artwork).

Protocols/Services:
- Uses OpenHome Pins:1 service via SOAP at
    http://<ip>:55178/<udn>/av.openhome.org-Pins-1/control
    - InvokeId: start playback for the selected pin
    - GetIdArray: retrieve device pin ID list (JSON)
    - ReadList: fetch metadata for a given pin ID (JSON in <List>)

Usage:
        python3 play_pin.py <ip_address> <udn> <pin_number>

Example:
        python3 play_pin.py 172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f 2

Notes:
- Pin numbers are 1-based indices as shown in the device UI/app.
- Description output is wrapped for readability.
"""

import requests
import json
import xml.etree.ElementTree as ET
import sys
import textwrap

def invoke_pin(ip, udn, pin_id):
    """Invoke a specific pin on the Linn device.

    Sends a Pins:1 InvokeId SOAP request to start playback of the content
    associated with the provided 1-based pin index.
    """
    url = f'http://{ip}:55178/{udn}/av.openhome.org-Pins-1/control'
    hdrs = {'SOAPACTION': '"urn:av-openhome-org:service:Pins:1#InvokeId"'}
    msg = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
   <s:Body>
      <u:InvokeId xmlns:u="urn:av-openhome-org:service:Pins:1">
         <Id>{pin_id}</Id>
      </u:InvokeId>
   </s:Body>
</s:Envelope>"""

    try:
        resp = requests.post(url, headers=hdrs, data=msg, timeout=10)
        if resp.status_code == 200:
            print(f"✓ Pin {pin_id} invoked successfully")
            return True
        else:
            print(f"✗ Error invoking pin {pin_id}: HTTP {resp.status_code}")
            print(f"Response: {resp.text}")
            return False
    except Exception as e:
        print(f"✗ Error invoking pin {pin_id}: {e}")
        return False

def get_pin_info(ip, udn, pin_index):
    """
    Get information (metadata) for a specific pin by 1-based index.

    Workflow:
    1. GetIdArray → returns a JSON array of device pin IDs.
    2. Map pin_index (1-based) to an ID from that array.
    3. ReadList → request metadata for the selected ID (JSON within <List>).

    Returns a dict with keys: title, description, artworkUri; or None on error.
    """
    print(f"Getting info for pin {pin_index}...")
    base_url = f'http://{ip}:55178/{udn}/av.openhome.org-Pins-1/control'

    # Step 1: GetIdArray
    try:
        hdrs = {'SOAPACTION': '"urn:av-openhome-org:service:Pins:1#GetIdArray"'}
        msg = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
   <s:Body>
      <u:GetIdArray xmlns:u="urn:av-openhome-org:service:Pins:1" />
   </s:Body>
</s:Envelope>"""
        resp = requests.post(base_url, headers=hdrs, data=msg, timeout=5)
        if resp.status_code != 200:
            print(f"Error getting pin ID array: HTTP {resp.status_code}")
            print(f"Response: {resp.text}")
            return None
        root = ET.fromstring(resp.text)
        id_array_json = None
        for elem in root.iter():
            if elem.tag.endswith('IdArray'):
                id_array_json = elem.text
                break
        if not id_array_json:
            print("Could not parse IdArray from response")
            return None
        try:
            id_array = json.loads(id_array_json)
        except Exception:
            print("Invalid IdArray JSON in response")
            return None
        # Convert pin index (1-based) to array index (0-based)
        idx = (pin_index - 1)
        if idx < 0 or idx >= len(id_array):
            print("Pin index out of range")
            return None
        pin_id = id_array[idx]
    except Exception as e:
        print(f"Error getting pin ID array: {e}")
        return None

    # Step 2: ReadList for the selected pin ID
    try:
        hdrs = {'SOAPACTION': '"urn:av-openhome-org:service:Pins:1#ReadList"'}
        ids_payload = json.dumps([pin_id])
        msg = f"""<?xml version=\"1.0\" encoding=\"utf-8\"?>
<s:Envelope s:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\" xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\">
   <s:Body>
      <u:ReadList xmlns:u=\"urn:av-openhome-org:service:Pins:1\">
         <Ids>{ids_payload}</Ids>
      </u:ReadList>
   </s:Body>
</s:Envelope>"""
        resp = requests.post(base_url, headers=hdrs, data=msg, timeout=5)
        if resp.status_code != 200:
            print(f"Error reading pin metadata: HTTP {resp.status_code}")
            print(f"Response: {resp.text}")
            return None
        root = ET.fromstring(resp.text)
        list_json = None
        for elem in root.iter():
            if elem.tag.endswith('List'):
                list_json = elem.text
                break
        if not list_json:
            print("Could not parse List from response")
            return None
        try:
            items = json.loads(list_json)
        except Exception:
            print("Invalid List JSON in response")
            return None
        if not items:
            return None
        item = items[0] if isinstance(items, list) else items
        return {
            'title': item.get('title') or 'Unknown',
            'description': item.get('description') or '',
            'artworkUri': item.get('artworkUri') or ''
        }
    except Exception as e:
        print(f"Error getting pin info: {e}")
        return None

def main():
    if len(sys.argv) == 1:
        print("Usage: python3 play_pin.py <ip_address> <udn> <pin_number>")
        print("\nExample:")
        print("python3 play_pin.py 172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f 2")
        return
    
    if len(sys.argv) < 4:
        print("Error: IP address, UDN, and pin number are required")
        return
    
    ip = sys.argv[1]
    udn = sys.argv[2]
    
    print(f"=== Linn OpenHome Pin Player ===")
    print(f"IP:  {ip}")
    print(f"UDN: {udn}")
    print("-" * 40)
    
    try:
        pin_number = int(sys.argv[3])
    except ValueError:
        print("Error: Pin number must be an integer")
        return
    
    print(f"Pin: {pin_number}")

    print(f"\nInvoking pin {pin_number}...")
    success = invoke_pin(ip, udn, pin_number)
    
    if success:
        print(f"✓ Pin {pin_number} has been invoked")
        print("The device should now be playing the content associated with this pin")
        returned_info = get_pin_info(ip, udn, pin_number)
        if returned_info:
            print("\nPin Info")
            print("-" * 40)
            print(f"Pin: {pin_number}")
            title = returned_info.get('title') or 'Unknown'
            print(f"Title: {title}")
            desc = (returned_info.get('description') or '').strip()
            if desc:
                print("Description:")
                print(textwrap.fill(desc, width=80))
            else:
                print("Description: None")
            artwork = returned_info.get('artworkUri') or 'None'
            print(f"Artwork: {artwork}")
        else:
            print("Could not retrieve pin info.")
    else:
        print(f"✗ Failed to invoke pin {pin_number}")
        print("\nTroubleshooting:")
        print("- Check that the pin number exists and is configured")
        print("- Verify the device is powered on and responsive")
        print("- Try listing available pins first")

if __name__ == "__main__":
    main()