"""Read-only Sense energy sensor discovery through configured HA Sense entries."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import math
from urllib.parse import urlencode, quote

from crestron import get_json, scalar
from ruckus import registries, token_value

ENTITY = re.compile(r'(sensor|binary_sensor)\.[a-z0-9_]+')
MAX_ENTRIES = 32
MAX_READINGS = 128


class SenseError(Exception):
    pass


def read_state(token, entity_id):
    if not ENTITY.fullmatch(entity_id):
        raise SenseError('Unsupported Sense diagnostic entity.')
    data = get_json(token, 'states/' + entity_id)
    if not isinstance(data, dict) or data.get('entity_id') != entity_id or not isinstance(data.get('attributes'), dict):
        raise SenseError('Unexpected Sense entity response.')
    attrs = data['attributes']
    allowed = ('unit_of_measurement', 'device_class', 'state_class', 'last_reset')
    return {'entity_id': entity_id, 'name': scalar(attrs.get('friendly_name')) or entity_id,
        'state': scalar(data.get('state')) or 'unknown', 'last_updated': scalar(data.get('last_updated')),
        'attributes': {key: scalar(attrs[key]) for key in allowed if key in attrs}}


def entries(token):
    data = get_json(token, 'config/config_entries/entry')
    if not isinstance(data, list):
        raise SenseError('Unexpected integration list response.')
    return [{'entry_id': item['entry_id'], 'title': scalar(item.get('title')) or item['entry_id'],
        'domain': 'sense', 'state': scalar(item.get('state')) or 'unknown',
        'disabled_by': scalar(item.get('disabled_by'))}
        for item in data if isinstance(item, dict) and item.get('domain') == 'sense'
        and isinstance(item.get('entry_id'), str)]


def collect(token=None, entries_fn=entries, registries_fn=registries, read_fn=read_state):
    try:
        token = token if token is not None else token_value()
        available = entries_fn(token)
        result = {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'entries': available[:MAX_ENTRIES], 'entry_count': len(available),
            'devices': [], 'entity_inventory': [], 'readings': [], 'entity_count': 0,
            'enabled_supported_count': 0, 'disabled_count': 0, 'unsupported_count': 0,
            'truncated': len(available) > MAX_ENTRIES, 'inventory_truncated': False,
            'limitations': ['Read-only discovery of configured Sense integrations; values are HA snapshots from the Sense cloud integration.',
                'Line voltage, power and energy are different measurements; only exposed sensor values and units are reported.',
                'HA last-update time is not a heartbeat. Missing or unavailable readings do not establish an electrical fault.',
                'History is read on demand from the existing HA recorder when available. No recorder settings or polling schedules are changed.',
                'Sampled voltage does not establish whether brief spikes, sags or other power-quality events occurred.']}
        enabled_entries = {e['entry_id'] for e in result['entries']
            if e.get('state') == 'loaded' and not e.get('disabled_by')}
        if not enabled_entries:
            return result
        registry, devices = registries_fn(token)
        matching = [d for d in devices if enabled_entries.intersection(d.get('config_entries', []))]
        blocked = {d['id'] for d in matching if d.get('disabled_by')}
        for d in matching[:512]:
            result['devices'].append({'id': d['id'], 'name': scalar(d.get('name_by_user') or d.get('name')) or 'Unnamed device',
                'manufacturer': scalar(d.get('manufacturer')), 'model': scalar(d.get('model')),
                'registry_sw_version': scalar(d.get('sw_version')), 'disabled_by': scalar(d.get('disabled_by'))})
        candidates = [e for e in registry if e.get('config_entry_id') in enabled_entries
            and e.get('platform') == 'sense' and isinstance(e.get('entity_id'), str)]
        main_ids = {e.get('device_id') for e in candidates if e.get('device_id') and (str(e.get('original_name', '')).casefold() in ('l1 voltage', 'l2 voltage') or re.search(r'(?:^|[_.])l[12]_voltage$', e['entity_id']))}
        result['main_monitor_device_ids'] = sorted(main_ids)
        result['entity_count'] = len(candidates)
        result['inventory_truncated'] = len(candidates) > 1024 or len(matching) > 512
        enabled = []
        for e in candidates:
            supported = bool(ENTITY.fullmatch(e['entity_id']))
            disabled = bool(e.get('disabled_by')) or e.get('device_id') in blocked
            result['disabled_count'] += int(disabled)
            result['unsupported_count'] += int(not supported)
            if supported and not disabled:
                enabled.append(e)
        for e in candidates[:1024]:
            result['entity_inventory'].append({'entity_id': e['entity_id'], 'device_id': scalar(e.get('device_id')),
                'name': scalar(e.get('name') or e.get('original_name')) or e['entity_id'],
                'disabled_by': scalar(e.get('disabled_by')), 'device_disabled': e.get('device_id') in blocked,
                'state_read_supported': bool(ENTITY.fullmatch(e['entity_id']))})
        enabled.sort(key=lambda e: (0 if e.get('device_id') in main_ids else 1, 0 if any(k in e['entity_id'] for k in ('voltage', 'energy_usage', 'active_usage', 'daily_usage')) else 1, e['entity_id']))
        result['enabled_supported_count'] = len(enabled)
        result['truncated'] = result['truncated'] or len(enabled) > MAX_READINGS
        def read(e):
            try:
                value = read_fn(token, e['entity_id'])
                value['device_id'] = scalar(e.get('device_id'))
                return value
            except Exception:
                return {'entity_id': e['entity_id'], 'device_id': scalar(e.get('device_id')),
                    'name': scalar(e.get('name') or e.get('original_name')) or e['entity_id'],
                    'state': 'read failed', 'last_updated': None, 'attributes': {}}
        with ThreadPoolExecutor(max_workers=8) as pool:
            result['readings'] = list(pool.map(read, enabled[:MAX_READINGS]))
        result['main_monitor_readings'] = [r for r in result['readings'] if r.get('device_id') in main_ids]
        return result
    except Exception:
        raise SenseError('Could not inspect Sense through Home Assistant. Check the integration and API availability.') from None


def report_payload(result):
    return {'format': 'adr-sense-discovery-v1', 'agent_version': '0.19.0',
        'read_only': True, 'source': 'existing_home_assistant_integration', 'snapshot': result}


def add_history(snapshot, token, get_fn=get_json, now=None):
    """Bounded historical reads of enabled, owned Sense measurement sensors only."""
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    selected = []
    for reading in snapshot.get('readings', []):
        attrs = reading.get('attributes', {})
        if not reading.get('entity_id', '').startswith('sensor.'):
            continue
        if attrs.get('device_class') not in ('voltage', 'power', 'energy'):
            continue
        if attrs.get('unit_of_measurement') not in ('V', 'W', 'kW', 'Wh', 'kWh'):
            continue
        selected.append(reading)
    main_ids = set(snapshot.get('main_monitor_device_ids', []))
    def priority(reading):
        attrs = reading['attributes']
        label = (reading['entity_id'] + ' ' + reading.get('name', '')).lower()
        main = reading.get('device_id') in main_ids
        rank = (0 if attrs.get('device_class') == 'voltage' else
            1 if attrs.get('device_class') == 'power' and any(k in label for k in ('energy_usage', 'active_usage', 'consumption')) else
            2 if 'daily_usage' in label or 'daily energy' in label else
            3 if attrs.get('device_class') == 'power' else 4)
        return (0 if main else 1, rank, reading['entity_id'])
    selected.sort(key=priority)
    snapshot['history'] = {'start': start.isoformat(), 'end': end.isoformat(), 'series': [],
        'limited': len(selected) > 6, 'note': 'Past 24 hours from HA recorder. Gaps and missing history remain unverified; readings are not a transient power-quality test.'}
    owned = {e['entity_id'] for e in snapshot.get('entity_inventory', [])
        if e.get('state_read_supported') and not e.get('disabled_by') and not e.get('device_disabled')}
    for reading in selected[:6]:
        entity_id = reading['entity_id']
        if entity_id not in owned or not ENTITY.fullmatch(entity_id):
            continue
        series = {'entity_id': entity_id, 'name': reading.get('name', entity_id),
            'unit': reading['attributes']['unit_of_measurement'], 'points': [], 'status': 'unverified', 'truncated': False}
        try:
            query = urlencode({'filter_entity_id': entity_id, 'end_time': end.isoformat(),
                'minimal_response': '1', 'no_attributes': '1', 'significant_changes_only': '0'})
            data = get_fn(token, 'history/period/' + quote(start.isoformat(), safe='') + '?' + query)
            if not isinstance(data, list):
                raise ValueError('Invalid history')
            # With a single entity filter, accept only its one returned series.
            if len(data) > 1 or (data and not isinstance(data[0], list)):
                raise ValueError('Unexpected history series')
            rows = data[0] if data else []
            if any(not isinstance(row, dict) or row.get('entity_id', entity_id) != entity_id for row in rows):
                raise ValueError('Unexpected history owner')
            series['truncated'] = len(rows) > 2000
            for row in rows[:2000]:
                stamp = row.get('last_changed') or row.get('last_updated')
                try:
                    when = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
                    if when.tzinfo is None or not start <= when <= end:
                        continue
                except (TypeError, ValueError):
                    continue
                try:
                    value = float(row.get('state'))
                    if not math.isfinite(value): value = None
                except (TypeError, ValueError):
                    value = None
                series['points'].append({'time': when.isoformat(), 'value': value})
            series['points'].sort(key=lambda point: point['time'])
            series['status'] = 'received' if any(p['value'] is not None for p in series['points']) else 'no history'
        except Exception:
            series['status'] = 'history unavailable'
        snapshot['history']['series'].append(series)
    if snapshot['history']['limited'] or any(s['truncated'] for s in snapshot['history']['series']):
        snapshot['limitations'].append('Sense history is bounded to six entities and 2000 states per entity; some history may be omitted.')
    if not snapshot['history']['series'] or any(s['status'] != 'received' for s in snapshot['history']['series']):
        snapshot['limitations'].append('Some Sense history is unavailable or not recorded. Current states are shown separately.')
    return snapshot


def collect_with_history(token=None):
    token = token if token is not None else token_value()
    snapshot = collect(token=token)
    return add_history(snapshot, token)
