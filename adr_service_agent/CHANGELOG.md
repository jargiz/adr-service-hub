# 0.18.1

- Keep phone navigation at the visible bottom while scrolling, including ingress frames.
- Remove Add observation and the Test Apple TV card. Retain saved notes and
  WattBox identity approval under Connections.

# 0.18.0

- Add a light touch-panel layout with three large category launch tiles, native
  outline icons, concise system cards and expandable readings/graphs.
- Use bottom category navigation on phones and a white sidebar on desktop.
- Move detailed status/progress and network tools behind compact controls while
  retaining source readings, findings, approval steps and all existing safeguards.
- Remove the top-right monitoring badge and use AV/Automation consistently.
- Preserve the selected category across automatic refresh with a fixed,
  hash-authorized presentation script; no new device or network requests.
- Validation: automated suite and four-width/category browser checks pass.

# 0.17.2

- Give the logo/navigation a white background with dark navigation text.
- Keep headings on one line, shorten mobile setup titles and remove section
  taglines, system-category subtitles and repeated explanatory captions.
- Collapse completed-check lists and setup help while preserving errors, approvals
  and measurements.
- Validation: 186 tests pass; browser checks at 320, 390, 768 and 1440 pixels
  confirm white navigation, single-line headings and no page-width overflow.

# 0.17.1

- Show the specific Ruckus certificate-approval requirement beside AP cards and
  open connection setup for that condition, preserving explicit certificate trust.
- Flag the speedtest-cli 1,800,000 ms failed-probe value and associated bandwidth
  readings for verification. Keep raw values but exclude that value from latency
  chart scaling, so gateway latency remains readable.
- Distinguish fresh timestamps from measurement quality in manual test results.
- Validation: 186 automated tests pass, including failed-probe recognition, raw
  value preservation, chart scaling, freshness/quality separation and approval UI.
- Live AP login and bandwidth accuracy still require validation at the house.

# 0.17.0

- Enable automatic local system monitoring every 20 minutes and speed tests every
  six hours by default. Expose configurable intervals and independent test disable.
- Persist attempt times, add startup delay, defer busy runs and avoid missed-run
  queues or immediate failure retries. Manual runs reset the matching schedule.
- Show next check/test times and approximate countdowns; refresh the idle dashboard
  automatically without triggering device reads from page requests.
- Default new installs to Start on boot; existing installations keep their app setting.
- Validation: 180 automated tests pass, including restart timing, busy deferral,
  opt-out, failure cadence, manual schedule resets and background operation.
- Retain the latest completed report during refresh. Schedules never invoke power
  commands or configure missing connections. Live house validation remains pending.

# 0.16.0

- Add a separate explicit Internet speed-test action using an enabled configured
  Speedtest connection, with one targeted update and automatic result refresh.
- Add optional pinned-HTTPS direct Ruckus Unleashed AP statistics, per-AP states
  and connected-device counts. Unknown state codes/counts remain unverified.
- Include direct AP reads in combined reports when configured; flag failed reads.
- Prioritize Sense main-monitor voltage, whole-house power and daily energy over
  detected appliances. Flag disparate line readings for source verification.
- Preserve on-demand read-only combined checks, ingress/CSRF and power safeguards.
- Validation: 168 automated tests pass; exact-library mocked login/statistics
  smoke check passes. Controller and speed-test service setup/live compatibility
  require house validation.

# 0.15.1

- Use plain system/reading labels throughout the app, including upstream messages
  and fallback sensor names, without displaying internal platform terminology.

- Show combined-run progress with the current system, completed count and per-system statuses.
- Auto-refresh the read-only page every three seconds while checks run, then stop
  refreshing once the completed report or failure status is displayed.
- Disable Run All Checks while running; retain duplicate-run and power safeguards.
- Refresh uses GET only, never replays the command POST or triggers extra checks.

# 0.15.0

- Match ADR Billing branding with the bundled ADR logo, red accents, white cards,
  light gray background and black system headings.
