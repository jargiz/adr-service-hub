"""Read-only Sonos snapshots through the local Home Assistant Core proxy.

Only entity-registry discovery and GET state reads are implemented. No service
calls, entity writes, subscriptions, or player-control messages are exposed.
"""
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, ProxyHandler

import websocket


class SonosError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def receive(ws):
    raw = ws.recv()
    if len(raw) > 4 * 1024 * 1024:
        raise SonosError('Home Assistant returned an unexpectedly large response.')
    return json.loads(raw)


def discover(token):
    ws = websocket.create_connection('ws://supervisor/core/websocket', timeout=6,
        http_no_proxy=['supervisor'], suppress_origin=True)
    try:
        if receive(ws).get('type') != 'auth_required':
            raise SonosError('Unexpected Home Assistant authentication response.')
        ws.send(json.dumps({'type': 'auth', 'access_token': token}))
        if receive(ws).get('type') != 'auth_ok':
            raise SonosError('Home Assistant API access was denied. Check that the updated app is installed and restarted.')
        ws.send(json.dumps({'id': 1, 'type': 'config/entity_registry/list'}))
        response = receive(ws)
        if response.get('id') != 1 or response.get('type') != 'result' or response.get('success') is not True:
            raise SonosError('Home Assistant did not allow Sonos entity discovery.')
        registry = response.get('result')
        if not isinstance(registry, list):
            raise SonosError('Unexpected entity registry response.')
        # Names are not used to guess a platform. Include only entities explicitly
        # assigned to the Sonos integration; exclude disabled registry entries.
        ids = sorted({e['entity_id'] for e in registry if isinstance(e, dict)
            and e.get('platform') == 'sonos' and not e.get('disabled_by')
            and re.fullmatch(r'media_player\.[a-z0-9_]+', e.get('entity_id', ''))})
        return ids
    finally:
        ws.close()


def read_state(token, entity_id):
    if not re.fullmatch(r'media_player\.[a-z0-9_]+', entity_id):
        raise SonosError('Invalid Sonos entity ID.')
    request = Request('http://supervisor/core/api/states/' + entity_id,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}, method='GET')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=4) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise SonosError('Player state response was too large.')
        result = json.loads(raw)
        if result.get('entity_id') != entity_id or not isinstance(result.get('attributes'), dict):
            raise SonosError('Unexpected player state response.')
        return result
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise SonosError('Home Assistant denied access to player state.') from None
        raise SonosError('Could not read this player from Home Assistant.') from None


def summarize(entity_id, state):
    attrs = state['attributes']
    value = attrs.get('volume_level')
    volume = round(value * 100) if type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1 else None
    mute = attrs.get('is_volume_muted')
    if type(mute) is not bool:
        mute = None
    members = attrs.get('group_members')
    members = [m for m in members if isinstance(m, str)] if isinstance(members, list) else None
    status = state.get('state', 'unknown')
    note = 'No issue established from these reported states.'
    if status in ('unavailable', 'unknown'):
        note = 'Home Assistant has no usable player state; power and network cause are unverified.'
    elif mute is True:
        note = 'Player reports muted.'
    elif volume == 0:
        note = 'Player reports zero volume.'
    elif status == 'paused':
        note = 'Playback reports paused.'
    elif status == 'idle':
        note = 'Player reports idle.'
    return {'entity_id': entity_id, 'name': attrs.get('friendly_name') or entity_id,
        'state': status, 'volume': volume, 'muted': mute, 'group_members': members,
        'source': attrs.get('source'), 'title': attrs.get('media_title'),
        'artist': attrs.get('media_artist'), 'ha_last_updated': state.get('last_updated'),
        'note': note}


def collect(token=None, discover_fn=discover, read_fn=read_state):
    token = token if token is not None else os.environ.get('SUPERVISOR_TOKEN', '')
    if not token:
        raise SonosError('Home Assistant API access is unavailable. Install the updated app and restart it.')
    try:
        ids = discover_fn(token)
    except SonosError:
        raise
    except Exception:
        raise SonosError('Could not discover Sonos players through Home Assistant. Check the app log and Home Assistant availability.') from None

    def player(entity_id):
        try:
            return summarize(entity_id, read_fn(token, entity_id))
        except Exception:
            return {'entity_id': entity_id, 'name': entity_id, 'state': 'read failed',
                'volume': None, 'muted': None, 'group_members': None, 'source': None,
                'title': None, 'artist': None, 'ha_last_updated': None,
                'note': 'Could not read this player. Its current state is unverified.'}

    # Keep on-demand requests bounded on small appliances. Do not persist playback
    # history, raw HA payloads, tokens, or track details in the service log.
    with ThreadPoolExecutor(max_workers=4) as pool:
        players = list(pool.map(player, ids[:32]))
    return {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'players': players, 'discovered_count': len(ids), 'truncated': len(ids) > 32}
