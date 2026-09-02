# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Command-line Python tools for controlling and monitoring Linn DSM network audio players via the OpenHome protocol (UPnP/SOAP). Functionality: device discovery, now-playing queries, Pin invocation, source querying, Songcast multi-room grouping/disbanding, device rebooting, and firmware debug log capture.

Dependencies are pinned in `requirements.txt` and installed into `.venv`. `pyproject.toml` exists only for `ruff`/`mypy` tool config — there is no packaging beyond that.

**Keep `.github/copilot-instructions.md` in sync with this file.** It's the Copilot-facing equivalent of this document and covers the same architecture/conventions in more granular detail. Whenever you learn something new about this codebase worth persisting (a corrected assumption, a new service/action, a new script, a changed workflow), update both files, not just this one.

## Commands

```bash
# Run any script — always via the venv interpreter, not system python3
.venv/bin/python <script>.py [args]

# Run all tests
.venv/bin/python -m pytest tests/ -v

# Run a single test file / test
.venv/bin/python -m pytest tests/test_songcast_disband.py -v
.venv/bin/python -m pytest tests/test_songcast_disband.py::TestClassifyDevices::test_classify_full_group -v

# Install dependencies
.venv/bin/pip install -r requirements.txt

# Lint (must pass — CI blocks on this)
.venv/bin/ruff check .

# Format check (informational — CI does not block on this)
.venv/bin/ruff format --check .

# Type check (informational — CI does not block on this)
.venv/bin/mypy --config-file pyproject.toml .
```

Terminal output reliability workaround used throughout development: pipe to `output.txt` and read it back rather than relying on live terminal capture: `.venv/bin/python script.py --debug > output.txt 2>&1; cat output.txt`.

## CRITICAL: Research-first development

Before implementing any device-control change:

1. **Search the existing codebase first** for a similar implementation — service names, action names, and SOAP patterns are usually already used somewhere (e.g. grep for `Volkano`, `Receiver`, `SetSender`, etc.) rather than guessed.
2. **Verify service/action names against real usage**, not assumption — e.g. reboot lives in `Volkano:1` (`linn.co.uk-Volkano-1`), *not* `Product`.
3. **Don't claim success without running the script end-to-end** against real hardware or the test suite. API call returning 200 does not mean the device did the right thing — cross-check with `lpec_utils.py` / `tests/songcast_monitor.py` state.
4. Common wrong assumptions to avoid: `Product` service does not have reboot; `openhomedevice.Device` takes a `location_url`, not `(ip, udn)`; most operations don't need `asyncio` if a plain synchronous SOAP `requests` call will do (see `reboot_all.py`, `songcast_disband.py`).

## CRITICAL: Validate before finishing any change

Any local AI coding assistant (Claude Code or otherwise) MUST run the following before considering a change complete or reporting success to the user — this mirrors the CI gate in `.github/workflows/ci.yml`:

```bash
.venv/bin/ruff check .              # must exit 0 — blocking, same as CI
.venv/bin/python -m pytest tests/ -v  # must pass — blocking, same as CI
.venv/bin/ruff format --check .     # informational — review findings, does not block
.venv/bin/mypy --config-file pyproject.toml .  # informational — review findings, does not block
```

`ruff check` and `pytest` failures must be fixed before claiming a task done. `ruff format --check` and `mypy` findings should be reviewed but do not need to be resolved before finishing — the codebase has not yet been fully reformatted or type-annotated, and fixing that wholesale is out of scope for most changes.

## Architecture

### Two device-communication styles coexist

- **Async, via `openhomedevice`** (`now_playing.py`, `play_pin.py`, `query_sources.py`, `songcast_group.py`): `dev = Device(location_url)` → `await dev.init()` → `await dev.device.service_id("urn:av-openhome-org:serviceId:X")` → `await service.action("Name").async_call(...)`. Wrap flaky/slow calls in `asyncio.wait_for(..., timeout=2.0)`.
- **Synchronous, raw SOAP via `requests`** (`reboot_all.py`, `songcast_disband.py`): hand-built `<s:Envelope>` XML posted to `http://<IP>:55178/<UDN>/<service-path>/control` with a `SOAPACTION` header. Used where async adds no value or where reliability under failure states matters more than convenience.

