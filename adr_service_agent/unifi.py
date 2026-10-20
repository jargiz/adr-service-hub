"""Selected-device UniFi sensor reads via Home Assistant; no control actions."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.request import Request, build_opener, ProxyHandler

from ruckus import entries, registries, token_value
from sonos import NoRedirect


class UniFiError(Exception):
    pass


def sensor_entities(registry, entry_id, device_id):
    return [e for e in registry if e.get('config_entry_id') == entry_id
        and e.get('device_id') == device_id and e.get('platform') == 'unifi'
        and re.fullmatch(r'(sensor|binary_sensor)\.[a-z0-9_]+', e.get('entity_id', ''))]


def read_state(token, entity_id):
    if not re.fullmatch(r'(sensor|binary_sensor)\.[a-z0-9_]+', entity_id):
        raise UniFiError('Only sensor readings are permitted.')
    req = Request('http://supervisor/core/api/states/' + entity_id,
        headers={'Authorization': 'Bearer ' + token}, method='GET')
    with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=4) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise UniFiError('Sensor response too large.')
    state = json.loads(raw)
    if state.get('entity_id') != entity_id or not isinstance(state.get('attributes'), dict):
        raise UniFiError('Unexpected sensor response.')
    a = state['attributes']
    return {'entity_id': entity_id, 'name': a.get('friendly_name') or entity_id,
        'state': state.get('state', 'unknown'), 'unit': a.get('unit_of_measurement'),
        'last_updated': state.get('last_updated')}


def collect(entry_id='', device_id='', token=None, entries_fn=entries,
            registries_fn=registries, read_fn=read_state):
    try:
        token = token if token is not None else token_value()
        available = entries_fn(token, domain='unifi')
        entry = next((e for e in available if e['entry_id'] == entry_id), None)
        if entry is None and len(available) == 1:
            entry = available[0]
        result = {'entries': available, 'entry': entry, 'devices': [], 'device': None,
            'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'sensors': [], 'disabled_sensors': [], 'sensor_count': 0, 'truncated': False}
        if entry is None or entry.get('disabled_by') or entry.get('state') != 'loaded':
            return result
        entry_id = entry['entry_id']
        registry, devices = registries_fn(token)
        for d in devices:
            if entry_id not in d.get('config_entries', []) or d.get('disabled_by'):
                continue
            if sensor_entities(registry, entry_id, d['id']):
                result['devices'].append({'id': d['id'], 'name': d.get('name_by_user') or d.get('name') or 'Unnamed device',
                    'model': d.get('model')})
        result['devices'].sort(key=lambda d: str(d['name']).casefold())
        device = next((d for d in result['devices'] if d['id'] == device_id), None)
        if device is None and len(result['devices']) == 1:
            device = result['devices'][0]
        result['device'] = device
        if device is None:
            return result
        candidates = sensor_entities(registry, entry_id, device['id'])
        enabled = sorted(e['entity_id'] for e in candidates if not e.get('disabled_by'))
        result['disabled_sensors'] = sorted(e.get('name') or e.get('original_name') or e['entity_id']
            for e in candidates if e.get('disabled_by'))
        result['sensor_count'] = len(enabled)
        result['truncated'] = len(enabled) > 64

        def read(entity_id):
            try:
                return read_fn(token, entity_id)
            except Exception:
                return {'entity_id': entity_id, 'name': entity_id, 'state': 'read failed',
                    'unit': None, 'last_updated': None}
        with ThreadPoolExecutor(max_workers=8) as pool:
            result['sensors'] = list(pool.map(read, enabled[:64]))
        return result
    except UniFiError:
        raise
    except Exception:
        raise UniFiError('Could not read UniFi diagnostics through Home Assistant. No network or device commands were sent.') from None
