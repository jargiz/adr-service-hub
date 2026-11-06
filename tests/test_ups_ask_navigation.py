import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'adr_service_agent'))
from dashboard import ups_panel, configure_site_timezone
from agent import Pilot, page


class Elements(HTMLParser):
    def __init__(self):
        super().__init__();self.ids=[];self.links=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if attrs.get('id'):self.ids.append(attrs['id'])
        if tag=='a':self.links.append(attrs)


class UpsAskTests(unittest.TestCase):
    def test_ups_baseline_event_and_receipt_times_are_local_and_distinct(self):
        configure_site_timezone({'site_timezone':'America/New_York'})
        output=ups_panel({'enabled':True,'status':'reported','current':'line_power',
            'listener_connected':True,'last_state':{'reported_at':'2026-11-04T02:46:51+00:00'},
            'events':[{'kind':'baseline','state':'line_power','reported_at':'2026-11-04T02:46:51+00:00','received_at':'2026-11-04T03:05:27+00:00'}]})
        self.assertIn('Utility power reported',output)
        self.assertIn('this is not an outage or restoration',output)
        self.assertIn('9:46 PM EST',output)
        self.assertIn('10:05 PM EST',output)
        self.assertNotIn('UTC',output)

    def test_disconnect_never_displays_old_state_as_current(self):
        output=ups_panel({'enabled':True,'status':'unverified','current':'line_power',
            'listener_connected':False,'error':'<script>bad</script>','events':[]})
        self.assertIn('Power status unverified',output)
        self.assertNotIn('Utility power reported',output)
        self.assertIn('&lt;script&gt;',output)
        self.assertIn('No UPS events recorded',output)

    def test_missing_source_time_not_invented_and_history_bounded(self):
        events=[{'kind':'on_battery','received_at':'2026-11-04T03:10:00+00:00'}]*30
        output=ups_panel({'enabled':True,'events':events})
        self.assertEqual(output.count('Switched to battery'),12)
        self.assertIn('Event time unreported',output)
        self.assertNotIn('Reported Nov',output)

    def test_single_overview_ask_form_and_dedicated_connections_navigation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);options=root/'options.json';options.write_text('{}')
            pilot=Pilot(root,options)
            for running in (False,True):
                pilot.service_running=running
                output=page(pilot);elements=Elements();elements.feed(output)
                self.assertEqual(elements.ids.count('ask-adr'),1)
                self.assertEqual(elements.ids.count('adr-question-form'),1)
                self.assertEqual(elements.ids.count('ups-results'),1)
                self.assertTrue(any('ask-tile' in a.get('class','') and a.get('href')=='#ask-adr' for a in elements.links))
                bottom=output.split('</main>',1)[1].split('</nav>',1)[0]
                self.assertNotIn('class="ask-nav"',bottom)
                self.assertIn('for="view-connections"',bottom)


if __name__=='__main__':unittest.main()

