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

### Discovery collection fixes (0.8.1)

Normalize terminal escape/control characters before detecting pager and help
prompts, avoiding a full receive timeout at each formatted prompt. Prioritize
system, environment-all, power/PoE and concise interface-status paths. Defer
verbose interface details/counters until the other discovery paths finish.
Avoid redundant individual CPU/RAM/fan/flash reads once env all is captured.
The same read-only allowlist, authentication and collection limits apply.
Live validation of the timing changes remains pending.

## Crestron discovery through Home Assistant (0.9.0)

Select **Discover Crestron readings**, allow the background check to complete,
then refresh. One configured Crestron entry is selected automatically; if there
are multiple entries, select the one to inspect and check again. An invalid
saved selection is not silently replaced. Select **Download Crestron report**
to save one JSON file containing inventory and exposed readings.

This uses the existing Home Assistant integration, not a new direct processor
connection. It queries config-entry metadata, device/entity registries and only
GET states for the selected entry and matching Crestron platform. Crestron-like
domains are identified by domain, not guessed from names. Failed/disabled
entries do not supply retained states as current data. Disabled devices/entities
are inventoried but not queried. Unsupported entities (buttons, scenes, etc.)
are inventoried without state reads. No service calls or configuration writes
are sent; no new HA permissions or processor credentials are needed.

The bounded check reads up to 128 enabled supported entities with eight workers,
prioritizing sensors/binary sensors. Device inventory is limited to 512 records
and entity inventory to 1024; limits and total counts are explicit. Device
registry software versions are metadata, not fresh firmware queries. Only
allowlisted scalar state attributes are retained, including exposed connectivity,
battery/sensor states, HVAC, shade position, light level and volume/mute/source
where available. No blanket online/offline or functional-health verdict is
inferred from entity state, missing values or update timestamps.

Selection is saved only in this app's data. Snapshots remain in memory; logs
contain the reading count, not device names or state history. Downloads require
HA ingress and CSRF, include only the selected connector's discovery data, and
exclude config-entry data/options, HA tokens and processor credentials. Reports
may include private room/device names and operational states. Live discovery on
the pilot's installed integration remains pending.

## CP4-R direct processor diagnostics (0.10.0)

Set optional `cp4_host`, `cp4_ssh_port` (22), `cp4_username` and `cp4_password`
in app Configuration, save and restart only ADR Service Agent. Use a working
processor SSH/Toolbox account; do not reset processor credentials or regenerate
its Home API token for this connector. Existing HA integration is unchanged.
Inspect and explicitly approve a separate CP4-R SSH key, then read diagnostics
and download the CP4-R report. A changed key is rejected; no agent/key login
fallbacks or automatic credential retries are used.

The fixed command allowlist is VER -V, HELP ALL, IPTABLE -p:all -t, UPTIME,
CPULOAD, RAMFREE, and the last three commands with a literal ? help argument.
After the version response identifies CP4-R, help is read to confirm supported
commands. IP table is read only if advertised. CPU/memory/uptime syntax is
captured first; a query is attempted only when help describes a display query
and does not indicate start/stop/reset or other control operations. Unsupported
or ambiguous metrics remain unverified. An incomplete response stops subsequent
commands. Output is bounded to 256 KB/64 pager advances/20 seconds per response.
The current CPU response alone is not a sustained-load assessment.

IP-table coverage is limited to configured IP-table entries, not all Crestron
Home devices, batteries or the Home Device Health dashboard. Firmware output,
resource readings and compatibility need live validation on the pilot processor.
Reports contain raw read responses and missing-command notes, not inferred
metrics. They stay in memory; logs contain only counts. The configured password
is redacted; credentials and keys are excluded from the report. Downloads use
HA ingress and CSRF protection. No new app API/network permissions are added.

Primary references:
- https://docs.crestron.com/en-us/8559/Content/Topics/Reference/Architecture.htm
- https://www.crestron.com/Products/Catalog/Control-and-Management/Control-System/Residential/CP4-R
- https://docs.crestron.com/en-us/8559/content/topics/Reference/Program-Management.htm

### CP4-R observed console syntax (0.10.1)

Use bare IPTABLE instead of all-program options rejected by the Home processor.
Classify Bad or Incomplete Command / Invalid Application Id responses as errors.
Accept the actual UPTIME no-parameters help and RAMFREE optional-flag help using
read-only purpose confirmed by HELP ALL. Add advertised SYSTEMREADY, PROGUPTIME,
REPORTCRESNET and TOP display queries. TOP is last and bounded; an incomplete
process snapshot closes the connection without sending further commands.
CPU, uptime, RAM, program-uptime and TOP help are captured before execution.
CPULOAD remains unattempted when absent. No arbitrary arguments are accepted.

The output now distinguishes hardware, control-engine and Home setup-program
versions. The pilot verified CP4-R HW2, control-engine 2.8000.00057 and Home
setup program 4.012.0168. Do not confuse those version namespaces or infer update
availability. New display queries still need live validation.

## Control4 discovery (0.11.0)

Configure the official Control4 integration in HA first. Select **Discover
Control4 readings**, wait for the background check, refresh, and download the
Control4 JSON report. No customer account credentials are copied into this app.
A single configured entry is selected automatically; multiple entries require
selection. Selection is saved separately from Crestron and other connectors.

