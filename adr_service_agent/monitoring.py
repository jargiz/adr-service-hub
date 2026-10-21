"""Local recurring monitor. Due times persist; missed runs never accumulate."""
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path


class MonitoringSchedule:
    def __init__(self, options, path, clock=time.time, grace=60):
        self.clock, self.path = clock, Path(path)
        self.enabled = options.get('automatic_monitoring', True) is True
        self.speed_enabled = options.get('automatic_speedtests', True) is True
        self.intervals = {
            'service': self.interval(options, 'monitor_interval_minutes', 20, 5, 1440),
            'internet_test': self.interval(options, 'speedtest_interval_minutes', 360, 60, 10080)}
        self.last_attempt = {}
        self.error = ''
        self.persistence_error = ''
        current = clock()
        try:
            raw = json.loads(self.path.read_text())
            if not isinstance(raw, dict) or raw.get('format') != 'adr-monitoring-v1':
                raise ValueError('Invalid schedule state')
            for kind, value in raw.get('last_attempt', {}).items():
                if kind in self.intervals and type(value) in (int, float) and math.isfinite(value) and 0 <= value <= current + 60:
                    self.last_attempt[kind] = value
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError):
            self.persistence_error = 'Saved monitoring times could not be read. A full interval will pass before automatic checks resume.'
        # Never send a startup burst or replay missed intervals.
        self.next_due = {kind: max(current + (seconds if self.persistence_error else grace),
            self.last_attempt.get(kind, 0) + seconds) for kind, seconds in self.intervals.items()}

    @staticmethod
    def interval(options, key, default, minimum, maximum):
        value = options.get(key, default)
        return (value if type(value) is int and minimum <= value <= maximum else default) * 60

    def active(self, kind):
        return self.enabled and (kind == 'service' or self.speed_enabled)

    def record_start(self, kind):
        current = self.clock()
        self.last_attempt[kind] = current
        self.next_due[kind] = current + self.intervals[kind]
        temp = self.path.with_suffix('.tmp')
        try:
            with temp.open('w', encoding='utf-8') as stream:
                os.chmod(temp, 0o600)
                json.dump({'format': 'adr-monitoring-v1', 'last_attempt': self.last_attempt}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
            self.persistence_error = ''
        except OSError:
            self.persistence_error = 'Monitoring times could not be saved. Restarting may reset the next run times.'

    def tick(self, dispatch, busy=False):
        """Caller serializes this with manual operations using the app lock."""
        if busy or not self.enabled:
            return None
        # A due speed test runs before a due report, so the report can read its results.
        for kind in ('internet_test', 'service'):
            if self.active(kind) and self.clock() >= self.next_due[kind]:
                self.record_start(kind)
                try:
                    dispatch(kind)
                    self.error = ''
                except Exception:
                    self.error = 'An automatic check could not start. It will wait until its next scheduled interval.'
                return kind
        return None

    def next_time(self, kind):
        return datetime.fromtimestamp(self.next_due[kind], timezone.utc).isoformat()
