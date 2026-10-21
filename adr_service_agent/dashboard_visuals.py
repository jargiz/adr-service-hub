"""Read-only snapshot charts. Missing measurements never become zero or online."""
import html
import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def esc(value):
    return html.escape(str(value), quote=True)


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def gauge(label, value):
    value = number(value)
    if value is None or not 0 <= value <= 100:
        return ''
    text = f'{value:g}%'
    return ('<div class="gauge"><svg viewBox="0 0 120 100" role="img" aria-label="' + esc(label + ': ' + text) + '">'
        '<title>' + esc(label + ': ' + text) + '</title><circle cx="60" cy="46" r="35" class="gauge-track"/>'
        '<circle cx="60" cy="46" r="35" class="gauge-fill" pathLength="100" stroke-dasharray="' + str(value) + ' 100" transform="rotate(-90 60 46)"/>'
        '<text x="60" y="47" class="gauge-value" text-anchor="middle">' + text + '</text>'
        '<text x="60" y="64" class="gauge-label" text-anchor="middle">' + esc(label) + '</text></svg></div>')


def visuals(name, snapshot, lines):
    if not snapshot:
        return ''
    output = ''
    if name in ('Araknis', 'CP4-R', 'UniFi'):
        gauges = ''
        if name == 'UniFi':
            for sensor in snapshot.get('sensors', []):
                label = str(sensor.get('name', '')).lower()
                if sensor.get('unit') == '%' and ('cpu utilization' in label or 'memory utilization' in label):
                    gauges += gauge('CPU' if 'cpu' in label else 'Memory', sensor.get('state'))
        else:
            for line in lines:
                match = re.fullmatch(r'(CPU|RAM) (\d+(?:\.\d+)?)%(?: in use)?', line)
                if match:
                    gauges += gauge('Memory' if match[1] == 'RAM' else 'CPU', match[2])
        if gauges:
            output += '<div class="gauges">' + gauges + '</div>'
    if name == 'Araknis':
        for reading in snapshot.get('readings', []):
            if reading.get('command') != 'show power detail' or reading.get('status') != 'response received' or reading.get('error') or reading.get('truncated'):
                continue
            text = reading.get('response', '')
            total = re.search(r'Total Power\s*:\s*([\d.]+) Watts', text)
            used = re.search(r'Total Power Consumed\s*:\s*([\d.]+) Watts', text)
            if total and used:
                maximum, consumed = number(total[1]), number(used[1])
                if maximum and consumed is not None and 0 <= consumed <= maximum:
                    output += '<div class="budget"><span>PoE budget · ' + f'{consumed:g} / {maximum:g} W' + '</span><meter min="0" max="' + str(maximum) + '" value="' + str(consumed) + '" aria-label="PoE power consumed">' + str(consumed) + ' W</meter></div>'
    if name == 'WattBox':
        output += '<div class="outlet-strip" aria-label="Reported outlet power">'
        for outlet in snapshot.get('outlets', [])[:32]:
            state = 'on' if outlet.get('on') is True else 'off' if outlet.get('on') is False else 'unknown'
            output += '<span class="outlet-' + state + '" title="' + esc(str(outlet.get('label', 'Outlet')) + ': ' + state) + '">' + esc(outlet.get('number', '·')) + '</span>'
        output += '</div><small>Reported outlet power only</small>'
    if name == 'Sense':
        series = snapshot.get('history', {}).get('series', [])
        output += '<div class="sense-history"><h4>Past 24 hours</h4>'
        if not series:
            output += '<p class="empty-state">No recorded Sense history received yet.</p>'
        for item in series[:6]:
            output += history_chart(item)
        output += '<small>HA recorder history · Missing samples remain gaps. Sampled voltage does not establish transient power quality.</small></div>'
    return output


