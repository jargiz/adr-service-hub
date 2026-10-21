import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'adr_service_agent'))
from monitoring import MonitoringSchedule
from agent import Pilot, page
from service_report import run_checks


class MonitoringTests(unittest.TestCase):
    def test_default_schedule_grace_priority_and_no_catchup_queue(self):
        with tempfile.TemporaryDirectory() as d:
            clock=[1000000]
            monitor=MonitoringSchedule({},Path(d)/'state.json',clock=lambda:clock[0])
            calls=[]
            self.assertIsNone(monitor.tick(calls.append));self.assertEqual(calls,[])
            clock[0]+=60
            self.assertEqual(monitor.tick(calls.append),'internet_test')
            self.assertEqual(monitor.tick(calls.append),'service')
            self.assertEqual(calls,['internet_test','service'])
            self.assertIsNone(monitor.tick(calls.append))
            self.assertEqual(monitor.next_due['service'],clock[0]+1200)
            self.assertEqual(monitor.next_due['internet_test'],clock[0]+21600)
            clock[0]+=86400
            monitor.tick(calls.append);monitor.tick(calls.append)
            self.assertIsNone(monitor.tick(calls.append))
            self.assertEqual(len(calls),4)

    def test_busy_defers_and_failure_waits_full_interval(self):
        with tempfile.TemporaryDirectory() as d:
            clock=[1000000]
            monitor=MonitoringSchedule({},Path(d)/'state.json',clock=lambda:clock[0])
            clock[0]+=60;dispatch=Mock(side_effect=RuntimeError('private-secret'))
            self.assertIsNone(monitor.tick(dispatch,busy=True));dispatch.assert_not_called()
            monitor.tick(dispatch)
            self.assertIn('next scheduled interval',monitor.error)
            self.assertNotIn('private-secret',monitor.error)
            self.assertEqual(monitor.next_due['internet_test'],clock[0]+21600)
            monitor.tick(dispatch);self.assertEqual(dispatch.call_count,2)
            self.assertIsNone(monitor.tick(dispatch))

    def test_persisted_attempts_prevent_restart_speedtest_and_manual_resets_due(self):
        with tempfile.TemporaryDirectory() as d:
            clock=[1000000];path=Path(d)/'state.json'
            monitor=MonitoringSchedule({},path,clock=lambda:clock[0])
            monitor.record_start('internet_test');monitor.record_start('service')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            clock[0]+=100
            restarted=MonitoringSchedule({},path,clock=lambda:clock[0])
            self.assertEqual(restarted.next_due['internet_test'],1000000+21600)
            self.assertEqual(restarted.next_due['service'],1000000+1200)
            self.assertIsNone(restarted.tick(Mock()))
            restarted.record_start('internet_test')
            self.assertEqual(restarted.next_due['internet_test'],clock[0]+21600)
            self.assertEqual(set(json.loads(path.read_text())),{'format','last_attempt'})

    def test_corrupt_saved_state_delays_a_full_interval_and_invalid_options_fall_back(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';path.write_text('{broken')
            monitor=MonitoringSchedule({'monitor_interval_minutes':True,'speedtest_interval_minutes':1},path,clock=lambda:1000000)
            self.assertEqual(monitor.next_due['service'],1001200)
            self.assertEqual(monitor.next_due['internet_test'],1021600)
            self.assertTrue(monitor.persistence_error)

    def test_disabled_monitor_or_speedtest_and_custom_intervals(self):
        with tempfile.TemporaryDirectory() as d:
            clock=[1000000];path=Path(d)/'state.json';dispatch=Mock()
            monitor=MonitoringSchedule({'automatic_monitoring':False},path,clock=lambda:clock[0]);clock[0]+=86400
            monitor.tick(dispatch);dispatch.assert_not_called()
            monitor=MonitoringSchedule({'automatic_speedtests':False,'monitor_interval_minutes':30,'speedtest_interval_minutes':120},path,clock=lambda:clock[0])
            clock[0]+=60;monitor.tick(dispatch)
            dispatch.assert_called_once_with('service')
            self.assertFalse(monitor.active('internet_test'))
            self.assertEqual(monitor.intervals,{'service':1800,'internet_test':7200})

    def test_schedule_storage_failure_does_not_hot_retry(self):
        with tempfile.TemporaryDirectory() as d:
            clock=[1000000]
            monitor=MonitoringSchedule({},Path(d)/'missing'/'state.json',clock=lambda:clock[0])
            clock[0]+=60;calls=[];monitor.tick(calls.append);monitor.tick(calls.append)
            self.assertTrue(monitor.persistence_error)
            self.assertIsNone(monitor.tick(calls.append))
            self.assertEqual(calls,['internet_test','service'])


class MonitoringWiringTests(unittest.TestCase):
    def pilot(self,root,options=None):
        (root/'options.json').write_text(json.dumps(options or {}));return Pilot(root,root/'options.json')

    def test_constructor_sends_nothing_and_one_daemon_starts_once(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('agent.run_internet_test') as speed,patch('agent.run_checks') as reads:
                pilot=self.pilot(Path(d));speed.assert_not_called();reads.assert_not_called()
                self.assertIsNone(pilot.monitor_thread)
            with patch('agent.threading.Thread') as thread:
                pilot.start_monitoring();pilot.start_monitoring()
                thread.assert_called_once();self.assertTrue(thread.call_args.kwargs['daemon'])
            self.assertTrue(pilot.monitor_active)

    def test_background_loop_needs_no_open_page_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            pilot=self.pilot(Path(d))
            with patch('agent.threading.Thread') as thread:
                pilot.start_monitoring();loop=thread.call_args.kwargs['target']
            with patch.object(pilot.monitor_stop,'wait',side_effect=[False,True]),patch.object(pilot,'monitoring_tick') as tick:
                loop();tick.assert_called_once()
            self.assertFalse(pilot.monitor_active)

    def test_tick_only_dispatches_existing_read_or_test_not_power_methods(self):
        with tempfile.TemporaryDirectory() as d:
            pilot=self.pilot(Path(d));pilot.monitor.next_due={'service':0,'internet_test':0}
            with patch.object(pilot,'start_service_checks') as report,patch.object(pilot,'start_network_job') as speed,patch.object(pilot,'reboot') as reboot,patch.object(pilot,'check') as power_check:
                self.assertEqual(pilot.monitoring_tick(),'internet_test')
                speed.assert_called_once_with('internet_test',scheduled=True)
                self.assertEqual(pilot.monitoring_tick(),'service')
                report.assert_called_once_with(scheduled=True)
                reboot.assert_not_called();power_check.assert_not_called()

    def test_checks_and_live_power_confirmation_defer_due_run(self):
        with tempfile.TemporaryDirectory() as d:
            pilot=self.pilot(Path(d));pilot.monitor.next_due={'service':0,'internet_test':0}
            for field in ('service_running','internet_test_running','controller_running','active','cp4_running','sense_running'):
                setattr(pilot,field,True)
                with patch.object(pilot,'start_network_job') as speed:
                    self.assertIsNone(pilot.monitoring_tick());speed.assert_not_called()
                setattr(pilot,field,False)
            pilot.confirmations={'pending':(time.monotonic(),{})}
            self.assertIsNone(pilot.monitoring_tick())
            pilot.confirmations={'expired':(time.monotonic()-121,{})}
            with patch.object(pilot,'start_network_job') as speed:
                self.assertEqual(pilot.monitoring_tick(),'internet_test');speed.assert_called_once()

    def test_manual_actions_reset_due_and_latest_report_survives_failed_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            pilot=self.pilot(Path(d))
            old,_=run_checks([('WattBox','test',lambda:{'outlets':[]})],{})
            pilot.service_report=old;pilot.monitor.next_due['service']=0
            with patch('agent.threading.Thread') as thread:
                pilot.start_service_checks();job=thread.call_args.kwargs['target']
            self.assertGreater(pilot.monitor.next_due['service'],time.time()+1100)
            self.assertIs(pilot.service_report,old)
            self.assertIn('WattBox',page(pilot))
            with patch('agent.run_checks',side_effect=RuntimeError('private')):job()
            self.assertIs(pilot.service_report,old)
            self.assertFalse(pilot.service_running)
            self.assertIn('previous report',pilot.service_error)
            pilot.monitor.next_due['internet_test']=0
            with patch('agent.threading.Thread'):pilot.start_network_job('internet_test')
            self.assertGreater(pilot.monitor.next_due['internet_test'],time.time()+21500)

    def test_idle_get_refresh_is_read_only_and_confirmation_page_does_not_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            pilot=self.pilot(Path(d));pilot.monitor_active=True
            with patch.object(pilot,'start_service_checks') as reports,patch.object(pilot,'start_network_job') as speed:
                rendered=page(pilot)
                self.assertIn('content="60;url=./"',rendered)
                self.assertIn('Every 20 minutes',rendered);self.assertIn('Every 6 hours',rendered)
                self.assertNotIn('Home Assistant',rendered)
                self.assertNotIn('http-equiv="refresh"',page(pilot,confirmation='pending'))
                reports.assert_not_called();speed.assert_not_called()
            pilot.internet_test_running=True
            self.assertIn('content="3;url=./"',page(pilot))


if __name__=='__main__':unittest.main()
