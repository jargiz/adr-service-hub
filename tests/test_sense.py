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
import sense
from agent import Pilot, Handler, page


def entry(_):
    return [{'entry_id': 'home', 'title': 'Home', 'domain': 'sense', 'state': 'loaded'}]


def entity(name, **extra):
    return dict(entity_id=name, config_entry_id='home', platform='sense', **extra)


def reading(_, name):
    return {'entity_id': name, 'name': name, 'state': '120.1', 'attributes': {'unit_of_measurement': 'V'}, 'last_updated': None}


class SenseTests(unittest.TestCase):
    def test_exact_ownership_disabled_entities_and_controls(self):
        registry = [entity('sensor.l1_voltage'), entity('sensor.disabled', disabled_by='user'),
            entity('sensor.blocked', device_id='disabled'), entity('switch.control'),
            dict(entity('sensor.foreign'), config_entry_id='other'),
            dict(entity('sensor.wrong'), platform='unifi')]
        devices = [{'id': 'disabled', 'config_entries': ['home'], 'disabled_by': 'user'}]
        read = Mock(side_effect=reading)
        result = sense.collect(token='test', entries_fn=entry, registries_fn=lambda _: (registry, devices), read_fn=read)
        read.assert_called_once_with('test', 'sensor.l1_voltage')
        self.assertEqual(result['entity_count'], 4)
        self.assertEqual(result['disabled_count'], 2)
        self.assertEqual(result['unsupported_count'], 1)

    def test_failed_integration_does_not_read_retained_states(self):
        forbidden = Mock(side_effect=AssertionError('No reads allowed'))
        result = sense.collect(token='test', entries_fn=lambda _: [dict(entry(None)[0], state='setup_retry')], registries_fn=forbidden)
        forbidden.assert_not_called()
        self.assertEqual(result['readings'], [])

    def test_state_units_metadata_only_and_no_secret_attributes(self):
        attrs = {'friendly_name': 'L1 Voltage', 'unit_of_measurement': 'V', 'state_class': 'measurement',
            'device_class': 'voltage', 'last_reset': None, 'token': 'private', 'raw_data': {'password': 'private'}}
        with patch('sense.get_json', return_value={'entity_id': 'sensor.l1_voltage', 'state': '120.1', 'attributes': attrs}) as get:
            result = sense.read_state('test', 'sensor.l1_voltage')
        get.assert_called_once_with('test', 'states/sensor.l1_voltage')
        self.assertNotIn('private', str(result))
        self.assertEqual(result['attributes']['unit_of_measurement'], 'V')
        with self.assertRaises(sense.SenseError): sense.read_state('test', 'switch.control')

    def test_read_limit_keeps_voltage_and_failures_do_not_leak(self):
        registry = [entity('sensor.device_'+str(i)) for i in range(140)]+[entity('sensor.l1_voltage')]
        def read(token, name):
            if name == 'sensor.l1_voltage': raise ValueError('private-token')
            return reading(token, name)
        result = sense.collect(token='test', entries_fn=entry, registries_fn=lambda _: (registry, []), read_fn=read)
        self.assertEqual(len(result['readings']), 128)
        self.assertEqual(result['readings'][0]['entity_id'], 'sensor.l1_voltage')
        self.assertEqual(result['readings'][0]['state'], 'read failed')
        self.assertNotIn('private-token', str(result))
        self.assertTrue(result['truncated'])

    def test_no_startup_reads_duplicate_job_guard_and_escaped_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'options.json').write_text('{}')
            with patch('agent.collect_sense') as collect:
                pilot = Pilot(root, root/'options.json'); collect.assert_not_called()
            with patch('agent.threading.Thread') as thread:
                pilot.start_sense_discovery(); pilot.start_sense_discovery()
                thread.assert_called_once(); job = thread.call_args.kwargs['target']
            result = sense.collect(token='test', entries_fn=entry, registries_fn=lambda _: ([entity('sensor.l1_voltage')], []), read_fn=reading)
            result['readings'][0]['name'] = '<script>bad</script>'
            with patch('agent.collect_sense', return_value=result): job()
            self.assertFalse(pilot.sense_running)
            self.assertIn('&lt;script&gt;bad&lt;/script&gt;', page(pilot))
            self.assertNotIn('<script>', page(pilot))

    def test_report_ingress_and_csrf(self):
        result = sense.collect(token='test', entries_fn=lambda _: [])
        for csrf, address, success in [('ok', '172.30.32.2', True), ('wrong', '172.30.32.2', False), ('ok', '192.0.2.1', False)]:
            h = Handler.__new__(Handler); body = ('csrf='+csrf).encode()
            h.server = SimpleNamespace(pilot=SimpleNamespace(lock=threading.Lock(), csrf='ok', sense=result, sense_running=False))
            h.client_address, h.path = (address, 123), '/sense-report'
            h.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/x-www-form-urlencoded'}
            h.rfile, h.wfile = io.BytesIO(body), io.BytesIO()
            h.send_response, h.send_header, h.end_headers, h.send_error = Mock(), Mock(), Mock(), Mock()
            h.do_POST()
            if success:
                self.assertEqual(json.loads(h.wfile.getvalue())['format'], 'adr-sense-discovery-v1')
                h.send_header.assert_any_call('Content-Disposition', 'attachment; filename="ADR-Sense-Discovery.json"')
            else:
                self.assertEqual(h.send_error.call_args.args[0], 403)
                self.assertEqual(h.wfile.getvalue(), b'')


if __name__ == '__main__': unittest.main()
