"""Read-only BluOS player discovery through configured HA Bluesound entries."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from crestron import get_json, read_state, scalar
from ruckus import registries, token_value

ENTITY = re.compile(r'(media_player|sensor|binary_sensor)\.[a-z0-9_]+')
MAX_ENTRIES = 32
MAX_READINGS = 128


class BluesoundError(Exception):
    pass


def entries(token):
    data = get_json(token, 'config/config_entries/entry')
    if not isinstance(data, list):
        raise BluesoundError('Unexpected integration list response.')
    return [{'entry_id': item['entry_id'], 'title': scalar(item.get('title')) or item['entry_id'],
        'domain': 'bluesound', 'state': scalar(item.get('state')) or 'unknown',
        'disabled_by': scalar(item.get('disabled_by'))}
        for item in data if isinstance(item, dict) and item.get('domain') == 'bluesound'
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
            'limitations': ['HA states are snapshots, not fresh tests of player connectivity or audio output.',
                'Off/idle do not mean offline; unavailable/unknown states do not establish a physical device failure.',
                'Last-update time is not a heartbeat. Registry software version is not a live firmware query.',
                'Only exposed HA fields are available. BluOS CPU, RAM, uptime and full network diagnostics remain unverified.',
                'Discovery covers configured Bluesound integration entries only, not a LAN scan or inventory inferred from names.']}
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
            and e.get('platform') == 'bluesound' and isinstance(e.get('entity_id'), str)]
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
        enabled.sort(key=lambda e: (0 if e['entity_id'].startswith(('sensor.', 'binary_sensor.')) else 1, e['entity_id']))
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
        return result
    except Exception:
        raise BluesoundError('Could not inspect Bluesound through Home Assistant. Check the integration and API availability.') from None


def report_payload(result):
    return {'format': 'adr-bluesound-discovery-v1', 'agent_version': '0.14.0',
        'read_only': True, 'source': 'existing_home_assistant_integration', 'snapshot': result}
