"""Read-only discovery of existing Crestron integrations through HA Core."""
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.request import Request, build_opener, ProxyHandler

from ruckus import registries, token_value
from sonos import NoRedirect


class CrestronError(Exception):
    pass


ENTITY = re.compile(r'(sensor|binary_sensor|light|cover|climate|lock|media_player|switch)\.[a-z0-9_]+')
DOMAIN = re.compile(r'crestron[a-z0-9_]*')
MAX_READINGS = 128
COMMON_ATTRIBUTES = ('device_class', 'unit_of_measurement', 'connection_status',
    'connectionStatus', 'online', 'is_online', 'available', 'is_available')
ATTRIBUTES = {
    'light': ('brightness', 'color_temp_kelvin', 'color_mode'),
    'cover': ('current_position', 'current_tilt_position'),
    'climate': ('current_temperature', 'temperature', 'target_temp_high',
        'target_temp_low', 'hvac_action', 'fan_mode', 'current_humidity'),
    'media_player': ('volume_level', 'is_volume_muted', 'source'),
}


def scalar(value, limit=256):
    if value is None or type(value) is bool:
        return value
    if type(value) in (int, float):
        return value if math.isfinite(value) else None
    return value[:limit] if isinstance(value, str) else None


def get_json(token, path):
    request = Request('http://supervisor/core/api/' + path,
        headers={'Authorization': 'Bearer ' + token}, method='GET')
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=4) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise CrestronError('Home Assistant response exceeded the size limit.')
    return json.loads(raw)


def entries(token):
    data = get_json(token, 'config/config_entries/entry')
    if not isinstance(data, list):
        raise CrestronError('Unexpected integration list response.')
    return [{'entry_id': item['entry_id'], 'title': scalar(item.get('title')) or item['entry_id'],
        'domain': item['domain'], 'state': scalar(item.get('state')) or 'unknown',
        'disabled_by': scalar(item.get('disabled_by'))}
        for item in data if isinstance(item, dict) and isinstance(item.get('entry_id'), str)
        and isinstance(item.get('domain'), str) and DOMAIN.fullmatch(item['domain'])]


def read_state(token, entity_id):
    if not ENTITY.fullmatch(entity_id):
        raise CrestronError('Unsupported Crestron diagnostic entity.')
    data = get_json(token, 'states/' + entity_id)
    if not isinstance(data, dict) or data.get('entity_id') != entity_id or not isinstance(data.get('attributes'), dict):
        raise CrestronError('Unexpected entity response.')
    attrs = data['attributes']
    allowed = COMMON_ATTRIBUTES + ATTRIBUTES.get(entity_id.split('.')[0], ())
    return {'entity_id': entity_id, 'name': scalar(attrs.get('friendly_name')) or entity_id,
        'state': scalar(data.get('state')) or 'unknown',
        'last_updated': scalar(data.get('last_updated')),
        'attributes': {key: scalar(attrs[key]) for key in allowed if key in attrs}}


def collect(entry_id='', token=None, entries_fn=entries, registries_fn=registries, read_fn=read_state):
    try:
        token = token if token is not None else token_value()
        available = entries_fn(token)
        entry = next((item for item in available if item['entry_id'] == entry_id), None)
        if not entry_id and len(available) == 1:
            entry = available[0]
        result = {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'entries': available, 'entry': entry, 'devices': [], 'entity_inventory': [],
            'readings': [], 'entity_count': 0, 'enabled_supported_count': 0,
            'disabled_count': 0, 'unsupported_count': 0, 'truncated': False,
            'inventory_truncated': False,
            'limitations': ['HA state snapshots are not fresh tests of the processor or physical equipment.',
                'Unavailable/unknown entities do not by themselves establish that a device or processor is offline.',
                'HA last-update time is not a heartbeat. Device registry metadata is not a live firmware query.',
                'Only health fields exposed by the installed integration can be shown; missing fields remain unverified.']}
        if entry is None or entry.get('disabled_by') or entry.get('state') != 'loaded':
            return result
        registry, devices = registries_fn(token)
        matching_devices = [device for device in devices if entry['entry_id'] in device.get('config_entries', [])]
        blocked = {device['id'] for device in matching_devices if device.get('disabled_by')}
        for device in matching_devices[:512]:
            result['devices'].append({'id': device['id'],
                'name': scalar(device.get('name_by_user') or device.get('name')) or 'Unnamed device',
                'manufacturer': scalar(device.get('manufacturer')), 'model': scalar(device.get('model')),
                'registry_sw_version': scalar(device.get('sw_version')),
                'disabled_by': scalar(device.get('disabled_by'))})
        candidates = [entity for entity in registry if entity.get('config_entry_id') == entry['entry_id']
            and entity.get('platform') == entry['domain'] and isinstance(entity.get('entity_id'), str)]
        result['entity_count'] = len(candidates)
        result['inventory_truncated'] = len(candidates) > 1024 or len(matching_devices) > 512
        enabled = []
        for entity in candidates:
            supported = bool(ENTITY.fullmatch(entity['entity_id']))
            disabled = bool(entity.get('disabled_by')) or entity.get('device_id') in blocked
            if disabled:
                result['disabled_count'] += 1
            if not supported:
                result['unsupported_count'] += 1
            if supported and not disabled:
                enabled.append(entity)
        for entity in candidates[:1024]:
            result['entity_inventory'].append({'entity_id': entity['entity_id'],
                'device_id': scalar(entity.get('device_id')),
                'name': scalar(entity.get('name') or entity.get('original_name')) or entity['entity_id'],
                'disabled_by': scalar(entity.get('disabled_by')),
                'device_disabled': entity.get('device_id') in blocked,
                'state_read_supported': bool(ENTITY.fullmatch(entity['entity_id']))})
        # Prefer exposed diagnostic readings over a potentially large lighting inventory.
        enabled.sort(key=lambda entity: (0 if entity['entity_id'].split('.')[0] in ('sensor', 'binary_sensor') else 1, entity['entity_id']))
        result['enabled_supported_count'] = len(enabled)
        result['truncated'] = len(enabled) > MAX_READINGS
        def read(entity):
            entity_id = entity['entity_id']
            try:
                value = read_fn(token, entity_id)
                value['device_id'] = scalar(entity.get('device_id'))
                return value
            except Exception:
                return {'entity_id': entity_id, 'device_id': scalar(entity.get('device_id')),
                    'name': scalar(entity.get('name') or entity.get('original_name')) or entity_id,
                    'state': 'read failed', 'last_updated': None, 'attributes': {}}
        with ThreadPoolExecutor(max_workers=8) as pool:
            result['readings'] = list(pool.map(read, enabled[:MAX_READINGS]))
        return result
    except CrestronError:
        raise
    except Exception:
        raise CrestronError('Could not inspect Crestron through Home Assistant. Check the existing integration and API availability.') from None


def report_payload(result):
    return {'format': 'adr-crestron-discovery-v1', 'agent_version': '0.16.0',
        'read_only': True, 'source': 'existing_home_assistant_integration', 'snapshot': result}
