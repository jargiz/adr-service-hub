# ADR Service Hub pilot

Version 0.3.0 is a local Home Assistant app for a single WattBox test device,
read-only Sonos diagnostics and Ruckus integration/presence diagnostics.
It is the first equipment connector, not the completed phone voice assistant.

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
