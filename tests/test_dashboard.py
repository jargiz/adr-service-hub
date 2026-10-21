import io
import json
import sys
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
from agent import Pilot, Handler, ProtocolError, page
from dashboard import cards, key_readings, SYSTEMS
from service_report import assess, run_checks
from test_service_report import switch, processor


class DetailsParser(HTMLParser):
    def __init__(self): super().__init__(); self.depth = 0; self.articles = 0
    def handle_starttag(self, tag, attrs):
        if tag == 'details': self.depth += 1
        if tag == 'article': self.articles += 1
    def handle_endtag(self, tag):
        if tag == 'details':
            self.depth -= 1
            assert self.depth >= 0


class DashboardTests(unittest.TestCase):
    def test_invalid_volume_and_unsupported_cpu_are_limitations_not_service_faults(self):
        result = assess('Control4', {'entry': {'state': 'loaded'}, 'readings': [
            {'name': 'TV', 'state': 'idle', 'attributes': {'volume_level': -0.01}}]})
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['service_findings'], [])
        self.assertIn('invalid reported volume', str(result['data_limitations']))
        result = assess('CP4-R', dict(processor('Monday'), not_attempted=['CPULOAD: not advertised']))
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['service_findings'], [])
        self.assertIn('CPULOAD', str(result['data_limitations']))

    def test_unavailable_is_service_finding_unknown_is_data_limitation(self):
        snap = {'players': [{'name': 'Player', 'state': 'unavailable'}, {'name': 'Other', 'state': 'unknown'}]}
        result = assess('Sonos', snap)
        self.assertEqual(result['status'], 'review')
        self.assertIn('physical connectivity and cause remain unverified', str(result['service_findings']))
        self.assertIn('state unknown', str(result['data_limitations']))

    def test_history_is_target_scoped_and_cannot_suppress_discard_observation(self):
        history = [{'system': 'Araknis', 'target': 'a', 'recorded_at': 'test', 'subject': 'NVX', 'note': 'User confirmed normal operation'},
            {'system': 'Araknis', 'target': 'b', 'recorded_at': 'test', 'subject': 'Other', 'note': 'Other switch'}]
        _, baseline = run_checks([('Araknis', 'a', lambda: switch(100))], {})
        report, _ = run_checks([('Araknis', 'a', lambda: switch(200))], baseline, history=history)
        check = report['checks'][0]
        self.assertEqual(len(check['historical_observations']), 1)
        self.assertEqual(check['status'], 'review')
        self.assertEqual(check['service_findings'], [])
        html = cards(report)
        self.assertIn('Observations to review', html)
        self.assertIn('User confirmed normal operation', html)
        self.assertIn('increased by 100', html)
        self.assertNotIn('Other switch', html)

    def test_history_survives_restart_baselines_do_not_and_no_history_in_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); options = root / 'options.json'; options.write_text('{}')
            pilot = Pilot(root, options)
            with self.assertRaises(ProtocolError): pilot.add_service_history('Araknis', 'Port', 'Note')
            (root / 'araknis_known_hosts').write_text('approved-key')
            pilot.add_service_history('Araknis', '<port>', '<script>private-note</script>')
            loaded = Pilot(root, options)
            self.assertEqual(loaded.service_history, pilot.service_history)
            self.assertEqual(loaded.service_baselines, {})
            self.assertEqual((root / 'service_history.json').stat().st_mode & 0o777, 0o600)
            self.assertNotIn('private-note', (root / 'events.jsonl').read_text())
            self.assertIn('&lt;script&gt;private-note&lt;/script&gt;', page(loaded))
            for args in [('invalid', 'Port', 'Note'), ('Araknis', '', 'Note'), ('Araknis', 'Port', 'x' * 601)]:
                with self.assertRaises(ProtocolError): loaded.add_service_history(*args)

    def test_history_does_not_attach_to_old_target_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'options.json').write_text('{}'); (root / 'araknis_known_hosts').write_text('key')
            pilot = Pilot(root, root / 'options.json')
            target = pilot.service_jobs()[7][1]
            pilot.service_report, _ = run_checks([('Araknis', target, lambda: switch(1))], {})
            pilot.araknis_options['araknis_host'] = 'changed-switch'
            pilot.add_service_history('Araknis', 'NVX', 'Historical note')
            self.assertEqual(pilot.service_report['checks'][0]['historical_observations'], [])

    def test_nine_cards_escaped_values_and_balanced_details_on_all_page_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); options = root / 'options.json'; options.write_text('{}')
            pilot = Pilot(root, options)
            for configured in (False, True):
                if configured:
                    pilot.config = {'device_alias': 'Test', 'wattbox_host': 'test-host', 'ssh_port': 22, 'test_outlet': 11, 'expected_outlet_label': 'TV'}
                rendered = page(pilot)
                parser = DetailsParser(); parser.feed(rendered)
                self.assertEqual(parser.depth, 0)
                self.assertEqual(parser.articles, 9)
            report, _ = run_checks([('Sonos', 'a', lambda: {'players': [{'name': '<script>bad</script>', 'state': 'idle'}]})], {})
            rendered = cards(report)
            self.assertNotIn('<script>', rendered)
            self.assertIn('&lt;script&gt;bad&lt;/script&gt;', rendered)

    def test_key_readings_do_not_show_threshold_as_usage_or_failed_console_output(self):
        snap = {'readings': [{'command': 'show env all', 'status': 'response received', 'response':
            'RAM Threshold   Current RAM  Usage\n-------------   ------------------\n80% 65%\nCPU Threshold: 100%\nCurrent CPU Usage: 45%\nThermal 1 85C 35C'}]}
        self.assertEqual(key_readings('Araknis', snap), ['CPU 45%', 'RAM 65%', 'Thermal 1: 35C'])
        snap['readings'][0]['truncated'] = True
        self.assertEqual(key_readings('Araknis', snap), [])

    def test_history_post_requires_ingress_and_csrf(self):
        for csrf, address, ok in [('ok', '172.30.32.2', True), ('wrong', '172.30.32.2', False), ('ok', '192.0.2.1', False)]:
            pilot = SimpleNamespace(lock=threading.Lock(), csrf='ok', service_running=False, add_service_history=Mock())
            h = Handler.__new__(Handler); body = ('csrf=' + csrf + '&system=Araknis&subject=Port&note=Normal').encode()
            h.server, h.client_address, h.path = SimpleNamespace(pilot=pilot), (address, 123), '/service-history'
            h.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/x-www-form-urlencoded'}
            h.rfile, h.wfile, h.send_page, h.send_error = io.BytesIO(body), io.BytesIO(), Mock(), Mock()
            h.do_POST()
            if ok: pilot.add_service_history.assert_called_once_with('Araknis', 'Port', 'Normal')
            else:
                pilot.add_service_history.assert_not_called()
                self.assertEqual(h.send_error.call_args.args[0], 403)


if __name__ == '__main__': unittest.main()
