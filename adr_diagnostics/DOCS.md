# Setup

This is a draft prototype. Read README.md for installation boundaries, supported
checks, resource limits and privacy details. It is a separate app alongside ADR
Service Agent; automatic data sharing and embedding in Service Agent are pending.

1. Configure allowed_subnets and up to sixteen target IPv4 addresses locally.
2. Start ADR Diagnostics Preview and open its Web UI. Startup sends no diagnostic
   traffic unless optional monitoring has been enabled and its delay has elapsed.
3. Select Run checks. Review results and app/host resource usage.
4. Select a configured subnet and Discover devices for one ICMP discovery pass.
5. Optionally import an ADR combined JSON report, up to 512 KB. Only fixed UniFi,
   Ruckus and WattBox fields are retained; original reading times remain visible
   to analysis. Import is manual and does not refresh any device.
6. Optionally configure cloud analysis, an API key and available model. Confirm
   sending collected evidence each time you use Ask ADR. No cloud request runs on
   a schedule. The model explains readings and cannot execute commands.

Do not uninstall, reconfigure or restart the existing ADR Service Agent or other
home services to test this app. Actual Green container and resource validation
remain pending.
