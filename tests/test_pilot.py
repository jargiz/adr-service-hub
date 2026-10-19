import copy
import json
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
from agent import Pilot, ProtocolError, page
from wattbox import WattBox, parse_inventory, pin_key
import paramiko


def inventory(label='Apple TV'):
    names = ','.join('{' + (label if i == 11 else 'Other') + '}' for i in range(1, 19))
    return parse_inventory('WB-800VPS-IPVM-18', '2.10.0.0', '18', names, ','.join(['1'] * 18))


class FakeBox:
    def __init__(self, inv):
        self.inv = inv
        self.resets = []
        self.fail = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def inventory(self):
        return copy.deepcopy(self.inv)

    def reset(self, outlet):
        self.resets.append(outlet)
        if self.fail:
            raise TimeoutError()


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.responses = b''

    def sendall(self, command):
        self.sent.append(command)
        if command == b'?OutletStatus\n':
            self.responses = b'~OutletStatus=0,0\r\n?OutletStatus\r\n?OutletStatus=1,0\r\n'
        elif command == b'!OutletSet=11,RESET\n':
            self.responses = b'!OutletSet=11,RESET\r\n~OutletStatus=0,0\r\nOK\r\n'

    def recv(self, size):
        if not self.responses:
            raise socket.timeout()
        result, self.responses = self.responses[:size], self.responses[size:]
        return result

    def recv_ready(self):
        return bool(self.responses)


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.options = self.root / 'options.json'
        self.config = {'wattbox_host': '192.0.2.10', 'ssh_port': 22, 'username': 'test',
            'password': 'not-a-real-secret', 'test_outlet': 11, 'expected_outlet_label': 'Apple TV',
            'device_alias': 'Test Apple TV', 'allow_reboot': True}
        self.options.write_text(json.dumps(self.config))
        self.fake = FakeBox(inventory())
        self.pilot = Pilot(self.root, self.options, lambda *_: self.fake)
        (self.root / 'known_hosts').touch()

    def tearDown(self):
        self.tmp.cleanup()

    def test_inventory_count_and_one_based_mapping(self):
        self.assertEqual(inventory()['outlets'][10]['number'], 11)
        self.assertEqual(inventory()['outlets'][10]['label'], 'Apple TV')
        with self.assertRaises(ProtocolError):
            parse_inventory('model', 'fw', '18', '{one}', '1')
        with self.assertRaises(ProtocolError):
            parse_inventory('model', 'fw', '1', '{one}', '2')

    def test_startup_does_not_connect_or_reboot(self):
        self.assertEqual(self.fake.resets, [])
        self.assertIsNone(self.pilot.inventory)

    def test_read_only_default(self):
        self.pilot.config['allow_reboot'] = False
        self.assertIsNone(self.pilot.check())
        with self.assertRaises(ProtocolError):
            self.pilot.reboot('anything')
        self.assertEqual(self.fake.resets, [])

    def test_confirmed_reboot_only_target_and_no_replay(self):
        nonce = self.pilot.check()
        with patch('agent.threading.Thread'):
            self.pilot.reboot(nonce)
        self.assertEqual(self.fake.resets, [11])
        with self.assertRaises(ProtocolError):
            self.pilot.reboot(nonce)

    def test_label_change_blocks_reboot(self):
        nonce = self.pilot.check()
        self.fake.inv['outlets'][10]['label'] = 'Network switch'
        with self.assertRaises(ProtocolError):
            self.pilot.reboot(nonce)
        self.assertEqual(self.fake.resets, [])

    def test_off_outlet_blocks_reboot(self):
        self.fake.inv['outlets'][10]['on'] = False
        self.assertIsNone(self.pilot.check())

    def test_expired_confirmation(self):
        nonce = self.pilot.check()
        _, inv = self.pilot.confirmations[nonce]
        self.pilot.confirmations[nonce] = (time.monotonic() - 121, inv)
        with self.assertRaises(ProtocolError):
            self.pilot.reboot(nonce)

    def test_unknown_result_is_not_retried_and_cooldown_survives_restart(self):
        self.fake.fail = True
        nonce = self.pilot.check()
        with self.assertRaises(TimeoutError):
            self.pilot.reboot(nonce)
        restarted = Pilot(self.root, self.options, lambda *_: self.fake)
        second = restarted.check()
        with self.assertRaises(ProtocolError):
            restarted.reboot(second)
        self.assertEqual(self.fake.resets, [11])

    def test_corrupt_saved_state_blocks_power(self):
        (self.root / 'reboot_state.json').write_text('bad json')
        pilot = Pilot(self.root, self.options, lambda *_: self.fake)
        with self.assertRaises(ProtocolError):
            pilot.reboot(pilot.check())
        self.assertEqual(self.fake.resets, [])

    def test_no_secret_in_html_or_log(self):
        self.pilot.check()
        rendered = page(self.pilot)
        events = (self.root / 'events.jsonl').read_text()
        self.assertNotIn(self.config['password'], rendered + events)
        self.fake.inv['outlets'][0]['label'] = '<script>alert(1)</script>'
        self.pilot.check()
        self.assertNotIn('<script>', page(self.pilot))

    def test_missing_pin_blocks_credentials(self):
        (self.root / 'known_hosts').unlink()
        with self.assertRaises(ProtocolError):
            self.pilot.check()

    def test_changed_ssh_key_rejected(self):
        key1 = paramiko.RSAKey.generate(1024)
        key2 = paramiko.RSAKey.generate(1024)
        path = self.root / 'known_hosts'
        pin_key(path, '192.0.2.10', 22, key1)
        with self.assertRaises(ProtocolError):
            pin_key(path, '192.0.2.10', 22, key2)

    def test_ascii_commands_and_unsolicited_updates(self):
        box = WattBox(self.config, self.root / 'known_hosts')
        box.channel = FakeChannel()
        self.assertEqual(box.query('OutletStatus'), '1,0')
        box.reset(11)
        self.assertEqual(box.channel.sent, [b'?OutletStatus\n', b'!OutletSet=11,RESET\n'])
        for invalid in (0, -1, 19, '11', True):
            with self.assertRaises(ValueError):
                box.reset(invalid)


if __name__ == '__main__':
    unittest.main()
