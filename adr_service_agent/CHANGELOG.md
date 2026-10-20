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
