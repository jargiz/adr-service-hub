import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'adr_service_agent'))
from dashboard import configure_site_timezone, ups_panel
from dashboard_visuals import trend_chart, network_history_charts

class TrendChartTests(unittest.TestCase):
    def setUp(self):configure_site_timezone({'site_timezone':'America/New_York'})
    def series(self, name, values):
        base=datetime(2026,11,1,12,tzinfo=timezone.utc)
        return {'name':name,'unit':'Mbit/s','max_gap_seconds':43200,
                'points':[{'time':(base+timedelta(hours=h)).isoformat(),'value':v} for h,v in values]}
    def test_daily_download_upload_share_axes_and_connect_despite_old_gap_setting(self):
        output=network_history_charts([
            self.series('UniFi speed test Download',[(0,900),(24.1,780),(48.2,938)]),
            self.series('UniFi speed test Upload',[(0,820),(24.1,850),(48.2,830)])], 'UniFi')
        self.assertEqual(output.count('data-trend-card'),1)
        self.assertEqual(output.count('class="trend-line"'),4) # week and all, both series
        self.assertIn('trend-color-1',output)
        self.assertIn('Download</span>',output);self.assertIn('Upload</span>',output)
        self.assertIn('chart-grid',output);self.assertIn('data-trend-range',output)
        self.assertIn('EST',output);self.assertNotIn('UTC',output)
    def test_missing_daily_runs_and_unknown_values_break_trends(self):
        output=trend_chart([self.series('Download',[(0,900),(24,800),(48,None),(72,850),(96,870),(168,910)])], 'History','Mbit/s')
        week=output.split('data-trend-window="day"')[0]
        self.assertEqual(week.count('class="trend-line"'),2)
        self.assertIn('long gaps and unavailable readings',output)
        self.assertNotIn('nan',output)
    def test_sources_are_named_and_untrusted_labels_are_escaped(self):
        output=trend_chart([self.series('<script>x</script>',[(0,781)])], 'Green Ookla <history>','Mbit/s')
        self.assertNotIn('<script>',output);self.assertIn('&lt;history&gt;',output)
        self.assertIn('781 Mbit/s',output)
    def test_ups_uses_event_list_without_inventing_continuous_power(self):
        events=[{'received_at':'2026-11-04T03:00:00+00:00','state':'line_power','kind':'baseline'},
                {'received_at':'2026-11-04T04:00:00+00:00','state':'unverified','kind':'monitoring_gap'},
                {'received_at':'2026-11-04T05:00:00+00:00','state':'on_battery','kind':'on_battery'}]
        output=ups_panel({'enabled':True,'status':'reported','current':'on_battery','events':events})
        self.assertNotIn('<svg class="history-chart"',output)
        self.assertIn('Switched to battery',output)
        self.assertNotIn('class="chart-point"',output);self.assertNotIn('class="chart-line"',output)
        self.assertIn('Monitoring gap',output)

    def test_speed_timeline_keeps_both_series_and_dated_times_without_point_markers(self):
        output=network_history_charts([
            self.series('Green speed test Download',[(0,900),(6,880),(12,920)]),
            self.series('Green speed test Upload',[(0,800),(6,810),(12,830)])],'Green')
        self.assertIn('speed-timeline',output)
        self.assertIn('Both speed series',output)
        self.assertIn('value="day" selected',output)
        self.assertIn('7:00 AM',output)
        self.assertIn('7:00 PM',output)
        self.assertNotIn('<circle',output)
        self.assertIn('data-sample-detail=',output)
        self.assertIn('Download</span>',output)
        self.assertIn('Upload</span>',output)

    def test_single_test_timestamp_is_not_repeated_or_drawn_as_continuous_line(self):
        output=network_history_charts([
            self.series('Download',[(0,900)]),self.series('Upload',[(0,800)])],'Green')
        self.assertNotIn('class="timeline-time"',output)
        self.assertIn('class="speed-latest"',output)
        self.assertNotIn('class="trend-line"',output)
        self.assertIn('More recorded tests will add a timeline.',output)

    def test_empty_duplicate_placeholder_cannot_hide_recorded_upload(self):
        output=network_history_charts([
            self.series('Green speed test Download',[]),
            self.series('Green speed test Upload',[]),
            self.series('Green speed test Download',[(0,900),(6,910)]),
            self.series('Green speed test Upload',[(0,800),(6,810)])],'Green')
        self.assertIn('900 Mbit/s',output)
        self.assertIn('800 Mbit/s',output)
        self.assertEqual(output.count('data-trend-card'),1)

if __name__=='__main__':unittest.main()


