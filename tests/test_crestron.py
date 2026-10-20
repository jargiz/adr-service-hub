import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
import crestron
from agent import Handler, Pilot, page


def entries(_):
    return [{'entry_id': 'home', 'domain': 'crestron_home', 'title': 'Pilot home',
        'state': 'loaded', 'disabled_by': None}]


def registries(_):
    return [
        {'entity_id': 'sensor.battery', 'config_entry_id': 'home', 'platform': 'crestron_home', 'device_id': 'processor'},
        {'entity_id': 'light.test', 'config_entry_id': 'home', 'platform': 'crestron_home', 'device_id': 'processor'},
        {'entity_id': 'sensor.disabled', 'config_entry_id': 'home', 'platform': 'crestron_home', 'disabled_by': 'integration'},
        {'entity_id': 'sensor.disabled_device', 'config_entry_id': 'home', 'platform': 'crestron_home', 'device_id': 'disabled'},
        {'entity_id': 'button.restart', 'config_entry_id': 'home', 'platform': 'crestron_home'},
        {'entity_id': 'sensor.other_entry', 'config_entry_id': 'other', 'platform': 'crestron_home'},
        {'entity_id': 'sensor.other_platform', 'config_entry_id': 'home', 'platform': 'unifi'},
    ], [
        {'id': 'processor', 'name': 'Pilot processor', 'model': 'CP4-R', 'sw_version': 'test-version', 'config_entries': ['home']},
        {'id': 'disabled', 'name': 'Disabled device', 'disabled_by': 'user', 'config_entries': ['home']},
        {'id': 'other', 'name': 'Not selected', 'config_entries': ['other']},
    ]


def state(_, entity_id):
    return {'entity_id': entity_id, 'name': entity_id, 'state': 'unavailable',
        'last_updated': 'test-time', 'attributes': {}}