- Group the dashboard into Power, Network and AV & Automation with accessible
  category selectors, compact gauges and outlet-power indicators.
- Add Sense to Run All Checks and individual discovery/JSON downloads using
  configured Home Assistant integrations only. Read exposed voltage, power,
  energy and measurement metadata without storing Sense credentials.
- Read up to six Sense sensor histories for the past 24 hours from the existing
  Home Assistant recorder. Show source names/units, gaps and missing history;
  bound requests to 1 MB and 2000 states per series. No polling/recorder changes.
- Display gateway latency and existing enabled Speedtest integration readings;
  never trigger a bandwidth test or enable sensors. Show registered Ruckus APs
  individually with per-AP status/client counts explicitly unverified.
- Format dashboard times in Eastern time; preserve raw report timestamps.
- Preserve ingress, CSRF, SSH pinning and confirmed single-outlet power safeguards.
- Simulated suite: 148 tests. Live 0.15 dashboard/Sense compatibility pending.

# 0.14.0

- Add responsive summary cards for all nine systems, with key readings and expandable findings.
- Separate service findings, data limitations, observations and target-specific historical notes.
- Classify unsupported CPU and invalid volume fields as limitations rather than service faults.
- Keep changed discard counters visible as observations without claiming a service fault or suppressing them from history.
- Add explicit local historical annotations, bounded to 50 records, persisted with private file permissions and matched to target identity.
- Collapse individual connection/setup panels; keep power confirmations visible when requested.
- Preserve on-demand checks, in-memory metric baselines, and separate confirmed WattBox actions.
- Live dashboard verification remains pending.

# 0.13.0

- Add read-only Bluesound discovery through configured Home Assistant integrations.
- Inspect all configured Bluesound players, bounded to 32 entries and 128 readings.
- Add a Bluesound dashboard section, downloadable JSON report and ninth combined check.
- Skip disabled devices/entities and unloaded integrations; exclude button actions and credential fields.
- Live Bluesound compatibility remains pending.

# 0.12.0

- Add background Run All Checks with one combined JSON report for all eight existing checks.
- Distinguish successful reads, findings to review, and unverified results without claiming full equipment health.
- Compare switch RX discard counters and CP4-R reported system/program start times for the same target within an app session.
- Continue after individual failures; block overlapping device operations during a combined run.
- Keep WattBox inventory read-only, with no power confirmation or reboot from combined checks.
- Prevent stale UniFi selections from silently reading a different controller/device.
- Combined report compatibility requires live verification.

# 0.11.0

- Add read-only Control4 discovery using the existing Home Assistant integration.
- Reuse bounded, selected-entry HA inventory/state reads without controller credentials.
- Add separate Control4 selection, background check and JSON report download.
- Keep resource/Zigbee/full connectivity health explicitly unverified.
- Live compatibility with the pilot's CORE 1 integration remains pending.

# 0.10.1

- Use the Home processor's bare IP-table query and classify console rejections correctly.
- Accept observed uptime/RAM help without requiring redundant description words.
- Add advertised system-ready, program-uptime, Cresnet and bounded process/CPU reads.
- Distinguish control-engine firmware from Home setup-program and hardware versions.
- Revised display reads require live validation; no control commands added.

# 0.10.0

- Add optional direct CP4-R SSH connection with separate explicit host-key trust.
- Read processor version, advertised diagnostics and read-only all-program IP table.
- Capture CPU/memory/uptime help and query only supported display syntax.
- Add a bounded CP4-R report without restarts, config writes or inferred health.
- Live processor access and command compatibility remain pending.

# 0.9.0

- Add background read-only discovery of existing Crestron HA integrations.
- Inventory the selected integration's devices/entities and exposed states.
- Preserve disabled, unknown, unavailable and failed readings without health inference.
- Add a Crestron JSON report download without processor credentials or new permissions.
- Live compatibility with the pilot integration remains pending.

# 0.8.1

- Normalize terminal controls before recognizing pager/help response boundaries.
- Prioritize system, resource, power/PoE and concise interface-status checks.
- Defer verbose interface reads and omit redundant env-all component reads.
- Keep the existing read-only limits and credential protections.
- Live timing and complete-report validation remain pending.

