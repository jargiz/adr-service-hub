# ADR Diagnostics Preview

Version 0.1.0 is a separate, experimental app for Home Assistant Green and amd64
systems. It does not replace ADR Service Agent. Nothing is deployed by adding
these source files to a draft branch.

Included:

- Fixed-target ICMP samples, TCP connection checks on 80/443, and DNS resolution.
- On-request ICMP discovery of one explicitly configured private IPv4 subnet,
  /24 or smaller; four workers and one bounded process per worker.
- Seven-day local history, capped at 96 samples and 256 observed addresses.
- An Ask ADR panel using one optional OpenAI Responses API request per click.
- Sanitized import of an ADR combined report for UniFi, Ruckus and WattBox context.
- Ingress-only access, CSRF validation, no published ports or Supervisor/Core APIs.

This is a diagnostic prototype with AI explanations, not an installed Codex CLI
or a fully offline model. AI cannot execute commands or invoke device controls.
There is no arbitrary shell, firmware change, reboot, configuration write,
automatic model request or automatic subnet discovery. Individual tools run with
fixed arguments and timeouts. Optional monitoring checks only configured targets.

Network measurements have limits: an absent ping reply is not proof of an outage;
three pings are a short sample; TCP accepts do not prove device operation; discovery
does not establish MAC addresses, Wi-Fi association, or complete inventory. DNS
uses the app resolver, which may differ from a client's resolver. Speed tests and
AP metrics come from imported readings, not new tests by this app.

## Review and installation

The draft must be reviewed before publication or installation. Add the repository
branch to a separate test app-store entry only when approved. Install ADR Diagnostics
Preview alongside ADR Service Agent; existing Service Agent settings are untouched.
Open the new app using its sidebar entry. The first prototype has a separate UI;
embedded navigation and automatic live data sharing with Service Agent are pending.

Architecture: aarch64 and amd64 are declared. Actual Green image build, ICMP
capability, network reachability, performance and cloud model access need installation
verification. Docker is unavailable in this development session; no image build
or physical Green resource measurement has been claimed.

## Configuration

Example addresses below are examples, not installation defaults. Enter the actual
client network locally in app Configuration:

```yaml
allowed_subnets:
  - 192.168.50.0/24
targets:
  - 192.168.50.1
  - 192.168.50.10
dns_name: example.com
automatic_monitoring: false
monitor_interval_minutes: 20
cloud_analysis_enabled: false
openai_api_key: ""
openai_model: ""
```

At most four private IPv4 subnets and sixteen explicit target addresses. Targets
must be host addresses in those subnets. Save and restart only this preview app
after configuration changes. Start with manual checks and observe resource usage.
Enable automatic_monitoring only after the manual pilot succeeds. It waits at
least 120 seconds on startup and checks configured targets at the chosen interval;
it does not run discovery, speed tests or AI analysis. One job runs at a time.

## Ask ADR

Set an OpenAI API key in the password field and an API model available to that
key, then enable cloud_analysis_enabled. Keep credentials out of chat and Git.
No credentials are present in the prototype defaults or tests.

Run checks and/or import a combined service report. Enter a question, review the
collected readings, confirm sending the question and evidence, then select Analyze
results. Model availability and API billing require local account setup. This is
API-key authentication, not reuse of the personal Home Agent login.

Only the latest result, one previous target-check sample, and the sanitized imported report are sent.
They can include local addresses, device labels and measured states. Questions
are not persisted by this app; results/history and imported readings stay in /data.
The request sets store:false; this is not a promise of zero retention across all
provider policies. No tools are supplied to the model and returned text is never
executed. Output is rendered as text. Imported content is treated as untrusted.

Ten analysis attempts per UTC day are reserved on disk before dispatch. Requests
are bounded to 48 KB, output to 1500 tokens, and HTTP reads to 128 KB with a 45-second
socket timeout. Failed calls are not retried automatically and count as attempts.
The token/attempt bounds are not a dollar budget; configure provider spending
controls separately. Missing credentials/model access produce a setup error.

## Resource and data boundaries

Python standard library only. One diagnostic job at a time; discovery has four
workers. Target checks are sequential, with bounded ping, TCP and DNS calls. The
display reports the app process's peak RSS, not total Green or subprocess memory.
There is no enforced container CPU/RAM ceiling in this manifest. Measure total
host use during the pilot before enabling unattended checks.

History retains at most seven days/96 samples; addresses without a recent response
age out. Private JSON files are written atomically with mode 0600. Logs do not
record questions, credentials, LAN addresses, imported raw console text or API
responses. The API key remains in protected app options/backups. No config, SSH
key or shared filesystem mount is requested. NET_RAW is requested for ICMP only;
default AppArmor stays enabled.

## Verification

231 offline unit tests pass across both apps (24 new prototype tests), covering
target/subnet scope, subprocess arguments/timeouts, absent ICMP handling,
read-only TCP, retention, private writes, report sanitization, AI opt-in and
no-retry behavior, quotas, ingress, CSRF, and script hashing. Tests use mocked
network/model calls; they do not establish live LAN or cloud compatibility.
Manifest consistency and JavaScript syntax were checked. Browser rendering and
the Green container build remain installation/review checks.

Official references:

- https://developers.home-assistant.io/docs/apps/configuration/
- https://developers.home-assistant.io/docs/apps/presentation/
- https://developers.openai.com/api/docs/guides/text
- https://developers.openai.com/api/reference/resources/responses/methods/create
