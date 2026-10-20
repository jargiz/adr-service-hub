# Setup

Enter the WattBox's **local** SSH credentials under this app's Configuration.
Set `wattbox_host`, `ssh_port` (normally 22), `test_outlet`,
`expected_outlet_label` (exact label from WattBox), and `device_alias`.

Start the app and choose **Open Web UI**. Inspect and approve its SSH identity,
then read the labels and status. The app sends no device requests at startup.

To run a reboot test, enable `allow_reboot`, save and restart this app only.
Read status, confirm the device/outlet mapping, and select the reboot button.
An off outlet, different label, unexpected model, expired confirmation, or active
cooldown blocks the action. RESET only is supported; no global reset or manual
off/on action is exposed. Five minutes must pass between reset attempts.

The saved SSH identity cannot be silently replaced. If it changes, investigate
the device identity before resetting app data. If the reboot acknowledgement
times out, its outcome is unknown and the command will not be resent.

Use Refresh results to see the outlet verification after 15, 30, and 60 seconds.
Check the TV itself to confirm the Apple TV is operating normally. Outlet status
does not establish device reachability, successful boot, HDMI output or playback.

## Sonos checks (0.2.0)

Select **Check Sonos** in the Web UI. The app reads the player states reported
by your installed Sonos integration without sending playback, volume, mute,
grouping, or other Sonos control commands. No extra configuration is required.

This update enables Home Assistant Core API access, using an internally supplied
token. Home Assistant's grant is broader than read-only; this Sonos connector
uses only entity discovery and individual state reads. The app has no Supervisor
administration API access. No manually entered token is needed.

Source, title and artist appear when reported. Missing values show Not reported.
Group members are displayed by player name where available. A failed read clears
old Sonos results; failure of one player does not erase readings for the others.

These readings may be cached by Home Assistant. The snapshot retrieval time and
HA last-update time are displayed separately; neither proves audible output.
No Sonos playback history or track details are written to the app service log.

This version has no phone voice connection or external cloud access.

## Ruckus checks (0.3.0)

Select **Check Ruckus**, choose the current integration from the discovered-entry
list, then select **Check Ruckus** again. The app remembers that selection locally.
It does not disable, delete, reload or modify any Home Assistant integration.

Only the selected entry supplies readings. Its setup state is displayed first;
failed/disabled entries cannot contribute retained readings as if they were
current. Device inventory is saved HA metadata. Entity values are HA-reported
states, mainly presence for the standard Ruckus integration. They do not prove
AP operational health, Wi-Fi signal, throughput, internet connectivity or root
cause. Deeper controller diagnostics require a later direct integration.

No extra credentials or API permissions are needed beyond the existing Core API
grant. Entry metadata, entity/device registries and individual entity states are
read; no HA configuration actions or Ruckus control commands are implemented.

## UniFi checks (0.4.0)

Select **Check UniFi**, choose the integration if requested, select the gateway
in the device menu, then select **Check UniFi** again. The app remembers the
selection in its own data. No UniFi credentials need to be entered in this app.

Values are read only from enabled sensor/binary_sensor entities on the selected
device and integration. CPU, memory, uptime, temperature and WAN latency appear
when available in HA. Disabled sensors are listed separately; the app never
enables them, controls network entities, changes firewall rules or restarts gear.

Values include units and HA timestamps. Last state update is not a heartbeat.
Unknown/unavailable/failed readings are retained as such, not converted to zero.
WAN latency is not bandwidth or download speed. Non-UniFi switch internals and
Ruckus Wi-Fi health require separate diagnostics. No new API permissions are used.
No Home Assistant configuration, automations or existing integrations are edited.
All credentials stay in app configuration; include them only in protected backups.

If the first check fails, verify local credentials, SSH availability, and the
saved identity. WattBox SSH implementations/firmware can vary; do not weaken
SSH or enable Telnet to work around a failure before reviewing it.

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

## Araknis diagnostic snapshot (0.6.1)

After SSH identity approval, select **Read Araknis diagnostics**. The check runs
in the background; use **Refresh Araknis results** to view completion. Starting
another check while one is running does not create a second job. Requests are
fixed: `show system`, `show env`, `show cpu`, `show interfaces`, `show power`,
`show poe`. Each uses a fresh authenticated SSH connection and requires a recognized
command prompt. An incomplete/invalid command requests that same fixed command's `?`
context help on a new SSH connection. There is no arbitrary command field, retry,
privilege escalation, running-config read, or switch control.

Responses have an eight-page/32 KB content limit per request and a four-second
receive limit per page. All six categories are displayed as raw responses,
including errors or failed reads. No CPU values, port states or PoE watts are
inferred or fabricated; a successful SSH request is not a device-health verdict.
A failed help request preserves the original response and its status. Other
requests use independent connections. Authentication and host-key failures abort
the snapshot. Responses stay in memory; logs contain completion and response count.
The pilot has verified SSH login and root show-help; diagnostic commands need
live validation on the selected firmware.
