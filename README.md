# ADR Service Hub pilot

Version 0.8.0 is a local Home Assistant app for a single WattBox test device,
read-only Sonos diagnostics, Ruckus integration/presence diagnostics and UniFi
sensor diagnostics, plus direct Araknis SSH login/help inspection.
Voice access is not connected in this version.

## Included

- Home Assistant ingress page; no published host ports or separate web login.
- Explicit SSH server-key approval before credentials are sent.
- On-demand model, firmware, outlet-name and outlet-power-state queries.
- One selected outlet, exact expected label, fresh state check, and explicit confirmation before RESET.
- Five-minute persisted reboot cooldown; never automatically resends a reset.
- Outlet power verification at 15, 30 and 60 seconds after acknowledgement.
- On-demand Sonos snapshots: reported playback, mute, volume, source, track,
  group members and Home Assistant update time. Discovers enabled Sonos media
  players through the entity registry and reads only their individual states.
- Private app data and service event history. No Home Assistant configuration
  mounts, Docker socket, host privileges, or Supervisor administration API access.
- Home Assistant Core API access uses the internal Supervisor-provided token.
  This grant is broader than read-only; the Sonos connector implements only
  registry discovery and GET state reads. It never calls services or writes states.

## Not included yet

Phone AI/voice connection, multi-client enrollment, external API access,
direct network-controller diagnostics, Crestron, Control4, Lutron, automatic recovery,
and Apple TV functional/reachability tests. Existing integrations are not
reconfigured; Sonos data is read through Home Assistant. Resource sharing on the Green
still requires a real-device trial.

## Installation once this source is hosted

1. Publish this directory's contents at the root of a dedicated Git repository
   reachable by Home Assistant. Do not upload credentials or private site data.
2. Home Assistant: Settings → Apps (or Add-ons) → App store → menu → Repositories.
   Add that repository URL. Refresh the store and select **ADR Service Agent**.
3. Install. The Supervisor builds the image on the device; allow several minutes
   and check build logs if it fails. No prebuilt image is supplied in this pilot.
4. In Configuration enter the WattBox IP, SSH port, local username/password,
   test outlet, expected label (exactly as stored in WattBox), and display alias.
   Leave `allow_reboot: false` for the first status check. Save and start this app.
5. Open Web UI. Inspect SSH identity, compare its SHA256 fingerprint with a
   trusted local SSH connection, then approve. A changed saved key is rejected.
6. Read outlet labels and status. Confirm the physical outlet mapping.
7. When ready for the test, enable `allow_reboot`, save and restart **this app
   only**. Read status again, confirm the mapping, and reboot the selected outlet.
8. Refresh results after 15, 30 and 60 seconds. Confirm the picture and normal
   operation on the actual Apple TV. An outlet returning on proves only its
   reported power state, not a successful Apple TV restart or working playback.

User supplies all credentials in Home Assistant, never in chat or GitHub.
The app does not need a manually entered Home Assistant token or a Proxmox connection.

## Sonos diagnostics

After updating to 0.2.0, start the app and choose **Check Sonos** in its Web UI.
No changes to the existing Sonos integration or WattBox configuration are needed.
Only players identified by Home Assistant as Sonos entities are queried. Data
stays inside the app's in-memory page state and is not sent to an external AI.
The service event log records only the check time and number of players.

A snapshot is a read of Home Assistant's cached/reported states, not a forced
device refresh or direct network test. Last state update is not a heartbeat.
“Playing” does not establish audible output; a Sonos Port's external amplifier
and speakers remain unverified. Missing readings remain unknown. Up to 32
players are read per check; larger installations show an explicit limit notice.

Version 0.1.0 was subsequently reported working by the pilot user on Green with
the WB-800VPS-IPVM-18, including outlet inventory and an outlet 11 reset. This
is a user-reported live test, not an independently observed result. Version
0.2.0 still requires a live Sonos trial.

## Ruckus diagnostics (0.3.0)

Choose **Check Ruckus** to discover Home Assistant Ruckus entries, select the
current entry, then choose **Check Ruckus** again. The selection is saved only
inside the ADR app; no HA configuration or Ruckus setting is changed.

The app lists each entry's reported setup state and queries only enabled
device_tracker, sensor and binary_sensor entities belonging to the selected
Ruckus platform and config entry. Failed or disabled entries do not supply
current entity readings. Saved inventory (name/model/manufacturer) is displayed
separately, since it does not prove live AP health. Up to 64 entities are read;
an explicit notice appears if more are available. Presence status is not a
signal-strength, bandwidth, switch-port or internet test. Ruckus credentials,
raw integration configuration and direct controller sessions are not accessed.

The selected-entry ID is saved locally; network and presence readings remain in
memory only. The service log contains check time and reading count, not client
MACs, addresses or presence history. No new API permission is added in 0.3.0.

## UniFi sensor diagnostics (0.4.0)

Configure UniFi Network in Home Assistant first. In the ADR app select **Check
UniFi**, select the integration if multiple entries exist, choose your gateway
from the device selector, and check again. The app remembers this local selection.

Only enabled sensor and binary_sensor entities belonging to that exact UniFi
entry and device are read. The app does not read unrelated clients' states,
control entities, controller credentials or raw controller configuration. Saved
device metadata is used to populate the selector. Disabled sensor names are
listed separately; the user enables desired sensors in Home Assistant.

