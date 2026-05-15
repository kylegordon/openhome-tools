# OpenHome Tools - AI Agent Instructions

## Project Overview

Command-line utilities for controlling Linn DSM network audio players via the OpenHome protocol (UPnP/SOAP-based). Core functionality: device discovery, now-playing queries, Pin invocation, source querying, and Songcast multi-room grouping.

## CRITICAL: Research-First Development

**ALWAYS check documentation and existing code BEFORE implementing ANY solution.**

### Pre-Implementation Checklist (MANDATORY)

1. **Search existing codebase** - Use `grep_search` or `semantic_search` to find similar implementations
   - Check root scripts for working patterns
   - Search for existing reboot/Volkano-related helpers (e.g., look for "reboot", "Volkano", or `linn.co.uk-Volkano-1` in script names and code)
   - Look for the same service names, action names, or operations

2. **Verify service details** - Don't assume, confirm:
   - Service names (e.g., `Volkano` for reboot, NOT `Product`)
   - Action names (e.g., `Reboot` action is in `linn.co.uk-Volkano-1`)
   - Required parameters and their types
   - Correct SOAP action URNs

3. **Test thoroughly** - Write tests FIRST, then implement:
   - Create standalone unit tests for parsing/formatting logic
   - Test with actual venv python (`/path/to/.venv/bin/python`)
   - Verify the script runs end-to-end before claiming success
   - Use output capture workaround (`> output.txt 2>&1; cat output.txt`)

4. **Don't guess** - If uncertain about an API or service:
   - Search for usage examples in existing scripts
   - Check external documentation links (see External Documentation section)
   - Look for comments in existing code explaining why certain approaches are used

### Common Mistakes to Avoid

