# ADR Service Hub pilot

Version 0.1.0 is a local Home Assistant app for a single WattBox test device.
It is the first equipment connector, not the completed phone voice assistant.

## Included

- Home Assistant ingress page; no published host ports or separate web login.
- Explicit SSH server-key approval before credentials are sent.
- On-demand model, firmware, outlet-name and outlet-power-state queries.
- One selected outlet, exact expected label, fresh state check, and explicit confirmation before RESET.
- Five-minute persisted reboot cooldown; never automatically resends a reset.
- Outlet power verification at 15, 30 and 60 seconds after acknowledgement.
- Private app data and service event history. No Home Assistant configuration mounts, Docker socket, host privileges, Home Assistant API, or Supervisor API access.

## Not included yet

Phone AI/voice connection, multi-client enrollment, external API access, Sonos,
network-controller diagnostics, Crestron, Control4, Lutron, automatic recovery,
and Apple TV functional/reachability tests. Existing integrations are unaffected
by design because this app does not access them. Resource sharing on the Green
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
The app does not need a Home Assistant token or a Proxmox connection.

## Removing the pilot

Stop and uninstall only ADR Service Agent. Home Assistant automations and other
apps are not modified by this app. Its own saved SSH identity, configuration,
cooldown and event history are removed according to Home Assistant's uninstall
and backup behavior. Protect backups because app options include the password.

## Validation and limits

Run `python -m unittest discover -s tests -v` after installing
`adr_service_agent/requirements.txt` in a test environment.
Tests use simulated responses, not a live WattBox. No Docker runtime or Green
was available during initial development: container build, ARM execution,
SSH handshake quirks on the installed firmware, ingress routing and live reset
behavior must be verified at the pilot installation.

Protocol reference: Snap One WattBox Integration Protocol v2.4:
https://www.snapav.com/wcsstore/ExtendedSitesCatalogAssetStore/attachments/documents/PowerManagement/ProtocolsAndDrivers/SnapAV_Wattbox_API_V2.4.pdf

Home Assistant app configuration and ingress:
https://developers.home-assistant.io/docs/apps/configuration/
https://developers.home-assistant.io/docs/apps/ingress/