New scripts should follow whichever style matches the operation being done, not the average of the two — check the most similar existing script first.

### Communication ports/protocols

| Port | Protocol | Purpose |
|------|----------|---------|
| 55178 | HTTP/SOAP | OpenHome service control (Product, Receiver, Sender, Pins, Info, Playlist, Volkano) |
| 23 | LPEC (telnet) | Device discovery (`ALIVE` messages), real-time state subscriptions/eventing |
| 2323 | Firmware debug stream | Read-only diagnostic log from the internal C++ media pipeline |
| 51972 | ohz:// multicast | Songcast audio streaming |

Device identity is always `IP address + UDN` (UUID, `4c494e4e-...` prefix decodes to "LINN" in hex). Device XML lives at `http://<IP>:55178/<UDN>/Upnp/device.xml`.

### `.env` device configuration

Shared across most scripts: `DEVICE_N=<IP> [<UDN>]` — the UDN is optional; when omitted it is auto-discovered via LPEC (telnet ALIVE probe, port 23) at runtime. Songcast roles: `SONGCAST_SENDER=DEVICE_1`, `SONGCAST_RECEIVERS=DEVICE_2,DEVICE_3` (only needed by `songcast_group.py`'s legacy config path — `songcast_disband.py` auto-detects sender/receiver/standalone roles by probing device state instead).

### Songcast grouping/disbanding flow

- **Group** (`songcast_group.py`): wake devices from standby → find/set receiver's source index to Songcast → discover sender's `ohz://` URI via `Receiver.Senders`/`Sender.Sender` → `Receiver.SetSender(Uri, Metadata)` on the receiver → poll `TransportState` via `lpec_utils.wait_for_state` until Playing/Buffering. Falls back to `ohSongcast://` descriptors if no `ohz://` URI is found.
- **Disband** (`songcast_disband.py`): auto-detect each device's role (sender/receiver/standalone) by probing `Receiver`/`Sender` state → for receivers: `Receiver.SetSender(Uri="", Metadata="")` (clears "zombie" receivers still bound to a dead `ohz://` URI — `Receiver.Stop` alone is not sufficient) → `Receiver.Stop` → `Product.SetSourceIndex` back to a non-Songcast source (e.g. Playlist). **The sender is left playing** — see below. Verifies final standalone state afterward.
- **Disbanding must not stop the sender.** Ungrouping detaches the receivers; whoever is listening on the sender keeps listening. `Sender.Status2` drops from `Sending` back to `Ready` on its own once the last receiver detaches, so no action on the sender is needed (verified on hardware). `--stop-sender` opts in to the old `Playlist.Stop` behaviour.
- `lpec_utils.py` is the shared verification layer used by both the grouping script and `tests/songcast_monitor.py`: `query_receiver_state`, `wait_for_state`, `check_transport_playing`, `check_sender_uri`, `format_state_summary`.

### The LPEC feedback-loop test harness (`tests/`)

Because SOAP calls can return HTTP 200 while the device silently fails to actually change state, this repo has a hardware-in-the-loop validation layer, not just unit tests:

- `tests/songcast_monitor.py` opens persistent LPEC telnet subscriptions to the sender + receivers from `.env` and prints real-time `TransportState`/`Sender`/`Status` transitions. It also supports `--test <scenario>.json` assertion mode (device/variable/value/timeout) with pass/fail exit codes — see `tests/test_songcast_join.json` for the schema.
- Workflow for validating a change to `songcast_group.py`/`songcast_disband.py` against real hardware: run `songcast_monitor.py --debug` in one terminal, the script under test in another, and read the state transitions rather than trusting the script's own success message.
- `device_logs.py` (root) is the complementary low-level tool: captures the port 2323 firmware debug stream (categorized into HLS/HTTP/PIPELINE/CONTAINER/SONGCAST/CODEC/VOLUME/TRANSPORT/ERROR/OTHER) and can wrap a command via `--around-command`, or run `--background`/`--stop` for daemonized capture. Use this to see *why* a Songcast join failed after `songcast_monitor.py` shows *that* it failed.
- `tests/test_*.py` are ordinary offline pytest unit tests (regex parsing, URL building, mocked SOAP responses) — run these before hardware validation, not instead of it.

### Project-specific conventions

- **Pins are 1-based** in the CLI/UI but the underlying `Pins.GetIdArray` JSON array is 0-based: `pin_id_from_array[pin_index - 1]`.
- **Metadata is DIDL-Lite XML** — extract `<dc:title>`, `<dc:creator>`, `<upnp:albumArtURI>`, and always run `html.unescape()` on text fields.
- **Source type detection** is name/type substring matching, not exact enum comparison (device firmware is inconsistent): Radio → `type == "radio"` or `"radio" in name`; Songcast receiver → `"receiver" in type` or `"songcast" in name` and visible; Songcast sender → `"sender" in type` or (`"songcast" in name` and `"sender" in name`).
- **Service action names must be read off the device, never guessed.** `curl -s http://<IP>:55178/<UDN>/Upnp/<service-path>/service.xml` lists the real actions in seconds. Three invented names shipped in this repo for months, each silently swallowed by a bare `except`: `Sender.Sender` and `Receiver.Senders` do not exist (the Sender service has `PresentationUrl`, `Metadata`, `Audio`, `Status`, `Status2`, `Enabled`, `Attributes`; Receiver has `Play`, `Stop`, `SetSender`, `Sender`, `ProtocolInfo`, `TransportState`).
- **`Sender.Metadata` is the authoritative source for a sender's `ohz://` URI** — its DIDL-Lite `<res>` element. Do not reconstruct the URI from the device UDN: the sender identifier in it is not always the bare UDN. The constructed `ohz://239.255.255.250:51972/<udn>` form remains a correct fallback for Linn senders only.
- **Treat device responses as untrusted input.** Anything read back over SOAP/LPEC is whatever some box on the network chose to say, and several values flow straight into control actions on *other* devices (`Sender.Metadata` → `Receiver.SetSender` being the sharp one). Validate before use — `_uri_from_didl` in `songcast_group.py` accepts only the `ohz`/`ohm`/`ohu` schemes within length bounds, and falls back to the locally-constructed URI otherwise. Equally, don't promote a value observed on one device into a documented fact about how devices behave.
- **`Sender.Status` does not tell you whether a device is sending.** It reports `Enabled` whenever the Sender service is switched on — true on every idle device — so keying off it classifies the whole fleet as senders. Use `Sender.Status2` (`Ready` vs `Sending`).
- **SOAP control endpoints ignore the service version** in both the URL path and the URN: `av.openhome.org-Sender-1/control` and `…-Sender-2/control` behave identically, as do `Volkano-1`/`Volkano-3`. So a version mismatch in a hardcoded path is not the cause of a failing call — look at the action name instead. (`service.xml` *does* 404 on a wrong version; only `/control` is tolerant.)
- **Airable radio URIs are portable between devices** — the `Uri` returned by `Info.Track()`/`Radio.Track()` for a station (e.g. `airable.radios://radio?version=1&radioId=...&deviceId=...`) can be replayed on a *different* device as-is via `Radio.SetChannel(Uri=..., Metadata=...)` followed by `Radio.Play()` — no need to resolve it to the underlying raw stream URL first. Ensure the target device's source is set to Radio (find the index via the `Product.Source` scan, same as the Songcast source-finding pattern) before calling `SetChannel`.

### Directory layout

- Root: the CLI tools + `lpec_utils.py` (shared LPEC helpers).
- `tests/`: pytest unit tests, plus the LPEC hardware-in-the-loop harness (`songcast_monitor.py`, `capture_disband.py`, test scenario JSON).
- `captures/`: gitignored output from `device_logs.py` and LPEC captures.
- `experimental/`: gitignored work-in-progress/superseded script variants — not maintained, don't treat as reference implementations.
- `.env`: gitignored real device config; never contains secrets but is environment-specific — don't assume its contents.
