"""On-demand read-only orchestration and evidence comparisons. No device actions."""
import copy
import re
from datetime import datetime, timezone


class SkipCheck(Exception):
    """A configured selection or previously approved identity is required."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()
                if k.lower() not in ('password', 'access_token', 'token', 'options', 'data')}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[redacted]')
    return value


def assess(name, snapshot):
    """Separate observed availability failures from limits of the data source."""
    result = {'service_findings': [], 'data_limitations': [], 'observations': []}
    service, limits, notes = (result[k] for k in ('service_findings', 'data_limitations', 'observations'))
    usable = True
    entry = snapshot.get('entry')
    if name in ('Crestron', 'Control4', 'UniFi', 'Ruckus'):
        if not entry:
            usable = False
            limits.append('No integration selected or discovered. Run its individual check to select it.')
        elif entry.get('state') != 'loaded' or entry.get('disabled_by'):
            usable = False
            service.append('Selected HA integration is not loaded and enabled; current device operation is unverified.')
        else:
            notes.append('Selected HA integration is loaded; states are snapshots, not physical tests.')
        if name == 'UniFi' and entry and not snapshot.get('device'):
            usable = False
            limits.append('Select a UniFi device using its individual check.')
    if name in ('Bluesound', 'Sense'):
        entries = snapshot.get('entries', [])
        if not entries:
            usable = False
            limits.append('No configured ' + name + ' integrations found. Add it in Home Assistant Devices & services.')
        else:
            notes.append(str(len(entries)) + ' configured ' + name + ' integration entries inspected.')
            for item in entries:
                if item.get('disabled_by') or item.get('state') != 'loaded':
                    service.append(str(item.get('title', name + ' entry')) + ': integration not loaded and enabled; device operation unverified.')
    readings = snapshot.get('readings', snapshot.get('sensors', snapshot.get('entities', snapshot.get('players', []))))
    if name == 'WattBox':
        usable = isinstance(snapshot.get('outlets'), list)
        notes.append('Outlet inventory received. Power state does not verify connected equipment operation.')
        off = [str(o.get('number')) + ' ' + str(o.get('label', '')) for o in snapshot.get('outlets', []) if o.get('on') is False]
        if off:
            notes.append('Reported off outlets: ' + '; '.join(off) + '. Expected power states are not configured.')
    elif name in ('Araknis', 'CP4-R'):
        if not readings:
            usable = False
            limits.append('No diagnostic responses received.')
        if name == 'CP4-R' and not snapshot.get('model_verified'):
            usable = False
            limits.append('CP4-R model was not verified; further processor checks are incomplete.')
        notes.append('Read-only console responses received; absent diagnostics remain unverified.')
        for item in readings:
            title = str(item.get('name', 'Diagnostic'))
            if item.get('error') or item.get('status') == 'read failed':
                service.append(title + ': diagnostic read failed; device operation is unverified.')
            if item.get('truncated') or item.get('status') in ('unsupported or denied', 'partial response'):
                limits.append(title + ': partial or unsupported response.')
            if item.get('command') == 'SYSTEMREADY' and re.search(r'SystemReady:\s*False', item.get('response', ''), re.I):
                service.append('Processor reports SystemReady: False.')
        limits.extend(str(item) for item in snapshot.get('not_attempted', []))
        if name == 'CP4-R':
            limits.append('TOP is a bounded process sample; overall CPU utilization is unverified.')
    else:
        notes.append(str(len(readings)) + ' HA readings received.')
        if not readings:
            usable = False
            limits.append('No supported enabled state readings were returned.')
        for item in readings:
            state = item.get('state')
            title = str(item.get('name') or item.get('entity_id', 'Entity'))
            if state in ('unavailable', 'read failed'):
                service.append(title + ': ' + state + ' in HA; physical connectivity and cause remain unverified.')
            elif state == 'unknown':
                limits.append(title + ': state unknown in HA.')
            volume = item.get('attributes', {}).get('volume_level')
            if volume is not None and (type(volume) not in (int, float) or not 0 <= volume <= 1):
                limits.append(title + ': invalid reported volume; treat as unknown.')
    if name == 'Ruckus':
        if snapshot.get('controller_error'):
            service.append('Direct access point statistics could not be read; per-access-point status and counts remain unverified.')
        controller = snapshot.get('controller')
        if controller is not None:
            aps = controller.get('access_points', [])
            notes.append(str(len(aps)) + ' access point statistics received directly from the controller.')
            if not aps:
                limits.append('Controller returned no access points; expected inventory is not configured.')
            for ap in aps:
                title = str(ap.get('name', 'Access point'))
                if ap.get('online') is False:
                    service.append(title + ': controller reports offline; cause unverified.')
                elif ap.get('online') is not True:
                    limits.append(title + ': controller state ' + str(ap.get('controller_state', 'unreported')) + ' is unverified.')
                if ap.get('connected_clients') is None:
                    limits.append(title + ': connected-device count unreported.')
            if controller.get('truncated'):
                limits.append('Access point inventory was limited to 128 records.')
            limits.extend(controller.get('limitations', []))
    if name == 'Sense':
        voltages = []
        for reading in snapshot.get('main_monitor_readings', []):
            attrs = reading.get('attributes', {})
            if attrs.get('device_class') != 'voltage' or attrs.get('unit_of_measurement') != 'V':
                continue
            try:
                value = float(reading.get('state'))
                if value >= 0:
                    voltages.append((str(reading.get('name', 'Line voltage')), value))
            except (ValueError, TypeError):
                pass
        # A relative source-data sanity check, not an electrical fault threshold.
        if len(voltages) == 2 and min(v for _, v in voltages) < max(v for _, v in voltages) / 2:
            service.append('Reported line voltages differ substantially: ' + '; '.join(f'{n}: {v:g} V' for n, v in voltages) + '. Verify the source readings; this does not establish an electrical fault.')
    if snapshot.get('discovery', {}).get('limit_reached'):
        limits.append('Discovery reached its limit; unvisited diagnostics remain unverified.')
    if snapshot.get('truncated') or snapshot.get('inventory_truncated'):
        limits.append('Snapshot is limited; some readings or inventory were omitted.')
    limits.extend(str(item) for item in snapshot.get('limitations', []))
    result['status'] = 'review' if service else ('verified' if usable else 'unverified')
    return result


def summarize(name, snapshot):
    result = assess(name, snapshot)
    return result['status'], result['observations'] + result['service_findings'] + result['data_limitations']


def metrics(name, snapshot):
    result = {}
    if name == 'Araknis':
        # Use one interface response only, never counters captured at a different time.
        for reading in snapshot.get('readings', []):
            if reading.get('command') == 'show interfaces' and not reading.get('truncated') and not reading.get('error'):
                for port in reading.get('ports', []):
                    value = port.get('rx_discards')
                    if type(value) is int and value >= 0:
                        result['rx_discards:' + port['port']] = value
                break
    if name == 'CP4-R':
        for reading in snapshot.get('readings', []):
            if reading.get('command') not in ('UPTIME', 'PROGUPTIME') or reading.get('truncated') or reading.get('status') != 'response received':
                continue
            text = reading.get('response', '')
            start = re.search(r'last started on:\s*([^\r\n]+)', text, re.I)
            if start:
                result[reading['command'] + ':started'] = start.group(1).strip()
    return result


def compare(current, previous):
    changes = []
    if previous is None:
        return ['Baseline established; run again to compare.']
    for key, value in current.items():
        old = previous.get(key)
        if old is None:
            continue
        if key.startswith('rx_discards:'):
            if value > old:
                changes.append(key.split(':', 1)[1] + ': RX discards increased by ' + str(value - old) + ' (cumulative counter).')
            elif value < old:
                changes.append(key.split(':', 1)[1] + ': RX discard counter decreased; wrap or reset is unverified. No loss rate calculated.')
        elif key.endswith(':started') and value != old:
            changes.append(key.split(':')[0] + ': reported start time changed; possible processor/program restart or clock adjustment.')
    return changes or ['No changes detected in comparable metrics.' if current else 'No comparable discard or processor start-time metrics exposed.']


def run_checks(jobs, baselines, progress=lambda *_: None, secrets=(), history=(), completed=lambda *_: None):
    report = {'format': 'adr-service-report-v1', 'agent_version': '0.17.0', 'read_only': True,
        'started_at': now(), 'completed_at': None, 'checks': [],
        'limitations': ['Verified means the specified read succeeded, not that every device function is healthy.',
            'Checks run sequentially; per-check timestamps differ. No automatic retries or device actions.',
            'HA state age is not a heartbeat. Off/idle do not mean offline.',
            'Comparisons use successful checks for the same target during this app session only. Restarting the app clears baselines.',
            'Counter decreases may be wraps or resets. No packet-loss rates or causes are inferred.']}
    next_baselines = copy.deepcopy(baselines)
    for name, target, read in jobs:
        progress(name)
        check = {'system': name, 'target_id': target, 'started_at': now(), 'completed_at': None, 'status': 'unverified',
            'findings': [], 'comparisons': [], 'snapshot': None,
            'service_findings': [], 'data_limitations': [], 'observations': [],
            'historical_observations': [copy.deepcopy(h) for h in history if h.get('system') == name and h.get('target') == target]}
        try:
            snapshot = read()
            check['snapshot'] = snapshot
            assessment = assess(name, snapshot)
            check.update(assessment)
            check['findings'] = assessment['observations'] + assessment['service_findings'] + assessment['data_limitations']
            current = metrics(name, snapshot)
            key = (name, target)
            if current:
                previous = baselines.get(key)
                check['comparisons'] = compare(current, previous)
                if previous is not None and any(previous.get(k) != v for k, v in current.items() if k in previous):
                    check['status'] = 'review'
                    check['observations'].append('Comparison changed. This does not by itself establish a service fault.')
                next_baselines[key] = current
            else:
                check['comparisons'] = ['Discard/restart comparisons are not available for this snapshot.']
        except SkipCheck as exc:
            check['findings'] = [str(exc)]
            check['data_limitations'] = [str(exc)]
        except Exception:
            # Exceptions can contain remote responses, passwords and tokens.
            check['service_findings'] = ['Read failed. Check this system individually; device operation and cause remain unverified.']
            check['findings'] = ['Read failed. Check this system individually for connection, selection or identity setup. No retry was made.']
        check['completed_at'] = now()
        report['checks'].append(check)
        completed(name, check['status'])
    report['completed_at'] = now()
    report['counts'] = {status: sum(c['status'] == status for c in report['checks'])
        for status in ('verified', 'review', 'unverified')}
    return redact(report, secrets), next_baselines
