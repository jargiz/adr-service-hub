"""Ingress-only ADR pilot. No HA config mounts or Supervisor API access."""
import html
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from wattbox import WattBox, ProtocolError, fingerprint, inspect_key, pin_key
from sonos import collect as collect_sonos, SonosError
from ruckus import collect as collect_ruckus, entries as ruckus_entries, token_value, RuckusError
from unifi import collect as collect_unifi, UniFiError
from araknis import settings as araknis_settings, inspect as inspect_araknis, snapshot as araknis_snapshot, discover as discover_araknis, report_payload as araknis_report_payload, AraknisError


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def load_config(path):
    data = json.loads(Path(path).read_text())
    host = data.get("wattbox_host", "").strip()
    if not host or len(host) > 253 or any(c.isspace() for c in host) or any(c in host for c in "/\\@"):
        raise ValueError("Set the WattBox address in the app Configuration tab, then restart this app.")
    if type(data.get("ssh_port")) is not int or not 1 <= data["ssh_port"] <= 65535:
        raise ValueError("Invalid SSH port")
    if type(data.get("test_outlet")) is not int or not 1 <= data["test_outlet"] <= 18:
        raise ValueError("Test outlet must be between 1 and 18")
    for key in ("username", "password", "expected_outlet_label", "device_alias"):
        if not isinstance(data.get(key), str) or not data[key].strip() or len(data[key]) > 256:
            raise ValueError(f"Set {key} in the app Configuration tab, then restart this app.")
    if type(data.get("allow_reboot")) is not bool:
        raise ValueError("allow_reboot must be true or false")
    data["wattbox_host"] = host
    return data


def target(config, inventory):
    if not inventory["model"].startswith("WB-800"):
        raise ProtocolError("This pilot permits power actions only for WB-800 models")
    number = config["test_outlet"]
    if number > len(inventory["outlets"]):
        raise ProtocolError("The configured outlet was not found")
    outlet = inventory["outlets"][number - 1]
    if outlet["label"].strip().casefold() != config["expected_outlet_label"].strip().casefold():
        raise ProtocolError("Outlet label differs from the configured expected label. Check the mapping.")
    if not outlet["on"]:
        raise ProtocolError("Test outlet is off. This pilot will not change an off outlet.")
    return outlet


