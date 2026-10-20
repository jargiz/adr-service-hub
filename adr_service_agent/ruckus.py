"""Read-only Ruckus entry diagnostics; never configures or controls equipment."""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.request import Request, build_opener, ProxyHandler

import websocket
from sonos import NoRedirect, receive


class RuckusError(Exception):
    pass


DOMAIN = 'ruckus_unleashed'


def token_value():
    token = os.environ.get('SUPERVISOR_TOKEN', '')
    if not token:
        raise RuckusError('Home Assistant API access is unavailable. Restart the updated app.')
    return token


def entries(token, domain=DOMAIN):
    if domain not in (DOMAIN, 'unifi'):
        raise RuckusError('Unsupported integration domain.')
    req = Request('http://supervisor/core/api/config/config_entries/entry?domain=' + domain,
        headers={'Authorization': 'Bearer ' + token}, method='GET')
    with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=6) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise RuckusError('Integration list response too large.')
    data = json.loads(raw)
    if not isinstance(data, list):
        raise RuckusError('Unexpected integration list response.')
    return [{'entry_id': e['entry_id'], 'title': e.get('title', e['entry_id']),
        'state': e.get('state', 'unknown'), 'disabled_by': e.get('disabled_by')}
        for e in data if e.get('domain') == domain and isinstance(e.get('entry_id'), str)]


def registries(token):
    ws = websocket.create_connection('ws://supervisor/core/websocket', timeout=6,
        http_no_proxy=['supervisor'], suppress_origin=True)
    try:
        if receive(ws).get('type') != 'auth_required':
            raise RuckusError('Unexpected Home Assistant authentication response.')
        ws.send(json.dumps({'type': 'auth', 'access_token': token}))
        if receive(ws).get('type') != 'auth_ok':
            raise RuckusError('Home Assistant API access denied.')
        results = []
        for number, name in enumerate(('config/entity_registry/list', 'config/device_registry/list'), 1):
            ws.send(json.dumps({'id': number, 'type': name}))
            result = receive(ws)
            if result.get('id') != number or result.get('success') is not True or not isinstance(result.get('result'), list):
                raise RuckusError('Home Assistant did not allow registry discovery.')
            results.append(result['result'])
        return results
    finally:
        ws.close()


def selected_entities(registry, entry_id):
    return sorted({e['entity_id'] for e in registry if e.get('config_entry_id') == entry_id
        and e.get('platform') == DOMAIN and not e.get('disabled_by')
        and re.fullmatch(r'(device_tracker|sensor|binary_sensor)\.[a-z0-9_]+', e.get('entity_id', ''))})


def read_state(token, entity_id):
    if not re.fullmatch(r'(device_tracker|sensor|binary_sensor)\.[a-z0-9_]+', entity_id):
        raise RuckusError('Unsupported diagnostic entity.')
    req = Request('http://supervisor/core/api/states/' + entity_id,
        headers={'Authorization': 'Bearer ' + token}, method='GET')
    with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=4) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise RuckusError('Entity response too large.')
    state = json.loads(raw)
    if state.get('entity_id') != entity_id or not isinstance(state.get('attributes'), dict):
        raise RuckusError('Unexpected entity state.')
    a = state['attributes']
    return {'entity_id': entity_id, 'name': a.get('friendly_name') or entity_id,
        'state': state.get('state', 'unknown'), 'last_updated': state.get('last_updated'),
        'ip': a.get('ip'), 'mac': a.get('mac'), 'source_type': a.get('source_type')}


def collect(entry_id, token=None, entries_fn=entries, registries_fn=registries, read_fn=read_state):
    token = token if token is not None else token_value()
    try:
        available = entries_fn(token)
        entry = next((e for e in available if e['entry_id'] == entry_id), None)
        if entry is None:
            raise RuckusError('Select one of the discovered Ruckus entries.')
        result = {'entry': entry, 'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'devices': [], 'entities': [], 'entity_count': 0, 'truncated': False}
        # Failed/disabled entries may retain stale entities. Do not report those
        # as current readings even when their old states remain in HA.
        if entry.get('disabled_by') or entry.get('state') != 'loaded':
            return result
        registry, devices = registries_fn(token)
        ids = selected_entities(registry, entry_id)
        result['entity_count'] = len(ids)
        result['truncated'] = len(ids) > 64
        result['devices'] = [{'name': d.get('name_by_user') or d.get('name') or 'Unnamed device',
            'manufacturer': d.get('manufacturer'), 'model': d.get('model')}
            for d in devices if entry_id in d.get('config_entries', []) and not d.get('disabled_by')]

        def read(entity_id):
            try:
                return read_fn(token, entity_id)
            except Exception:
                return {'entity_id': entity_id, 'name': entity_id, 'state': 'read failed',
                    'last_updated': None, 'ip': None, 'mac': None, 'source_type': None}
        with ThreadPoolExecutor(max_workers=8) as pool:
            result['entities'] = list(pool.map(read, ids[:64]))
        return result
    except RuckusError:
        raise
    except Exception:
        raise RuckusError('Could not read Ruckus information through Home Assistant. No configuration or device actions were sent.') from None
