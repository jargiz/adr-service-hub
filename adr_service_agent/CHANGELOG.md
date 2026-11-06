## Unreleased

- Tap or press Enter on any history graph to open an enlarged screen with local timestamps, exact recorded sample details, pinch zoom, pan, +/− controls, and Reset zoom.
- Cover ping latency, packet loss, Internet speed, WattBox, UPS, and sensor history using one local viewer. Preserve the displayed period and visible series when opening.
- Close or Escape returns focus to the original graph. The viewer retains its opening snapshot while dashboard collection and refresh continue.
- Add exact timestamp/value inspection to sensor and UPS history without adding dot markers or connecting missing data.
- No device requests, configuration changes, monitoring schedule changes, or automatic restarts. Install only after the active 24-hour ping trial finishes.
- Validation: Python suite, existing JavaScript checks, and desktop/mobile Chromium interaction tests including touch pinch.

## 0.27.1

- Count Bluesound audio zones by media-player entity rather than all readings or hardware devices. Multiple zones sharing one device or integration remain separate.
- Show individual zone cards and separate registered zone count from available states. Disabled/unavailable players remain visible without being labeled online.
- Reserve read capacity for player states when many sensors are present; keep existing global query limits and read-only access.
- Live inventory completeness still requires validation against the actual zones.

## 0.27.0

- Remove dot markers from history graphs and system tiles. Use connected trend lines, short bars for isolated readings, and existing discrete UPS observation bars.
- Add semicircular needle gauges for measured CPU/memory percentages and compact UniFi managed-device cards using existing controller evidence.
- Show discovery rows as labeled cards on mobile, retaining Manufacturer and IP address next to each other.
- Keep Download and Upload together in one timeline with distinct colors, a shared Mbit/s scale, and dated local time labels. Default to 24 hours; week/all views remain available.
- Add bottom local-time ticks to the ping trial and exact timestamp/readings on graph tap or keyboard navigation. Retain selections during display refresh.
- Preserve unknown values, sampling gaps, collection schedules, retention, device controls and the 24-hour trial deadline. No live data is fabricated to fill charts.
- Install after the running ping trial completes; updating restarts the app.

## 0.26.1

- Move IP address directly after Manufacturer in discovery and observed-device tables.

## 0.26.0

- Enrich scoped device discovery with manufacturer, hostname, MAC and IP addresses, reported device type and identity source.
- Read existing pinned UniFi client/device records; fall back to exact local ARP matches and bounded reverse DNS. Conflicting MAC identities remain unverified; do not guess manufacturers from hostnames or randomized MAC prefixes.
- Refresh the last selected, still-allowed discovery subnet every 20 minutes when automatic monitoring and diagnostics are enabled. Persist attempts, defer busy scans and avoid catch-up bursts.
- Check only TCP 80/443 on ICMP responders and provide click-to-open browser links. Keep the configured WattBox HTTP-only exception. Do not fetch pages or log in automatically.
- Retain discovery results separately from connectivity checks; clear stale identities on address reuse and bound enriched history below the existing reader limit.
- Requires a Green update and live validation after the current ping trial finishes.

## 0.25.1

- Remove the empty UniFi gateway measurements dropdown from the Green Internet tile. Gateway readings and history remain in the UniFi tile.
- An active Network Monitoring trial ends on app restart; wait until the trial completes before installing this update.

## 0.25.0

- Add Network → Network Monitoring with Start/Stop for an opt-in 24-hour ICMP trial.
- Sample the configured gateway, Cloudflare and Google once per minute, with a five-minute baseline, latency/loss charts and a JSON history download.
- Stop at the original deadline; duplicate starts cannot extend it. Stop retains history; app restarts interrupt trials without silently resuming.
- Retain up to seven days, 10,080 samples and 32 trials. Missing/failed readings remain unknown; storage errors stop collection.
- Defer ADR speed tests during the trial; existing system checks continue. Speed tests resume on their existing schedule after the trial.
- Requires Green installation and live ICMP verification; simulated tests do not establish live connectivity.

## 0.24.6

- Replace outlet-state graphs with whole-WattBox voltage and amperage readings and history, using the documented read-only PowerStatus query.
- Persist seven days of bounded metered history separately from old outlet observations; preserve missing readings as gaps and isolate history by configured WattBox identity.
- Keep outlet inventory usable when metering is unsupported or fails, without estimating electrical values from outlet state.
- Separate reported outlet state badges from neutral On / Off / Reset controls; pending verification shows Awaiting read.

