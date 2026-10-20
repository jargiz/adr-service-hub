import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
import ruckus


def entries(_):
    return [{'entry_id': 'old-entry', 'title': 'OLD', 'state': 'setup_retry', 'disabled_by': None},
        {'entry_id': 'new-entry', 'title': 'CURRENT', 'state': 'loaded', 'disabled_by': None}]


def registry(_):
    return [
        {'entity_id': 'device_tracker.old', 'config_entry_id': 'old-entry', 'platform': 'ruckus_unleashed'},
        {'entity_id': 'device_tracker.new', 'config_entry_id': 'new-entry', 'platform': 'ruckus_unleashed'},
        {'entity_id': 'device_tracker.other', 'config_entry_id': 'new-entry', 'platform': 'other'},
        {'entity_id': 'device_tracker.disabled', 'config_entry_id': 'new-entry', 'platform': 'ruckus_unleashed', 'disabled_by': 'user'},
        {'entity_id': 'button.restart', 'config_entry_id': 'new-entry', 'platform': 'ruckus_unleashed'},
    ], [{'name': 'Current AP', 'model': 'Example', 'manufacturer': 'Ruckus', 'config_entries': ['new-entry']},
        {'name': 'Old AP', 'model': 'Example', 'config_entries': ['old-entry']}]


class RuckusTests(unittest.TestCase):
    def test_only_selected_entry_and_read_domains(self):
        calls = []
        def read(_token, entity):
            calls.append(entity)
            return {'entity_id': entity, 'state': 'home'}
        result = ruckus.collect('new-entry', token='test', entries_fn=entries, registries_fn=registry, read_fn=read)
        self.assertEqual(calls, ['device_tracker.new'])
        self.assertEqual([d['name'] for d in result['devices']], ['Current AP'])

    def test_failed_entry_does_not_read_stale_entities(self):
        def forbidden(*_):
            self.fail('Failed entry must not fetch entity states or registry')
        result = ruckus.collect('old-entry', token='test', entries_fn=entries, registries_fn=forbidden, read_fn=forbidden)
        self.assertEqual(result['entities'], [])
        self.assertEqual(result['entry']['state'], 'setup_retry')

    def test_disabled_entry_does_not_read_states(self):
        disabled = lambda _: [{'entry_id': 'disabled', 'state': 'loaded', 'disabled_by': 'user'}]
        with patch('ruckus.registries', side_effect=AssertionError):
            result = ruckus.collect('disabled', token='test', entries_fn=disabled)
        self.assertEqual(result['entities'], [])

    def test_unknown_entry_rejected(self):
        with self.assertRaises(ruckus.RuckusError):
            ruckus.collect('invented', token='test', entries_fn=entries)

    def test_failed_state_is_unknown_not_away_and_secret_not_returned(self):
        def fail(*_):
            raise RuntimeError('secret-token')
        result = ruckus.collect('new-entry', token='secret-token', entries_fn=entries, registries_fn=registry, read_fn=fail)
        self.assertEqual(result['entities'][0]['state'], 'read failed')
        self.assertNotIn('secret-token', str(result))

    def test_controls_cannot_be_read_as_diagnostics(self):
        with self.assertRaises(ruckus.RuckusError):
            ruckus.read_state('test', 'button.restart')


if __name__ == '__main__':
    unittest.main()
