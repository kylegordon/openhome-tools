# OpenHome Tools - AI Agent Instructions

## Project Overview

Command-line utilities for controlling Linn DSM network audio players via the OpenHome protocol (UPnP/SOAP-based). Core functionality: device discovery, now-playing queries, Pin invocation, source querying, Songcast multi-room grouping/disbanding, device rebooting, and firmware debug log capture.

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

### Pre-Completion Checklist (MANDATORY)

Any local AI coding assistant (GitHub Copilot or otherwise) MUST run the following before considering a change complete or reporting success to the user — this mirrors the CI gate in `.github/workflows/ci.yml`:

```bash
.venv/bin/ruff check .                          # must exit 0 — blocking, same as CI
.venv/bin/python -m pytest tests/ -v            # must pass — blocking, same as CI
.venv/bin/ruff format --check .                 # informational — review findings, does not block
.venv/bin/mypy --config-file pyproject.toml .   # informational — review findings, does not block
```

`ruff check` and `pytest` failures must be fixed before claiming a task done. `ruff format --check` and `mypy` findings should be reviewed but do not need to be resolved before finishing — the codebase has not yet been fully reformatted or type-annotated, and fixing that wholesale is out of scope for most changes.

## Architecture & Key Patterns

### Device Communication
- **Protocol Stack**: OpenHome over UPnP/SOAP + LPEC (Linn Protocol for Eventing and Control)
- **Port 55178**: HTTP/SOAP control for OpenHome services
- **Port 23**: LPEC telnet — used for ALIVE messages, subscriptions, real-time events
- **Port 2323**: Firmware debug log stream (read-only diagnostic output from internal C++ media pipeline)
- **Port 51972**: ohz:// multicast streaming (Songcast)
- **Device Identification**: IP address + UDN (Unique Device Name, UUID format)
- **URL Structure**: `http://<IP>:55178/<UDN>/<service-path>/control`

### Python Environment & Dependencies
- **Virtual Environment Required**: All scripts expect `.venv` in project root
- **Install**: `.venv/bin/pip install -r requirements.txt` (pins `openhomedevice`, `requests`, `pytest`, `ruff`, `mypy`)
- **Critical Dependencies**: `openhomedevice` (async OpenHome client), `requests` (SOAP), standard lib (`asyncio`, `xml.etree.ElementTree`, `argparse`)
- **Python Version**: 3.7+ required for async/await support; CI (`.github/workflows/ci.yml`) targets 3.13 specifically
- **Invocation Pattern**: `.venv/bin/python script.py` OR `source .venv/bin/activate && python script.py`
- **Lint/Format/Type-check**: `.venv/bin/ruff check .` (blocking, same as CI), `.venv/bin/ruff format --check .` (informational), `.venv/bin/mypy --config-file pyproject.toml .` (informational) — config lives in `pyproject.toml`

### Configuration Pattern
- **`.env` File**: Device configurations stored as `DEVICE_N=<IP> <UDN>` entries
- **Songcast Config**: `SONGCAST_SENDER=DEVICE_1` and `SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3`
- **Loading**: Scripts parse `.env` at startup, support both env-driven and CLI argument modes
- **Example**: `DEVICE_1=172.24.32.211 4c494e4e-0026-0f22-5661-01531488013f`

### Async/Await Pattern
- **All device interactions are async**: Use `asyncio.run()` in main, `await` for all device calls
- **Device Init Pattern**: `dev = Device(...)` → `await dev.init()` → operations → no explicit cleanup
- **Service Access**: `dev.device.service_id("urn:av-openhome-org:serviceId:Product")` → `await service.action("MethodName").async_call(param=value)`
- **Timeouts**: Wrap service calls in `asyncio.wait_for(call, timeout=2.0)` for Songcast/Receiver queries