- Remove redundant History and Connections shortcut icons from the mobile header, leaving the ADR logo.
- Keep the existing History and Connections sections and desktop navigation links.

## 0.24.5

- Replace separate network dot plots with larger paired download/upload line charts, shared axes, colored legends and gridlines inspired by the supplied OvrC references.
- Add local chart controls for individual readings and 24-hour, week or all-recorded periods; retain selection during dashboard refresh without running tests or contacting devices.
- Connect daily scheduled speed-test observations while preserving explicit unknown readings and gaps longer than 36 hours; never extend results to the current time.
- Group latency series on a shared chart, retain Green/UniFi source separation and use client-site local dates in labels and sample details.
- Replace UPS and WattBox history dots with observation bars on dashed unobserved-time rails; never infer uninterrupted utility power or exact outage durations between reports.

## 0.24.4

- Feature an expanded Internet tile at the top of Network with Green speed/latency results and source-labeled history graphs; keep UniFi gateway results separate.
- Persist bounded WattBox outlet observations for seven days and show sampled outlet count/change history without inventing wattage or exact transition times.
- Plot USB UPS observations as receipt-time event markers, preserving monitoring gaps and separate reported times.
- Add Green sampled ICMP-loss and DNS-lookup timing history; render all graph axes in the configured site timezone.
- Add a Power-view USB UPS card showing reported utility/battery state, listener gaps and the latest recorded events in the client site's timezone.
- Separate baseline, outage/restoration and communication events; never promote last-known state to current when disconnected.
- Add an Ask ADR tile on every view and a fifth bottom-bar shortcut, sharing one form, question and answer.
- Keep Ask ADR and navigation available during the first running system check; shortcuts clear summary filters without changing the selected view or starting a recording/request.

## 0.24.3

- Add an explicit Ookla SpeedTest add-on provider for Green, independent of UniFi gateway tests.
- Read only the add-on's fixed download/upload/ping sensors and require matching server IDs, transfer-byte metadata, finite values and recent aligned timestamps.
- Start only the known installed SpeedTest add-on through the Core service; never trigger the original Python integration, accept licenses, restart an app or retry an ambiguous start.
- Require three new results after a test request; retain original measurement times and isolate history by provider/server.
- Preserve Cloudflare as an explicit provider option, without automatic fallback from failed Ookla results.

## 0.24.2

- Run router-independent HTTPS throughput tests from Green, with a fixed Cloudflare endpoint, verified TLS, bounded payload and no retries or redirects.
- Include Green ICMP latency/loss samples and host DNS resolution in system checks at every site, without controller credentials.
- Keep Green and UniFi gateway tests available separately; scheduled speed tests use Green.
- Preserve measurement timestamps and separate Green history; include fresh individual results in the dashboard, reports and Ask ADR.
- Preserve unverified missing directions and remove throughput older than 24 hours from current readings.

## 0.24.1

- Accept seconds/milliseconds in UniFi result timestamps and avoid rejecting new results from the same start second.
- Distinguish controller authentication/endpoint failures and stop further network requests after access denial.

- Make summary totals open matching systems and findings, with a clear filter and retained selection across background refreshes.

- Use the configured client site timezone in dashboard, browser event history and Ask ADR.
- Convert timestamp copies before analysis, preserving local dates and daylight-saving abbreviations; retain original journal timestamps.
- Explain that an unchanged sensor timestamp alone does not establish stopped monitoring.

## 0.24.0

- Add read-only USB/NUT status and native notification subscriptions with persistent, bounded outage/restoration history for Ask ADR and report downloads.
- Prefer configured USB monitoring over WattBox UPS polling while retaining outlet controls.
- Separate baseline, monitoring-gap, communication and battery/line events; retain source and receipt times and suppress duplicate transition reports.

- Add a shared network-evidence format with UniFi as the primary controller adapter.
- Read UniFi device/port STP state, error and multicast/broadcast counters, and per-network IGMP snooping settings through fixed GET-only controller routes.
- Compare target-scoped port states and counters without interpreting cumulative counts as loss rates or storms.
- Include bounded older STP/IGMP/loop-related native reports in Ask ADR, preserving original event and receipt times.
- Add secondary Araknis help-gated STP, loop-protection, IGMP, MAC-count and LLDP display discovery.
- Preserve unverified coverage for unsupported root/querier/membership fields and unconfirmed native event delivery.
- Include the unpublished 0.23.1 cleanup. No port, root, VLAN, multicast or protection configuration changes.
- Live UniFi key/firmware and Araknis display formats still require acceptance. USB/NUT status readings were observed in the lab; native notification delivery and outage capture still require live acceptance.

