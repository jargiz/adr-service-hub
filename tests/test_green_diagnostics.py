import copy
import hashlib
import base64
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]/'adr_diagnostics'
sys.path.insert(0,str(ROOT))
import diagnostics as diag
import analysis as ai
import server as green


class Tools(unittest.TestCase):
    def options(self):return {'allowed_subnets':['192.168.50.0/24'],'targets':['192.168.50.10'],'dns_name':'example.com'}

    def test_only_explicit_small_private_subnets(self):
        for subnet in ('0.0.0.0/0','8.8.8.0/24','192.168.0.0/16','127.0.0.0/24','169.254.1.0/24','::1/128'):
            with self.subTest(subnet=subnet),self.assertRaises(diag.DiagnosticError):
                diag.config({'allowed_subnets':[subnet]})
        for target in ('192.168.51.1','192.168.50.0','192.168.50.255','--help','host.example','192.168.50.1; reboot'):
            with self.subTest(target=target),self.assertRaises(diag.DiagnosticError):
                diag.config(dict(self.options(),targets=[target]))
        self.assertEqual(diag.config(self.options())['targets'],['192.168.50.10'])

    def test_config_bounds(self):
        for options in (dict(self.options(),targets=['192.168.50.10']*17),dict(self.options(),dns_name='bad\nname'),dict(self.options(),monitor_interval_minutes=True)):
            with self.assertRaises(diag.DiagnosticError):diag.config(options)

    def test_surrounding_whitespace_is_normalized(self):
        c=diag.config({'allowed_subnets':[' 192.168.50.0/24 '],
            'targets':[' 192.168.50.1\n'],'dns_name':' example.com '})
        self.assertEqual(c['targets'],['192.168.50.1'])
        self.assertEqual(c['dns_name'],'example.com')

    def test_joined_addresses_have_actionable_error(self):
        with self.assertRaises(diag.DiagnosticError) as error:
            diag.config(dict(self.options(),targets=['192.168.50.1,192.168.50.2']))
        self.assertIn('Add each address separately',str(error.exception))

    def test_ping_fixed_args_and_short_sample(self):
        runner=Mock(return_value=SimpleNamespace(stdout='3 packets transmitted, 2 received, 33% packet loss\nrtt min/avg/max/mdev = 1.0/2.0/3.0/1.0 ms',returncode=0))
        r=diag.ping('192.168.50.10',runner=runner)
        self.assertEqual(r['received'],2);self.assertEqual(r['average_ms'],2);self.assertEqual(r['loss_percent'],33.3)
        args,kwargs=runner.call_args
        self.assertEqual(args[0],['ping','-n','-c','3','-W','1','-w','4','--','192.168.50.10'])
        self.assertNotIn('shell',kwargs);self.assertEqual(kwargs['timeout'],5)

    def test_ping_unavailable_never_invents_loss(self):
        runner=Mock(side_effect=OSError('no permission'))
        r=diag.ping('192.168.50.10',runner=runner)
        self.assertEqual(r['status'],'unverified');self.assertIsNone(r['loss_percent'])
        runner=Mock(return_value=SimpleNamespace(stdout='3 packets transmitted, 0 received',returncode=1))
        self.assertEqual(diag.ping('192.168.50.10',runner=runner)['status'],'no_reply')

    def test_tcp_is_connect_only(self):
        connection=Mock();connection.__enter__=Mock();connection.__exit__=Mock(return_value=False)
        connector=Mock(return_value=connection)
        self.assertEqual(diag.tcp('192.168.50.10',443,connector)['status'],'reachable')
        connection.send.assert_not_called();connection.recv.assert_not_called()
        with self.assertRaises(diag.DiagnosticError):diag.tcp('192.168.50.10',22,connector)

    def test_dns_bounded_child_and_failures(self):
        runner=Mock(return_value=SimpleNamespace(stdout='["192.0.2.1"]',returncode=0))
        self.assertEqual(diag.dns('example.com',runner)['status'],'resolved')
        self.assertEqual(runner.call_args.kwargs['timeout'],5)
        runner.side_effect=TimeoutError()
        self.assertEqual(diag.dns('example.com',runner)['status'],'unverified')

    def test_check_uses_only_configured_targets_and_ports(self):
        ping=Mock(return_value={'status':'responded'});tcp=Mock(return_value={'status':'reachable'});dns=Mock(return_value={'status':'resolved'})
        c=diag.config(self.options());r=diag.check(c,ping,tcp,dns)
        ping.assert_called_once_with('192.168.50.10')
        self.assertEqual([x.args[1] for x in tcp.call_args_list],[80,443]);dns.assert_called_once_with('example.com')
        self.assertEqual(len(r['targets']),1)

    def test_discovery_one_configured_subnet_only(self):
        c=diag.config({'allowed_subnets':['192.168.50.0/30']})
        probe=Mock(side_effect=lambda ip,count:{'status':'responded' if ip.endswith('.1') else 'no_reply'})
        r=diag.discover(c,'192.168.50.0/30',probe)
        self.assertEqual(r['responding'],['192.168.50.1']);self.assertEqual(r['tested'],2)
        self.assertNotIn('offline',json.dumps(r).lower().split('limitations')[0])
        with self.assertRaises(diag.DiagnosticError):diag.discover(c,'192.168.51.0/24',probe)

    def test_retention_caps_and_prunes_observed(self):
        old={'saved_at':time.time()-8*86400,'result':{'kind':'discovery','responding':['192.168.50.1'],'checked_at':'old'}}
        h={'samples':[old]};diag.retain(h)
        self.assertEqual(h['observed'],[])
        r={'kind':'discovery','responding':['192.168.50.2'],'checked_at':'new'}
        for _ in range(110):diag.retain(h,r)
        self.assertEqual(len(h['samples']),96);self.assertEqual(h['observed'][0]['ip'],'192.168.50.2')

    def test_report_import_has_fixed_fields_only(self):
        r={'format':'adr-service-report-v1','checks':[{'system':'WattBox','snapshot':{'password':'secret','readings':[{'response':'private console'}],'outlets':[{'number':1,'label':'TV','on':True,'password':'secret'}]}}]}
        result=diag.import_report(r);self.assertNotIn('secret',json.dumps(result));self.assertNotIn('private console',json.dumps(result))
        self.assertTrue(result['systems'][0]['readings'][0]['on'])

    def test_report_import_nested_controller(self):
        r={'format':'adr-service-report-v1','checks':[{'system':'Ruckus','snapshot':{'controller':{'access_points':[{'name':'Office','online':None,'connected_clients':25}]}}}]}
        reading=diag.import_report(r)['systems'][0]['readings'][0]
        self.assertIsNone(reading['online']);self.assertEqual(reading['connected_clients'],25)

    def test_import_keeps_speed_and_post_action_timestamps(self):
        r={'format':'adr-service-report-v1','checks':[
            {'system':'WattBox','completed_at':'original','post_action_verified_at':'fresh','snapshot':{'outlets':[]}},
            {'system':'UniFi','snapshot':{'sensors':[],'internet_readings':[{'name':'Download','state':'918','unit':'Mbit/s','last_updated':'test-time','password':'never-copy'}]}}]}
        result=diag.import_report(r)
        self.assertEqual(result['systems'][0]['checked_at'],'fresh')
        self.assertEqual(result['systems'][1]['readings'][0]['state'],'918')
        self.assertNotIn('never-copy',json.dumps(result))

    def test_private_atomic_file(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'history.json';diag.save(path,{'test':1})
            self.assertEqual(path.stat().st_mode&0o777,0o600);self.assertFalse(path.with_suffix('.tmp').exists())


class Analysis(unittest.TestCase):
    def opts(self):return {'cloud_analysis_enabled':True,'openai_api_key':'fake-test-key','openai_model':'test-model'}
    def connection(self,body,status=200):
        c=Mock();response=Mock();response.status=status;response.read.return_value=json.dumps(body).encode();c.getresponse.return_value=response
        return c,Mock(return_value=c)

    def test_one_request_no_tools_and_no_storage(self):
        c,factory=self.connection({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'Review DNS.'}]}]})
        result=ai.ask(self.opts(),'Why slow?',{'dns':'unverified'},True,factory)
        self.assertEqual(result,'Review DNS.');c.request.assert_called_once()
        args,kwargs=c.request.call_args;self.assertEqual(args[:2],('POST','/v1/responses'))
        payload=json.loads(kwargs['body']);self.assertFalse(payload['store']);self.assertNotIn('tools',payload)
        self.assertNotIn('fake-test-key',kwargs['body']);self.assertEqual(payload['max_output_tokens'],1500)
        self.assertIsNotNone(factory.call_args.kwargs['context']);c.close.assert_called_once()

    def test_cloud_requires_both_config_and_explicit_consent(self):
        factory=Mock()
        for opts,confirm in (({},True),(self.opts(),False)):
            with self.assertRaises(diag.DiagnosticError):ai.ask(opts,'question',{},confirm,factory)
        factory.assert_not_called()

    def test_cloud_errors_never_leak_or_retry(self):
        c,factory=self.connection({'secret':'fake-test-key'},429)
        with self.assertRaises(diag.DiagnosticError) as error:ai.ask(self.opts(),'question',{},True,factory)
        self.assertNotIn('fake-test-key',str(error.exception));c.request.assert_called_once()

    def test_partial_answer_and_tool_calls_not_executed(self):
        c,factory=self.connection({'status':'incomplete','output':[{'type':'function_call','name':'reboot'}]})
        with self.assertRaises(diag.DiagnosticError):ai.ask(self.opts(),'question',{},True,factory)
        c.request.assert_called_once()


