import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
import araknis
from agent import Handler, Pilot, ProtocolError


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.keys = self.root / 'keys'
        self.keys.touch()
        self.config = {'host': '192.0.2.20', 'port': 22, 'username': 'reader', 'password': 'test-secret'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_traverses_only_advertised_allowlisted_paths_and_executes_only_cr(self):
        calls = []
        def request(config, keys, command, factory, reader, help_only=False):
            calls.append((command, help_only))
            if not help_only:
                return 'System reading', False
            return {
                'show system': 'information      System details\nreload      Forbidden\npassword      Forbidden',
                'show system information': '<cr>      Execute command',
                'show env': 'all      All resources',
                'show env all': 'slot      Needs a numeric argument',
            }.get(command, 'No further syntax'), False
        with patch('araknis.diagnostic_request', side_effect=request):
            result = araknis.discover(self.config, self.keys)
        self.assertEqual([command for command, help_only in calls if not help_only], ['show system information'])
        self.assertEqual(len(result['readings']), 1)
        self.assertIn(('show env all', True), calls)
        self.assertNotIn(('show env all', False), calls)
        self.assertFalse(any('reload' in command or 'password' in command for command, _ in calls))

    def test_truncated_help_never_authorizes_execution(self):
        with patch('araknis.diagnostic_request', return_value=('<cr>    Execute', True)) as request:
            result = araknis.discover(self.config, self.keys)
        self.assertEqual(result['readings'], [])
        self.assertTrue(all(call.kwargs['help_only'] for call in request.call_args_list))

    def test_probe_count_and_read_count_are_bounded(self):
        with patch('araknis.diagnostic_request', return_value=('<cr>    Execute', False)) as request:
            result = araknis.discover(self.config, self.keys, max_probes=3, max_reads=1)
        self.assertEqual(len(result['discovery']['probes']), 3)
        self.assertEqual(len(result['readings']), 1)
        self.assertTrue(result['discovery']['limit_reached'])
        self.assertEqual(request.call_count, 4)

    def test_deadline_prevents_new_requests_and_preserves_limit(self):
        with patch('araknis.diagnostic_request') as request:
            result = araknis.discover(self.config, self.keys, deadline_seconds=-1)
        request.assert_not_called()
        self.assertTrue(result['discovery']['limit_reached'])
        self.assertEqual(result['discovery']['remaining_paths'], 5)

    def test_failures_preserved_without_secret_and_other_families_continue(self):
        with patch('araknis.diagnostic_request', side_effect=[RuntimeError('test-secret')] + [('no executable form', False)] * 4):
            result = araknis.discover(self.config, self.keys)
        self.assertEqual(len(result['discovery']['probes']), 5)
        self.assertTrue(result['discovery']['probes'][0]['error'])
        self.assertNotIn('test-secret', str(result))

    def test_discovery_rejects_control_config_and_injection_paths(self):
        for command in ['show running-config', 'show system password', 'show power reset',
                'show poe port reload', 'show env all;reload', 'show env all\rreload',
                'show interfaces status | include secret', 'configure terminal']:
            self.assertFalse(araknis.permitted_request(command), command)

    def test_export_redacts_nested_password_and_preserves_json(self):
        secret = 'quoted"secret\\value'
        payload = araknis.report_payload({'readings': [{'response': 'value ' + secret}],
            'discovery': {'probes': [{'response': secret}]}}, secret)
        data = json.loads(json.dumps(payload))
        self.assertEqual(data['snapshot']['readings'][0]['response'], 'value [redacted]')
        self.assertEqual(data['snapshot']['discovery']['probes'][0]['response'], '[redacted]')
        self.assertNotIn('options', data)
        self.assertTrue(data['read_only'])

    def pilot(self):
        path = self.root / 'options.json'
        path.write_text(json.dumps({'araknis_password': 'test-secret'}))
        pilot = Pilot(self.root, path)
        pilot.araknis_diagnostics = {'checked_at': 'test', 'readings': [{'response': 'test-secret'}]}
        return pilot

    def handler(self, pilot, csrf=None, address='172.30.32.2'):
        handler = Handler.__new__(Handler)
        body = ('csrf=' + (csrf or pilot.csrf)).encode()
        handler.server = SimpleNamespace(pilot=pilot)
        handler.client_address = (address, 123)
        handler.path = '/araknis-report'
        handler.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/x-www-form-urlencoded'}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.send_error = Mock()
        return handler

    def test_download_is_json_attachment_and_excludes_app_credentials(self):
        handler = self.handler(self.pilot())
        handler.do_POST()
        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call('Content-Disposition', 'attachment; filename="ADR-Araknis-Discovery.json"')
        handler.send_header.assert_any_call('Cache-Control', 'no-store')
        body = handler.wfile.getvalue()
        self.assertNotIn(b'test-secret', body)
        self.assertEqual(json.loads(body)['snapshot']['readings'][0]['response'], '[redacted]')

    def test_download_requires_ingress_and_csrf(self):
        for csrf, address in [('wrong', '172.30.32.2'), (None, '192.0.2.55')]:
            handler = self.handler(self.pilot(), csrf=csrf, address=address)
            handler.do_POST()
            self.assertEqual(handler.send_error.call_args.args[0], 403)
            self.assertEqual(handler.wfile.getvalue(), b'')

    def test_download_not_available_during_run_or_without_result(self):
        pilot = self.pilot()
        handler = self.handler(pilot)
        pilot.araknis_running = True
        with self.assertRaises(ProtocolError):
            handler.send_araknis_report()
        pilot.araknis_running = False
        pilot.araknis_diagnostics = None
        with self.assertRaises(ProtocolError):
            handler.send_araknis_report()


if __name__ == '__main__':
    unittest.main()
