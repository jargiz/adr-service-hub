"""Ingress-only ADR pilot. No HA config mounts or Supervisor API access."""
import html
import hashlib
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from service_report import run_checks, SkipCheck
from wattbox import WattBox, ProtocolError, fingerprint, inspect_key, pin_key
from sonos import collect as collect_sonos, SonosError
from ruckus import collect as collect_ruckus, entries as ruckus_entries, token_value, RuckusError
from unifi import collect as collect_unifi, UniFiError
from crestron import collect as collect_crestron, report_payload as crestron_report_payload, CrestronError
from bluesound import collect as collect_bluesound, report_payload as bluesound_report_payload, BluesoundError
from control4 import collect as collect_control4, report_payload as control4_report_payload, Control4Error
from cp4 import collect as collect_cp4, settings as cp4_settings, report_payload as cp4_report_payload, CP4Error
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
        self.cp4_options = dict(self.araknis_options)
        self.cp4 = None
        self.cp4_error = None
        self.cp4_running = False
        self.cp4_candidate = None
        self.cp4_candidates = {}
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
        self.crestron = None
        self.crestron_error = None
        self.crestron_running = False
        self.crestron_selection = ''
        try:
            self.crestron_selection = json.loads((self.data / 'crestron_selection.json').read_text()).get('entry_id', '')
        except (OSError, ValueError, AttributeError):
            pass
        self.bluesound = None
        self.bluesound_error = None
        self.bluesound_running = False
        self.control4 = None
        self.control4_error = None
        self.control4_running = False
        self.control4_selection = ''
        try:
            self.control4_selection = json.loads((self.data / 'control4_selection.json').read_text()).get('entry_id', '')
        except (OSError, ValueError, AttributeError):
            pass
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
        self.service_report = None
        self.service_running = False
        self.service_progress = ''
        self.service_baselines = {}
        self.service_error = None
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

    def service_jobs(self):
        def selected(read, selection):
            if not selection:
                raise SkipCheck('Select this integration using its individual check first.')
            return read(selection)

        def console(config_fn, options, keyfile, read):
            if not (self.data / keyfile).exists():
                raise SkipCheck('Configure this system and approve its SSH identity using its individual check first.')
            return read(config_fn(options), self.data / keyfile)

        def wattbox():
            if self.config is None or not (self.data / 'known_hosts').exists():
                raise SkipCheck('Configure WattBox and approve its SSH identity using its individual check first.')
            # Inventory only. Never call check(), create a confirmation, or reboot.
            with self.box() as box:
                return box.inventory()

        def target_id(prefix, keyfile):
            pin = (self.data / keyfile).read_text() if (self.data / keyfile).exists() else ''
            identity = [self.araknis_options.get(prefix + '_host', ''),
                self.araknis_options.get(prefix + '_ssh_port', 22), pin]
            return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

        return [
            ('WattBox', 'inventory', wattbox),
            ('Sonos', 'ha-sonos', collect_sonos),
            ('Bluesound', 'ha-bluesound', collect_bluesound),
            ('Ruckus', self.ruckus_selection, lambda: selected(collect_ruckus, self.ruckus_selection)),
            ('UniFi', json.dumps(self.unifi_selection, sort_keys=True),
                lambda: collect_unifi(self.unifi_selection.get('entry_id', ''), self.unifi_selection.get('device_id', ''))),
            ('Crestron', self.crestron_selection, lambda: collect_crestron(self.crestron_selection)),
            ('Control4', self.control4_selection, lambda: collect_control4(self.control4_selection)),
            ('Araknis', target_id('araknis', 'araknis_known_hosts'),
                lambda: console(araknis_settings, self.araknis_options, 'araknis_known_hosts', discover_araknis)),
            ('CP4-R', target_id('cp4', 'cp4_known_hosts'),
                lambda: console(cp4_settings, self.cp4_options, 'cp4_known_hosts', collect_cp4)),
        ]

    def start_service_checks(self):
        if self.service_running:
            return
        if any((self.araknis_running, self.cp4_running, self.crestron_running,
                self.control4_running, self.bluesound_running, self.active)):
            raise ProtocolError('Wait for the current check or power action to finish before running all checks.')
        jobs = self.service_jobs()
        self.service_report = None
        self.service_error = None
        self.service_progress = 'Starting'
        self.service_running = True
        def progress(name):
            with self.lock:
                self.service_progress = 'Checking ' + name
        def run():
            try:
                report, baselines = run_checks(jobs, self.service_baselines, progress,
                    tuple(self.araknis_options.get(k, '') for k in
                        ('password', 'araknis_password', 'cp4_password')))
                with self.lock:
                    self.service_report = report
                    self.service_baselines = baselines
                    self.audit('service_report_read', str(len(report['checks'])) + ' checks')
            except Exception:
                with self.lock:
                    self.service_error = 'Combined report could not finish. Run again on demand; no automatic retry was made.'
            finally:
                with self.lock:
                    self.service_running = False
                    self.service_progress = ''
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self.service_running = False
            raise

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

    def cp4_identity(self):
        config = cp4_settings(self.cp4_options)
        self.cp4_candidate = None
        key = inspect_key(config['host'], config['port'])
        nonce = secrets.token_urlsafe(24)
        self.cp4_candidates = {nonce: (time.monotonic(), key, config['host'], config['port'])}
        self.cp4_candidate = (nonce, fingerprint(key))

    def cp4_trust(self, nonce):
        item = self.cp4_candidates.pop(nonce, None)
        if item is None or time.monotonic() - item[0] > 120:
            raise ProtocolError('CP4-R identity approval expired. Inspect again.')
        config = cp4_settings(self.cp4_options)
        if (config['host'], config['port']) != (item[2], item[3]):
            raise ProtocolError('CP4-R target changed. Inspect again.')
        pin_key(self.data / 'cp4_known_hosts', item[2], item[3], item[1])
        self.cp4_candidate = None
        self.audit('cp4_identity_approved')

    def start_cp4_diagnostics(self):
        if self.cp4_running:
            return
        config = cp4_settings(self.cp4_options)
        if not (self.data / 'cp4_known_hosts').exists():
            raise ProtocolError('Inspect and approve the CP4-R SSH identity first.')
        self.cp4 = None
        self.cp4_error = None
        self.cp4_running = True
        def run():
            result, error = None, None
            try:
                result = collect_cp4(config, self.data / 'cp4_known_hosts')
            except CP4Error as exc:
                error = str(exc)
            except Exception:
                error = 'CP4-R diagnostics failed. No automatic retry was made.'
            with self.lock:
                self.cp4 = result
                self.cp4_error = error
                self.cp4_running = False
                if result:
                    self.audit('cp4_diagnostics_read', str(len(result['readings'])) + ' response(s)')
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self.cp4_running = False
            raise

    def start_crestron_discovery(self, entry_id=''):
        if self.crestron_running:
            return
        selected = entry_id or self.crestron_selection
        self.crestron = None
        self.crestron_error = None
        self.crestron_running = True
        def run():
            result, error = None, None
            try:
                result = collect_crestron(selected)
                if result['entry']:
                    atomic_json(self.data / 'crestron_selection.json', {'entry_id': result['entry']['entry_id']})
            except CrestronError as exc:
                error = str(exc)
            except Exception:
                error = 'Crestron discovery failed. No device actions or configuration changes were requested.'
            with self.lock:
                self.crestron = result
                self.crestron_error = error
                self.crestron_running = False
                if result:
                    if result['entry']:
                        self.crestron_selection = result['entry']['entry_id']
                    self.audit('crestron_status_read', str(len(result['readings'])) + ' reading(s)')
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self.crestron_running = False
            raise

    def start_control4_discovery(self, entry_id=''):
        if self.control4_running:
            return
        selected = entry_id or self.control4_selection
        self.control4 = None
        self.control4_error = None
        self.control4_running = True
        def run():
            result, error = None, None
            try:
                result = collect_control4(selected)
                if result['entry']:
                    atomic_json(self.data / 'control4_selection.json', {'entry_id': result['entry']['entry_id']})
            except Control4Error as exc:
                error = str(exc)
            except Exception:
                error = 'Control4 discovery failed. No device actions or configuration changes were requested.'
            with self.lock:
                self.control4 = result
                self.control4_error = error
                self.control4_running = False
                if result:
                    if result['entry']:
                        self.control4_selection = result['entry']['entry_id']
                    self.audit('control4_status_read', str(len(result['readings'])) + ' reading(s)')
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self.control4_running = False
            raise

    def start_bluesound_discovery(self):
        if self.bluesound_running:
            return
        self.bluesound = None
        self.bluesound_error = None
        self.bluesound_running = True
        def run():
            result, error = None, None
            try:
                result = collect_bluesound()
            except BluesoundError as exc:
                error = str(exc)
            except Exception:
                error = 'Bluesound discovery failed. No device actions or configuration changes were requested.'
            with self.lock:
                self.bluesound = result
                self.bluesound_error = error
                self.bluesound_running = False
                if result:
                    self.audit('bluesound_status_read', str(len(result['readings'])) + ' reading(s)')
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self.bluesound_running = False
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
    text += f'<title>ADR Service Agent</title><style>{CSS}</style><main><h1>ADR Service Agent</h1><small>ADR diagnostics pilot · 0.13.0</small>'
    text += '<section class="notice"><p>' + esc(error or pilot.result) + '</p></section>'
    text += '<section><h2>Combined service report</h2><p>Run the existing read-only checks once. No outlet reboots or device configuration changes are included. Allow several minutes, then refresh.</p>'
    text += form('service-check', 'Run All Checks') + form('refresh', 'Refresh service report')
    if pilot.service_running:
        text += '<p>' + esc(pilot.service_progress) + '</p>'
    if pilot.service_error:
        text += '<p>' + esc(pilot.service_error) + '</p>'
    if pilot.service_report:
        report = pilot.service_report
        text += form('service-report', 'Download combined report')
        text += '<p>Completed: ' + esc(report['completed_at']) + '. Verified means the read succeeded, not that every function is healthy.</p>'
        text += '<p>' + esc(report['counts']['verified']) + ' verified reads · ' + esc(report['counts']['review']) + ' to review · ' + esc(report['counts']['unverified']) + ' unverified.</p>'
        text += '<table><tr><th>System</th><th>Result</th><th>Findings and comparisons</th></tr>'
        for check in report['checks']:
            text += '<tr><td>' + esc(check['system']) + '</td><td>' + esc(check['status']) + '</td><td>'
            for finding in check['findings'] + check['comparisons']:
                text += '<p>' + esc(finding) + '</p>'
            text += '</td></tr>'
        text += '</table><p>Comparisons use the same target during this app session. Restarting the app clears baselines. Individual check results below are separate snapshots.</p>'
    text += '</section>'
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
    text += '<section><h2>CP4-R processor diagnostics</h2><p>Configure cp4_host, cp4_ssh_port, cp4_username and cp4_password in app Configuration. Use the processor SSH/Toolbox account.</p>'
    text += form('cp4-identity', 'Inspect CP4-R SSH identity')
    if pilot.cp4_candidate:
        nonce, key_fingerprint = pilot.cp4_candidate
        text += '<p>First-use identity: <code>' + esc(key_fingerprint) + '</code>. Verify the target and compare independently where available; this displayed fingerprint alone does not independently prove identity.</p>'
        text += form('cp4-trust', 'Approve CP4-R SSH identity', '<input type="hidden" name="nonce" value="' + esc(nonce) + '">')
    text += form('cp4-check', 'Read CP4-R diagnostics')
    text += form('refresh', 'Refresh CP4-R results')
    if pilot.cp4_running:
        text += '<p>Reading processor diagnostics. Allow a couple of minutes, then refresh results.</p>'
    if pilot.cp4_error:
        text += '<p>' + esc(pilot.cp4_error) + '</p>'
    if pilot.cp4:
        text += form('cp4-report', 'Download CP4-R report')
        text += '<p>Completed: ' + esc(pilot.cp4['checked_at']) + ' · SSH authenticated · CP4-R model ' + ('identified' if pilot.cp4['model_verified'] else 'unverified') + '</p>'
        version_data = pilot.cp4.get('versions', {})
        if version_data:
            text += '<table><tr><th>Version reading</th><th>Reported value</th></tr>'
            for key, label in [('hardware_version', 'Hardware version'), ('control_engine_version', 'Control-engine firmware'), ('home_setup_program_version', 'Home setup-program version')]:
                text += '<tr><td>' + esc(label) + '</td><td>' + esc(version_data.get(key) or 'Not reported') + '</td></tr>'
            text += '</table>'
        for item in pilot.cp4['readings']:
            text += '<details><summary>' + esc(item['name']) + ' · ' + esc(item['status']) + '</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(item['response'] or 'No response captured.') + '</pre></details>'
        for note in pilot.cp4['not_attempted']:
            text += '<p>' + esc(note) + '</p>'
    text += '<p>Reads processor version and supported diagnostic commands. IP-table and main Cresnet results cover those device lists, not the full Home device-health inventory. Unsupported metrics remain unverified. No restart or configuration commands are implemented.</p></section>'
    text += '<section><h2>Crestron discovery</h2><p>Inspect your existing Crestron integration in Home Assistant. No additional processor credentials are needed.</p>'
    extra = ''
    c_report = pilot.crestron
    if c_report and c_report['entries']:
        extra = '<label>Crestron integration <select name="entry_id" required><option value="">Select an integration</option>'
        for entry in c_report['entries']:
            selected = ' selected' if c_report['entry'] and entry['entry_id'] == c_report['entry']['entry_id'] else ''
            extra += '<option value="' + esc(entry['entry_id']) + '"' + selected + '>' + esc(entry['title']) + ' · ' + esc(entry['domain']) + ' · ' + esc(entry['state']) + '</option>'
        extra += '</select></label>'
    text += form('crestron-discover', 'Discover Crestron readings', extra)
    text += form('refresh', 'Refresh Crestron results')
    if pilot.crestron_running:
        text += '<p>Reading Crestron through Home Assistant. Allow up to a couple of minutes, then refresh results.</p>'
    if pilot.crestron_error:
        text += '<p>' + esc(pilot.crestron_error) + '</p>'
    if c_report:
        text += form('crestron-report', 'Download Crestron report')
        text += '<p>Snapshot retrieved: ' + esc(c_report['checked_at']) + '</p>'
        if not c_report['entries']:
            text += '<p>No configured Crestron integration entries were found. This does not establish whether the processor is reachable. The report records what discovery found.</p>'
        elif not c_report['entry']:
            text += '<p>Select the integration above and run discovery again.</p>'
        elif c_report['entry']['state'] != 'loaded' or c_report['entry'].get('disabled_by'):
            text += '<p>Selected integration is not loaded and enabled. Retained entity states are not presented as current readings.</p>'
        else:
            text += '<p>' + esc(len(c_report['devices'])) + ' registered devices · ' + esc(c_report['entity_count']) + ' entities · ' + esc(c_report['disabled_count']) + ' disabled · ' + esc(len(c_report['readings'])) + ' readings.</p>'
            if c_report['truncated']:
                text += '<p>Reading the first 128 enabled supported entities, prioritizing diagnostic sensors. The report includes inventory and the total count.</p>'
            if c_report['inventory_truncated']:
                text += '<p>Device/entity inventory exceeded its limit; the report is partial.</p>'
            text += '<details><summary>Registered devices</summary><table><tr><th>Device</th><th>Model</th><th>Registry software version</th></tr>'
            for device in c_report['devices']:
                text += '<tr><td>' + esc(device['name']) + '</td><td>' + esc(device['model'] or 'Not reported') + '</td><td>' + esc(device['registry_sw_version'] or 'Not reported') + '</td></tr>'
            text += '</table></details><table><tr><th>Reading</th><th>HA reported state</th><th>Last HA update</th></tr>'
            for reading in c_report['readings']:
                value = str(reading['state'])
                unit = reading['attributes'].get('unit_of_measurement')
                if unit and reading['state'] not in ('unknown', 'unavailable', 'read failed'):
                    value += ' ' + str(unit)
                text += '<tr><td>' + esc(reading['name']) + '</td><td>' + esc(value) + '</td><td>' + esc(reading['last_updated'] or 'Not reported') + '</td></tr>'
            text += '</table>'
            if not c_report['readings']:
                text += '<p>No enabled supported readings were exposed by this integration. Device inventory remains available in the report.</p>'
        text += '<p>HA states are snapshots, not physical functional tests. An unavailable entity does not by itself establish that the processor is offline. Last-update time is not a heartbeat. The report includes exposed state attributes; absent health fields remain unverified.</p>'
    text += '</section>'
    text += '<section><h2>Control4 discovery</h2><p>Inspect your existing Control4 integration in Home Assistant. No additional processor credentials are needed.</p>'
    extra = ''
    c_report = pilot.control4
    if c_report and c_report['entries']:
        extra = '<label>Control4 integration <select name="entry_id" required><option value="">Select an integration</option>'
        for entry in c_report['entries']:
            selected = ' selected' if c_report['entry'] and entry['entry_id'] == c_report['entry']['entry_id'] else ''
            extra += '<option value="' + esc(entry['entry_id']) + '"' + selected + '>' + esc(entry['title']) + ' · ' + esc(entry['domain']) + ' · ' + esc(entry['state']) + '</option>'
        extra += '</select></label>'
    text += form('control4-discover', 'Discover Control4 readings', extra)
    text += form('refresh', 'Refresh Control4 results')
    if pilot.control4_running:
        text += '<p>Reading Control4 through Home Assistant. Allow up to a couple of minutes, then refresh results.</p>'
    if pilot.control4_error:
        text += '<p>' + esc(pilot.control4_error) + '</p>'
    if c_report:
        text += form('control4-report', 'Download Control4 report')
        text += '<p>Snapshot retrieved: ' + esc(c_report['checked_at']) + '</p>'
        if not c_report['entries']:
            text += '<p>No configured Control4 integration entries were found. This does not establish whether the processor is reachable. The report records what discovery found.</p>'
        elif not c_report['entry']:
            text += '<p>Select the integration above and run discovery again.</p>'
        elif c_report['entry']['state'] != 'loaded' or c_report['entry'].get('disabled_by'):
            text += '<p>Selected integration is not loaded and enabled. Retained entity states are not presented as current readings.</p>'
        else:
            text += '<p>' + esc(len(c_report['devices'])) + ' registered devices · ' + esc(c_report['entity_count']) + ' entities · ' + esc(c_report['disabled_count']) + ' disabled · ' + esc(len(c_report['readings'])) + ' readings.</p>'
            if c_report['truncated']:
                text += '<p>Reading the first 128 enabled supported entities, prioritizing diagnostic sensors. The report includes inventory and the total count.</p>'
            if c_report['inventory_truncated']:
                text += '<p>Device/entity inventory exceeded its limit; the report is partial.</p>'
            text += '<details><summary>Registered devices</summary><table><tr><th>Device</th><th>Model</th><th>Registry software version</th></tr>'
            for device in c_report['devices']:
                text += '<tr><td>' + esc(device['name']) + '</td><td>' + esc(device['model'] or 'Not reported') + '</td><td>' + esc(device['registry_sw_version'] or 'Not reported') + '</td></tr>'
            text += '</table></details><table><tr><th>Reading</th><th>HA reported state</th><th>Last HA update</th></tr>'
            for reading in c_report['readings']:
                value = str(reading['state'])
                unit = reading['attributes'].get('unit_of_measurement')
                if unit and reading['state'] not in ('unknown', 'unavailable', 'read failed'):
                    value += ' ' + str(unit)
                text += '<tr><td>' + esc(reading['name']) + '</td><td>' + esc(value) + '</td><td>' + esc(reading['last_updated'] or 'Not reported') + '</td></tr>'
            text += '</table>'
            if not c_report['readings']:
                text += '<p>No enabled supported readings were exposed by this integration. Device inventory remains available in the report.</p>'
        text += '<p>HA states are snapshots, not physical functional tests. An unavailable entity does not by itself establish that the processor is offline. Last-update time is not a heartbeat. The report includes exposed state attributes; absent health fields remain unverified.</p>'
    text += '</section>'
    text += '<section><h2>Bluesound discovery</h2><p>Inspect your existing Bluesound integration in Home Assistant. All configured players are included. No additional player credentials are needed.</p>'
    extra = ''
    c_report = pilot.bluesound
    text += form('bluesound-discover', 'Discover Bluesound readings', extra)
    text += form('refresh', 'Refresh Bluesound results')
    if pilot.bluesound_running:
        text += '<p>Reading Bluesound through Home Assistant. Allow up to a couple of minutes, then refresh results.</p>'
    if pilot.bluesound_error:
        text += '<p>' + esc(pilot.bluesound_error) + '</p>'
    if c_report:
        text += form('bluesound-report', 'Download Bluesound report')
        text += '<p>Snapshot retrieved: ' + esc(c_report['checked_at']) + '</p>'
        if not c_report['entries']:
            text += '<p>No configured Bluesound integration entries were found. This does not establish whether the player is reachable. The report records what discovery found.</p>'
        else:
            for entry in c_report['entries']:
                if entry.get('disabled_by') or entry.get('state') != 'loaded':
                    text += '<p>' + esc(entry['title']) + ': integration not loaded and enabled; readings unverified.</p>'
            text += '<p>' + esc(len(c_report['devices'])) + ' registered devices · ' + esc(c_report['entity_count']) + ' entities · ' + esc(c_report['disabled_count']) + ' disabled · ' + esc(len(c_report['readings'])) + ' readings.</p>'
            if c_report['truncated']:
                text += '<p>Discovery was limited to 32 integrations or 128 readings, prioritizing diagnostic sensors. See the report for total counts.</p>'
            if c_report['inventory_truncated']:
                text += '<p>Device/entity inventory exceeded its limit; the report is partial.</p>'
            text += '<details><summary>Registered devices</summary><table><tr><th>Device</th><th>Model</th><th>Registry software version</th></tr>'
            for device in c_report['devices']:
                text += '<tr><td>' + esc(device['name']) + '</td><td>' + esc(device['model'] or 'Not reported') + '</td><td>' + esc(device['registry_sw_version'] or 'Not reported') + '</td></tr>'
            text += '</table></details><table><tr><th>Reading</th><th>HA reported state</th><th>Last HA update</th></tr>'
            for reading in c_report['readings']:
                value = str(reading['state'])
                unit = reading['attributes'].get('unit_of_measurement')
                if unit and reading['state'] not in ('unknown', 'unavailable', 'read failed'):
                    value += ' ' + str(unit)
                text += '<tr><td>' + esc(reading['name']) + '</td><td>' + esc(value) + '</td><td>' + esc(reading['last_updated'] or 'Not reported') + '</td></tr>'
            text += '</table>'
            if not c_report['readings']:
                text += '<p>No enabled supported readings were exposed by this integration. Device inventory remains available in the report.</p>'
        text += '<p>HA states are snapshots, not physical functional tests. An unavailable entity does not by itself establish that the player is offline. Last-update time is not a heartbeat. The report includes exposed state attributes; absent health fields remain unverified.</p>'
    text += '</section>'
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

    def send_service_report(self):
        pilot = self.server.pilot
        if pilot.service_running or not pilot.service_report:
            raise ProtocolError('Complete Run All Checks before downloading its report.')
        body = json.dumps(pilot.service_report, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Disposition', 'attachment; filename="ADR-Service-Report.json"')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
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

    def send_crestron_report(self):
        pilot = self.server.pilot
        if pilot.crestron_running or not pilot.crestron:
            raise ProtocolError('Complete Crestron discovery before downloading its report.')
        body = json.dumps(crestron_report_payload(pilot.crestron), indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Disposition', 'attachment; filename="ADR-Crestron-Discovery.json"')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def send_control4_report(self):
        pilot = self.server.pilot
        if pilot.control4_running or not pilot.control4:
            raise ProtocolError('Complete Control4 discovery before downloading its report.')
        body = json.dumps(control4_report_payload(pilot.control4), indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Disposition', 'attachment; filename="ADR-Control4-Discovery.json"')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def send_bluesound_report(self):
        pilot = self.server.pilot
        if pilot.bluesound_running or not pilot.bluesound:
            raise ProtocolError('Complete Bluesound discovery before downloading its report.')
        body = json.dumps(bluesound_report_payload(pilot.bluesound), indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Disposition', 'attachment; filename="ADR-Bluesound-Discovery.json"')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def send_cp4_report(self):
        pilot = self.server.pilot
        if pilot.cp4_running or not pilot.cp4:
            raise ProtocolError('Complete a CP4-R check before downloading its report.')
        body = json.dumps(cp4_report_payload(pilot.cp4), indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Disposition', 'attachment; filename="ADR-CP4-Diagnostics.json"')
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
                if getattr(pilot, 'service_running', False) and action not in ('refresh', 'service-check', 'service-report'):
                    raise ProtocolError('Combined checks are running. Refresh results or wait for completion before another action.')
                if action == 'service-check':
                    pilot.start_service_checks()
                    self.send_page()
                elif action == 'service-report':
                    self.send_service_report()
                elif action == 'identity':
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
                elif action == 'cp4-identity':
                    pilot.cp4_identity()
                    self.send_page()
                elif action == 'cp4-trust':
                    pilot.cp4_trust(params.get('nonce', [''])[0])
                    self.send_page()
                elif action == 'cp4-check':
                    pilot.start_cp4_diagnostics()
                    self.send_page()
                elif action == 'cp4-report':
                    self.send_cp4_report()
                elif action == 'bluesound-discover':
                    pilot.start_bluesound_discovery()
                    self.send_page()
                elif action == 'bluesound-report':
                    self.send_bluesound_report()
                elif action == 'control4-discover':
                    pilot.start_control4_discovery(params.get('entry_id', [''])[0])
                    self.send_page()
                elif action == 'control4-report':
                    self.send_control4_report()
                elif action == 'crestron-discover':
                    pilot.start_crestron_discovery(params.get('entry_id', [''])[0])
                    self.send_page()
                elif action == 'crestron-report':
                    self.send_crestron_report()
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
                if action.startswith('cp4-'):
                    self.send_page(502, error='CP4-R connection failed. Check its SSH settings and approved identity.')
                elif action.startswith('araknis-'):
                    self.send_page(502, error='Araknis connection failed. Check the address, SSH port, credentials and saved SSH identity.')
                else:
                    self.send_page(502, error='Connection or command failed. Check the address, credentials, and saved SSH identity. If a reboot was attempted, its outcome may be unknown; no automatic retry was made.')


def main():
    server = ThreadingHTTPServer(('0.0.0.0', 8099), Handler)
    server.pilot = Pilot('/data', '/data/options.json')
    print('ADR Service Agent 0.13.0 ready for Home Assistant ingress. No startup device actions.')
    server.serve_forever()


if __name__ == '__main__':
    main()
