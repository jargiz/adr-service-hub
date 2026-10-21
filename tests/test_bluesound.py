import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
import bluesound
from agent import Pilot, Handler, page
from service_report import summarize


def entries(_):
    return [{'entry_id': name, 'title': name, 'domain': 'bluesound', 'state': 'loaded', 'disabled_by': None} for name in ('zone-a', 'zone-b')]


def entity(name, entry='zone-a', **kwargs):
    return dict(entity_id=name, config_entry_id=entry, platform='bluesound', **kwargs)


def state(_, name):
    return {'entity_id': name, 'name': name, 'state': 'idle', 'attributes': {}, 'last_updated': None}


class BluesoundTests(unittest.TestCase):
    def test_multiple_players_exact_platform_no_controls_disabled_or_foreign_reads(self):
        registry = [entity('media_player.a'), entity('media_player.b', 'zone-b'),
            entity('button.sleep'), entity('media_player.disabled', disabled_by='user'),
            entity('media_player.blocked', device_id='disabled'), entity('media_player.foreign', 'other'),
            dict(entity('media_player.wrong_platform'), platform='sonos')]
        devices = [{'id': 'disabled', 'config_entries': ['zone-a'], 'disabled_by': 'user'}]
        calls = []
        def read(token, name): calls.append(name); return state(token, name)
        result = bluesound.collect(token='test', entries_fn=entries, registries_fn=lambda _: (registry, devices), read_fn=read)
        self.assertEqual(sorted(calls), ['media_player.a', 'media_player.b'])
        self.assertEqual(result['entity_count'], 5)
        self.assertEqual(result['disabled_count'], 2)
        self.assertEqual(result['unsupported_count'], 1)

    def test_unloaded_and_disabled_entries_never_read_retained_states(self):
        def inactive(_):
            return [dict(entries(None)[0], state='setup_retry'), dict(entries(None)[1], disabled_by='user')]
        forbidden = Mock(side_effect=AssertionError('No registry allowed'))
        result = bluesound.collect(token='test', entries_fn=inactive, registries_fn=forbidden)
        forbidden.assert_not_called()
        self.assertEqual(result['readings'], [])
        self.assertEqual(summarize('Bluesound', result)[0], 'review')

    def test_missing_integration_is_downloadable_and_unverified(self):
        result = bluesound.collect(token='test', entries_fn=lambda _: [])
        self.assertEqual(bluesound.report_payload(result)['format'], 'adr-bluesound-discovery-v1')
        self.assertEqual(summarize('Bluesound', result)[0], 'unverified')

    def test_entry_metadata_does_not_export_secrets_or_infer_from_names(self):
        raw = [dict(entries(None)[0], data={'password': 'private-secret'}),
            {'entry_id': 'other', 'domain': 'sonos', 'title': 'Bluesound'}]
        with patch('bluesound.get_json', return_value=raw): result = bluesound.entries('test')
        self.assertEqual(len(result), 1)
        self.assertNotIn('private-secret', str(result))

    def test_limits_are_global_across_players_and_diagnostics_first(self):
        registry = [entity('media_player.zone_' + str(i), 'zone-b') for i in range(140)] + [entity('sensor.temperature')]
        result = bluesound.collect(token='test', entries_fn=entries, registries_fn=lambda _: (registry, []), read_fn=state)
        self.assertEqual(len(result['readings']), 128)
        self.assertEqual(result['readings'][0]['entity_id'], 'sensor.temperature')
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['entity_inventory']), 141)

    def test_failed_reads_do_not_leak_exception_and_other_players_continue(self):
        def read(token, name):
            if name.endswith('.a'): raise RuntimeError('private-secret')
            return state(token, name)
        result = bluesound.collect(token='test', entries_fn=entries,
            registries_fn=lambda _: ([entity('media_player.a'), entity('media_player.b', 'zone-b')], []), read_fn=read)
        self.assertEqual([r['state'] for r in result['readings']], ['read failed', 'idle'])
        self.assertNotIn('private-secret', str(result))

    def test_state_get_only_allowlisted_attributes(self):
        raw = {'entity_id': 'media_player.zone', 'state': 'playing', 'attributes': {
            'volume_level': 0.25, 'is_volume_muted': False, 'source': 'Line In',
            'media_content_id': 'private-url', 'access_token': 'private-secret', 'media_title': 'private-title'}}
        with patch('crestron.get_json', return_value=raw) as get:
            result = bluesound.read_state('test', 'media_player.zone')
        get.assert_called_once_with('test', 'states/media_player.zone')
        self.assertEqual(result['attributes'], {'volume_level': 0.25, 'is_volume_muted': False, 'source': 'Line In'})

    def test_background_duplicate_jobs_and_html_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'options.json').write_text('{}')
            with patch('agent.collect_bluesound') as collect:
                pilot = Pilot(root, root / 'options.json'); collect.assert_not_called()
            with patch('agent.threading.Thread') as thread:
                pilot.start_bluesound_discovery(); pilot.start_bluesound_discovery()
                thread.assert_called_once(); job = thread.call_args.kwargs['target']
            result = bluesound.collect(token='test', entries_fn=entries, registries_fn=lambda _: ([entity('media_player.a')], []), read_fn=state)
            result['readings'][0]['name'] = '<script>bad</script>'
            with patch('agent.collect_bluesound', return_value=result): job()
            self.assertFalse(pilot.bluesound_running)
            self.assertIn('&lt;script&gt;bad&lt;/script&gt;', page(pilot))
            self.assertNotIn('<script>', page(pilot))

    def test_report_ingress_csrf_attachment(self):
        result = bluesound.collect(token='test', entries_fn=lambda _: [])
        for csrf, address, success in [('ok', '172.30.32.2', True), ('bad', '172.30.32.2', False), ('ok', '192.0.2.1', False)]:
            h = Handler.__new__(Handler); body = ('csrf=' + csrf).encode()
            h.server = SimpleNamespace(pilot=SimpleNamespace(lock=threading.Lock(), csrf='ok', bluesound=result, bluesound_running=False))
            h.client_address, h.path = (address, 123), '/bluesound-report'
            h.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/x-www-form-urlencoded'}
            h.rfile, h.wfile = io.BytesIO(body), io.BytesIO()
            h.send_response, h.send_header, h.end_headers, h.send_error = Mock(), Mock(), Mock(), Mock()
            h.do_POST()
            if success:
                self.assertTrue(json.loads(h.wfile.getvalue())['read_only'])
                h.send_header.assert_any_call('Content-Disposition', 'attachment; filename="ADR-Bluesound-Discovery.json"')
            else:
                self.assertEqual(h.send_error.call_args.args[0], 403)
                self.assertEqual(h.wfile.getvalue(), b'')


if __name__ == '__main__': unittest.main()