Reported values include their units and HA update timestamps. CPU, memory,
uptime, temperature and WAN latency appear only where HA exposes them as enabled
entities; no fields or values are fabricated. Values are snapshots of HA states,
not fresh network tests. Latency does not measure internet download speed and
cannot establish whether Ruckus Wi-Fi or an Araknis switch is healthy.

No UniFi control commands are implemented. The app cannot restart the gateway,
change firewall/network settings or cycle a PoE port. No permissions beyond the
existing Home Assistant Core API grant are added. The selection is saved locally;
readings stay in memory and are not logged as network/client history.

## Removing the pilot

Stop and uninstall only ADR Service Agent. Home Assistant automations and other
apps are not modified by this app. Its own saved SSH identity, configuration,
cooldown and event history are removed according to Home Assistant's uninstall
and backup behavior. Protect backups because app options include the password.

## Validation and limits

Run `python -m unittest discover -s tests -v` after installing
`adr_service_agent/requirements.txt` in a test environment.
Tests use simulated responses, not live equipment. No Docker runtime or Green
is available in the development environment. The next update must build on the
Green and its new Sonos connector must be checked against the live integration.

Protocol reference: Snap One WattBox Integration Protocol v2.4:
https://www.snapav.com/wcsstore/ExtendedSitesCatalogAssetStore/attachments/documents/PowerManagement/ProtocolsAndDrivers/SnapAV_Wattbox_API_V2.4.pdf

Home Assistant app configuration and ingress:
https://developers.home-assistant.io/docs/apps/configuration/
https://developers.home-assistant.io/docs/apps/ingress/

## Araknis SSH inspection (0.5.1)

Configure `araknis_host`, `araknis_ssh_port` (22), `araknis_username` and
`araknis_password` in the app Configuration tab, save and restart only this app.
Existing WattBox configuration is unchanged. These optional fields do not need
values to use the other connectors. Credentials remain in app options and its
protected backups; no switch credentials are committed to this repository.

Open the Web UI, inspect the Araknis SSH identity and explicitly approve its
first-use key. Compare the fingerprint independently when available. A changed
saved key is rejected. Then test login and read CLI help. This opens a bounded
SSH session and sends `show ?` without a newline to request context help.
It advances only explicit `--More--` pager prompts with a space, with an
eight-page and 32 KB content limit. It does not send configuration,
restart, PoE or arbitrary user-entered commands. No automatic retries or startup
connections occur. This stage verifies login and discovers the CLI, not switch
health. The separate diagnostic snapshot requests fixed show commands; their live syntax
and responses still require verification.
Responses are bounded, HTML escaped, kept in memory only and not logged. The
SSH key is saved separately from the WattBox key. Live switch validation is
pending; automated tests use simulated SSH clients.

## Araknis diagnostic snapshot (0.7.0)

After SSH identity approval, select **Read Araknis diagnostics**. The check runs
in the background; use **Refresh Araknis results** to view completion. Starting
another check while one is running does not create a second job. Requests are
fixed: `show system information`, `show env all`, `show interfaces`,
`show power detail`, `show power inline`, `show poe port`. Each uses a fresh authenticated SSH connection and requires a recognized
command prompt. An incomplete/invalid command requests that same fixed command's `?`
context help on a new SSH connection. There is no arbitrary command field, retry,
privilege escalation, running-config read, or switch control.

Most responses have an eight-page/32 KB content limit. Interface details allow
96 pages/256 KB so the full switch can fit. Reads have a four-second limit per
page and a 90-second pagination deadline. Truncation is displayed explicitly. All six categories retain raw responses,
including errors or failed reads. Interface links, speeds and counters also appear in a parsed table, preserving
missing values as not reported. Counters are cumulative; no rates or diagnoses
are inferred. The root `show cpu` query was removed because it reports mirroring,
not utilization. Environment output may report resource thresholds rather than
current utilization. No CPU values, port states or PoE watts are fabricated; a successful SSH request is not a device-health verdict.
A failed help request preserves the original response and its status. Other
requests use independent connections. Authentication and host-key failures abort
the snapshot. Responses stay in memory; logs contain completion and response count.
The pilot has verified SSH login and root show-help; diagnostic commands need
live validation on the selected firmware.

The 0.7.0 command suffixes come from the pilot's own CLI help. Live validation
of those requests and completion of the full interface read are still pending.
The supported interface output format has been tested with sanitized fixtures
based on the observed switch format; other formats remain available as raw text.

## One-run discovery report (0.8.0)

Select **Run discovery and prepare report** once, allow a few minutes, and
refresh results. Select **Download Araknis report** and attach the JSON file in
the support conversation. There is no automatic upload or external API setup.
The report is generated on demand from memory, with no stored report file.

Discovery walks only allowlisted system/environment/interfaces/power/PoE show
paths actually advertised in CLI help. It uses at most 24 help probes, 12 reads,
and a 180-second deadline checked between requests (an in-flight bounded request
may finish after that deadline). Only paths explicitly advertising `<cr>` are
executed. No numeric arguments are inferred, arbitrary input is accepted, or
configuration/control requests are sent. The result records failures, captured
syntax help and discovery limits, so one report can be inspected without
repeated screen copying. Authentication/key failures abort the run.

The download contains switch responses (including possible addresses, device
names and identifiers), parsed port data and discovery metadata. It excludes app
options, credentials, saved SSH keys and other connectors' data. The configured
Araknis password is redacted from response values. The download requires HA
ingress and a valid CSRF-protected form. No new app permissions are required.
Live discovery/export validation remains pending.
