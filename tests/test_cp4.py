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
import paramiko
import cp4
from agent import Handler, Pilot, ProtocolError, page


class CP4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.keys = self.root / 'cp4_known_hosts'
        self.keys.touch()
        self.config = {'host': '192.0.2.30', 'port': 22, 'username': 'reader', 'password': 'private-password'}

    def tearDown(self):
        self.tmp.cleanup()

    def run_fixture(self, replies, client=None):
        client = client or Mock()
        values = iter(replies)
        result = cp4.collect(self.config, self.keys, lambda: client, lambda *args, **kwargs: next(values))
        return result, client

    def test_fixed_reads_follow_supported_help_with_one_login(self):
        replies = [('CP4-R>', False), ('CP4-R firmware test-version\nCP4-R>', False),
            ('IPTABLE   Displays table\nUPTIME    Displays uptime\nCPULOAD    Displays load\nRAMFREE    Displays free RAM\nCP4-R>', False),
            ('IP table entries\nCP4-R>', False),
            ('UPTIME: Displays uptime.\nCP4-R>', False), ('Uptime: test-time\nCP4-R>', False),
            ('CPULOAD: Displays CPU usage.\nCP4-R>', False), ('CPU: test-value\nCP4-R>', False),
            ('RAMFREE: Displays available RAM.\nCP4-R>', False), ('RAM: test-value\nCP4-R>', False)]
        result, client = self.run_fixture(replies)
        self.assertTrue(result['model_verified'])
        self.assertTrue(result['ssh_authenticated'])
        self.assertEqual(result['not_attempted'], [])
        commands = [call.args[0] for call in client.invoke_shell.return_value.sendall.call_args_list]
        self.assertEqual(commands, [b'VER -V\r', b'HELP ALL\r', b'IPTABLE -p:all -t\r',
            b'UPTIME ?\r', b'UPTIME\r', b'CPULOAD ?\r', b'CPULOAD\r', b'RAMFREE ?\r', b'RAMFREE\r'])
        client.connect.assert_called_once()
        client.close.assert_called_once()
        self.assertIsInstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.RejectPolicy)
        self.assertFalse(client.connect.call_args.kwargs['allow_agent'])
        self.assertFalse(client.connect.call_args.kwargs['look_for_keys'])

    def test_unidentified_model_stops_after_version(self):
        result, client = self.run_fixture([('Other>', False), ('Other device\nOther>', False)])
        self.assertFalse(result['model_verified'])
        client.invoke_shell.return_value.sendall.assert_called_once_with(b'VER -V\r')
        self.assertTrue(result['not_attempted'])

    def test_partial_response_prevents_any_later_commands(self):
        result, client = self.run_fixture([('CP4-R>', False), ('CP4-R firmware\nCP4-R>', False),
            ('IPTABLE  Displays table\nUPTIME  Displays uptime\nCP4-R>', False),
            ('unfinished table', True)])
        commands = [call.args[0] for call in client.invoke_shell.return_value.sendall.call_args_list]
        self.assertEqual(commands, [b'VER -V\r', b'HELP ALL\r', b'IPTABLE -p:all -t\r'])
        self.assertEqual(result['readings'][-1]['status'], 'partial response')

    def test_control_or_ambiguous_help_not_executed(self):
        result, client = self.run_fixture([('CP4-R>', False), ('CP4-R firmware\nCP4-R>', False),
            ('CPULOAD   Load query\nRAMFREE   Memory query\nCP4-R>', False),
            ('CPULOAD: Start or stop CPU measurement display.\nCP4-R>', False),
            ('RAMFREE: Arguments required.\nCP4-R>', False)])
        commands = [call.args[0] for call in client.invoke_shell.return_value.sendall.call_args_list]
        self.assertNotIn(b'CPULOAD\r', commands)
        self.assertNotIn(b'RAMFREE\r', commands)
        self.assertTrue(any('syntax needs verification' in note for note in result['not_attempted']))

    def test_unknown_commands_and_arguments_cannot_be_sent(self):
        client = Mock()
        console = cp4.Console(client, lambda *a, **k: ('CP4-R>', False))
        for command in ('REBOOT', 'IPTABLE -c -p:all', 'UPTIME;REBOOT', 'VER -V\rREBOOT', 'RAMFREE RESET', 'HELP REBOOT'):
            with self.assertRaises(cp4.CP4Error):
                console.query(command)
        client.invoke_shell.return_value.sendall.assert_not_called()

    def test_key_approval_required_before_client_created(self):
        self.keys.unlink()
        client_factory = Mock()
        with self.assertRaises(cp4.CP4Error):
            cp4.collect(self.config, self.keys, client_factory)
        client_factory.assert_not_called()

    def test_auth_or_changed_key_failure_never_opens_console_or_leaks_secret(self):
        key = paramiko.RSAKey.generate(1024)
        for error in (paramiko.AuthenticationException('private-password'),
                paramiko.BadHostKeyException('test', key, key)):
            client = Mock()
            client.connect.side_effect = error
            with self.assertRaises(cp4.CP4Error) as caught:
                cp4.collect(self.config, self.keys, lambda: client)
            self.assertNotIn('private-password', str(caught.exception))
            client.invoke_shell.assert_not_called()
            client.close.assert_called_once()

    def test_password_is_redacted_from_raw_response(self):
        result, _ = self.run_fixture([('CP4-R>', False), ('CP4-R private-password firmware\nCP4-R>', False),
            ('no supported diagnostics\nCP4-R>', False)])
        payload = cp4.report_payload(result)
        self.assertNotIn('private-password', json.dumps(payload))
        self.assertNotIn('username', payload)

    def test_formatted_pager_and_prompt_are_bounded(self):
        clock = [0.0]
        channel = Mock()
        channel.closed = False
        state = {'chunks': [b'first\r\n\x1b[7m--More--\x1b[0m']}
        channel.recv_ready.side_effect = lambda: bool(state['chunks'])
        channel.recv.side_effect = lambda _: state['chunks'].pop(0)
        def send(value):
            self.assertEqual(value, b' ')
            state['chunks'].append(b'last\r\nCP4-R>')
        channel.sendall.side_effect = send
        def sleep(seconds): clock[0] += seconds
        with patch('cp4.time.monotonic', side_effect=lambda: clock[0]), patch('cp4.time.sleep', side_effect=sleep):
            text, partial = cp4.receive(channel, prompt='CP4-R>')
        self.assertFalse(partial)
        self.assertIn('first', text)
        self.assertIn('last', text)
        channel.sendall.assert_called_once_with(b' ')
        self.assertLess(clock[0], 2)

    def test_background_identity_and_report(self):
        options = self.root / 'options.json'
        options.write_text(json.dumps({'cp4_host': self.config['host'], 'cp4_ssh_port': 22,
            'cp4_username': self.config['username'], 'cp4_password': self.config['password']}))
        with patch('agent.collect_cp4') as collect:
            pilot = Pilot(self.root, options)
            collect.assert_not_called()
        key = paramiko.RSAKey.generate(1024)
        self.keys.unlink()
        with patch('agent.inspect_key', return_value=key):
            pilot.cp4_identity()
        nonce = pilot.cp4_candidate[0]
        pilot.cp4_trust(nonce)
        with self.assertRaises(ProtocolError): pilot.cp4_trust(nonce)
        with patch('agent.threading.Thread') as thread:
            pilot.start_cp4_diagnostics()
            pilot.start_cp4_diagnostics()
            thread.assert_called_once()
            job = thread.call_args.kwargs['target']
        result = {'checked_at': 'test', 'ssh_authenticated': True, 'model_verified': True,
            'readings': [{'name': 'Version', 'response': '<script>test</script>', 'status': 'response received'}],
            'not_attempted': []}
        with patch('agent.collect_cp4', return_value=result): job()
        self.assertFalse(pilot.cp4_running)
        self.assertNotIn('<script>', page(pilot))
        self.assertNotIn('private-password', (self.root / 'events.jsonl').read_text())
        self.assertFalse((self.root / 'known_hosts').exists())

    def test_download_requires_ingress_and_csrf(self):
        result = {'checked_at': 'test', 'readings': []}
        pilot = SimpleNamespace(lock=threading.Lock(), csrf='test-csrf', cp4=result, cp4_running=False)
        for csrf, address, success in [('test-csrf', '172.30.32.2', True),
                ('wrong', '172.30.32.2', False), ('test-csrf', '192.0.2.90', False)]:
            handler = Handler.__new__(Handler)
            body = ('csrf=' + csrf).encode()
            handler.server = SimpleNamespace(pilot=pilot)
            handler.client_address = (address, 123)
            handler.path = '/cp4-report'
            handler.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/x-www-form-urlencoded'}
            handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
            handler.send_response, handler.send_header = Mock(), Mock()
            handler.end_headers, handler.send_error = Mock(), Mock()
            handler.do_POST()
            if success:
                self.assertEqual(json.loads(handler.wfile.getvalue())['source'], 'direct_processor_ssh')
                handler.send_header.assert_any_call('Content-Disposition', 'attachment; filename="ADR-CP4-Diagnostics.json"')
            else:
                self.assertEqual(handler.send_error.call_args.args[0], 403)
                self.assertEqual(handler.wfile.getvalue(), b'')


if __name__ == '__main__':
    unittest.main()
