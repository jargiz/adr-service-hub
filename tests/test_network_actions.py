import asyncio
import io
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
import internet_test
import ruckus_controller as rc
import sense
from agent import Pilot, Handler, page
from dashboard_visuals import network_panels
from service_report import assess


class InternetTests(unittest.TestCase):
    def run_test(self, values, **kwargs):
        with patch('internet_test.speedtest_readings', side_effect=values):
            return internet_test.run(token='test-only', **kwargs)

    def values(self, stamp):
        return [{'entity_id': 'sensor.speedtest_'+name, 'name': 'Speedtest '+name,
            'state': value, 'unit': 'ms' if name == 'ping' else 'Mbit/s', 'last_updated': stamp}
            for name, value in [('download', '500'), ('upload', '300'), ('ping', '7')]]

    def test_one_targeted_request_and_fresh_numeric_values(self):
        post = Mock()
        fresh = (datetime.now(timezone.utc)+timedelta(seconds=2)).isoformat()
        result = self.run_test([self.values('2020-01-01T00:00:00Z'), self.values(fresh)], post_fn=post)
        post.assert_called_once_with('test-only', 'sensor.speedtest_download')
        self.assertTrue(result['fresh_values_confirmed'])

    def test_old_missing_invalid_and_unavailable_values_are_unverified(self):
        stamp = (datetime.now(timezone.utc)+timedelta(seconds=2)).isoformat()
        for rows in [self.values('2020-01-01T00:00:00Z'), self.values(stamp)[:1], [],
                     [dict(r, state='unavailable') for r in self.values(stamp)],
                     [dict(r, state='nan') for r in self.values(stamp)]]:
            with self.subTest(rows=rows):
                result = self.run_test([self.values(stamp), rows], post_fn=Mock())
                self.assertFalse(result['fresh_values_confirmed'])
                self.assertTrue(result['limitations'])

    def test_missing_multiple_and_control_targets_never_post(self):
        for values in [[], self.values(None)*2, [dict(self.values(None)[0], entity_id='switch.control')]]:
            post = Mock()
            with self.assertRaises(internet_test.InternetTestError):
                self.run_test([values], post_fn=post)
            post.assert_not_called()

    def test_real_discovery_excludes_foreign_disabled_and_unloaded(self):
        post = Mock()
        entries = [{'entry_id': 'test', 'domain': 'speedtestdotnet', 'state': 'loaded'}]
        registry = [{'entity_id': 'sensor.download', 'config_entry_id': 'test', 'platform': 'speedtestdotnet', 'disabled_by': 'user'},
                    {'entity_id': 'sensor.foreign_download', 'config_entry_id': 'test', 'platform': 'other'},
                    {'entity_id': 'sensor.old_download', 'config_entry_id': 'other', 'platform': 'speedtestdotnet'}]
        with self.assertRaises(internet_test.InternetTestError):
            internet_test.run(token='test', get_fn=lambda *_: entries, registries_fn=lambda _: (registry, []), post_fn=post)
        post.assert_not_called()

    def test_service_failure_has_one_attempt_and_no_secret_in_error(self):
        opener=Mock(); opener.open.side_effect=TimeoutError('private-token')
        with patch('internet_test.speedtest_readings', return_value=self.values(None)), patch('internet_test.build_opener', return_value=opener):
            with self.assertRaises(internet_test.InternetTestError) as error:
                internet_test.run(token='private-token')
        self.assertNotIn('private-token', str(error.exception))
        self.assertEqual(opener.open.call_count, 1)
        request=opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data), {'entity_id': 'sensor.speedtest_download'})


