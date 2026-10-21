import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
from sense import add_history
from dashboard import grouped_cards
from dashboard_visuals import gauge, history_chart, network_panels
from unifi import speedtest_readings


class HistoryVisualTests(unittest.TestCase):
    def snapshot(self):
        return {'readings': [{'entity_id': 'sensor.l1', 'name': 'L1 Voltage', 'state': '120',
            'attributes': {'device_class': 'voltage', 'unit_of_measurement': 'V'}}],
            'entity_inventory': [{'entity_id': 'sensor.l1', 'state_read_supported': True}], 'limitations': []}

    def test_history_get_is_owned_bounded_and_preserves_unknown_gaps(self):
        now = datetime(2026, 10, 21, 3, tzinfo=timezone.utc)
        get = Mock(return_value=[[{'entity_id': 'sensor.l1', 'state': '120', 'last_changed': '2026-10-21T02:00:00+00:00'},
            {'state': 'unavailable', 'last_changed': '2026-10-21T02:01:00+00:00'},
            {'state': '121', 'last_changed': '2026-10-21T02:02:00+00:00'},
            {'state': '999', 'last_changed': '2027-10-21T02:02:00+00:00'}]])
        result = add_history(self.snapshot(), 'test', get_fn=get, now=now)
        self.assertEqual([p['value'] for p in result['history']['series'][0]['points']], [120, None, 121])
        token, url = get.call_args.args
        self.assertEqual(token, 'test')
        self.assertTrue(url.startswith('history/period/'))
        self.assertIn('filter_entity_id=sensor.l1', url)
        self.assertIn('no_attributes=1', url)
        self.assertNotIn('services/', url)
        output = history_chart(result['history']['series'][0])
        self.assertEqual(output.count('class="chart-point"'), 2)
        self.assertNotIn('class="chart-line"', output)

    def test_foreign_history_and_errors_do_not_leak_or_replace_current_values(self):
        for response in ([[{'entity_id': 'sensor.foreign', 'state': '120', 'last_changed': '2026-10-21T02:00:00+00:00'}]], {'error': 'private'}):
            snap = self.snapshot()
            result = add_history(snap, 'test', get_fn=lambda *_: response)
            self.assertEqual(result['readings'][0]['state'], '120')
            self.assertEqual(result['history']['series'][0]['status'], 'history unavailable')
            self.assertNotIn('private', str(result))
        snap = self.snapshot(); snap['entity_inventory'][0]['disabled_by'] = 'user'
        forbidden = Mock(side_effect=AssertionError('no foreign reads'))
        add_history(snap, 'test', get_fn=forbidden)
        forbidden.assert_not_called()

    def test_missing_history_and_invalid_gauges_are_not_zero_or_normal(self):
        for value in (None, 'unknown', 'unavailable', float('nan'), -1, 101, True):
            self.assertEqual(gauge('CPU', value), '')
        self.assertIn('17.3%', gauge('CPU', 17.3))
        self.assertIn('no history', history_chart({'name': '<script>x</script>', 'points': [], 'status': 'no history'}))
        self.assertNotIn('<script>', history_chart({'name': '<script>x</script>', 'points': []}))
        output = network_panels({})
        self.assertIn('Unverified', output)
        self.assertNotIn('0 Mbps', output)

    def test_grouped_dashboard_has_ten_systems_and_power_sense(self):
        output = grouped_cards(None)
        self.assertEqual(output.count('<article'), 10)
        self.assertIn('group-power', output)
        self.assertIn('Sense', output)
        self.assertIn('view-network', output)
        self.assertNotIn('<script', output)

    def test_speedtest_reads_only_existing_owned_enabled_sensors(self):
        entries = [{'entry_id': 'speed', 'domain': 'speedtestdotnet', 'state': 'loaded'},
            {'entry_id': 'disabled', 'domain': 'speedtestdotnet', 'state': 'loaded', 'disabled_by': 'user'}]
        registry = [{'entity_id': 'sensor.download', 'config_entry_id': 'speed', 'platform': 'speedtestdotnet'},
            {'entity_id': 'sensor.foreign', 'config_entry_id': 'other', 'platform': 'speedtestdotnet'},
            {'entity_id': 'button.run', 'config_entry_id': 'speed', 'platform': 'speedtestdotnet'},
            {'entity_id': 'sensor.disabled', 'config_entry_id': 'disabled', 'platform': 'speedtestdotnet'}]
        read = Mock(return_value={'name': 'Download', 'state': '800', 'attributes': {'unit_of_measurement': 'Mbit/s'}})
        output = speedtest_readings('test', get_fn=lambda *_: entries, registries_fn=lambda _: (registry, []), read_fn=read)
        read.assert_called_once_with('test', 'sensor.download')
        self.assertEqual(output[0]['unit'], 'Mbit/s')
        rendered = network_panels({'UniFi': {'snapshot': {'internet_readings': output}}})
        self.assertIn('800 Mbit/s', rendered)


if __name__ == '__main__': unittest.main()
