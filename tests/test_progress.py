import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))

from agent import Pilot, Handler, page, service_progress_panel
from service_report import run_checks, SkipCheck


class ProgressTests(unittest.TestCase):
    def test_finished_failed_and_skipped_reads_all_advance_once(self):
        events = []
        def fail(): raise RuntimeError('private-error')
        def skip(): raise SkipCheck('Not configured')
        report, _ = run_checks([('WattBox', 'a', lambda: {'outlets': []}),
            ('Sonos', 'b', fail), ('Sense', 'c', skip)], {},
            progress=lambda name: events.append(('start', name)),
            completed=lambda name, status: events.append(('done', name, status)))
        self.assertEqual(events, [('start', 'WattBox'), ('done', 'WattBox', 'verified'),
            ('start', 'Sonos'), ('done', 'Sonos', 'unverified'), ('start', 'Sense'), ('done', 'Sense', 'unverified')])
        self.assertEqual(len(report['checks']), 3)

    def test_running_page_refreshes_via_get_and_completed_page_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'options.json').write_text('{}')
            pilot = Pilot(root, root/'options.json')
            self.assertNotIn('<meta name="adr-refresh"', page(pilot))
            pilot.service_running = True
            pilot.service_progress = 'Checking Sense'
            pilot.service_steps = {'WattBox': 'verified', 'Sense': 'checking'}
            rendered = page(pilot)
            self.assertIn('<meta name="adr-refresh" content="3">', rendered)
            self.assertIn('1 of 2 checks finished', rendered)
            self.assertIn('Checking Sense', rendered)
            self.assertIn('value="1"', rendered)
            self.assertIn('disabled>Checks running', rendered)
            self.assertEqual(urljoin('https://ha.example/api/hassio_ingress/session/service-check', './'),
                'https://ha.example/api/hassio_ingress/session/')
            pilot.service_running = False
            pilot.service_report, _ = run_checks([('WattBox', 'a', lambda: {'outlets': []}),
                ('Sense', 'b', lambda: {'entries': [], 'readings': []})], {})
            rendered = page(pilot)
            self.assertNotIn('<meta name="adr-refresh"', rendered)
            self.assertIn('Check complete', rendered)
            self.assertIn('2 of 2 checks finished', rendered)
            self.assertIn('Unverified', rendered)
            pilot.service_report = None
            pilot.service_error = 'Stopped'
            self.assertIn('Checks stopped', page(pilot))
            self.assertNotIn('<meta name="adr-refresh"', page(pilot))

    def test_refresh_get_never_starts_or_restarts_device_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'options.json').write_text('{}')
            pilot = Pilot(root, root/'options.json')
            pilot.service_running = True
            handler = Handler.__new__(Handler)
            handler.path = '/'
            handler.server = Mock(pilot=pilot)
            handler.authorized = Mock(return_value=True)
            handler.send_page = Mock()
            with patch.object(pilot, 'start_service_checks') as start:
                handler.do_GET(); handler.do_GET()
                start.assert_not_called()
            self.assertEqual(handler.send_page.call_count, 2)


if __name__ == '__main__': unittest.main()
