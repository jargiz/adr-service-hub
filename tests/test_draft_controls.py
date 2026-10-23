import copy
import hashlib
import io
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'adr_service_agent'))
from agent import Pilot, atomic_json, page, VIEW_SCRIPT, VIEW_SCRIPT_HASH
from outlet_control import prepare, execute
from wattbox import WattBox, ProtocolError
import unifi_gateway as gateway
from network_history import append


class DraftControls(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.options=self.root/'options.json'
        self.config={'wattbox_host':'192.0.2.1','ssh_port':22,'username':'test','password':'private','test_outlet':1,'expected_outlet_label':'TV','device_alias':'TV','allow_reboot':False,'allow_outlet_control':True}
        self.options.write_text(json.dumps(self.config));(self.root/'known_hosts').write_text('approved-key')
        self.inventory={'model':'WB-800VPS-IPVM-18','firmware':'test','outlets':[{'number':1,'label':'TV','on':True}]}
        self.box=Mock();self.box.__enter__=Mock(return_value=self.box);self.box.__exit__=Mock(return_value=False);self.box.inventory.side_effect=lambda:copy.deepcopy(self.inventory)
        self.pilot=Pilot(self.root,self.options,lambda *_:self.box)

    def test_named_confirmation_single_command_and_replay_blocked(self):
        item=prepare(self.pilot,1,'OFF');self.box.set_power.assert_not_called()
        self.assertEqual(item['label'],'TV');self.assertFalse(self.pilot.config['allow_reboot'])
        execute(self.pilot,item['nonce'],True,atomic_json)
        self.box.set_power.assert_called_once_with(1,'OFF')
        self.assertEqual((self.root/'outlet_control_state.json').stat().st_mode&0o777,0o600)
        with self.assertRaises(ProtocolError):execute(self.pilot,item['nonce'],True,atomic_json)
        self.assertEqual(self.box.set_power.call_count,1)

    def test_mapping_state_host_or_key_change_never_sends(self):
        for change in ('label','on','host','key'):
            with self.subTest(change=change):
                self.setUp();item=prepare(self.pilot,1,'OFF')
                if change=='label':self.inventory['outlets'][0]['label']='Router'
                if change=='on':self.inventory['outlets'][0]['on']=False
                if change=='host':self.pilot.config['wattbox_host']='192.0.2.2'
                if change=='key':(self.root/'known_hosts').write_text('changed-key')
                with self.assertRaises(ProtocolError):execute(self.pilot,item['nonce'],True,atomic_json)
                self.box.set_power.assert_not_called()

    def test_unconfirmed_expired_or_disabled_never_sends(self):
        for variant in ('no','expired','disabled'):
            item=prepare(self.pilot,1,'ON')
            if variant=='expired':item['created']-=121
            if variant=='disabled':self.pilot.araknis_options['allow_outlet_control']=False
            with self.assertRaises(ProtocolError):execute(self.pilot,item['nonce'],variant!='no',atomic_json)
            self.box.set_power.assert_not_called()

    def test_timeout_is_single_attempt_and_cooldown_persists(self):
        item=prepare(self.pilot,1,'RESET');self.box.set_power.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):execute(self.pilot,item['nonce'],True,atomic_json)
        second=prepare(self.pilot,1,'RESET')
        with self.assertRaises(ProtocolError):execute(self.pilot,second['nonce'],True,atomic_json)
        self.assertEqual(self.box.set_power.call_count,1)

    def test_off_outlet_can_turn_on_but_not_reset(self):
        self.inventory['outlets'][0]['on']=False
        with self.assertRaises(ProtocolError):prepare(self.pilot,1,'RESET')
        item=prepare(self.pilot,1,'ON');execute(self.pilot,item['nonce'],True,atomic_json)
        self.box.set_power.assert_called_once_with(1,'ON')

    def test_pending_approval_blocks_reads_and_refresh(self):
        prepare(self.pilot,1,'OFF');self.pilot.monitor_active=True
        self.assertTrue(self.pilot.monitoring_busy())
        with self.assertRaises(ProtocolError):self.pilot.start_service_checks()
        self.assertNotIn('<meta name="adr-refresh"',page(self.pilot))
        self.assertIn('Confirm outlet action',page(self.pilot))

    def test_protocol_accepts_only_explicit_single_outlet_actions(self):
        box=WattBox({},None);box.channel=Mock();box.channel.recv_ready.return_value=False
        box._line=Mock(return_value='OK')
        for action in ('ON','OFF','RESET'):box.set_power(1,action)
        self.assertEqual([c.args[0] for c in box.channel.sendall.call_args_list],[b'!OutletSet=1,ON\n',b'!OutletSet=1,OFF\n',b'!OutletSet=1,RESET\n'])
        for number,action in [(0,'ON'),(19,'RESET'),(True,'OFF'),(1,'TOGGLE'),(1,'ON\n!RESET')]:
            with self.assertRaises(ValueError):box.set_power(number,action)
        self.assertEqual(box.channel.sendall.call_count,3)

    def test_controller_mapping_requires_fresh_explicit_verification(self):
        self.pilot.controller_pin={'host':'controller.example','port':443,'sha256':'a'*64}
        self.pilot.controller_result={'checked_at':datetime.now(timezone.utc).isoformat(),'access_points':[{'name':'Office','controller_state':'1'}]}
        with self.assertRaises(ProtocolError):self.pilot.confirm_controller_online(False)
        self.assertNotIn('verified_online_codes',self.pilot.controller_pin)
        self.pilot.confirm_controller_online(True)
        self.assertEqual(self.pilot.controller_pin['verified_online_codes'],['1'])
        self.assertEqual((self.root/'ruckus_controller_certificate.json').stat().st_mode&0o777,0o600)
        self.pilot.controller_result['checked_at']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        with self.assertRaises(ProtocolError):self.pilot.confirm_controller_online(True)

    def test_script_hash_and_no_full_page_reload(self):
        self.assertEqual(VIEW_SCRIPT_HASH,__import__('base64').b64encode(hashlib.sha256(VIEW_SCRIPT.encode()).digest()).decode())
        self.pilot.monitor_active=True
        rendered=page(self.pilot)
        self.assertIn('<meta name="adr-refresh" content="60">',rendered)
        self.assertNotIn('http-equiv="refresh"',rendered)
        self.assertIn("fetch('./'",rendered)


