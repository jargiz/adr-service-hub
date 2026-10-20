import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
import paramiko
import araknis
from agent import Pilot, page


class AraknisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.options = {'araknis_host': '192.0.2.20', 'araknis_ssh_port': 22,
            'araknis_username': 'reader', 'araknis_password': 'private-test-password'}
        self.config = araknis.settings(self.options)
        self.keys = self.root / 'keys'
        self.keys.touch()

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_help_is_sent_and_client_closed(self):
        client = Mock()
        channel = client.invoke_shell.return_value
        responses = iter([('Switch>', False), ('show help', False)])
        result = araknis.inspect(self.config, self.keys, lambda: client, lambda _: next(responses))
        channel.sendall.assert_called_once_with(b'?')
        client.close.assert_called_once()
        self.assertIsInstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.RejectPolicy)
        self.assertFalse(client.connect.call_args.kwargs['allow_agent'])
        self.assertFalse(client.connect.call_args.kwargs['look_for_keys'])
        self.assertEqual(result['help'], 'show help')

    def test_identity_required_before_login(self):
        self.keys.unlink()
        factory = Mock()
        with self.assertRaises(araknis.AraknisError):
            araknis.inspect(self.config, self.keys, factory)
        factory.assert_not_called()

    def test_auth_failure_does_not_send_commands_or_leak_secret(self):
        client = Mock()
        client.connect.side_effect = paramiko.AuthenticationException('private-test-password')
        with self.assertRaises(araknis.AraknisError) as error:
            araknis.inspect(self.config, self.keys, lambda: client)
        client.invoke_shell.assert_not_called()
        client.close.assert_called_once()
        self.assertNotIn(self.config['password'], str(error.exception))

    def test_changed_key_rejected_without_shell(self):
        client = Mock()
        key = paramiko.RSAKey.generate(1024)
        client.connect.side_effect = paramiko.BadHostKeyException('test', key, key)
        with self.assertRaisesRegex(araknis.AraknisError, 'identity changed'):
            araknis.inspect(self.config, self.keys, lambda: client)
        client.invoke_shell.assert_not_called()
        client.close.assert_called_once()

    def test_response_size_bounded(self):
        channel = Mock()
        channel.recv_ready.return_value = True
        channel.recv.side_effect = lambda size: b'x' * size
        text, truncated = araknis.receive(channel)
        self.assertEqual(len(text), 32768)
        self.assertTrue(truncated)

    def test_pilot_no_startup_connection_optional_config_and_escaped_output(self):
        options = self.root / 'options.json'
        options.write_text(json.dumps(self.options))
        with patch('agent.inspect_araknis') as connect, patch('agent.inspect_key') as key:
            pilot = Pilot(self.root, options)
            connect.assert_not_called()
            key.assert_not_called()
        pilot.araknis = {'checked_at': 'test', 'welcome': '<script>alert(1)</script>',
            'help': 'help', 'truncated': False}
        rendered = page(pilot)
        self.assertIn('Araknis switch connection', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn(self.config['password'], rendered)

    def test_identity_nonce_expires_and_replay_rejected(self):
        options = self.root / 'options.json'
        options.write_text(json.dumps(self.options))
        pilot = Pilot(self.root, options)
        key = paramiko.RSAKey.generate(1024)
        with patch('agent.inspect_key', return_value=key):
            pilot.araknis_identity()
        nonce = pilot.araknis_candidate[0]
        pilot.araknis_trust(nonce)
        self.assertTrue((self.root / 'araknis_known_hosts').exists())
        with self.assertRaisesRegex(araknis.ProtocolError, 'expired'):
            pilot.araknis_trust(nonce)
        self.assertNotIn(self.config['password'], (self.root / 'events.jsonl').read_text())

    def test_rejects_invalid_target_and_port(self):
        for name, value in [('araknis_host', 'x/y'), ('araknis_ssh_port', 0), ('araknis_username', '')]:
            with self.assertRaises(araknis.AraknisError):
                araknis.settings(dict(self.options, **{name: value}))


if __name__ == '__main__':
    unittest.main()