## 0.23.1 — development

- Stop HTTPS connectivity probes to the configured HTTP-only WattBox.
- Remove recording-file upload controls; retain Speak and transcript review.

- Give Ask ADR newer individual Araknis diagnostics with original timestamps.
- Keep raw switch console text out of cloud analysis and retain the combined report.
- Remove the dedicated power section from Ask ADR; keep relevant power evidence.
- Preserve native log integration behavior; no historical outage was retrieved.

## 0.23.0 — development

- Add disabled-by-default source-allowlisted UDP syslog input in the existing app.
- Retain CEF/syslog messages and explicit text-log imports with separate device/receipt times.
- Feed recent native events and coverage limits directly into Ask ADR.
- Add compact source status/history and log import controls, with no new graphs.
- Include 0.22.1 conversation usability and Araknis polling-blocker fixes.
- Native forwarding/backfill and live firmware compatibility require on-site acceptance.

## 0.22.1 — development

- Make daily analysis and voice limits configurable; default to 100 each, 0 unlimited.
- Remove repeated page checkboxes; explicit Ask/Speak/Transcribe buttons send requests.
- Read new replies aloud by default, keeping manual Read and Stop controls.
- Allow manual Araknis read-only operations during a separate WattBox UPS poll.
- Keep cloud/voice configuration gates and all outlet confirmations intact.

## 0.22.0 — development

- Add optional read-only UPS link/status polling using the approved WattBox SSH connection.
- Persist bounded power observations and state changes with explicit coverage gaps.
- Feed current UPS status and recent events directly into Ask ADR.
- Show a concise power status line and expandable history; no extra graphs.
- Preserve outlet inventory on failed UPS reads and existing action confirmations.
- Default new polling off; firmware compatibility still requires live verification.

## 0.21.0 — development

- Add opt-in push-to-talk and audio-file transcription inside Ask ADR.
- Review transcribed questions before submitting; preserve typed edits.
- Read answers using the browser voice, with optional automatic readout.
- Stop microphone tracks on cancellation or page exit; no audio files retained.
- Gate audio uploads with ingress, CSRF, consent, operation guards and daily quota.
- Keep voice off by default; existing 0.20.0 settings continue to work.

## 0.20.0 — development

- Combine bounded local diagnostics and Ask ADR into the existing Service Agent.
- Use current service readings directly for analysis; no report imports.
- Run configured connectivity checks in the existing check schedule.
- Preserve questions and expanded views during status updates.
- Keep cloud analysis opt-in, request-bound and separate from confirmed controls.
- Add optional configuration, iputils-ping and NET_RAW for local diagnostics.
- Existing 0.19.1 settings default to unchanged monitoring with new features off.

# 0.19.1

- Automatically read WattBox outlet status after On / Off / Restart actions,
  including an unconfirmed command response. Power commands are never retried.
- On / Off checks run after 2, 5 and 15 seconds, stopping when the requested
  state is observed. Restart checks run after 15, 30 and 60 seconds.
- Refresh only the WattBox tile and its read timestamp; retain other systems
  and the original combined-run timestamp. Report exports include the post-action
  verification timestamp and expected/observed power state.
- Keep background display updates active during verification and block further
  outlet actions until it finishes. Failed reads retain an unverified marker.
- Validation: 207 automated tests. Physical outlet verification requires a live check.

# 0.19.0

- Replace timed whole-page reloads with hash-authorized same-origin background
  GET updates. Preserve the selected category, existing expanded details and
  scroll anchor; pause updates while editing forms or confirming power actions.
- Add WB-800 per-outlet On, Off and Restart controls with a separate opt-in,
  fresh inventory/label/SSH identity checks, expiring single-use confirmation,
  persistent cooldown and no automatic command retries.
- Replace displayed Speedtest.net readings with a direct pinned-HTTPS UniFi
  gateway connection. Require a local Network API key, explicit site/WAN and
  certificate approval. No source fallback or invented measurements.
- Add bounded persistent speed-test and gateway-latency graphs, keeping test
  timestamps distinct from collection time and separating gateway identities.
- Add an explicit Ruckus Online-code verification step tied to the pinned
  controller. Unknown numeric codes remain unknown until verified against its UI.
- Validation: 201 automated tests; browser checks for in-place refresh, scroll,
  expansion, no background POSTs, failed-read retention and responsive layout.
- Installation checks still required: local gateway API compatibility, a real
  gateway result and scheduling; Ruckus code verification; actual outlet controls.
  No household power commands or live network tests were sent during development.

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

