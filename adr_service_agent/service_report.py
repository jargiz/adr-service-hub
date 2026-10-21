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


def summarize(name, snapshot):
    notes, issues = [], []
    entry = snapshot.get('entry')
    if name in ('Crestron', 'Control4', 'UniFi', 'Ruckus'):
        if not entry:
            return 'unverified', ['No integration selected or discovered. Run its individual check to select it.']
        if entry.get('state') != 'loaded' or entry.get('disabled_by'):
            return 'review', ['Selected HA integration is not loaded and enabled; current device operation is unverified.']
        notes.append('Selected HA integration is loaded; states are snapshots, not physical tests.')
        if name == 'UniFi' and not snapshot.get('device'):
            return 'unverified', ['Select a UniFi device using its individual check.']
    readings = snapshot.get('readings', snapshot.get('sensors', snapshot.get('entities', snapshot.get('players', []))))
    if name == 'WattBox':
        notes.append('Outlet inventory received. Power state does not verify connected equipment operation.')
    elif name in ('Araknis', 'CP4-R'):
        if not readings:
            return 'unverified', ['No diagnostic responses received.']
        if name == 'CP4-R' and not snapshot.get('model_verified'):
            issues.append('CP4-R model was not verified; further processor checks are incomplete.')
        notes.append('Read-only console responses received; absent diagnostics remain unverified.')
        for item in readings:
            if item.get('error') or item.get('truncated') or item.get('status') in ('read failed', 'unsupported or denied', 'partial response'):
                issues.append(str(item.get('name', 'Diagnostic')) + ': failed, partial or unsupported response.')
            if item.get('command') == 'SYSTEMREADY' and re.search(r'SystemReady:\s*False', item.get('response', ''), re.I):
                issues.append('Processor reports SystemReady: False.')
        if snapshot.get('not_attempted'):
            issues.append('Some processor diagnostics remain unverified; see not_attempted in the snapshot.')
    else:
        notes.append(str(len(readings)) + ' HA readings received.')
        if not readings:
            return 'unverified', notes + ['No supported enabled state readings were returned.']
        for item in readings:
            if item.get('state') in ('unknown', 'unavailable', 'read failed'):
                issues.append(str(item.get('entity_id', 'Entity')) + ': ' + item['state'] + '; physical connectivity unverified.')
            volume = item.get('attributes', {}).get('volume_level')
            if volume is not None and (type(volume) not in (int, float) or not 0 <= volume <= 1):
                issues.append(str(item.get('entity_id', 'Entity')) + ': invalid reported volume; treat as unknown.')
    if snapshot.get('discovery', {}).get('limit_reached'):
        issues.append('Discovery reached its limit; unvisited diagnostics remain unverified.')
    if snapshot.get('truncated') or snapshot.get('inventory_truncated'):
        issues.append('Snapshot is limited; some readings or inventory were omitted.')
    return ('review' if issues else 'verified'), notes + issues


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


def run_checks(jobs, baselines, progress=lambda *_: None, secrets=()):
    report = {'format': 'adr-service-report-v1', 'agent_version': '0.12.0', 'read_only': True,
        'started_at': now(), 'completed_at': None, 'checks': [],
        'limitations': ['Verified means the specified read succeeded, not that every device function is healthy.',
            'Checks run sequentially; per-check timestamps differ. No automatic retries or device actions.',
            'HA state age is not a heartbeat. Off/idle do not mean offline.',
            'Comparisons use successful checks for the same target during this app session only. Restarting the app clears baselines.',
            'Counter decreases may be wraps or resets. No packet-loss rates or causes are inferred.']}
    next_baselines = copy.deepcopy(baselines)
    for name, target, read in jobs:
        progress(name)
        check = {'system': name, 'started_at': now(), 'completed_at': None, 'status': 'unverified',
            'findings': [], 'comparisons': [], 'snapshot': None}
        try:
            snapshot = read()
            check['snapshot'] = snapshot
            check['status'], check['findings'] = summarize(name, snapshot)
            current = metrics(name, snapshot)
            key = (name, target)
            if current:
                previous = baselines.get(key)
                check['comparisons'] = compare(current, previous)
                if previous is not None and any(previous.get(k) != v for k, v in current.items() if k in previous):
                    check['status'] = 'review'
                next_baselines[key] = current
            else:
                check['comparisons'] = ['Discard/restart comparisons are not available for this snapshot.']
        except SkipCheck as exc:
            check['findings'] = [str(exc)]
        except Exception:
            # Exceptions can contain remote responses, passwords and tokens.
            check['findings'] = ['Read failed. Check this system individually for connection, selection or identity setup. No retry was made.']
        check['completed_at'] = now()
        report['checks'].append(check)
    report['completed_at'] = now()
    report['counts'] = {status: sum(c['status'] == status for c in report['checks'])
        for status in ('verified', 'review', 'unverified')}
    return redact(report, secrets), next_baselines