class CrestronTests(unittest.TestCase):
    def test_selected_entry_platform_only_no_disabled_or_control_reads(self):
        calls = []
        def read(token, entity_id):
            calls.append(entity_id)
            return state(token, entity_id)
        result = crestron.collect(token='test', entries_fn=entries, registries_fn=registries, read_fn=read)
        self.assertEqual(calls, ['sensor.battery', 'light.test'])
        self.assertEqual(result['entity_count'], 5)
        self.assertEqual(result['disabled_count'], 2)
        self.assertEqual(result['unsupported_count'], 1)
        self.assertEqual(len(result['devices']), 2)
        self.assertEqual(result['devices'][0]['registry_sw_version'], 'test-version')
        self.assertEqual(result['readings'][0]['state'], 'unavailable')

    def test_multiple_entries_require_selection_and_stale_selection_not_replaced(self):
        multiple = lambda _: entries(None) + [{'entry_id': 'other', 'domain': 'crestron_home', 'state': 'loaded'}]
        def forbidden(*_): self.fail('No selected entry')
        for entry_id, source in [('', multiple), ('stale-id', entries)]:
            result = crestron.collect(entry_id, token='test', entries_fn=source, registries_fn=forbidden)
            self.assertIsNone(result['entry'])
            self.assertEqual(result['readings'], [])

    def test_failed_or_disabled_entry_never_reads_registry_or_states(self):
        def forbidden(*_): self.fail('Inactive entry must not read retained states')
        for status, disabled in [('setup_retry', None), ('loaded', 'user')]:
            source = lambda _: [dict(entries(None)[0], state=status, disabled_by=disabled)]
            result = crestron.collect(token='test', entries_fn=source, registries_fn=forbidden)
            self.assertEqual(result['readings'], [])

    def test_no_entries_returns_downloadable_discovery_without_registry(self):
        result = crestron.collect(token='test', entries_fn=lambda _: [])
        self.assertIsNone(result['entry'])
        self.assertEqual(crestron.report_payload(result)['format'], 'adr-crestron-discovery-v1')

    def test_state_read_is_get_and_excludes_unlisted_attributes(self):
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _):
                return json.dumps({'entity_id': 'climate.test', 'state': 'heat', 'last_updated': 'test-time',
                    'attributes': {'friendly_name': 'Test HVAC', 'current_temperature': 72,
                        'temperature': 70, 'connectionStatus': 'online', 'password': 'never-export',
                        'access_token': 'never-export', 'raw_device': {'token': 'never-export'}}}).encode()
        class Opener:
            def open(self, request, **kwargs):
                calls.append((request.method, request.full_url))
                return Response()
        with patch('crestron.build_opener', return_value=Opener()):
            result = crestron.read_state('test-token', 'climate.test')
        self.assertEqual(calls, [('GET', 'http://supervisor/core/api/states/climate.test')])
        self.assertEqual(result['attributes']['connectionStatus'], 'online')
        self.assertEqual(result['attributes']['current_temperature'], 72)
        self.assertNotIn('never-export', json.dumps(result))
        self.assertNotIn('test-token', json.dumps(result))

    def test_entity_ids_cannot_target_services_or_path_injection(self):
        with patch('crestron.get_json') as get:
            for entity_id in ('button.restart', 'scene.all_off', 'sensor.x/../../services',
                    'light.test?token=value', 'device_tracker.processor'):
                with self.assertRaises(crestron.CrestronError):
                    crestron.read_state('test', entity_id)
            get.assert_not_called()

    def test_config_entry_metadata_filters_by_domain_and_strips_credentials(self):
        raw = [dict(entries(None)[0], data={'token': 'never-export'}, options={'password': 'never-export'}),
            {'entry_id': 'foreign', 'domain': 'unifi', 'title': 'Crestron misleading title'},
            {'entry_id': 'another', 'domain': 'crestron_custom', 'state': 'loaded'}]
        with patch('crestron.get_json', return_value=raw) as get:
            result = crestron.entries('token')
        get.assert_called_once_with('token', 'config/config_entries/entry')
        self.assertEqual([item['entry_id'] for item in result], ['home', 'another'])
        self.assertNotIn('never-export', str(result))
        self.assertTrue(all('data' not in item and 'options' not in item for item in result))

    def test_read_failures_stay_failed_and_exception_secrets_are_not_exposed(self):
        def fail(*_): raise RuntimeError('private-token')
        result = crestron.collect(token='private-token', entries_fn=entries, registries_fn=registries, read_fn=fail)
        self.assertEqual(result['readings'][0]['state'], 'read failed')
        self.assertNotIn('private-token', json.dumps(result))

    def test_read_limit_prioritizes_diagnostics_and_inventory_is_retained(self):
        registry = [{'entity_id': 'light.load_' + str(i), 'config_entry_id': 'home', 'platform': 'crestron_home'} for i in range(140)]
        registry += [{'entity_id': 'sensor.battery', 'config_entry_id': 'home', 'platform': 'crestron_home'}]
        result = crestron.collect(token='test', entries_fn=entries,
            registries_fn=lambda _: (registry, []), read_fn=state)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['enabled_supported_count'], 141)
        self.assertEqual(len(result['readings']), 128)
        self.assertEqual(result['readings'][0]['entity_id'], 'sensor.battery')
        self.assertEqual(len(result['entity_inventory']), 141)

    def test_background_startup_and_duplicate_clicks_do_not_create_extra_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            options = root / 'options.json'
            options.write_text('{}')
            with patch('agent.collect_crestron') as collect:
                pilot = Pilot(root, options)
                collect.assert_not_called()
            with patch('agent.threading.Thread') as thread:
                pilot.start_crestron_discovery()
                pilot.start_crestron_discovery()
                thread.assert_called_once()
                job = thread.call_args.kwargs['target']
            result = crestron.collect(token='test', entries_fn=entries, registries_fn=registries, read_fn=state)
            with patch('agent.collect_crestron', return_value=result):
                job()
            self.assertFalse(pilot.crestron_running)
            self.assertEqual(pilot.crestron_selection, 'home')
            self.assertEqual(json.loads((root / 'crestron_selection.json').read_text()), {'entry_id': 'home'})
            self.assertNotIn('unavailable', (root / 'events.jsonl').read_text())
            pilot.crestron['readings'][0]['name'] = '<script>bad</script>'
            rendered = page(pilot)
            self.assertIn('&lt;script&gt;bad&lt;/script&gt;', rendered)
            self.assertNotIn('<script>', rendered)

    def test_report_requires_ingress_and_csrf_and_returns_attachment(self):
        result = crestron.collect(token='test', entries_fn=entries, registries_fn=registries, read_fn=state)
        pilot = SimpleNamespace(lock=__import__('threading').Lock(), csrf='test-csrf',
            crestron=result, crestron_running=False)
        for csrf, address, success in [('test-csrf', '172.30.32.2', True),
                ('wrong', '172.30.32.2', False), ('test-csrf', '192.0.2.90', False)]:
            handler = Handler.__new__(Handler)
            body = ('csrf=' + csrf).encode()
            handler.server = SimpleNamespace(pilot=pilot)
            handler.client_address = (address, 123)
            handler.path = '/crestron-report'
            handler.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/x-www-form-urlencoded'}
            handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
            handler.send_response, handler.send_header = Mock(), Mock()
            handler.end_headers, handler.send_error = Mock(), Mock()
            handler.do_POST()
            if success:
                handler.send_response.assert_called_once_with(200)
                handler.send_header.assert_any_call('Content-Disposition', 'attachment; filename="ADR-Crestron-Discovery.json"')
                payload = json.loads(handler.wfile.getvalue())
                self.assertTrue(payload['read_only'])
                self.assertEqual(payload['source'], 'existing_home_assistant_integration')
            else:
                self.assertEqual(handler.send_error.call_args.args[0], 403)
                self.assertEqual(handler.wfile.getvalue(), b'')


if __name__ == '__main__':
    unittest.main()