class ControllerTests(unittest.TestCase):
    def config(self): return {'host': 'controller.example', 'port': 443, 'username': 'monitor', 'password': 'private'}

    def test_allow_only_one_pinned_origin_and_statistics_payloads(self):
        http=Mock(headers={}); guard=rc.StatisticsSession(http, self.config(), 'pin')
        guard.post('https://controller.example/admin/_cmdstat.jsp', data='<ajax-request action="getstat" comp="stamgr"><ap LEVEL="1"/></ajax-request>')
        self.assertEqual(http.request.call_args.kwargs['ssl'], 'pin')
        self.assertFalse(http.request.call_args.kwargs['allow_redirects'])
        for method, url, data in [
            ('GET', 'https://elsewhere.example/admin/login.jsp', ''),
            ('GET', 'http://controller.example/admin/login.jsp', ''),
            ('GET', 'https://user:password@controller.example/', ''),
            ('DELETE', 'https://controller.example/admin/_cmdstat.jsp', ''),
            ('POST', 'https://controller.example/admin/_conf.jsp', '<ajax-request action="getconf"/>'),
            ('POST', 'https://controller.example/admin/_cmdstat.jsp', '<ajax-request action="setconf" comp="stamgr"><ap/></ajax-request>'),
            ('POST', 'https://controller.example/admin/_cmdstat.jsp', '<ajax-request action="getstat" comp="stamgr"><reboot/></ajax-request>')]:
            with self.subTest(method=method,url=url,data=data), self.assertRaises(rc.ControllerError):
                guard.request(method,url,data=data)
        self.assertEqual(http.request.call_count, 1)

    def test_missing_counts_numeric_state_codes_and_actual_zero(self):
        result=rc.normalize([{'devname': '<script>AP</script>', 'state': '1', 'password': 'secret'},
            {'devname': 'Online AP', 'state': 'connected', 'num-sta': '0'},
            {'devname': 'Offline AP', 'state': 'disconnected', 'num-sta': '-1'}])
        a,b,c=result['access_points']
        self.assertIsNone(a['online']); self.assertIsNone(a['connected_clients'])
        self.assertIs(b['online'], True); self.assertEqual(b['connected_clients'],0)
        self.assertIs(c['online'], False); self.assertIsNone(c['connected_clients'])
        self.assertNotIn('secret', str(result))
        report={'Ruckus': {'snapshot': {'controller': result}}}
        rendered=network_panels(report)
        self.assertIn('&lt;script&gt;AP&lt;/script&gt;',rendered)
        self.assertIn('Status: <strong>Offline',rendered)
        self.assertIn('Connected devices: <strong>0',rendered)
        self.assertNotIn('<script>',rendered)
        assessed=assess('Ruckus',{'entry':{'state':'loaded'},'entities':[{'state':'home'}],'controller':result})
        self.assertEqual(assessed['status'],'review')
        self.assertTrue(any('state 1 is unverified' in s for s in assessed['data_limitations']))

    def test_unapproved_target_never_authenticates(self):
        with patch('ruckus_controller._read') as read:
            for pin in [{}, {'host': 'other.example', 'port':443,'sha256':'a'*64}]:
                with self.assertRaises(rc.ControllerError): rc.collect(self.config(), pin)
            read.assert_not_called()

    def test_redirect_response_fails_without_sdk_retry_and_body_is_bounded(self):
        class Context:
            def __init__(self, status, content=b''):
                self.response=SimpleNamespace(status=status,content=SimpleNamespace(read=Mock()))
                self.data=content
                async def read(n):
                    chunk,self.data=self.data[:n],self.data[n:];return chunk
                self.response.content.read=read
            async def __aenter__(self): return self.response
            async def __aexit__(self,*_): pass
        async def run():
            with self.assertRaises(rc.ControllerError):
                async with rc.BoundedResponse(Context(302),'POST'): pass
            with self.assertRaises(rc.ControllerError):
                async with rc.BoundedResponse(Context(200,b'x'*(1024*1024+1)),'POST') as response:
                    await response.text()
        asyncio.run(run())

    def test_direct_read_failure_changes_report_to_review(self):
        result=assess('Ruckus',{'entry':{'state':'loaded'}, 'entities':[{'state':'home'}], 'controller_attempted':True,'controller_error':'failed'})
        self.assertEqual(result['status'],'review')
        self.assertIn('could not be read',result['service_findings'][0])


