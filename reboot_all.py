import os
import re
import sys
import requests

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")

DEVICE_LINE_RE = re.compile(r"^DEVICE_\d+=(\S+)\s+(\S+)")

def reboot_device(ip, udn):
    """Reboot a Linn device using Volkano service"""
    url = f'http://{ip}:55178/{udn}/linn.co.uk-Volkano-1/control'
    hdrs = {'SOAPACTION': '"urn:linn-co-uk:service:Volkano:1#Reboot"'}
    msg = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
   <s:Body>
      <u:Reboot xmlns:u="urn:linn-co-uk:service:Volkano:1" />
   </s:Body>
</s:Envelope>"""
    
    try:
        resp = requests.post(url, headers=hdrs, data=msg, timeout=5)
        print(f"Reboot command sent to {ip} ({udn}): [{resp.status_code}]")
    except Exception as e:
        print(f"Failed to reboot {ip} ({udn}): {e}")

def main():
    if not os.path.exists(ENV_PATH):
        print(f".env file not found at {ENV_PATH}")
        sys.exit(1)
    devices = []
    with open(ENV_PATH) as f:
        for line in f:
            m = DEVICE_LINE_RE.match(line.strip())
            if m:
                ip, udn = m.groups()
                devices.append((ip, udn))
    if not devices:
        print("No devices found in .env")
        sys.exit(1)
    
    # Reboot all devices
    for ip, udn in devices:
        reboot_device(ip, udn)

if __name__ == "__main__":
    main()
