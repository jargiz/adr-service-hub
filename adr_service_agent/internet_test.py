"""Explicit, scoped speed-test requests through a configured test service."""
import json
import math
import re
from datetime import datetime, timezone
from urllib.request import Request, build_opener, ProxyHandler

from crestron import get_json
from internet_quality import quality_issues
from ruckus import registries, token_value
from sonos import NoRedirect
from unifi import speedtest_readings
from wattbox import ProtocolError


class InternetTestError(ProtocolError):
    pass


def run(token=None, get_fn=get_json, registries_fn=registries, post_fn=None, read_fn=None):
    token = token if token is not None else token_value()
    initial = speedtest_readings(token, get_fn=get_fn, registries_fn=registries_fn, read_fn=read_fn)
    candidates = [r for r in initial if r.get('unit') in ('Mbps', 'Mbit/s') and 'download' in r.get('name', '').casefold()
        and re.fullmatch(r'sensor\.[a-z0-9_]+', r.get('entity_id', ''))]
    if not candidates:
        raise InternetTestError('No configured Internet speed-test service was found. Add Speedtest.net in connection settings, then try again.')
    if len(candidates) != 1:
        raise InternetTestError('More than one speed-test connection is configured. Select a single test connection before running a test.')
    started = datetime.now(timezone.utc).isoformat()
    # One explicit request, targeting a sensor already proven to belong to the test integration.
    target = candidates[0]['entity_id']
    if post_fn:
        post_fn(token, target)
    else:
        request = Request('http://supervisor/core/api/services/homeassistant/update_entity',
            data=json.dumps({'entity_id': target}).encode(),
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=120) as response:
                if response.status != 200 or len(response.read(1024*1024+1)) > 1024*1024:
                    raise ValueError('Invalid service response')
        except Exception:
            raise InternetTestError('Speed-test request did not return a confirmed result. It may still be running; no automatic retry was made.') from None
    readings = speedtest_readings(token, get_fn=get_fn, registries_fn=registries_fn, read_fn=read_fn)
    finished = datetime.now(timezone.utc).isoformat()
    # Successful service completion alone does not prove unchanged stored readings were refreshed.
    fresh = []
    for reading in readings:
        stamp = reading.get('last_updated')
        try:
            value = float(reading.get('state'))
            fresh.append(math.isfinite(value) and value >= 0 and datetime.fromisoformat(str(stamp).replace('Z', '+00:00')) >= datetime.fromisoformat(started))
        except (ValueError, TypeError): fresh.append(False)
    required = all(any(word in r.get('name', '').casefold() and r.get('unit') in ('Mbps', 'Mbit/s') for r in readings) for word in ('download', 'upload'))
    confirmed = required and bool(readings) and all(fresh)
    issues = quality_issues(readings)
    return {'started_at': started, 'completed_at': finished, 'readings': readings,
        'fresh_values_confirmed': confirmed, 'quality_issues': issues,
        'measurement_quality': 'review' if issues else 'no issue established',
        'note': 'Measured from the service host. This is not a measurement of subscribed ISP plan speed or phone Wi-Fi speed.',
        'limitations': issues + ([] if confirmed else ['The test request completed, but fresh timestamps were not confirmed for every value. Stored readings remain unverified.'])}
