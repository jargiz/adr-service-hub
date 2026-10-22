import copy
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'adr_service_agent'))
from internet_quality import failed_latency,quality_issues
from dashboard_visuals import network_panels
from service_report import assess,run_checks
import internet_test
from agent import Pilot,page


def readings(ping='1800000'):
    stamp=(datetime.now(timezone.utc)+timedelta(seconds=2)).isoformat()
    return [{'entity_id':'sensor.test_'+kind,'name':'Speedtest '+kind,'state':value,
        'unit':'ms' if kind=='ping' else 'Mbit/s','last_updated':stamp}
        for kind,value in [('download','347.05'),('upload','100.61'),('ping',ping)]]


class QualityTests(unittest.TestCase):
    def test_exact_failed_probe_value_flagged_without_arbitrary_low_speed_threshold(self):
        for value in ('1800000',1800000,'1800000.0'):
            self.assertTrue(failed_latency(dict(readings()[-1],state=value)))
        for value in ('7','0','25.9','nan',None,'unavailable'):
            self.assertFalse(failed_latency(dict(readings()[-1],state=value)))
        self.assertFalse(failed_latency(dict(readings()[-1],unit='s')))
        self.assertEqual(quality_issues(readings('7')),[])
        self.assertIn('does not establish an ISP fault',quality_issues(readings())[0])

    def test_report_preserves_source_values_but_flags_quality_for_review(self):
        rows=readings();before=copy.deepcopy(rows)
        snapshot={'entry':{'state':'loaded'},'device':{'name':'Gateway'},'sensors':[{'name':'State','state':'connected'}],'internet_readings':rows}
        result=assess('UniFi',snapshot)
        self.assertEqual(result['status'],'review')
        self.assertTrue(any('failed-probe' in note for note in result['service_findings']))
        self.assertEqual(snapshot['internet_readings'],before)
        snapshot['internet_readings']=readings('7')
        self.assertEqual(assess('UniFi',snapshot)['status'],'verified')

    def test_failed_latency_cannot_flatten_gateway_bars_and_speeds_labelled(self):
        sensors=[{'name':'Google WAN latency','state':'5','unit':'ms'}, {'name':'Cloudflare WAN latency','state':'7','unit':'ms'}]
        rendered=network_panels({'UniFi':{'snapshot':{'sensors':sensors,'internet_readings':readings()}}})
        self.assertIn('347.05 Mbit/s',rendered)
        self.assertIn('100.61 Mbit/s',rendered)
        self.assertIn('Needs verification',rendered)
        self.assertIn('Speed-test result needs verification',rendered)
        self.assertIn('width:100.0%',rendered)
        bars=rendered.split('aria-label="Latency comparison in milliseconds"')[1]
        self.assertNotIn('Speedtest ping',bars)
        self.assertNotIn('1800000 ms',bars)
        self.assertIn('5 ms',bars);self.assertIn('7 ms',bars)

    def test_freshness_is_separate_from_failed_measurement_quality(self):
        with patch('internet_test.speedtest_readings',side_effect=[readings('7'),readings()]):
            result=internet_test.run(token='test',post_fn=Mock())
        self.assertTrue(result['fresh_values_confirmed'])
        self.assertEqual(result['measurement_quality'],'review')
        self.assertTrue(result['quality_issues'])
        self.assertIn('failed-probe',result['limitations'][0])

    def test_specific_approval_instruction_shown_and_connection_setup_opened(self):
        failure='Inspect and approve this Ruckus controller certificate first.'
        snapshot={'entry':{'state':'loaded'},'entities':[{'state':'home'}], 'controller_error':failure}
        html=network_panels({'Ruckus':{'snapshot':snapshot}})
        self.assertIn(failure,html)
        self.assertIn('href="#connections"',html)
        self.assertIn('Read Access Points',html)
        self.assertNotIn('Status: <strong>Online',html)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'options.json').write_text('{}');pilot=Pilot(root,root/'options.json')
            pilot.service_report,_=run_checks([('Ruckus','test',lambda:snapshot)],{})
            rendered=page(pilot)
        self.assertIn('id="connections" open',rendered)
        self.assertIn('inspect and approve',rendered)

    def test_external_controller_error_is_escaped(self):
        html=network_panels({'Ruckus':{'snapshot':{'controller_error':'<script>bad</script>'}}})
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;',html)


if __name__=='__main__':unittest.main()