The shared HA reader inventories only devices/entities associated with the
selected control4 entry and platform. Failed/disabled entries do not supply
retained states as current readings. Disabled entities/devices are inventoried
without queries. Supported enabled sensor, binary_sensor, light, cover, climate,
lock, media_player and switch states are GET-only snapshots. Scenes/buttons are
inventory only. Limits remain 128 readings (diagnostic sensors first), eight
workers, 512 devices and 1024 inventory entities, with explicit truncation.

No controller commands, scenes, device services, account changes, reloads or
config writes are implemented. This does not establish CORE CPU, RAM, uptime,
Zigbee health or full device connectivity. Those require independently verified
diagnostic interfaces. Registry software version is metadata, not a fresh
firmware query. Last-update time is not a heartbeat, and off is not offline.
The report retains only allowlisted state attributes, excludes credentials and
config-entry data/options, and requires ingress plus CSRF to download. Snapshots
remain in memory; logs include only reading counts. Live Control4 discovery and
report compatibility remain pending.

Reference: https://www.home-assistant.io/integrations/control4/


## Combined service report (0.12.0)

Click **Run All Checks**, wait several minutes, then **Refresh service report**.
Download **ADR-Service-Report.json** for a single report covering WattBox, Sonos,
Ruckus, UniFi, Crestron, Control4, Araknis and CP4-R. It runs sequentially in the
background and continues when one system fails or needs setup. Existing SSH
identities must already be approved. Existing saved HA selections are used;
Ruckus requires explicit selection. If an HA integration/device needs selection,
run its individual check first. Combined results do not replace individual panels.

“Verified” means the specified read succeeded, not full equipment health.
Unavailable/unknown states, partial reads and invalid volume values are findings
to review. Missing setup or failed reads remain unverified. Per-check timestamps
record the collection window; HA state age is not a heartbeat. Off/idle is not
offline. CPU/Zigbee/full connectivity limits of the individual checks still apply.

A second successful run compares Araknis RX discard counters and CP4-R system
and program start times against the preceding successful comparable result for
the same target in this app session. A decreased counter can mean wrap/reset;
no packet-loss rate or cause is inferred. Changed start times mean a possible
restart or clock adjustment. Unread metrics are not carried into current results.
Reports and comparison baselines remain in memory and clear on app restart.
Logs contain only timestamps and check counts, not raw reports or credentials.

Duplicate clicks do not launch extra runs. Other device operations are blocked
while the combined run is active. Combined WattBox checks read inventory only:
they never create reboot confirmations or issue power commands. Scheduling and
alerts are not included. Live combined-report verification remains pending.


## Bluesound / BluOS (0.13.0)

Use Home Assistant's Bluesound integration, then click **Discover Bluesound readings**,
refresh, and download **ADR-Bluesound-Discovery.json**. If not configured, add Bluesound
under HA Settings > Devices & services > Add Integration. The agent does not install,
reload or change integrations. Reference: https://www.home-assistant.io/integrations/bluesound/

All configured Bluesound entries are included, up to 32, with exact platform and
entry matching. Only loaded enabled entries supply states. Supported enabled
media_player, sensor and binary_sensor entities are GET-only reads, bounded to
128 readings (diagnostic sensors first), eight workers, 512 device records and
1024 inventory entities. Limits are explicit. Disabled devices/entities and buttons
are not queried. HA registry model/software metadata and allowlisted state
attributes (volume, mute, source, exposed diagnostic fields) are retained; credentials,
config-entry options/data, raw media URLs and playback titles are excluded.

Bluesound is also the ninth **Run All Checks** item. Off/idle is not offline;
unavailable/unknown/read failures remain findings to review, not proof of physical
failure. HA timestamps are not a heartbeat; CPU/RAM/uptime/full network diagnostics
remain unverified. No playback, grouping, volume, sleep-timer, reboot or configuration
actions are added. Reports remain in memory, with count-only audit events.
Live integration/report compatibility requires verification.


## Summary dashboard and historical observations (0.14.0)

Run All Checks fills nine responsive summary cards. Key readings come from the
latest combined snapshot. Expand Service findings, Data limitations, or Observations
and comparisons beneath each card. Read completed means the query succeeded; it
is not a full health verdict. Unavailable/read-failed entities remain service
findings to review, with physical connectivity/cause unverified. Unknown states,
invalid volumes and unsupported/partial diagnostics are data limitations. Changed
counters/start times are observations to review, not confirmed equipment faults.
Full raw evidence remains available in the combined JSON download. Individual
checks and connection setup are in a separate expandable section; these remain
separate snapshots. Confirmation panels automatically open their container.

Add historical observation saves an explicit note for the currently selected
system/target. Enter the subject (such as a port) and the confirmed operating
context, then Save. Notes are local app data, not public repository content.
They persist across app restarts, are bounded to 50 records, and are included in
matching-target cards and reports. They do not suppress findings or establish the
cause of a counter. Console history requires an already approved SSH identity;
a changed target/key does not inherit the old target's note. The form requires
Home Assistant ingress plus CSRF and cannot run during combined checks.

Existing chat history is not automatically copied into the installed app. Enter
any desired operating context once using this form. Do not enter credentials.
Raw diagnostic reports and comparison baselines remain in memory and clear on
restart; local historical annotations persist. Logs record annotation events
without note text. No scheduled checks, device writes or new power actions are added.
