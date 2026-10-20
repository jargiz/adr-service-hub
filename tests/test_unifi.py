import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
import unifi


def entries(_token, domain):
    assert domain == 'unifi'
    return [{'entry_id': 'network', 'title': 'Test network', 'state': 'loaded', 'disabled_by': None}]


def registries(_token):
    return [
        {'entity_id': 'sensor.gateway_cpu', 'device_id': 'gateway', 'config_entry_id': 'network', 'platform': 'unifi'},
        {'entity_id': 'sensor.gateway_temperature', 'device_id': 'gateway', 'config_entry_id': 'network', 'platform': 'unifi', 'disabled_by': 'integration'},
        {'entity_id': 'sensor.client_bandwidth', 'device_id': 'client', 'config_entry_id': 'network', 'platform': 'unifi'},
        {'entity_id': 'sensor.foreign', 'device_id': 'gateway', 'config_entry_id': 'other-network', 'platform': 'unifi'},
        {'entity_id': 'sensor.other_platform', 'device_id': 'gateway', 'config_entry_id': 'network', 'platform': 'other'},
        {'entity_id': 'button.gateway_restart', 'device_id': 'gateway', 'config_entry_id': 'network', 'platform': 'unifi'},
    ], [
        {'id': 'gateway', 'name': 'Test gateway', 'model': 'UCG-Fiber', 'config_entries': ['network']},
        {'id': 'client', 'name': 'Test client', 'config_entries': ['network']},
        {'id': 'foreign', 'name': 'Foreign device', 'config_entries': ['other-network']},
    ]


class UniFiTests(unittest.TestCase):
    def test_only_selected_entry_and_device_sensors_are_read(self):
        calls = []
        def read(_token, entity):
            calls.append(entity)
            return {'entity_id': entity, 'name': 'CPU', 'state': '16.6', 'unit': '%', 'last_updated': None}
        r = unifi.collect('network', 'gateway', token='test', entries_fn=entries, registries_fn=registries, read_fn=read)
        self.assertEqual(calls, ['sensor.gateway_cpu'])
        self.assertEqual(r['device']['id'], 'gateway')
        self.assertEqual(r['sensors'][0]['unit'], '%')
        self.assertEqual(r['disabled_sensors'], ['sensor.gateway_temperature'])

    def test_multiple_devices_require_selection_and_no_state_requests(self):
        def forbidden(*_): self.fail('No device was selected')
        r = unifi.collect(token='test', entries_fn=entries, registries_fn=registries, read_fn=forbidden)
        self.assertIsNone(r['device'])
        self.assertEqual(len(r['devices']), 2)

    def test_failed_or_disabled_entry_does_not_read_registry_or_stale_states(self):
        for state, disabled in [('setup_retry', None), ('loaded', 'user')]:
            def source(_token, domain):
                return [{'entry_id': 'network', 'state': state, 'disabled_by': disabled}]
            def forbidden(*_): self.fail('Inactive entry must not be queried')
            r = unifi.collect('network', 'gateway', token='test', entries_fn=source, registries_fn=forbidden, read_fn=forbidden)
            self.assertEqual(r['sensors'], [])

    def test_failed_sensor_remains_failed_and_secret_is_not_reported(self):
        def fail(*_): raise ValueError('private-token')
        r = unifi.collect('network', 'gateway', token='private-token', entries_fn=entries, registries_fn=registries, read_fn=fail)
        self.assertEqual(r['sensors'][0]['state'], 'read failed')
        self.assertNotIn('private-token', str(r))

    def test_no_control_or_tracker_requests(self):
        for entity in ('button.gateway_restart', 'switch.firewall', 'device_tracker.gateway', 'sensor.bad/../../'):
            with self.assertRaises(unifi.UniFiError):
                unifi.read_state('test', entity)

    def test_read_is_get_and_preserves_units(self):
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _):
                return json.dumps({'entity_id': 'sensor.latency', 'state': '3.5', 'last_updated': 'test-time',
                    'attributes': {'friendly_name': 'WAN latency', 'unit_of_measurement': 'ms'}}).encode()
        class Opener:
            def open(self, request, **kwargs):
                calls.append((request.method, request.full_url))
                return Response()
        with patch('unifi.build_opener', return_value=Opener()):
            result = unifi.read_state('test', 'sensor.latency')
        self.assertEqual(calls, [('GET', 'http://supervisor/core/api/states/sensor.latency')])
        self.assertEqual(result['unit'], 'ms')

    def test_no_integrations_returns_empty_discovery(self):
        r = unifi.collect(token='test', entries_fn=lambda *a, **k: [])
        self.assertIsNone(r['entry'])
        self.assertEqual(r['sensors'], [])


if __name__ == '__main__':
    unittest.main()
