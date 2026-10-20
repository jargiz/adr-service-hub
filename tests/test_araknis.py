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
        channel.sendall.assert_called_once_with(b'show ?')
        client.close.assert_called_once()
        self.assertIsInstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.RejectPolicy)
        self.assertFalse(client.connect.call_args.kwargs['allow_agent'])
        self.assertFalse(client.connect.call_args.kwargs['look_for_keys'])
        self.assertEqual(result['help'], 'show help')

    def test_pager_advances_only_after_explicit_marker(self):
        channel = Mock()
        replies = iter([('first --More--', False), ('second --More--', False), ('last', False)])
        text, truncated = araknis.show_help(channel, lambda _: next(replies))
        self.assertEqual([call.args[0] for call in channel.sendall.call_args_list], [b'show ?', b' ', b' '])
        self.assertIn('last', text)
        self.assertFalse(truncated)

    def test_pager_bounded_even_if_switch_never_stops(self):
        channel = Mock()
        text, truncated = araknis.show_help(channel, lambda _: ('next --More--', False))
        self.assertTrue(truncated)
        self.assertEqual(channel.sendall.call_count, 8)
        self.assertEqual(len(text.splitlines()), 8)

    def test_no_pager_space_for_error_or_embedded_marker(self):
        channel = Mock()
        araknis.show_help(channel, lambda _: ('--More-- is not a pager here\n(switch)#', False))
        channel.sendall.assert_called_once_with(b'show ?')

    def test_help_output_total_bound(self):
        channel = Mock()
        text, truncated = araknis.show_help(channel, lambda _: ('x' * 20000 + '--More--', False))
        self.assertTrue(truncated)
        self.assertLessEqual(len(text), 32769)
        self.assertEqual(channel.sendall.call_count, 2)

    def test_query_rejects_arbitrary_commands_before_opening_channel(self):
        client = Mock()
        for command in ('reload', 'configure', 'show running-config', 'show system; reload', 'show poe\rreload'):
            with self.assertRaises(araknis.AraknisError):
                araknis.query(client, command)
        client.invoke_shell.assert_not_called()

    def test_query_requires_prompt_and_closes_channel(self):
        client = Mock()
        channel = client.invoke_shell.return_value
        with self.assertRaisesRegex(araknis.AraknisError, 'prompt'):
            araknis.query(client, 'show system', lambda _: ('Select a menu item:', False))
        channel.sendall.assert_not_called()
        channel.close.assert_called_once()

    def test_snapshot_uses_six_fixed_commands_on_fresh_channels(self):
        client = Mock()
        channels = [Mock() for _ in range(6)]
        client.invoke_shell.side_effect = channels
        responses = iter([reply for _ in range(6) for reply in [('(switch)#', False), ('test reading\n(switch)#', False)]])
        result = araknis.snapshot(self.config, self.keys, lambda: client, lambda _: next(responses))
        for channel, (_, command) in zip(channels, araknis.DIAGNOSTIC_COMMANDS):
            channel.sendall.assert_called_once_with((command + '\r').encode())
            channel.close.assert_called_once()
        self.assertEqual(len(result['readings']), 6)
        client.close.assert_called_once()
        self.assertIsInstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.RejectPolicy)

    def test_incomplete_command_requests_only_its_context_help(self):
        client = Mock()
        with patch('araknis.query', side_effect=[('% Incomplete command', False), ('usage text', False)] * 6) as query:
            result = araknis.snapshot(self.config, self.keys, lambda: client)
        self.assertEqual(query.call_count, 12)
        for n, (_, command) in enumerate(araknis.DIAGNOSTIC_COMMANDS):
            self.assertEqual(query.call_args_list[2*n].args[1], command)
            self.assertTrue(query.call_args_list[2*n+1].kwargs['help_only'])
            self.assertEqual(query.call_args_list[2*n+1].args[1], command)
        self.assertEqual(result['readings'][0]['status'], 'command needs verification')
        self.assertEqual(result['readings'][0]['help'], 'usage text')

    def test_snapshot_redacts_password_and_preserves_failed_reads(self):
        client = Mock()
        replies = [(self.config['password'], False)] + [RuntimeError(self.config['password'])] * 5
        with patch('araknis.query', side_effect=replies):
            result = araknis.snapshot(self.config, self.keys, lambda: client)
        self.assertNotIn(self.config['password'], str(result))
        self.assertEqual(result['readings'][1]['status'], 'read failed')
        self.assertEqual(result['readings'][1]['response'], '')

    def test_background_single_job_no_stale_readings_after_failure(self):
        options = self.root / 'options.json'
        options.write_text(json.dumps(self.options))
        pilot = Pilot(self.root, options)
        (self.root / 'araknis_known_hosts').touch()
        pilot.araknis_diagnostics = {'old': 'snapshot'}
        with patch('agent.threading.Thread') as thread:
            pilot.start_araknis_diagnostics()
            pilot.start_araknis_diagnostics()
            thread.assert_called_once()
            self.assertTrue(pilot.araknis_running)
            self.assertIsNone(pilot.araknis_diagnostics)
            job = thread.call_args.kwargs['target']
        with patch('agent.araknis_snapshot', side_effect=RuntimeError(self.config['password'])):
            job()
        self.assertFalse(pilot.araknis_running)
        self.assertIsNone(pilot.araknis_diagnostics)
        self.assertNotIn(self.config['password'], pilot.araknis_error)

    def test_query_help_has_no_newline_and_uses_bounded_pager(self):
        client = Mock()
        channel = client.invoke_shell.return_value
        responses = iter([('(switch)#', False), ('help --More--', False), ('last help', False)])
        text, truncated = araknis.query(client, 'show power', lambda _: next(responses), help_only=True)
        self.assertEqual([call.args[0] for call in channel.sendall.call_args_list], [b'show power ?', b' '])
        self.assertFalse(truncated)
        self.assertIn('last help', text)

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