def history_chart(series):
    points = series.get('points', [])[:2000]
    parsed = []
    for item in points:
        try:
            stamp = datetime.fromisoformat(str(item.get('time', '')).replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                continue
            parsed.append((stamp.timestamp(), number(item.get('value'))))
        except (ValueError, TypeError):
            continue
    parsed.sort()
    valid = [(t, v) for t, v in parsed if v is not None]
    title = esc(series.get('name', 'Sense sensor'))
    unit = esc(series.get('unit', ''))
    output = '<div class="sense-series"><h4>' + title + ' <small>' + unit + '</small></h4>'
    if not valid:
        return output + '<p class="empty-state">' + esc(series.get('status', 'History unavailable')) + '</p></div>'
    low, high = min(v for _, v in valid), max(v for _, v in valid)
    xmin, xmax = min(t for t, _ in parsed), max(t for t, _ in parsed)
    span = high - low
    ymin, ymax = (low - span * .1, high + span * .1) if span else (low - max(abs(low)*.01, .1), high + max(abs(high)*.01, .1))
    segments, active = [], []
    previous = None
    for stamp, value in parsed:
        # Do not draw across explicit unavailable states or long sampling gaps.
        if value is None or (previous is not None and stamp - previous > 900):
            if active: segments.append(active)
            active = []
        if value is not None:
            x = 38 + (stamp-xmin) / max(xmax-xmin, 1) * 250
            y = 95 - (value-ymin) / (ymax-ymin) * 72
            active.append((x, y))
        previous = stamp
    if active: segments.append(active)
    output += '<svg class="history-chart" viewBox="0 0 308 136" role="img" aria-label="' + title + ' history, ' + f'{low:g} to {high:g} ' + unit + '"><title>' + title + ' history</title>'
    output += '<path d="M38 18V102H290" class="chart-axis"/>'
    for segment in segments:
        if len(segment) == 1:
            x, y = segment[0]
            output += f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" class="chart-point"/>'
        else:
            coords = ' '.join(('M' if i == 0 else 'L') + f'{x:.2f},{y:.2f}' for i, (x, y) in enumerate(segment))
            output += '<path d="' + coords + '" class="chart-line"/>'
    output += '<text x="33" y="27" text-anchor="end">' + f'{high:.3g}' + '</text><text x="33" y="99" text-anchor="end">' + f'{low:.3g}' + '</text>'
    try:
        zone = ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    first = datetime.fromtimestamp(xmin, zone)
    last = datetime.fromtimestamp(xmax, zone)
    start, end = first.strftime('%H:%M'), last.strftime('%H:%M')
    output += '<text x="38" y="122">' + start + '</text><text x="288" y="122" text-anchor="end">' + end + '</text></svg>'
    output += '<small>Range ' + f'{low:g}–{high:g} ' + unit + ' · ' + str(len(valid)) + ' samples · ' + last.strftime('%Z') + (' · partial history' if series.get('truncated') else '') + '</small></div>'
    return output


def network_panels(checks):
    uni = (checks.get('UniFi') or {}).get('snapshot') or {}
    ruckus = (checks.get('Ruckus') or {}).get('snapshot') or {}
    sensors = uni.get('sensors', []) + uni.get('internet_readings', [])
    def metric(words, unit, speed=False):
        for sensor in sensors:
            label = str(sensor.get('name', '')).lower()
            if all(word in label for word in words) and (not speed or 'speedtest' in label or 'speed test' in label):
                value = number(sensor.get('state'))
                if value is not None and value >= 0 and sensor.get('unit') in unit:
                    return f'{value:g} ' + esc(sensor['unit'])
        return 'Unverified'
    output = '<div class="network-panels"><section class="internet-panel"><h3>Internet</h3><p class="subtitle">Gateway-reported readings · No speed tests are triggered</p><div class="internet-metrics">'
    for label, value in [('Download speed test', metric(('download',), ('Mbps', 'Mbit/s'), True)),
        ('Upload speed test', metric(('upload',), ('Mbps', 'Mbit/s'), True)),
        ('Cloudflare latency', metric(('cloudflare', 'latency'), ('ms',))),
        ('Google latency', metric(('google', 'latency'), ('ms',)))]:
        output += '<div><span>' + label + '</span><strong>' + value + '</strong></div>'
    output += '</div>'
    latency = []
    for sensor in sensors:
        label = str(sensor.get('name', ''))
        value = number(sensor.get('state'))
        if sensor.get('unit') == 'ms' and ('latency' in label.lower() or 'ping' in label.lower()) and value is not None and value >= 0:
            latency.append((label, value))
    if latency:
        ceiling = max(max(value for _, value in latency), 1)
        output += '<div class="latency-bars" aria-label="Latency comparison in milliseconds">'
        for label, value in latency[:8]:
            output += '<div class="latency-bar-row"><span>' + esc(label) + '</span><div class="latency-bar-track"><span style="width:' + str(value / ceiling * 100) + '%"></span></div><strong>' + f'{value:g} ms' + '</strong></div>'
        output += '</div>'
    output += '<small>ISP plan speed is not configured. Missing measurements are not zero.</small></section><h3 class="ap-heading">Registered access points</h3><div class="ap-grid">'

    aps = [d for d in ruckus.get('devices', []) if str(d.get('manufacturer', '')).casefold() == 'ruckus' and re.fullmatch(r'r\d+[a-z]*', str(d.get('model', '')).lower())]
    if not aps:
        output += '<p class="empty-state">Run checks to discover registered access points.</p>'
    for ap in aps[:32]:
        output += '<div class="ap-card"><h4>' + esc(ap.get('name', 'Access point')) + '</h4><small>' + esc(ap.get('model', '')) + '</small><p>Status: <strong>Unverified</strong></p><p>Connected devices: <strong>Unverified</strong></p><small>The current Ruckus HA snapshot does not establish per-AP status or counts.</small></div>'
    return output + '</div></div>'
