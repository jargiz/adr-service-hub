# ADR Service Hub pilot

Version 0.19.0 (draft) is a local Home Assistant app for a single WattBox test device,
read-only Sonos diagnostics, Ruckus integration/presence diagnostics and UniFi
sensor diagnostics, Sense energy/voltage with existing HA history, and direct
Araknis SSH login/help inspection.
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


## Dashboard and Sense (0.15.0)

ADR Billing branding, the bundled ADR logo and black system headings are used
throughout the overview. Category controls show Power, Network or AV & Automation;
Overview shows all ten systems. Gauges display only finite utilization readings
between 0 and 100. Outlet tiles indicate reported power only.

Run All Checks includes Sense. Individual Sense discovery and its JSON download
are also available under Individual checks and connection setup. Only enabled
sensor/binary-sensor entities owned by configured, loaded Sense entries are read.
No additional Sense credentials are stored. Current reads are limited to 128
entities across 32 entries; disabled entities and controls are inventory only.

Sense history is pulled on demand from the existing HA recorder for the past
24 hours, limited to six enabled voltage/power/energy sensors, 1 MB per response
and 2000 states per series. Main usage/voltage labels are prioritized when limits
apply, but every graph displays its actual source sensor name and unit. Missing
states remain gaps, and no history is synthesized. Sampled voltage does not
establish whether short power-quality events occurred. HA continues its existing
Sense collection independently; this app does not change polling, install a new
collection service or change recorder settings. Historical availability depends
on HA recorder configuration and retention. No history or report data is uploaded
or permanently stored by this app; downloads include it for review.

The Network panel displays existing gateway latency and enabled readings from
configured Speedtest integrations when present. It never triggers bandwidth tests,
installs integrations or enables disabled sensors. Subscribed ISP plan speed is
unconfigured. Registered Ruckus APs are shown by name and model. The existing HA
snapshot does not establish per-AP online state or connected-client counts, so
these stay explicitly unverified. Router client presence is not AP health.

Dashboard timestamps use Eastern time with bundled timezone data; downloadable
reports retain their original timestamps. Startup still performs no device checks.
Existing connection settings, local notes and power safeguards are unchanged.


## Run progress and automatic refresh (0.15.1)

Run All Checks shows the current system, completed count, a progress bar and each
system's status. Every finished read, including skipped/failed reads, advances
one step. The percentage counts systems, not elapsed time or equipment health.
During the combined run, the page automatically navigates to its read-only GET
view every three seconds. It never resubmits the POST command, restarts checks
or sends extra device commands. On completion or failure, automatic refresh
stops and the final status/report appears. Duplicate Run All clicks remain
blocked server-side and the button is disabled while running.

Visible app copy uses plain system names and reading labels. Internal protocol
identifiers and raw report schemas remain intact for diagnostics.


## Network measurements (0.16.0)

Internet speed tests are a separate explicit action. Run All Checks remains read-only
and only reads stored speed-test results. In Settings → Devices & services, configure
Speedtest.net once if absent. Its upstream default is hourly polling; turn off
"Enable polling for updates" in its system options if tests should be on demand only.
Keep its download/upload/ping sensors enabled. Open the ADR app and select
Run Internet Speed Test. The one targeted update may use substantial Internet
capacity; wait for automatic refresh. Duplicate in-flight app requests are blocked.
Stored values retain their timestamps, and a completed request without confirmed
fresh timestamps remains explicitly unverified. This measures the service host,
not the subscribed ISP plan speed or a phone's Wi-Fi performance.

For direct Ruckus Unleashed AP statistics, set ruckus_controller_host, port (443),
username and password in app Configuration. Use the management/master address,
not a member AP. Then open Connections → Individual checks, inspect the controller
certificate, compare its SHA-256 fingerprint over a trusted connection, and approve.
Read Access Points performs one direct statistics read. Run All Checks includes
it when configured. No AP configuration, restart, or firmware commands are sent.
HTTPS is pinned, cross-origin redirects are rejected, responses are bounded, and
credentials/raw session data are excluded from reports. Unknown numeric controller
state codes remain unverified until mapped from confirmed controller evidence;
missing counts remain unknown. No live-controller compatibility claim is made.

Sense now prioritizes main-monitor voltage, power and daily energy before appliance
readings and history. A large difference between two reported line voltages is
flagged for source verification, not classified as proof of an electrical fault.


## Automatic local monitoring (0.17.0)

Monitoring is enabled by default, including upgrades with the new options absent.
System reports run every 20 minutes and Internet speed tests every 360 minutes
(6 hours). The first due operation waits at least 60 seconds after app startup.
It runs on the app host, even with the dashboard closed; no ChatGPT task is required.
The app must remain running. New installs default to Start on boot. On an existing installation, check that
Start on boot is enabled in app settings if monitoring should resume after a host reboot.

Options in app Configuration:
- automatic_monitoring: true (false disables all automatic jobs)
- monitor_interval_minutes: 20 (5–1440)
- automatic_speedtests: true (false keeps system monitoring but disables scheduled tests)
- speedtest_interval_minutes: 360 (60–10080)

Save options and restart only the ADR app to change intervals. Configured connection
and approved device identities remain required. Scheduling does not configure missing
Speedtest or Ruckus connections, approve certificates, or enable disabled sensors.
Disable Speedtest.net's own polling to avoid a separate upstream hourly schedule.