### Key OpenHome Services
- **Product:4** - Source selection (`SourceCount`, `Source`, `SetSourceIndex`, `SourceIndex`), standby control
- **Receiver:1** - Songcast follower. Actions are exactly: `Play`, `Stop`, `SetSender`, `Sender`, `ProtocolInfo`, `TransportState`. There is **no** `Senders` action — the repo called one for months and silently swallowed the failure.
- **Sender:2** - Songcast leader. Actions are exactly: `PresentationUrl`, `Metadata`, `Audio`, `Status`, `Status2`, `Enabled`, `Attributes`. There is **no** `Sender` action on this service (that lives on Receiver). `Metadata` returns the DIDL-Lite descriptor whose `<res>` holds the leader's `ohz://` URI. `Status` returns Enabled/Disabled and is **not** a sending indicator; `Status2` returns Ready/Sending and is.
- **Pins:1** - Presets/favorites (`InvokeId`, `GetIdArray`, `ReadList`)
- **Info** - Track metadata (`TrackTitle`, `Metatext` for radio stations)
- **Playlist:1** - Playback control (`Stop` used only under `songcast_disband.py --stop-sender`)
- **Volkano:1** - Linn-specific device management (`Reboot` action - NOT in Product service!) — service path: `linn.co.uk-Volkano-1`

**Output-argument names are declared, not guessable.** `Receiver.TransportState` → `{"Value": ...}`; `Product.SourceIndex`/`SourceCount` → `{"Value": <int>}`; `Product.SetSourceIndex` takes `Value` (never `aIndex`). Don't write `.get("A") or .get("b")` guess-chains — when every guess is wrong the result is a permanent silent `None`, and an `or` chain also turns a valid index `0` into the fallback.

**`Receiver:1` has no `Status` action** (only `Play`, `Stop`, `SetSender`, `Sender`, `ProtocolInfo`, `TransportState`); `Status`/`Status2` are on `Sender:2`. `TransportState` ∈ `Buffering|Playing|Stopped|Waiting` — `"Connecting"` is not real, and `Waiting` (bound, sender idle) still counts as grouped.

**LPEC wire format**, captured from firmware: `SUBSCRIBE Ds/X` → `SUBSCRIBE <id>`, then `EVENT <subscription-id> <seq> <var> "<value>" ...`. The id is a per-device counter, never 0, and the service name is absent from event lines. `Ds/Receiver` emits `Uri`, `Metadata`, `TransportState`, `ProtocolInfo` — **no `Sender`, no `Status`**; the bound sender is `Uri`. Anchor variable names at a token boundary.

**Pins: `InvokeId` wants the device pin Id from `GetIdArray`** (e.g. `[1, 0, 2, 3, 0, 4]`, where 0 is an empty slot), not the 1-based UI number. Use `resolve_pin_id()`.

**Verify action names against the device, never assume.** `curl -s http://<IP>:55178/<UDN>/Upnp/<service-path>/service.xml` lists them in seconds. Note that `/control` endpoints **ignore the service version** in both the URL path and the URN (`Sender-1/control` ≡ `Sender-2/control`; `Volkano-1` ≡ `Volkano-3`), so a version mismatch in a hardcoded path is never the cause of a failing call — suspect the action name. Only `service.xml` is version-strict.