class App(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=green.State(self.temp.name,{'allowed_subnets':[],'targets':[]})

    def test_startup_has_no_checks_or_model_calls(self):
        with patch.object(green,'check') as check,patch.object(green,'ask') as ask:
            self.state.monitor();self.assertFalse(self.state.busy);check.assert_not_called();ask.assert_not_called()

    def test_invalid_config_serves_setup_page_without_work(self):
        path=Path(self.temp.name)/'options.json'
        path.write_text(json.dumps({'allowed_subnets':[],'targets':['192.168.50.1'],'openai_api_key':'private-never-log'}))
        state=green.startup(self.temp.name,path)
        self.assertIsInstance(state,green.SetupNeeded)
        self.assertTrue(state.status()['blocked'])
        self.assertIn('targets:',state.status()['progress'])
        self.assertNotIn('private-never-log',json.dumps(state.status()))
        self.assertIn('Network diagnostics',green.page(state))
        with self.assertRaises(diag.DiagnosticError):state.start('check',{})

    def test_bad_saved_json_produces_safe_notice_without_deleting(self):
        path=Path(self.temp.name)/'options.json';path.write_text('{}')
        saved=Path(self.temp.name)/'history.json';saved.write_text('{private-never-log')
        state=green.startup(self.temp.name,path)
        self.assertIsInstance(state,green.SetupNeeded)
        self.assertIn('history.json',state.message)
        self.assertNotIn('private-never-log',state.message)
        self.assertEqual(saved.read_text(),'{private-never-log')

    def test_unexpected_startup_exception_never_prints_secret(self):
        with patch.object(green,'State',side_effect=RuntimeError('private-never-log')):
            state=green.startup(self.temp.name,Path(self.temp.name)/'options.json')
        self.assertIsInstance(state,green.SetupNeeded)
        self.assertNotIn('private-never-log',json.dumps(state.status()))

    def test_job_guard_and_configuration(self):
        with self.assertRaises(diag.DiagnosticError):self.state.start('check',{})
        self.state.busy=True
        with self.assertRaises(diag.DiagnosticError):self.state.start('import',{'report':'{}'})

    def test_one_running_job_and_no_background_model_calls(self):
        self.state.settings=diag.config({'allowed_subnets':['192.168.50.0/24'],'targets':['192.168.50.1']})
        thread=Mock();self.state.start('check',{},thread)
        self.assertTrue(self.state.busy);thread.assert_called_once()
        with self.assertRaises(diag.DiagnosticError):self.state.start('check',{},thread)

    def test_quota_reserved_before_network_and_survives_restart(self):
        self.state.options.update(cloud_analysis_enabled=True)
        self.state.result={'kind':'discovery','responding':[]}
        thread=Mock();self.state.start('ask',{'question':'Why?','confirm':'yes'},thread)
        self.assertEqual(self.state.quota['count'],1)
        saved=green.load(Path(self.temp.name)/'analysis_attempts.json');self.assertEqual(saved['count'],1)
        self.state.busy=False;self.state.last_started=0;self.state.quota['count']=10
        with self.assertRaises(diag.DiagnosticError):self.state.start('ask',{'question':'Why?','confirm':'yes'},thread)

    def test_render_has_no_credentials_and_script_is_hashed(self):
        self.state.options['openai_api_key']='private-test-value'
        body=green.page(self.state)
        self.assertNotIn('private-test-value',body);self.assertNotIn('innerHTML',body)
        self.assertNotIn('__CSRF__',body)
        self.assertEqual(green.SCRIPT_HASH,base64.b64encode(hashlib.sha256(green.SCRIPT.encode()).digest()).decode())

    def test_actual_peer_required_not_forwarded_header(self):
        handler=object.__new__(green.Handler);handler.client_address=('192.0.2.1',123)
        handler.headers={'X-Forwarded-For':'172.30.32.2'};handler.send_error=Mock()
        self.assertFalse(handler.authorized());handler.send_error.assert_called_once_with(403)

    def test_http_csrf_blocks_job_and_get_never_starts_work(self):
        import http.client
        class Trusted(green.Handler):
            def authorized(self):return True
        server=green.ThreadingHTTPServer(('127.0.0.1',0),Trusted);server.state=self.state
        self.addCleanup(server.server_close)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.addCleanup(server.shutdown)
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
        with patch.object(self.state,'start') as start:
            conn.request('GET','/state');r=conn.getresponse();self.assertEqual(r.status,200);r.read();start.assert_not_called()
            conn.request('POST','/action',body='action=check&csrf=wrong',headers={'Content-Type':'application/x-www-form-urlencoded'})
            r=conn.getresponse();self.assertEqual(r.status,403);r.read();start.assert_not_called()
            conn.request('POST','/action',body='action=check&csrf='+self.state.csrf)
            r=conn.getresponse();self.assertEqual(r.status,202);r.read();start.assert_called_once_with('check',{})
        conn.close()


if __name__=='__main__':unittest.main()