The scheduler serializes with manual operations, defers while checks/power operations
or a live power-confirmation review are pending, and runs a due speed test before a
due system report. Missed runs are not queued. A failed attempt waits until its normal
next interval; no immediate retry is sent. Manual runs reset the matching next due
time. Attempt times persist privately across app restarts, preventing restart bursts.
A corrupt schedule file delays the first runs by a full interval. Previous completed
reports stay visible while a refresh runs, with original collection timestamps.
The page refreshes by GET every 60 seconds while idle and monitoring, every three
seconds during an active check, and avoids idle refresh during power confirmation.
The schedule panel shows intervals, next times, approximate minutes remaining, and
running/deferred states. Opening or refreshing the page never triggers a check.

Automatic jobs only invoke the existing read-only report and the explicit bandwidth
measurement service. No schedule can invoke WattBox resets or configuration changes.


## Measurement quality and controller setup (0.17.1)

The known speedtest-cli failed-probe ping value of 1,800,000 ms is retained in raw
reports but excluded from the latency chart scale. Associated bandwidth readings
are labelled as needing verification. The app does not replace the numbers with
zero, claim an ISP fault or treat a failed server probe as a valid latency reading.
Gateway latency remains separate. Verify/select the Speedtest server and compare
bandwidth with a gateway or other wired test before drawing a network conclusion.
Reference: https://github.com/sivel/speedtest-cli/blob/master/speedtest.py

A missing matching Ruckus certificate approval now appears directly beside the
AP cards with the setup instruction. The Connections section opens for that
condition; inspect, independently compare and approve the controller certificate,
then Read Access Points. No trust is automatically granted. Unknown controller
status codes still remain unverified until confirmed from controller evidence.


## Compact dashboard (0.17.2)

Use a white navigation/logo background and black single-line headings. Remove
section taglines, repeated system categories and category-count captions. Shorten
setup titles for mobile widths and move configuration instructions into collapsed
Setup details. Preserve measurement warnings, connection errors, approvals,
reports and monitoring behaviour. Long dynamic headings can be read via tooltips.


## Light touch-panel dashboard (0.18.0)

The overview opens with three large Power, Network and AV/Automation tiles.
Selecting a category shows its systems. On phones, category navigation stays at
the bottom; desktop uses the light sidebar. System tiles show a native outline
icon, recorded status, one key reading and update time. Tap a tile to expand its
readings, charts and findings. Original metadata stays available in expanded
content and downloads; no sensor reading or device-control behaviour is changed.

Validation: 186 automated tests pass. Browser checks cover all four category views
at 320, 390, 768 and 1440 pixels, plus native tile expansion and page overflow.
The conversation preview uses the previously supplied report and disables device
actions; it does not represent new live checks. The selected category persists within the browser tab across automatic refreshes.
A fixed, hash-authorized script saves only that category in session storage and
makes no network or device requests. If storage is unavailable, navigation still
works, but refresh returns to Overview.

## Mobile navigation (0.19.0)

Phone navigation remains outside the scrolling dashboard sections and tracks the
visible viewport in the embedded app. Add observation and the Test Apple TV card
are removed. Existing saved notes remain readable; WattBox identity approval
remains under Connections.

## Draft dashboard changes (0.19.0, not published)

Automatic display refresh now reads the page in the background rather than
navigating. Existing details and category selections remain in place. Changed
values are patched without replacing the page. Form editing and power approval
pause updates. Fetch failures retain the current page; a software change requires
reopening the app. Background GETs never start checks or power actions.

WattBox controls require `allow_outlet_control: true`, separately from the legacy
single-outlet pilot's `allow_reboot`. Each On/Off/Restart request reads labels and
states, then asks for confirmation naming the outlet and equipment. Execution
checks the same pinned target and fresh mapping again. Off and Restart can cut
network access. Device-enforced outlet modes remain authoritative. A timeout is
never retried automatically; acknowledgement alone does not establish recovery.

UniFi speed results require these app Configuration fields:
- `unifi_gateway_host`: local UniFi OS gateway hostname/IP, without a URL prefix.
- `unifi_gateway_port`: HTTPS port, normally 443.
- `unifi_gateway_api_key`: local Network Integration API key (password field).
- `unifi_gateway_site`: internal site reference, normally `default`.
- `unifi_gateway_wan`: primary `WAN` (secondary WAN reads are explicitly selected;
  scheduled tests currently support primary WAN only).

Create the key through the local Network application, then use Connections →
UniFi gateway → Inspect gateway certificate. Independently compare the fingerprint
before approving. The key is sent only after that certificate matches. Read-only
speed results use the controller dashboard endpoint; test execution sends one
`speedtest` command and polls for a newer result. Firmware API compatibility must
be checked against the installed gateway. No alternative endpoint is guessed and
no failed request starts a second test. Scheduled testing uses the existing
six-hour schedule once the gateway connection is configured. Speedtest.net is no
longer a display fallback. Speed history retains up to seven days, latency up to
24 hours, bounded to 512 points per series. Only real samples are graphed; the
reported test timestamp is shown, even when an old test is read again.

Ruckus: Read Access Points, compare the listed APs with the controller dashboard,
then use Connections → Ruckus connection → Verify AP status if every listed AP is
Online. The mapping is explicit and bound to that pinned controller; missing
counts are never zero and other unknown numeric codes remain unverified. This
setup does not infer Offline from a failed read.

Primary API references reviewed:
- UniFi gateway source: https://github.com/biofects/HA-Unifi-Speedtest/blob/main/custom_components/ha_unifi_speedtest/api.py
- WattBox protocol: https://www.snapav.com/wcsstore/ExtendedSitesCatalogAssetStore/attachments/documents/PowerManagement/SupportDocuments/SnapAV_Wattbox_API_V2.2.pdf

This branch is a draft. Live gateway access, actual outlet switching and Ruckus
status calibration were not performed from the development environment.