# 0.8.0

- Add one-run, bounded read-only command discovery from supported CLI help.
- Run only allowlisted paths that explicitly advertise an executable <cr> form.
- Add an authenticated, CSRF-protected JSON report download with credential redaction.
- Include captured syntax, failures and limits without copying each screen.
- Keep reports in memory and require an explicit download; no automatic upload.
- Live discovery and phone download validation remain pending.

# 0.7.0

- Use system/environment/power command suffixes reported by the pilot CLI help.
- Remove show cpu, which reports traffic mirroring rather than CPU utilization.
- Raise bounded interface pagination to 96 pages/256 KB with a 90-second deadline.
- Show reported interface links, negotiated speeds and cumulative receive counters in a table.
- Keep raw responses, missing fields and explicit truncation; no inferred health verdicts.
- New command suffixes and full-interface reads need live validation.

# 0.6.1

- Use an independent authenticated SSH connection for every diagnostic/help request.
- Preserve incomplete-command output and status when its syntax-help request fails.
- Keep unrelated reads independent; abort on authentication or host-key failures.
- Add regression tests for session loss, independent connections and changed keys.
- Live validation of this collector fix remains pending.

# 0.6.0

- Add background, on-demand Araknis diagnostic snapshots with six fixed show requests.
- Request category-specific syntax help for incomplete or invalid commands.
- Use separate command channels, bounded pagination, and explicit error states.
- Keep all raw responses in memory; no configuration or power controls.
- SSH login/show help verified on the pilot; diagnostic requests need live validation.

# 0.5.1

- Request `show ?` context help instead of root CLI help.
- Advance explicit pager prompts, limited to eight pages and 32 KB of content.
- Add simulated pager and output-bound tests; live show-help testing pending.

# 0.5.0

- Add optional Araknis SSH configuration and separate host-key approval.
- Add on-demand authenticated login and CLI help inspection from ingress.
- Send only the help character; no port, PoE, restart or configuration commands.
- Keep bounded responses in memory and reject changed saved SSH keys.
- Live switch validation is pending.

# 0.4.0

- Add read-only UniFi diagnostics with integration and device selection.
- Read only enabled sensor/binary_sensor entities for the selected device/entry.
- Show values with units, snapshot/update timestamps, disabled sensor names,
  and explicit unavailable/read-failed states without assuming network health.
- Never send gateway, firewall, switch, PoE, restart or other network commands.
- No new API permissions or manual controller credentials are required.
- Add seven simulated connector tests. Live UniFi display testing is pending.

# 0.3.0

- Add read-only Ruckus diagnostics with explicit config-entry selection.
- Show HA entry state, saved integration device inventory and supported reported
  entity states for only the selected Ruckus entry.
- Retain selection in this app's private data; never rename, reload, disable or
  delete Home Assistant integrations or devices.
- Exclude retained entity readings when an entry is failed or disabled.
- Clearly separate reported presence and inventory from live network/AP health.
- Add six simulated tests; live Ruckus display testing remains pending.

# 0.2.0

- Add on-demand read-only Sonos diagnostics through the installed Home Assistant
  Sonos integration: playback state, mute, volume, source/track, and grouping.
- Discover only enabled media players registered to the Sonos platform.
- Show snapshot and HA update times, missing values and per-player failures.
- Enable Home Assistant Core API access for the connector. Its token is supplied
  internally; no manual token configuration is required. That permission is not
  read-only at the platform level; the Sonos connector implements reads only.
- Do not send Sonos control commands or persist playback/track history.
- Preserve existing WattBox configuration, saved identity and reboot safeguards.
- Sonos connector tests use simulated HA responses; live Green testing is pending.

# 0.1.0

- Initial experimental WattBox connector with ingress UI, SSH identity pinning,
  outlet inventory, confirmed single-outlet RESET, cooldown and power verification.
- Hardware build and live integration testing remain pending.
