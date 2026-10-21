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
from service_report import run_checks, summarize, metrics, SkipCheck
from agent import Pilot, Handler, ProtocolError, page
from test_pilot import FakeBox, inventory
import unifi
from test_unifi import entries, registries


def switch(value, partial=False):
    return {'readings': [{'command': 'show interfaces', 'status': 'response received',
        'truncated': partial, 'ports': [{'port': 'Gi0/1', 'rx_discards': value}]}]}


def processor(start, partial=False):
    return {'model_verified': True, 'readings': [{'command': 'UPTIME', 'status': 'response received',
        'truncated': partial, 'response': 'The system last started on: ' + start}]}


class ServiceReportTests(unittest.TestCase):
    def test_failure_continues_and_exception_secrets_never_leak(self):
        calls = []
        def fail():
            calls.append('fail')
            raise ValueError('private-secret')
        def good():
            calls.append('good')
            return {'outlets': [], 'firmware': 'contains-private-secret', 'password': 'private-secret'}
        report, _ = run_checks([('Control4', '', fail), ('WattBox', '', good)], {}, secrets=('private-secret',))
        self.assertEqual(calls, ['fail', 'good'])
        self.assertEqual(report['counts'], {'verified': 1, 'review': 0, 'unverified': 1})
        self.assertIsNone(report['checks'][0]['snapshot'])
        self.assertNotIn('private-secret', json.dumps(report))
        self.assertNotIn('password', report['checks'][1]['snapshot'])
        self.assertIsNotNone(report['checks'][0]['completed_at'])

    def test_counter_delta_decrease_and_changed_target(self):
        _, baseline = run_checks([('Araknis', 'switch-a', lambda: switch(100))], {})
        report, baseline2 = run_checks([('Araknis', 'switch-a', lambda: switch(125))], baseline)
        self.assertIn('increased by 25', str(report))
        self.assertEqual(report['checks'][0]['status'], 'review')
        report, _ = run_checks([('Araknis', 'switch-a', lambda: switch(5))], baseline2)
        self.assertIn('wrap or reset', str(report))
        self.assertNotIn('increased by -', str(report))
        report, _ = run_checks([('Araknis', 'switch-b', lambda: switch(500))], baseline2)
        self.assertIn('Baseline established', str(report))
        self.assertEqual(baseline[('Araknis', 'switch-a')]['rx_discards:Gi0/1'], 100)

    def test_partial_and_failed_reads_do_not_replace_comparison_baseline(self):
        _, baseline = run_checks([('Araknis', 'a', lambda: switch(100))], {})
        report, next_base = run_checks([('Araknis', 'a', lambda: switch(900, True))], baseline)
        self.assertEqual(next_base, baseline)
        self.assertEqual(report['checks'][0]['status'], 'verified')
        def fail(): raise TimeoutError()
        report, next_base = run_checks([('Araknis', 'a', fail)], baseline)
        self.assertEqual(next_base, baseline)
        self.assertIsNone(report['checks'][0]['snapshot'])

    def test_processor_start_changes_with_clock_caveat_and_partial_skipped(self):
        _, baseline = run_checks([('CP4-R', 'a', lambda: processor('Monday at 10:00'))], {})
        report, _ = run_checks([('CP4-R', 'a', lambda: processor('Tuesday at 10:00'))], baseline)
        self.assertIn('possible processor/program restart or clock adjustment', str(report))
        self.assertEqual(metrics('CP4-R', processor('Tuesday', True)), {})

    def test_off_idle_are_valid_unknown_and_invalid_volume_need_review(self):
        entry = {'state': 'loaded'}
        for state, status in [('off', 'verified'), ('idle', 'verified'), ('unavailable', 'review'), ('read failed', 'review')]:
            actual, _ = summarize('Control4', {'entry': entry, 'readings': [{'state': state}]})
            self.assertEqual(actual, status)
        actual, notes = summarize('Control4', {'entry': entry, 'readings': [{'attributes': {'volume_level': -0.01}}]})
        self.assertEqual(actual, 'verified')
        self.assertIn('treat as unknown', str(notes))
        self.assertEqual(summarize('Control4', {'entry': None})[0], 'unverified')
        self.assertEqual(summarize('Control4', {'entry': {'state': 'setup_retry'}})[0], 'review')

    def test_no_startup_jobs_duplicate_clicks_and_refreshable_escaped_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'options.json').write_text('{}')
            with patch('agent.run_checks') as run:
                pilot = Pilot(root, root / 'options.json')
                run.assert_not_called()
            with patch('agent.threading.Thread') as thread:
                pilot.start_service_checks()
                pilot.start_service_checks()
                thread.assert_called_once()
                job = thread.call_args.kwargs['target']
            # The captured job receives injected readers, so it cannot use the LAN.
            report, baseline = run_checks([('WattBox', '', lambda: {'outlets': []})], {})
            report['checks'][0]['observations'].append('<script>bad</script>')
            with patch('agent.run_checks', return_value=(report, baseline)):
                job()
            self.assertFalse(pilot.service_running)
            self.assertEqual(pilot.service_report, report)
            self.assertIn('&lt;script&gt;bad&lt;/script&gt;', page(pilot))
            self.assertNotIn('<script>', page(pilot))
            restarted = Pilot(root, root / 'options.json')
            self.assertEqual(restarted.service_baselines, {})
            self.assertIsNone(restarted.service_report)
            self.assertNotIn('outlets', (root / 'events.jsonl').read_text())

    def test_wattbox_suite_is_inventory_only_no_confirmation_or_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'options.json').write_text('{}')
            box = FakeBox(inventory())
            pilot = Pilot(root, root / 'options.json', box_factory=lambda *_: box)
            pilot.config = {'allow_reboot': True}
            (root / 'known_hosts').write_text('approved-test-key')
            jobs = pilot.service_jobs()
            self.assertEqual([j[0] for j in jobs], ['WattBox', 'Sonos', 'Bluesound', 'Ruckus', 'UniFi', 'Crestron', 'Control4', 'Araknis', 'CP4-R', 'Sense'])
            report, _ = run_checks(jobs[:1], {})
            self.assertEqual(report['checks'][0]['status'], 'verified')
            self.assertEqual(box.resets, [])
            self.assertEqual(pilot.confirmations, {})
            self.assertIsNone(pilot.inventory)
            with self.assertRaises(SkipCheck): jobs[3][2]()
            with self.assertRaises(SkipCheck): jobs[7][2]()
            with self.assertRaises(SkipCheck): jobs[8][2]()

    def test_all_nine_readers_run_with_saved_selections_and_approved_keys(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'options.json').write_text('{}')
            box = FakeBox(inventory())
            pilot = Pilot(root, root / 'options.json', box_factory=lambda *_: box)
            pilot.config = {'allow_reboot': True}
            for filename in ('known_hosts', 'araknis_known_hosts', 'cp4_known_hosts'):
                (root / filename).write_text('approved-test-key')
            pilot.ruckus_selection = 'ruckus-current'
            pilot.unifi_selection = {'entry_id': 'network', 'device_id': 'gateway'}
            pilot.crestron_selection, pilot.control4_selection = 'home', 'core'
            def ha(entry, field):
                return {'entry': {'entry_id': entry, 'state': 'loaded'}, field: [{'state': 'off'}]}
            with ExitStack() as stack:
                stack.enter_context(patch('agent.collect_sense', return_value={'entries': [{'state': 'loaded'}], 'readings': [{'state': '120', 'attributes': {'unit_of_measurement': 'V'}}]}))
                stack.enter_context(patch('agent.collect_bluesound', return_value={'entries': [{'state': 'loaded'}], 'readings': [{'state': 'idle'}]}))
                sonos = stack.enter_context(patch('agent.collect_sonos', return_value={'players': [{'state': 'idle'}]}))
                ruckus = stack.enter_context(patch('agent.collect_ruckus', return_value=ha('ruckus-current', 'entities')))
                uni = ha('network', 'sensors'); uni['device'] = {'id': 'gateway'}
                unifi_read = stack.enter_context(patch('agent.collect_unifi', return_value=uni))
                stack.enter_context(patch('agent.collect_crestron', return_value=ha('home', 'readings')))
                control4 = stack.enter_context(patch('agent.collect_control4', return_value=ha('core', 'readings')))
                stack.enter_context(patch('agent.araknis_settings', return_value={'host': 'switch'}))
                stack.enter_context(patch('agent.cp4_settings', return_value={'host': 'processor'}))
                araknis = stack.enter_context(patch('agent.discover_araknis', return_value=switch(100)))
                cp4 = stack.enter_context(patch('agent.collect_cp4', return_value=processor('Monday')))
                report, baselines = run_checks(pilot.service_jobs(), {})
                self.assertEqual(report['counts'], {'verified': 10, 'review': 0, 'unverified': 0})
                sonos.assert_called_once_with()
                ruckus.assert_called_once_with('ruckus-current')
                unifi_read.assert_called_once_with('network', 'gateway')
                control4.assert_called_once_with('core')
                araknis.assert_called_once_with({'host': 'switch'}, root / 'araknis_known_hosts')
                cp4.assert_called_once_with({'host': 'processor'}, root / 'cp4_known_hosts')
                self.assertEqual(len(baselines), 2)
                self.assertEqual(box.resets, [])
                old_target = pilot.service_jobs()[7][1]
                pilot.araknis_options['araknis_host'] = 'another-switch'
                self.assertNotEqual(pilot.service_jobs()[7][1], old_target)

    def test_busy_individual_check_blocks_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'options.json').write_text('{}')
            pilot = Pilot(root, root / 'options.json')
            pilot.cp4_running = True
            with patch('agent.threading.Thread') as thread:
                with self.assertRaises(ProtocolError): pilot.start_service_checks()
                thread.assert_not_called()

    def test_report_ingress_csrf_and_active_run_guards(self):
        report, _ = run_checks([], {})
        for csrf, address, running, expected in [('ok', '172.30.32.2', False, 200),
                ('bad', '172.30.32.2', False, 403), ('ok', '192.0.2.90', False, 403),
                ('ok', '172.30.32.2', True, 400)]:
            h = Handler.__new__(Handler)
            body = ('csrf=' + csrf).encode()
            h.server = SimpleNamespace(pilot=SimpleNamespace(lock=threading.Lock(), csrf='ok', service_report=report, service_running=running))
            h.client_address, h.path = (address, 123), '/service-report'
            h.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/x-www-form-urlencoded'}
            h.rfile, h.wfile = io.BytesIO(body), io.BytesIO()
            h.send_response, h.send_header, h.end_headers, h.send_error, h.send_page = Mock(), Mock(), Mock(), Mock(), Mock()
            h.do_POST()
            if expected == 200:
                self.assertEqual(json.loads(h.wfile.getvalue())['format'], 'adr-service-report-v1')
                h.send_header.assert_any_call('Content-Disposition', 'attachment; filename="ADR-Service-Report.json"')
            elif expected == 403:
                self.assertEqual(h.send_error.call_args.args[0], 403)
            else:
                self.assertEqual(h.send_page.call_args.args[0], 400)

    def test_suite_blocks_device_actions_during_run(self):
        h = Handler.__new__(Handler)
        pilot = SimpleNamespace(lock=threading.Lock(), csrf='ok', service_running=True, reboot=Mock())
        h.server = SimpleNamespace(pilot=pilot)
        h.client_address, h.path = ('172.30.32.2', 123), '/reboot'
        body = b'csrf=ok&confirm=yes&nonce=test'
        h.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/x-www-form-urlencoded'}
        h.rfile, h.wfile = io.BytesIO(body), io.BytesIO()
        h.send_page = Mock()
        h.do_POST()
        pilot.reboot.assert_not_called()
        self.assertEqual(h.send_page.call_args.args[0], 400)

    def test_stale_unifi_selection_cannot_read_another_target(self):
        forbidden = Mock(side_effect=AssertionError('Wrong target read'))
        result = unifi.collect('stale', token='test', entries_fn=entries, registries_fn=forbidden)
        self.assertIsNone(result['entry'])
        forbidden.assert_not_called()
        def one_device(token):
            entities, devices = registries(token)
            return entities, devices[:1]
        result = unifi.collect('network', 'stale', token='test', entries_fn=entries, registries_fn=one_device, read_fn=forbidden)
        self.assertIsNone(result['device'])
        forbidden.assert_not_called()


if __name__ == '__main__':
    unittest.main()