### Songcast Multi-Room Architecture
- **ohz:// URIs** - Preferred multicast streaming protocol (port 51972, `ohz://239.255.255.250:51972/...`)
- **ohSongcast:// URIs** - Fallback descriptor format with room/name query params
- **Leader Discovery**: Query follower's `Receiver.Sender()` Uri, parse for leader UDN/room/name
- **Leader URI**: ask the leader itself via `Sender.Metadata` and read the `<res>` element (`_uri_from_didl` in `songcast_group.py`). Do **not** reconstruct it from the UDN — the sender identifier in it is not always the bare UDN. `ohz://239.255.255.250:51972/<udn>` stays a valid fallback for Linn leaders.
- **Device responses are untrusted input.** `Sender.Metadata` comes from another box on the network and its `<res>` value is fed straight into `Receiver.SetSender` on a different device, so `_uri_from_didl` validates it (schemes `ohz`/`ohm`/`ohu` only, length-bounded) and falls back to the locally-constructed URI on rejection. Never widen a value observed on one device into a general claim about device behaviour.
- **Read SOAP output arguments with `_soap_out(text, name)`** (`songcast_disband.py`), never a regex: it parses with `ElementTree`, matches the local tag name so namespaces don't matter, and unescapes entities (the old regexes returned `Kitchen &amp; Diner` verbatim). `re.IGNORECASE` on XML tag names is always wrong.
- **`bounded()` before matching, `safe_for_display()` before printing** (both in `lpec_utils.py`): cap device strings that feed role selection, and strip control characters/collapse whitespace/truncate anything echoed to a terminal so a device cannot forge output with ANSI escapes. Sanitise at the print site; compare on the raw value.
- **Grouping Flow**: Wake devices → Set follower source to Songcast (find index via `Product.Source`) → Call `Receiver.SetSender(Uri, Metadata)` → Poll `TransportState` for "playing"
- **Disbanding Flow**: `Receiver.SetSender(Uri="", Metadata="")` → `Receiver.Stop` → `Product.SetSourceIndex(0)` to switch from Songcast to Playlist. Key insight: `Receiver.Stop` alone is insufficient for zombie receivers still bound to an ohz:// URI — must clear the URI first.
- **The sender keeps playing.** Disbanding detaches followers; it must not interrupt whoever is listening on the leader. `Sender.Status2` falls from `Sending` to `Ready` by itself once the last follower detaches (verified on hardware), so nothing needs sending to the leader. `--stop-sender` opts in to `Playlist.Stop`.
- **Role detection**: a device is the leader only if `Sender.Status2 == "Sending"`. `Sender.Status` reports `Enabled` on every idle device and will classify the entire fleet as leaders.
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
- **Root Scripts**: Main CLI tools (`find_linn_udn.py`, `now_playing.py`, `play_pin.py`, `query_sources.py`, `songcast_group.py`, `songcast_disband.py`, `reboot_all.py`, `device_logs.py`)
- **Shared Modules**: `lpec_utils.py` — LPEC helper functions (query_receiver_state, wait_for_state, check_transport_playing, check_sender_uri, format_state_summary)
- **`tests/`**: Unit tests (`test_reboot_all.py`, `test_reboot_standalone.py`, `test_songcast_disband.py`, `test_device_logs.py`, `test_lpec_utils.py`), live monitoring (`songcast_monitor.py`), LPEC capture (`capture_disband.py`), test scenarios (`test_songcast_join.json`)
- **`captures/`**: Output directory for device log captures and LPEC event captures (gitignored artifacts)
- **`experimental/`**: Work-in-progress variants and older snapshots
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

### Airable Radio URIs Are Portable
The `Uri` returned by `Info.Track()`/`Radio.Track()` for a station (e.g. `airable.radios://radio?version=1&radioId=...&deviceId=...`) can be replayed on a *different* device as-is — no need to resolve it to the underlying raw stream URL first. Pattern: ensure target device's source is Radio (find index via `Product.Source` scan, same as Songcast source-finding), then `Radio.SetChannel(Uri=..., Metadata=...)` → `Radio.Play()`.

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
- [songcast_disband.py](songcast_disband.py) - Synchronous SOAP disband workflow, auto-detect sender/receiver roles, LPEC UDN discovery
- [now_playing.py](now_playing.py) - Device iteration, Songcast leader resolution, metadata parsing patterns
- [reboot_all.py](reboot_all.py) - Synchronous Volkano SOAP reboot (the canonical reboot implementation)
- [device_logs.py](device_logs.py) - Multi-device firmware debug log capture (port 2323), log classification, analysis reports
- [lpec_utils.py](lpec_utils.py) - Shared LPEC query/verification functions used by songcast_group.py and tests/songcast_monitor.py
- [find_linn_udn.py](find_linn_udn.py) - LPEC telnet communication, UDN extraction from ALIVE messages
- [tests/songcast_monitor.py](tests/songcast_monitor.py) - Real-time LPEC event monitor and test harness
- [tests/capture_disband.py](tests/capture_disband.py) - Multi-service LPEC event capture tool for reverse-engineering
- [.vscode/tasks.json](.vscode/tasks.json) - Preconfigured run commands (note: paths may be absolute and need adjustment)

