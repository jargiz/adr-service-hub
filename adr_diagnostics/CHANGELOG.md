# 0.1.1 preview

- Keep the Web UI available when setup validation fails. Show a specific, safe
  setup message and block all checks until configuration is corrected.
- Trim surrounding whitespace in subnet, target and DNS fields. Targets remain
  explicit private IPv4 hosts; multiple addresses must still be separate entries.
- Handle malformed saved JSON without printing its contents or deleting data.

# 0.1.0 preview

- Add a separate Green-compatible diagnostics app, with fixed target checks,
  bounded ICMP discovery, limited local history and optional cloud explanations.
- Add manual, field-limited import of combined reports for network/power context.
- No changes to the existing Service Agent app. No deployment or live tests.