class PilotNetworkTests(unittest.TestCase):
    def pilot(self, root):
        (root/'options.json').write_text('{}');return Pilot(root,root/'options.json')

    def test_no_startup_calls_duplicate_guard_auto_refresh_and_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('agent.run_internet_test') as run,patch('agent.collect_controller') as collect:
                pilot=self.pilot(Path(directory));run.assert_not_called();collect.assert_not_called()
            with patch('agent.threading.Thread') as thread:
                pilot.start_network_job('internet_test')
                with self.assertRaises(Exception): pilot.start_network_job('internet_test')
                self.assertIn('http-equiv="refresh"',page(pilot))
                job=thread.call_args.kwargs['target']
            with patch('agent.run_internet_test',side_effect=internet_test.InternetTestError('Test failed')) as run:
                job();run.assert_called_once()
            self.assertFalse(pilot.internet_test_running)
            self.assertNotIn('http-equiv="refresh"',page(pilot))
            self.assertIn('Test failed',page(pilot))

    def test_certificate_approval_bound_to_target_expiry_and_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pilot=self.pilot(root)
            pilot.araknis_options.update(ruckus_controller_host='controller.example',ruckus_controller_port=443,ruckus_controller_username='test',ruckus_controller_password='private')
            with patch('agent.inspect_certificate',return_value='a'*64): pilot.controller_identity()
            nonce,_=pilot.controller_candidate;pilot.controller_trust(nonce)
            self.assertEqual((root/'ruckus_controller_certificate.json').stat().st_mode & 0o777,0o600)
            self.assertNotIn('private',(root/'ruckus_controller_certificate.json').read_text())
            with self.assertRaises(Exception): pilot.controller_trust(nonce)
            with patch('agent.inspect_certificate',return_value='b'*64): pilot.controller_identity()
            with self.assertRaises(Exception): pilot.controller_trust(pilot.controller_candidate[0])
            self.assertEqual(pilot.controller_pin['sha256'],'a'*64)

    def test_network_actions_require_ingress_and_csrf(self):
        for action in ('internet-speedtest','controller-read','controller-identity','controller-trust'):
            for csrf,addr in [('bad','172.30.32.2'),('ok','192.0.2.1')]:
                h=Handler.__new__(Handler);body=('csrf='+csrf).encode()
                h.server=SimpleNamespace(pilot=SimpleNamespace(csrf='ok',lock=threading.Lock()))
                h.client_address,h.path=(addr,123),'/' + action
                h.headers={'Content-Length':str(len(body)),'Content-Type':'application/x-www-form-urlencoded'}
                h.rfile,h.wfile=io.BytesIO(body),io.BytesIO()
                h.send_error=Mock();h.do_POST()
                self.assertEqual(h.send_error.call_args.args[0],403)


class SensePriorityTests(unittest.TestCase):
    def test_main_power_daily_energy_and_voltages_survive_appliance_limit_and_history(self):
        def entity(name,device='main'):
            return {'entity_id':'sensor.'+name,'device_id':device,'config_entry_id':'sense','platform':'sense'}
        registry=[entity('a_appliance_'+str(i),'appliance') for i in range(150)]
        registry += [entity(n) for n in ('l1_voltage','l2_voltage','energy_usage','daily_usage','energy_production','daily_from_grid','daily_to_grid','daily_production')]
        def read(_,eid):
            cls='voltage' if 'voltage' in eid else 'power' if 'energy_' in eid else 'energy'
            return {'entity_id':eid,'name':eid,'state':'1.3' if 'l2_' in eid else '123.2', 'attributes':{'device_class':cls,'unit_of_measurement':{'voltage':'V','power':'W','energy':'kWh'}[cls]}}
        result=sense.collect(token='test',entries_fn=lambda _:[{'entry_id':'sense','state':'loaded'}],registries_fn=lambda _:(registry,[]),read_fn=read)
        ids={r['entity_id'] for r in result['main_monitor_readings']}
        self.assertIn('sensor.energy_usage',ids);self.assertIn('sensor.daily_usage',ids)
        calls=[]
        def history(_,path): calls.append(path);return []
        sense.add_history(result,'test',get_fn=history)
        series={s['entity_id'] for s in result['history']['series']}
        for name in ('l1_voltage','l2_voltage','energy_usage','daily_usage'): self.assertIn('sensor.'+name,series)
        assessed=assess('Sense',result)
        self.assertTrue(any('1.3 V' in s and 'does not establish an electrical fault' in s for s in assessed['service_findings']))


if __name__=='__main__':unittest.main()
