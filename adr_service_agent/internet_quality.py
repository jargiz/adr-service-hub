"""Recognize known failed-probe values without inventing corrected measurements."""
import math


def failed_latency(reading):
    label = (str(reading.get('name', '')) + ' ' + str(reading.get('entity_id', ''))).casefold()
    if reading.get('unit') != 'ms' or not any(word in label for word in ('ping', 'latency')):
        return False
    try:
        value = float(reading.get('state'))
        # speedtest-cli get_best_server adds 3600 for each failed latency
        # request; three failures yield (3 * 3600 / 6) * 1000 = 1800000.
        # https://github.com/sivel/speedtest-cli/blob/master/speedtest.py
        return math.isfinite(value) and value == 1800000
    except (ValueError, TypeError):
        return False


def quality_issues(readings):
    if any(failed_latency(reading) for reading in readings):
        return ['Speed-test ping reports 1,800,000 ms, matching a failed-probe value from the test software. Verify the test server and associated bandwidth readings; this does not establish an ISP fault.']
    return []