class GatewayTests(unittest.TestCase):
    def options(self):return {'unifi_gateway_host':'192.0.2.5','unifi_gateway_api_key':'private-key'}
    def row(self,stamp=None):return {'time':(stamp or datetime.now(timezone.utc)).timestamp()*1000,'download_mbps':918,'upload_mbps':942,'latency_ms':5,'wan_networkgroup':'WAN'}

    def test_mbps_timestamp_selection_and_no_invented_ping(self):
        body={'data':[self.row(),dict(self.row(),wan_networkgroup='WAN2',download_mbps=100),dict(self.row(),status='running')]}
        r=gateway.normalize(body);self.assertEqual(len(r),1);self.assertEqual(r[0]['download'],918);self.assertEqual(r[0]['upload'],942)
        r=gateway.normalize({'data':[dict(self.row(),latency_ms=None)]});self.assertIsNone(r[0]['ping'])
        self.assertEqual(gateway.normalize({'data':[dict(self.row(),download_mbps='nan')]}),[])
        self.assertEqual(gateway.normalize({'data':[dict(self.row(),time=1000)]}),[])

    def test_pin_mismatch_prevents_key_being_sent(self):
        config=gateway.settings(self.options());pin={'host':config['host'],'port':443,'sha256':'a'*64}
        connection=Mock();connection.sock.getpeercert.return_value=b'wrong-cert'
        with patch('unifi_gateway.http.client.HTTPSConnection',return_value=connection):
            with self.assertRaises(gateway.GatewayError):gateway.request(config,pin,'GET','results')
        connection.request.assert_not_called()

    def test_gateway_read_is_get_only_and_no_legacy_source(self):
        request=Mock(return_value={'data':[self.row()]})
        r=gateway.collect(self.options(),{},request)
        self.assertEqual(request.call_args.args[2:],('GET','results'))
        self.assertEqual(r['source'],'unifi_gateway');self.assertEqual(r['readings'][0]['state'],'918.0')
        self.assertNotIn('private-key',json.dumps(r))

    def test_run_posts_exactly_once_and_polls_only_reads(self):
        initial=self.row(datetime.now(timezone.utc)-timedelta(hours=1));new=self.row(datetime.now(timezone.utc)+timedelta(seconds=2))
        def request(c,p,method,op):
            if op=='start':return {'meta':{'rc':'ok'}}
            return {'data':[initial] if request_mock.call_count==1 else [new]}
        request_mock=Mock(side_effect=request)
        result=gateway.run(self.options(),{},request_mock,lambda _:None)
        self.assertTrue(result['fresh_values_confirmed'])
        self.assertEqual(sum(c.args[2]=='POST' for c in request_mock.call_args_list),1)

    def test_no_new_result_never_restarts_test(self):
        old=self.row(datetime.now(timezone.utc)-timedelta(hours=1))
        request=Mock(side_effect=lambda c,p,m,o:{'meta':{'rc':'ok'}} if o=='start' else {'data':[old]})
        result=gateway.run(self.options(),{},request,lambda _:None)
        self.assertFalse(result['fresh_values_confirmed'])
        self.assertEqual(sum(c.args[2]=='POST' for c in request.call_args_list),1)

    def test_history_deduplicates_and_separates_targets(self):
        stamp=datetime.now(timezone.utc).isoformat();store={}
        rows=[{'name':'UniFi speed test Download','state':'918','unit':'Mbit/s','last_updated':stamp}]
        append(store,'one',rows);append(store,'one',rows)
        self.assertEqual(len(store['one'][rows[0]['name']]['points']),1)
        append(store,'two',rows);self.assertNotIn('one',store)