class Pilot:
    def __init__(self, data_dir, options_path, box_factory=WattBox):
        self.data = Path(data_dir)
        self.data.mkdir(parents=True, exist_ok=True)
        self.config = None
        self.config_error = None
        try:
            self.config = load_config(options_path)
        except (ValueError, OSError, KeyError):
            self.config_error = "Complete the app Configuration fields, save, and restart this app."
        self.araknis_options = {}
        try:
            self.araknis_options = json.loads(Path(options_path).read_text())
        except (OSError, ValueError):
            pass
        self.araknis = None
        self.araknis_diagnostics = None
        self.araknis_running = False
        self.araknis_progress = ''
        self.araknis_error = None
        self.araknis_candidate = None
        self.araknis_candidates = {}
        self.box_factory = box_factory
        self.lock = threading.Lock()
        self.csrf = secrets.token_urlsafe(32)
        self.confirmations = {}
        self.candidates = {}
        self.result = "Ready for an on-demand check. No device commands have been sent by starting the app."
        self.inventory = None
        self.sonos = None
        self.sonos_error = None
        self.ruckus = None
        self.ruckus_error = None
        self.ruckus_entries = []
        self.ruckus_selection = ''
        self.unifi = None
        self.unifi_error = None
        self.unifi_selection = {}
        try:
            self.unifi_selection = json.loads((self.data / 'unifi_selection.json').read_text())
            if not isinstance(self.unifi_selection, dict):
                self.unifi_selection = {}
        except (OSError, ValueError):
            pass
        try:
            self.ruckus_selection = json.loads((self.data / 'ruckus_selection.json').read_text())['entry_id']
        except (OSError, ValueError, KeyError):
            pass
        self.active = False
        self.last_attempt = 0
        self.cooldown_error = False
        state_path = self.data / "reboot_state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                self.last_attempt = float(state["last_attempt"])
                if not 0 <= self.last_attempt <= time.time() + 60:
                    raise ValueError()
            except (ValueError, KeyError, OSError, TypeError):
                self.cooldown_error = True

    def ready(self):
        if self.config is None:
            raise ProtocolError(self.config_error)

    def araknis_identity(self):
        config = araknis_settings(self.araknis_options)
        self.araknis = None
        self.araknis_candidate = None
        key = inspect_key(config['host'], config['port'])
        nonce = secrets.token_urlsafe(24)
        self.araknis_candidates = {nonce: (time.monotonic(), key, config['host'], config['port'])}
        self.araknis_candidate = (nonce, fingerprint(key))

    def araknis_trust(self, nonce):
        item = self.araknis_candidates.pop(nonce, None)
        if item is None or time.monotonic() - item[0] > 120:
            raise ProtocolError('Araknis identity approval expired. Inspect again.')
        config = araknis_settings(self.araknis_options)
        if (config['host'], config['port']) != (item[2], item[3]):
            raise ProtocolError('Araknis target changed. Inspect again.')
        pin_key(self.data / 'araknis_known_hosts', item[2], item[3], item[1])
        self.araknis_candidate = None
        self.audit('araknis_identity_approved')
        self.result = 'Araknis SSH identity saved. You can now test login and read CLI help.'

    def check_araknis(self):
        self.araknis = None
        self.araknis = inspect_araknis(araknis_settings(self.araknis_options),
            self.data / 'araknis_known_hosts')
        self.audit('araknis_ssh_help_read')
        self.result = 'Araknis SSH login succeeded. CLI help was requested. Use Read Araknis diagnostics for switch responses.'

    def start_araknis_diagnostics(self, discovery=False):
        if self.araknis_running:
            return
        config = araknis_settings(self.araknis_options)
        if not (self.data / 'araknis_known_hosts').exists():
            raise ProtocolError('Inspect and approve the Araknis SSH identity first.')
        self.araknis_diagnostics = None
        self.araknis_error = None
        self.araknis_running = True
        self.araknis_progress = 'Starting discovery' if discovery else 'Starting diagnostics'
        def progress(message):
            with self.lock:
                self.araknis_progress = message
        def run():
            result, error = None, None
            try:
                if discovery:
                    result = discover_araknis(config, self.data / 'araknis_known_hosts', progress=progress)
                else:
                    result = araknis_snapshot(config, self.data / 'araknis_known_hosts')
            except AraknisError as exc:
                error = str(exc)
            except Exception:
                error = 'Araknis diagnostics failed. No automatic retry was made.'
            with self.lock:
                self.araknis_diagnostics = result
                self.araknis_error = error
                self.araknis_running = False
                if result:
                    self.audit('araknis_diagnostics_read', str(len(result['readings'])) + ' response(s)')
        worker = threading.Thread(target=run, daemon=True)
        try:
            worker.start()
        except Exception:
            self.araknis_running = False
            raise

    def check_unifi(self, entry_id='', device_id=''):
        self.unifi = None
        self.unifi_error = None
        try:
            self.unifi = collect_unifi(entry_id or self.unifi_selection.get('entry_id', ''),
                device_id or self.unifi_selection.get('device_id', ''))
            if self.unifi['entry'] and self.unifi['device']:
                self.unifi_selection = {'entry_id': self.unifi['entry']['entry_id'],
                    'device_id': self.unifi['device']['id']}
                atomic_json(self.data / 'unifi_selection.json', self.unifi_selection)
            self.audit('unifi_status_read', f"{len(self.unifi['sensors'])} reading(s)")
        except UniFiError as exc:
            self.unifi_error = str(exc)
        except Exception:
            self.unifi = None
            self.unifi_error = 'Could not read UniFi information. No device actions were sent.'

    def check_ruckus(self, entry_id=''):
        self.ruckus = None
        self.ruckus_error = None
        self.ruckus_entries = []
        try:
            token = token_value()
            self.ruckus_entries = ruckus_entries(token)
            selected = entry_id or self.ruckus_selection
            valid = {e['entry_id'] for e in self.ruckus_entries}
            if selected not in valid:
                self.ruckus_selection = ''
                return
            self.ruckus = collect_ruckus(selected, token=token,
                entries_fn=lambda _: self.ruckus_entries)
            self.ruckus_selection = selected
            atomic_json(self.data / 'ruckus_selection.json', {'entry_id': selected})
            self.audit('ruckus_status_read', f"{len(self.ruckus['entities'])} reading(s)")
        except RuckusError as exc:
            self.ruckus_error = str(exc)
        except Exception:
            self.ruckus_error = 'Could not read Ruckus integration status. No device or configuration changes were sent.'

    def check_sonos(self):
        self.sonos = None
        self.sonos_error = None
        try:
            self.sonos = collect_sonos()
            self.audit('sonos_status_read', f"{len(self.sonos['players'])} player(s)")
        except SonosError as exc:
            self.sonos_error = str(exc)

    def box(self):
        self.ready()
        return self.box_factory(self.config, self.data / "known_hosts")

    def audit(self, event, detail=""):
        # Do not log credentials, raw responses, network addresses, or tokens.
        with (self.data / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": time.time(), "event": event, "detail": detail}) + "\n")
        (self.data / "events.jsonl").chmod(0o600)

    def key_candidate(self):
        self.ready()
        key = inspect_key(self.config["wattbox_host"], self.config["ssh_port"])
        nonce = secrets.token_urlsafe(24)
        self.candidates = {nonce: (time.monotonic(), key)}
        return nonce, fingerprint(key)

    def trust(self, nonce):
        item = self.candidates.pop(nonce, None)
        if item is None or time.monotonic() - item[0] > 120:
            raise ProtocolError("Identity approval expired. Inspect the identity again.")
        pin_key(self.data / "known_hosts", self.config["wattbox_host"], self.config["ssh_port"], item[1])
        self.audit("ssh_identity_approved")
        self.result = "SSH identity saved. You can now read the outlet labels and status."

    def check(self):
        self.ready()
        if not (self.data / "known_hosts").exists():
            raise ProtocolError("Inspect and approve the SSH identity before connecting with credentials.")
        with self.box() as box:
            inventory = box.inventory()
        self.inventory = inventory
        self.confirmations.clear()
        nonce = None
        self.result = "WattBox responded. Outlet power status does not establish whether the Apple TV is working."
        try:
            target(self.config, inventory)
            if self.config["allow_reboot"]:
                nonce = secrets.token_urlsafe(24)
                self.confirmations[nonce] = (time.monotonic(), inventory)
        except ProtocolError as exc:
            self.result += " " + str(exc)
        self.audit("status_read")
        return nonce

    def reboot(self, nonce):
        self.ready()
        if not self.config["allow_reboot"]:
            raise ProtocolError("Reboot is disabled in Configuration")
        if self.cooldown_error:
            raise ProtocolError("Saved reboot state is invalid. Reboots are blocked pending review.")
        item = self.confirmations.pop(nonce, None)
        if item is None or time.monotonic() - item[0] > 120:
            raise ProtocolError("Confirmation expired or already used. Run a fresh check.")
        if self.active or time.time() - self.last_attempt < 300:
            raise ProtocolError("Reboot cooldown is active. Wait at least five minutes after the previous attempt.")
        expected = target(self.config, item[1])
        with self.box() as box:
            fresh = box.inventory()
            actual = target(self.config, fresh)
            if fresh["model"] != item[1]["model"] or len(fresh["outlets"]) != len(item[1]["outlets"]) or actual != expected:
                raise ProtocolError("Device or outlet changed since confirmation. Run a fresh check.")
            # Persist BEFORE sending; an ambiguous response never triggers a retry.
            self.last_attempt = time.time()
            atomic_json(self.data / "reboot_state.json", {"last_attempt": self.last_attempt})
            self.audit("reboot_attempt", f"outlet {actual['number']}")
            self.result = "Reboot attempted; acknowledgement not yet established. Do not immediately retry."
            box.reset(actual["number"])
        self.result = "WattBox accepted the reboot. Checking outlet power after 15, 30, and 60 seconds."
        self.active = True
        threading.Thread(target=self.verify, daemon=True).start()

    def verify(self):
        for delay, elapsed in ((15, 15), (15, 30), (30, 60)):
            time.sleep(delay)
            try:
                with self.lock:
                    with self.box() as box:
                        inventory = box.inventory()
                    actual = target(self.config, inventory)
                    self.inventory = inventory
                    self.result = (f"After {elapsed} seconds: WattBox reports outlet {actual['number']} on. "
                        "Confirm the Apple TV picture and operation on the TV; device recovery has not been measured.")
                    self.audit("outlet_power_on_observed", f"outlet {actual['number']}; {elapsed}s")
            except Exception:
                with self.lock:
                    self.result = (f"After {elapsed} seconds: could not verify the expected outlet as on. "
                        "No further power commands were sent. Check the device manually.")
                    self.audit("verification_inconclusive", f"{elapsed}s")
        with self.lock:
            self.active = False


CSS = """body{font:16px system-ui;background:#f3f5f7;color:#182635;margin:0;padding:24px}
main{max-width:850px;margin:auto}section{background:white;border:1px solid #dbe1e7;border-radius:12px;padding:20px;margin:18px 0}
h1{margin-bottom:4px}p{line-height:1.55}button{font:inherit;background:#164d77;color:white;padding:12px 18px;border:0;border-radius:7px;cursor:pointer}
.danger{background:#a52e27}form{display:inline-block;margin:6px 8px 6px 0}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:9px;border-bottom:1px solid #ddd}
code{overflow-wrap:anywhere}small{color:#536574}.notice{border-left:4px solid #164d77}label{display:block;margin:12px 0}"""


def page(pilot, confirmation=None, candidate=None, error=None):
    esc = lambda value: html.escape(str(value), quote=True)
    def form(action, label, extra="", danger=False):
        return (f'<form method="post" action="{action}"><input type="hidden" name="csrf" value="{pilot.csrf}">'
            + extra + f'<button class="{"danger" if danger else ""}">{esc(label)}</button></form>')
    text = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    text += f'<title>ADR Service Agent</title><style>{CSS}</style><main><h1>ADR Service Agent</h1><small>ADR diagnostics pilot · 0.8.0</small>'
    text += '<section class="notice"><p>' + esc(error or pilot.result) + '</p></section>'
    text += '<section><h2>Araknis switch connection</h2><p>Configure the Araknis address, SSH port, username and password in the app Configuration tab.</p>'
    text += form('araknis-identity', 'Inspect Araknis SSH identity')
    if pilot.araknis_candidate:
        nonce, key_fingerprint = pilot.araknis_candidate
        text += '<p>First-use SSH identity: <code>' + esc(key_fingerprint) + '</code></p><p>Approve only if this is your switch. A fingerprint shown here alone does not independently verify its identity. Saved keys cannot be silently replaced.</p>'
        text += form('araknis-trust', 'Approve Araknis SSH identity', '<input type="hidden" name="nonce" value="' + esc(nonce) + '">')
    text += form('araknis-check', 'Test Araknis login and read CLI help')
    text += form('araknis-discover', 'Run discovery and prepare report')
    text += form('araknis-diagnostics', 'Read Araknis diagnostics')
    text += form('refresh', 'Refresh Araknis results')
    if pilot.araknis_running:
        text += '<p>' + esc(pilot.araknis_progress) + '. Allow a few minutes, then refresh results.</p>'
    if pilot.araknis_error:
        text += '<p>' + esc(pilot.araknis_error) + '</p>'
    if pilot.araknis_diagnostics:
        text += form('araknis-report', 'Download Araknis report')
        text += '<p>The report includes switch responses and network identifiers. Download it and attach it here; no screen copying is needed.</p>'
        discovery = pilot.araknis_diagnostics.get('discovery')
        if discovery:
            text += '<p>Discovery completed: ' + esc(len(discovery['probes'])) + ' syntax checks and ' + esc(len(pilot.araknis_diagnostics['readings'])) + ' read requests. Report includes all captured syntax help.</p>'
            if discovery['limit_reached']:
                text += '<p>The discovery limit was reached; the report identifies unverified paths.</p>'
        text += '<h3>Araknis diagnostic snapshot</h3><p>Completed: ' + esc(pilot.araknis_diagnostics['checked_at']) + '</p>'
        for item in pilot.araknis_diagnostics['readings']:
            text += '<h3>' + esc(item['name']) + '</h3><p><code>' + esc(item['command']) + '</code> · ' + esc(item['status']) + '</p>'
            if item.get('ports'):
                text += '<div style="overflow-x:auto"><table><tr><th>Port</th><th>Link / protocol</th><th>Speed</th><th>RX errors</th><th>RX discards</th></tr>'
                for port in item['ports']:
                    text += '<tr>'
                    for value in (port['port'], port['link'] + ' / ' + port['protocol'], port['speed'], port['rx_errors'], port['rx_discards']):
                        text += '<td>' + esc(value if value is not None else 'Not reported') + '</td>'
                    text += '</tr>'
                text += '</table></div><p>Showing ' + esc(len(item['ports'])) + ' reported interfaces. Errors and discards are cumulative counters, not current rates or a diagnosis. Link speed is the negotiated connection speed, not a bandwidth test.</p>'
                text += '<details><summary>Raw interface response and remaining counters</summary>'
            text += '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(item['response'] or 'No response captured.') + '</pre>'
            if item.get('ports'):
                text += '</details>'
            if item.get('error'):
                text += '<p>' + esc(item['error']) + '</p>'
            if item['help']:
                text += '<details open><summary>Command syntax help</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(item['help']) + '</pre></details>'
            if item['truncated']:
                text += '<p>Response reached the page or size limit.</p>'
        text += '<p>These are raw switch responses. A response does not establish switch or connected-device health. Syntax errors and failed reads require verification.</p>'

    if pilot.araknis:
        a = pilot.araknis
        text += '<p>SSH authenticated. Snapshot retrieved: ' + esc(a['checked_at']) + '</p>'
        text += '<h3>Login response</h3><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(a['welcome'] or 'No login text returned.') + '</pre>'
        text += '<h3>Show-command help response</h3><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(a['help'] or 'No help text returned. The CLI may require a different help syntax.') + '</pre>'
        if a['truncated']:
            text += '<p>Response reached the page or size limit.</p>'
    text += '<p>This check requests show-command help using show ? and advances up to eight explicit pager pages. The diagnostic button requests system, environment, interface, power and PoE information using fixed show commands. Unsupported syntax is shown with help where available. Responses stay in memory; credentials are not displayed.</p></section>'
    text += '<section><h2>Sonos diagnostics</h2><p>Read the player states reported by your existing Home Assistant Sonos integration.</p>'
    text += form('sonos', 'Check Sonos')
    if pilot.sonos_error:
        text += '<p>' + esc(pilot.sonos_error) + '</p>'
    if pilot.sonos is not None:
        report = pilot.sonos
        names = {p['entity_id']: p['name'] for p in report['players']}
        text += '<p>Snapshot retrieved: ' + esc(report['checked_at']) + '</p>'
        if not report['players']:
            text += '<p>No enabled Sonos media-player entities were discovered. Check the Sonos integration in Devices &amp; services.</p>'
        if report['truncated']:
            text += '<p>Showing the first 32 of ' + esc(report['discovered_count']) + ' discovered players.</p>'
        for p in report['players']:
            mute = 'Yes' if p['muted'] is True else 'No' if p['muted'] is False else 'Not reported'
            volume = str(p['volume']) + '%' if p['volume'] is not None else 'Not reported'
            group = ', '.join(str(names.get(m, m)) for m in p['group_members']) if p['group_members'] else 'Not reported'
            text += '<h3>' + esc(p['name']) + '</h3><table>'
            for label, value in [('Reported state', p['state']), ('Muted', mute), ('Volume', volume),
                ('Source', p['source']), ('Track / program', p['title']), ('Artist', p['artist']),
                ('Group members', group), ('Last HA state update', p['ha_last_updated'])]:
                text += '<tr><th>' + esc(label) + '</th><td>' + esc(value if value is not None else 'Not reported') + '</td></tr>'
            text += '</table><p>' + esc(p['note']) + '</p>'
        text += '<p>These are Home Assistant states, not direct network tests. “Playing” does not prove sound is reaching the speakers. State-update time is not a device heartbeat. No Sonos commands were sent.</p>'
    text += '</section>'
    text += '<section><h2>Ruckus diagnostics</h2><p>Select the current integration to exclude older entries from these readings.</p>'
    extra = ''
    if pilot.ruckus_entries:
        extra = '<label>Ruckus integration <select name="entry_id" required><option value="">Select an entry</option>'
        for e in pilot.ruckus_entries:
            selected = ' selected' if e['entry_id'] == pilot.ruckus_selection else ''
            extra += '<option value="' + esc(e['entry_id']) + '"' + selected + '>' + esc(e['title']) + ' — ' + esc(e['state']) + '</option>'
        extra += '</select></label>'
    text += form('ruckus', 'Check Ruckus', extra)
    if pilot.ruckus_error:
        text += '<p>' + esc(pilot.ruckus_error) + '</p>'
    if pilot.ruckus is not None:
        r = pilot.ruckus
        text += '<p><strong>' + esc(r['entry']['title']) + '</strong> · HA integration state: ' + esc(r['entry']['state']) + '</p>'
        text += '<p>Snapshot retrieved: ' + esc(r['checked_at']) + '</p>'
        if r['entry']['state'] != 'loaded' or r['entry'].get('disabled_by'):
            text += '<p>This entry is not loaded and enabled. Its retained entities are not presented as current readings.</p>'
        else:
            text += '<h3>Integration device inventory</h3><table><tr><th>Name</th><th>Manufacturer</th><th>Model</th></tr>'
            for d in r['devices']:
                text += '<tr>' + ''.join('<td>' + esc(d[k] if d[k] is not None else 'Not reported') + '</td>' for k in ('name','manufacturer','model')) + '</tr>'
            text += '</table><p>Inventory is saved Home Assistant metadata, not a live AP health test.</p>'
            text += '<h3>Reported entity states</h3><table><tr><th>Name</th><th>State</th><th>IP / MAC</th><th>Last HA update</th></tr>'
            for e in r['entities']:
                text += '<tr><td>' + esc(e['name']) + '</td><td>' + esc(e['state']) + '</td><td>' + esc(e['ip'] or e['mac'] or 'Not reported') + '</td><td>' + esc(e['last_updated'] or 'Not reported') + '</td></tr>'
            text += '</table>'
            if r['truncated']:
                text += '<p>Showing the first 64 of ' + esc(r['entity_count']) + ' supported entities.</p>'
            elif not r['entities']:
                text += '<p>No enabled diagnostic entities were found for this entry.</p>'
        text += '<p>Presence states (home/not_home) describe what the integration reports; they do not establish AP health, signal strength, internet performance, or the reason for a disconnection. No Ruckus settings were changed.</p>'
    text += '</section>'
    text += '<section><h2>UniFi diagnostics</h2><p>Read enabled sensor states for a selected UniFi device through Home Assistant.</p>'
    extra = ''
    u = pilot.unifi
    if u and u['entries']:
        extra = '<label>UniFi integration <select name="entry_id" required><option value="">Select an entry</option>'
        for e in u['entries']:
            selected = ' selected' if u['entry'] and e['entry_id'] == u['entry']['entry_id'] else ''
            extra += '<option value="' + esc(e['entry_id']) + '"' + selected + '>' + esc(e['title']) + ' — ' + esc(e['state']) + '</option>'
        extra += '</select></label>'
    if u and u['devices']:
        extra += '<label>Device <select name="device_id" required><option value="">Select the gateway</option>'
        for d in u['devices']:
            selected = ' selected' if u['device'] and d['id'] == u['device']['id'] else ''
            extra += '<option value="' + esc(d['id']) + '"' + selected + '>' + esc(d['name']) + ' · ' + esc(d['model'] or 'Model not reported') + '</option>'
        extra += '</select></label>'
    text += form('unifi', 'Check UniFi', extra)
    if pilot.unifi_error:
        text += '<p>' + esc(pilot.unifi_error) + '</p>'
    if u is not None:
        if not u['entries']:
            text += '<p>No UniFi Network entries were discovered. Configure UniFi Network in Devices &amp; services first.</p>'
        elif not u['entry']:
            text += '<p>Select the UniFi integration to use.</p>'
        else:
            text += '<p>HA integration state: ' + esc(u['entry']['state']) + '</p>'
            if u['entry']['state'] != 'loaded' or u['entry'].get('disabled_by'):
                text += '<p>This entry is not loaded and enabled. Retained sensor readings are not shown as current.</p>'
            elif not u['devices']:
                text += '<p>No devices with supported sensor entities were discovered for this entry.</p>'
            elif not u['device']:
                text += '<p>Select Cloud Gateway Fiber above, then check again.</p>'
            else:
                text += '<h3>' + esc(u['device']['name']) + '</h3><p>Snapshot retrieved: ' + esc(u['checked_at']) + '</p>'
                text += '<table><tr><th>Reading</th><th>Reported value</th><th>Last HA update</th></tr>'
                for s in u['sensors']:
                    value = str(s['state'])
                    if s['unit'] is not None and s['state'] not in ('unknown', 'unavailable', 'read failed'):
                        value += ' ' + str(s['unit'])
                    text += '<tr><td>' + esc(s['name']) + '</td><td>' + esc(value) + '</td><td>' + esc(s['last_updated'] or 'Not reported') + '</td></tr>'
                text += '</table>'
                if not u['sensors']:
                    text += '<p>No enabled sensor readings are available for this device.</p>'
                if u['truncated']:
                    text += '<p>Showing the first 64 of ' + esc(u['sensor_count']) + ' enabled sensor entities.</p>'
                if u['disabled_sensors']:
                    text += '<details><summary>Disabled sensors (' + esc(len(u['disabled_sensors'])) + ')</summary><p>' + esc(', '.join(u['disabled_sensors'])) + '</p><p>Enable only the needed sensors in Home Assistant; this app does not change entity settings.</p></details>'
        text += '<p>Values are reported by the Home Assistant UniFi integration, not fresh tests run by this app. WAN latency is not internet download speed. Last-update time is not a heartbeat. Araknis and Ruckus switches need their own connections for internal switch diagnostics.</p>'
    text += '</section>'
    if pilot.config is None:
        return text + '<section><p>' + esc(pilot.config_error) + '</p></section></main></html>'
    c = pilot.config
    text += f'<section><h2>{esc(c["device_alias"])}</h2><p>WattBox: <code>{esc(c["wattbox_host"])}:{c["ssh_port"]}</code><br>'
    text += f'Test outlet: <strong>{c["test_outlet"]}</strong> · Expected label: <strong>{esc(c["expected_outlet_label"])}</strong></p>'
    text += form('identity', 'Inspect SSH identity') + form('check', 'Read outlet labels and status')
    text += form('refresh', 'Refresh results') + '</section>'
    if candidate:
        nonce, fp = candidate
        text += '<section><h2>Approve this WattBox identity</h2><p>Verify the address above and compare this SSH fingerprint with a trusted local connection before approving. No password has been sent.</p>'
        text += f'<p><code>{esc(fp)}</code></p>'
        text += form('trust', 'Approve this identity', f'<input type="hidden" name="nonce" value="{esc(nonce)}">') + '</section>'
    if pilot.inventory:
        text += '<section><h2>Latest observed status</h2><p>' + esc(pilot.inventory['model']) + ' · Firmware ' + esc(pilot.inventory['firmware']) + '</p>'
        text += '<table><tr><th>Outlet</th><th>WattBox label</th><th>Power</th></tr>'
        for o in pilot.inventory['outlets']:
            text += f'<tr><td>{o["number"]}</td><td>{esc(o["label"])}</td><td>{"On" if o["on"] else "Off"}</td></tr>'
        text += '</table><p>These are WattBox readings, not an Apple TV functional test.</p></section>'
    if confirmation and not pilot.active:
        text += '<section><h2>Test reboot</h2><p>Confirm that this outlet powers only the named test device.</p>'
        extra = f'<input type="hidden" name="nonce" value="{esc(confirmation)}"><label><input type="checkbox" name="confirm" value="yes" required> I confirm the device and outlet mapping.</label>'
        text += form('reboot', f'Reboot outlet {c["test_outlet"]} only', extra, True) + '</section>'
    text += '<p><small>On-demand local pilot. Phone voice access is not connected in this version.</small></p></main></html>'
    return text


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_page(self, status=200, **kwargs):
        body = page(self.server.pilot, **kwargs).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_araknis_report(self):
        pilot = self.server.pilot
        if pilot.araknis_running or not pilot.araknis_diagnostics:
            raise ProtocolError('Complete a diagnostic or discovery run before downloading its report.')
        payload = araknis_report_payload(pilot.araknis_diagnostics,
            pilot.araknis_options.get('araknis_password', ''))
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Disposition', 'attachment; filename="ADR-Araknis-Discovery.json"')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        # Do not trust spoofable forwarded headers; enforce the actual peer.
        if self.client_address[0] != '172.30.32.2':
            self.send_error(403, 'Home Assistant ingress required')
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if urlsplit(self.path).path not in ('', '/'):
            self.send_error(404)
            return
        with self.server.pilot.lock:
            self.send_page()

    def do_POST(self):
        if not self.authorized():
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_error(400)
            return
        if not 0 < length <= 4096 or self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            self.send_error(400)
            return
        try:
            params = parse_qs(self.rfile.read(length).decode('utf-8'), max_num_fields=8)
        except (UnicodeDecodeError, ValueError):
            self.send_error(400)
            return
        csrf = params.get('csrf', [''])[0]
        pilot = self.server.pilot
        if not secrets.compare_digest(csrf, pilot.csrf):
            self.send_error(403)
            return
        action = urlsplit(self.path).path.strip('/')
        with pilot.lock:
            try:
                if action == 'identity':
                    self.send_page(candidate=pilot.key_candidate())
                elif action == 'trust':
                    pilot.trust(params.get('nonce', [''])[0])
                    self.send_page()
                elif action == 'check':
                    self.send_page(confirmation=pilot.check())
                elif action == 'araknis-identity':
                    pilot.araknis_identity()
                    self.send_page()
                elif action == 'araknis-trust':
                    pilot.araknis_trust(params.get('nonce', [''])[0])
                    self.send_page()
                elif action == 'araknis-discover':
                    pilot.start_araknis_diagnostics(discovery=True)
                    self.send_page()
                elif action == 'araknis-report':
                    self.send_araknis_report()
                elif action == 'araknis-diagnostics':
                    pilot.start_araknis_diagnostics()
                    self.send_page()
                elif action == 'araknis-check':
                    pilot.check_araknis()
                    self.send_page()
                elif action == 'sonos':
                    pilot.check_sonos()
                    self.send_page()
                elif action == 'ruckus':
                    pilot.check_ruckus(params.get('entry_id', [''])[0])
                    self.send_page()
                elif action == 'unifi':
                    pilot.check_unifi(params.get('entry_id', [''])[0], params.get('device_id', [''])[0])
                    self.send_page()
                elif action == 'reboot':
                    if params.get('confirm') != ['yes']:
                        raise ProtocolError('Confirm the outlet mapping before rebooting')
                    pilot.reboot(params.get('nonce', [''])[0])
                    self.send_page()
                elif action == 'refresh':
                    self.send_page()
                else:
                    self.send_error(404)
            except ProtocolError as exc:
                self.send_page(400, error=str(exc))
            except Exception:
                # Paramiko and OS exceptions may include sensitive remote strings.
                if action.startswith('araknis-'):
                    self.send_page(502, error='Araknis connection failed. Check the address, SSH port, credentials and saved SSH identity.')
                else:
                    self.send_page(502, error='Connection or command failed. Check the address, credentials, and saved SSH identity. If a reboot was attempted, its outcome may be unknown; no automatic retry was made.')


def main():
    server = ThreadingHTTPServer(('0.0.0.0', 8099), Handler)
    server.pilot = Pilot('/data', '/data/options.json')
    print('ADR Service Agent 0.8.0 ready for Home Assistant ingress. No startup device actions.')
    server.serve_forever()


if __name__ == '__main__':
    main()