- ❌ Assuming `Product` service has all device operations (it doesn't, check `Volkano` for reboot)
- ❌ Using wrong constructor signatures (e.g., `Device(location_url)` NOT `Device(ip, udn)`)
- ❌ Claiming success without running the actual script
- ❌ Using async when SOAP requests are simpler and don't require it
- ❌ Ignoring existing working implementations already in the repository (search before re-implementing)

## Architecture & Key Patterns

### Device Communication
- **Protocol Stack**: OpenHome over UPnP/SOAP + LPEC (Linn Protocol for Eventing and Control)
- **Primary Port**: 55178 (HTTP/SOAP control), 23 (telnet/LPEC for discovery)
- **Device Identification**: IP address + UDN (Unique Device Name, UUID format)
- **URL Structure**: `http://<IP>:55178/<UDN>/<service-path>/control`

### Python Environment & Dependencies
- **Virtual Environment Required**: All scripts expect `.venv` in project root
- **Critical Dependencies**: `openhomedevice` (async OpenHome client), `requests` (SOAP), standard lib (`asyncio`, `xml.etree.ElementTree`, `argparse`)
- **Python Version**: 3.7+ required for async/await support
- **Invocation Pattern**: `.venv/bin/python script.py` OR `source .venv/bin/activate && python script.py`

### Configuration Pattern
- **`.env` File**: Device configurations stored as `DEVICE_N=<IP> <UDN>` entries
- **Songcast Config**: `SONGCAST_MASTER=DEVICE_1` and `SONGCAST_MEMBERS=DEVICE_2,DEVICE_3`
- **Loading**: Scripts parse `.env` at startup, support both env-driven and CLI argument modes
- **Example**: `DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f`

### Async/Await Pattern
- **All device interactions are async**: Use `asyncio.run()` in main, `await` for all device calls
- **Device Init Pattern**: `dev = Device(...)` → `await dev.init()` → operations → no explicit cleanup
- **Service Access**: `dev.device.service_id("urn:av-openhome-org:serviceId:Product")` → `await service.action("MethodName").async_call(param=value)`
- **Timeouts**: Wrap service calls in `asyncio.wait_for(call, timeout=2.0)` for Songcast/Receiver queries

### Key OpenHome Services
- **Product:4** - Source selection (`SourceCount`, `Source`, `SetSourceIndex`), standby control
- **Receiver:1** - Songcast follower (`SetSender`, `Sender`, `TransportState`, `Status`)
- **Sender:1** - Songcast leader (`Sender` returns `Uri`/`Metadata`)
- **Pins:1** - Presets/favorites (`InvokeId`, `GetIdArray`, `ReadList`)
- **Info** - Track metadata (`TrackTitle`, `Metatext` for radio stations)
- **Volkano:1** - Device management (`Reboot` action for rebooting devices - NOT in Product service!)

### Songcast Multi-Room Architecture
- **ohz:// URIs** - Preferred multicast streaming protocol (port 51972, `ohz://239.255.255.250:51972/...`)
- **ohSongcast:// URIs** - Fallback descriptor format with room/name query params
- **Leader Discovery**: Query follower's `Receiver.Sender()` Uri, parse for leader UDN/room/name
- **Grouping Flow**: Wake devices → Set follower source to Songcast (find index via `Product.Source`) → Call `Receiver.SetSender(Uri, Metadata)` → Poll `TransportState` for "playing"
- **Verification**: Check `Sender` Uri scheme is `ohz` OR `TransportState` is "playing"/"buffering"

## Development Workflows

### Terminal Output Workaround
**CRITICAL**: Pipe all terminal commands to `output.txt` (overwrite mode) and read from file:
```bash
.venv/bin/python script.py --debug > output.txt 2>&1
cat output.txt
```
*Reason*: Current Copilot terminal output reading has reliability issues.

### Testing/Running Scripts
- **Tasks**: Use VS Code tasks (`Run now_playing`, `Run songcast_group join`) for common operations
- **Direct Invocation**: `.venv/bin/python <script>.py [args]` (tasks in `.vscode/tasks.json` show hardcoded paths—adjust for local workspace)
- **Device Discovery**: Start with `find_linn_udn.py <IP>` to get UDN for new devices
- **Debugging**: Add `--debug` flag to scripts for verbose SOAP/service call output

### Common Code Patterns
- **Device Name Resolution**: Try `await dev.name()` (Product.Name), fallback to friendly_name from device.xml, fallback to IP
- **Standby Check**: `await dev.is_in_standby()` → `await dev.set_standby(False)` if True
- **Source Iteration**: Query `Product.SourceCount` → loop 0..count-1 → `Product.Source(Index=i)` → check `Type`/`Name`/`Visible`
- **SOAP Envelope**: Use requests with `SOAPACTION` header, XML body with `<s:Envelope>` → `<s:Body>` → `<u:ActionName xmlns:u="urn:...">`
- **Error Handling**: Catch exceptions per-service-call, provide fallback values (name→IP, metadata→empty)

### File Organization
- **Root Scripts**: Main CLI tools (`find_linn_udn.py`, `now_playing.py`, `play_pin.py`, `query_sources.py`, `songcast_group.py`)
- **`experimental/`**: Work-in-progress variants (e.g., `songcast_group.py.working.ai2`)
- **`.env`**: User device configuration (gitignored)
- **`output.txt`**: Temporary output capture file (gitignored)

## Project-Specific Conventions

### Pin Numbers (1-Based Indexing)
Pins are 1-based in UI and script args, but underlying JSON arrays are 0-based. Convert: `pin_id_from_array[pin_index - 1]`

### Metadata XML Parsing
- **Track Info**: Parse DIDL-Lite XML from service responses, extract `<dc:title>`, `<dc:creator>`, `<upnp:albumArtURI>`
- **Radio Stations**: Use `Info.title` as station name, `Info.Metatext` as track metadata
- **HTML Entities**: Use `html.unescape()` on all text fields

### Source Type Detection
- **Radio**: Check `source["type"].lower() == "radio"` OR `"radio" in source["name"].lower()`
- **Songcast**: Check `"receiver" in source["type"].lower()` OR `"songcast" in source["name"].lower()` AND `source["visible"]`
- **Sender**: Check `"sender" in source["type"].lower()` OR (`"songcast" in source["name"].lower()` AND `"sender" in source["name"].lower()`)

### Device UDN Format
Always UUID format: `4c494e4e-0026-0f22-5661-01531488013f` (prefix `4c494e4e` is "LINN" in hex)

## External Documentation

**Primary References** (use for protocol details, service schemas, LPEC commands):
- https://github.com/openhome/ohNet - Core OpenHome library
- https://github.com/bazwilliams/openhomedevice/ - Python client library
- http://wiki.openhome.org/wiki/OhMediaDevelopers - Service documentation
- http://wiki.openhome.org/wiki/Av:Developer:Songcast:Ohz - ohz protocol spec
- http://wiki.openhome.org/wiki/Av:Developer:Songcast:Ohm - Songcast multicast details
- https://docs.linn.co.uk/wiki/index.php/Developer:LPEC - LPEC telnet protocol
- https://docs.linn.co.uk/wiki/images/3/32/LPEC_V2-5.pdf - LPEC PDF spec
- https://docs.linn.co.uk/wiki/index.php/FAQ-Linn_DS/DSM#Services.2C_ports.2C_protocols - Ports/services reference

## Key Files to Reference

- [README.md](README.md) - Full usage documentation, examples, troubleshooting
- [songcast_group.py](songcast_group.py) - Complex async workflow, ohz URI handling, Receiver/Sender service usage
- [now_playing.py](now_playing.py) - Device iteration, Songcast leader resolution, metadata parsing patterns
- [find_linn_udn.py](find_linn_udn.py) - LPEC telnet communication, UDN extraction from ALIVE messages
- [experimental/oneshot-reboot-ds.py](experimental/oneshot-reboot-ds.py) - Proven working reboot implementation using Volkano service
- [.vscode/tasks.json](.vscode/tasks.json) - Preconfigured run commands (note: paths may be absolute and need adjustment)

