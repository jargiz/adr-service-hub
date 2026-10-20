import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
import sonos
from agent import Pilot, page


class FakeWS:
    def __init__(self, registry):
        self.messages = iter([{'type': 'auth_required'}, {'type': 'auth_ok'},
            {'id': 1, 'type': 'result', 'success': True, 'result': registry}])
        self.sent = []
        self.closed = False

    def recv(self):
        return json.dumps(next(self.messages))

    def send(self, value):
        self.sent.append(json.loads(value))

    def close(self):
        self.closed = True


def state(entity_id, **attributes):
    return {'entity_id': entity_id, 'state': 'playing', 'attributes': attributes,
        'last_updated': '2026-10-20T00:00:00Z'}


class SonosTests(unittest.TestCase):
    def test_discovery_filters_platform_domain_and_disabled(self):
        ws = FakeWS([
            {'entity_id': 'media_player.kitchen', 'platform': 'sonos', 'disabled_by': None},
            {'entity_id': 'media_player.apple_tv', 'platform': 'apple_tv'},
            {'entity_id': 'media_player.disabled', 'platform': 'sonos', 'disabled_by': 'user'},
            {'entity_id': 'sensor.battery', 'platform': 'sonos'},
            {'entity_id': 'media_player.bad/path', 'platform': 'sonos'},
        ])
        with patch('sonos.websocket.create_connection', return_value=ws):
            self.assertEqual(sonos.discover('test-token'), ['media_player.kitchen'])
        self.assertEqual([x['type'] for x in ws.sent], ['auth', 'config/entity_registry/list'])
        self.assertTrue(ws.closed)

    def test_summary_reports_missing_values_as_unknown(self):
        p = sonos.summarize('media_player.kitchen', state('media_player.kitchen'))
        self.assertIsNone(p['volume'])
        self.assertIsNone(p['muted'])
        self.assertIsNone(p['group_members'])
        for value in (float('nan'), 3, True):
            self.assertIsNone(sonos.summarize('media_player.kitchen', state('media_player.kitchen', volume_level=value))['volume'])

    def test_muted_grouped_player(self):
        p = sonos.summarize('media_player.kitchen', state('media_player.kitchen',
            is_volume_muted=True, volume_level=0.17, group_members=['media_player.kitchen', 'media_player.patio']))
        self.assertEqual(p['volume'], 17)
        self.assertEqual(p['note'], 'Player reports muted.')
        self.assertEqual(len(p['group_members']), 2)

    def test_unavailable_not_reported_as_power_off(self):
        data = state('media_player.kitchen')
        data['state'] = 'unavailable'
        p = sonos.summarize('media_player.kitchen', data)
        self.assertIn('unverified', p['note'])

    def test_partial_failure_preserves_other_players_without_secret(self):
        def read(_token, entity_id):
            if entity_id.endswith('patio'):
                raise ValueError('secret-token is not disclosed')
            return state(entity_id, friendly_name='Kitchen')
        report = sonos.collect('secret-token', lambda _: ['media_player.kitchen', 'media_player.patio'], read)
        self.assertEqual(report['players'][0]['state'], 'playing')
        self.assertEqual(report['players'][1]['state'], 'read failed')
        self.assertNotIn('secret-token', json.dumps(report))

    def test_missing_token_and_auth_failure(self):
        with self.assertRaises(sonos.SonosError):
            sonos.collect('', lambda _: [], lambda *_: None)
        ws = FakeWS([])
        ws.messages = iter([{'type': 'auth_required'}, {'type': 'auth_invalid', 'message': 'private detail'}])
        with patch('sonos.websocket.create_connection', return_value=ws):
            with self.assertRaisesRegex(sonos.SonosError, 'denied'):
                sonos.discover('test-token')
        self.assertTrue(ws.closed)

    def test_http_only_gets_selected_entity(self):
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _): return json.dumps(state('media_player.kitchen')).encode()
        class Opener:
            def open(self, request, **kwargs):
                calls.append((request.full_url, request.method))
                return Response()
        with patch('sonos.build_opener', return_value=Opener()):
            sonos.read_state('test-token', 'media_player.kitchen')
        self.assertEqual(calls, [('http://supervisor/core/api/states/media_player.kitchen', 'GET')])
        with self.assertRaises(sonos.SonosError):
            sonos.read_state('test-token', 'lock.front_door')

    def test_failed_check_clears_previous_snapshot(self):
        p = object.__new__(Pilot)
        p.sonos = {'players': ['old data']}
        p.sonos_error = None
        with patch('agent.collect_sonos', side_effect=sonos.SonosError('Unavailable')):
            p.check_sonos()
        self.assertIsNone(p.sonos)
        self.assertEqual(p.sonos_error, 'Unavailable')


if __name__ == '__main__':
    unittest.main()
