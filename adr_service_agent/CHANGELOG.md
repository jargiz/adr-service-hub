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
