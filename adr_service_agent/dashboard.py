"""Small server-rendered summary cards; every external label is escaped."""
import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dashboard_visuals import visuals, network_panels

SYSTEMS = ('WattBox', 'Sonos', 'Bluesound', 'Ruckus', 'UniFi', 'Crestron', 'Control4', 'Araknis', 'CP4-R', 'Sense')


def key_readings(name, snapshot):
    if not snapshot:
        return []
    lines = []
    if name == 'WattBox':
        outlets = snapshot.get('outlets', [])
        lines = [str(snapshot.get('model', 'Model unreported')),
            str(sum(o.get('on') is True for o in outlets)) + '/' + str(len(outlets)) + ' outlets reported on']
    elif name in ('Araknis', 'CP4-R'):
        for item in snapshot.get('readings', []):
            if item.get('error') or item.get('truncated') or item.get('status') != 'response received':
                continue
            command, text = item.get('command'), item.get('response', '')
            if name == 'Araknis' and command == 'show env all':
                for label, pattern in [('CPU', r'Current CPU Usage\s*:\s*(\d+%)'), ('RAM', r'RAM Threshold[^\n]*\n[^\n]*\n\s*\d+%\s+(\d+%)')]:
                    m = re.search(pattern, text)
                    if m: lines.append(label + ' ' + m.group(1))
                for unit, temp in re.findall(r'Thermal\s+(\d+)\s+\d+C\s+(\d+C)', text):
                    lines.append('Thermal ' + unit + ': ' + temp)
            if name == 'Araknis' and command == 'show power detail':
                m = re.search(r'Total Power Consumed\s*:\s*([\d.]+ Watts)', text)
                if m: lines.append('PoE ' + m.group(1))
            if name == 'CP4-R' and command == 'SYSTEMREADY':
                m = re.search(r'SystemReady:\s*(True|False)', text, re.I)
                if m: lines.append('System ready: ' + m.group(1))
            if name == 'CP4-R' and command == 'RAMFREE':
                m = re.search(r'(\d+) percent of memory in use', text)
                if m: lines.append('RAM ' + m.group(1) + '% in use')
            if name == 'CP4-R' and command in ('UPTIME', 'PROGUPTIME'):
                m = re.search(r'has been running for ([^\r\n]+)', text)
                if m: lines.append(('System' if command == 'UPTIME' else 'Program') + ' uptime: ' + m.group(1).strip())
    elif name == 'Sense':
        readings = snapshot.get('main_monitor_readings') or snapshot.get('readings', [])
        chosen = sorted(readings, key=lambda r: (0 if r.get('attributes', {}).get('device_class') == 'voltage' else 1 if any(t in (r.get('entity_id', '') + ' ' + r.get('name', '')).lower() for t in ('usage', 'consumption')) else 2, r.get('entity_id', '')))
        lines = [str(r.get('name', r.get('entity_id', 'Sense sensor'))) + ': ' + str(r.get('state', 'unknown')) + ' ' + str(r.get('attributes', {}).get('unit_of_measurement', '')) for r in chosen[:8]]
    elif name == 'UniFi':
        lines.append(str((snapshot.get('device') or {}).get('name', 'Device not selected')))
        for sensor in snapshot.get('sensors', []):
            if sensor.get('state') not in ('unknown', 'unavailable', 'read failed'):
                lines.append(str(sensor.get('name', 'Sensor')) + ': ' + str(sensor.get('state')) + (' ' + str(sensor['unit']) if sensor.get('unit') else ''))
    elif name == 'Ruckus':
        aps = [d for d in snapshot.get('devices', []) if str(d.get('manufacturer', '')).casefold() == 'ruckus']
        lines.append(str(len(aps)) + ' registered devices')
        lines.append(str(len(snapshot.get('entities', []))) + ' device readings')
        if snapshot.get('controller') is not None:
            direct = snapshot['controller'].get('access_points', [])
            lines[0] = str(len(direct)) + ' access points read directly from controller'
            lines.append(str(sum(ap.get('online') is True for ap in direct)) + ' online; ' + str(sum(ap.get('online') is False for ap in direct)) + ' offline; ' + str(sum(ap.get('online') is None for ap in direct)) + ' unverified')
    else:
        readings = snapshot.get('readings', snapshot.get('players', []))
        available = sum(r.get('state') not in ('unknown', 'unavailable', 'read failed') for r in readings)
        lines.append(str(available) + '/' + str(len(readings)) + ' readings available')
        if name == 'Crestron':
            lights = [r for r in readings if r.get('entity_id', '').startswith('light.')]
            lines.append(str(sum(r.get('state') == 'on' for r in lights)) + '/' + str(len(lights)) + ' lights reported on')
        elif name in ('Bluesound', 'Sonos'):
            for reading in readings[:8]:
                lines.append(str(reading.get('name', 'Player')) + ': ' + str(reading.get('state', 'unknown')))
    return lines[:8]


def display_time(value):
    """Compact Eastern time for the dashboard; raw report timestamps stay intact."""
    if not value:
        return 'Time unreported'
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            return str(value)
        try:
            stamp = stamp.astimezone(ZoneInfo('America/New_York'))
        except ZoneInfoNotFoundError:
            pass
        return stamp.strftime('%b %d · %I:%M %p %Z').replace(' 0', ' ')
    except (ValueError, TypeError):
        return str(value)


CATEGORIES = {
    'WattBox': ('PW', 'Power management'), 'Sonos': ('SO', 'Audio'),
    'Bluesound': ('BL', 'Audio'), 'Ruckus': ('RU', 'Wireless'),
    'UniFi': ('UN', 'Network gateway'), 'Crestron': ('CR', 'Home automation'),
    'Control4': ('C4', 'Home automation'), 'Araknis': ('AR', 'Network switch'),
    'CP4-R': ('CP', 'Control processor'), 'Sense': ('SE', 'Energy & line voltage'),
}


def cards(report, names=SYSTEMS):
    esc = lambda x: html.escape(str(x), quote=True)
    checks = {c['system']: c for c in (report or {}).get('checks', [])}
    output = '<div class="system-grid">'
    for name in names:
        check = checks.get(name)
        if check is None:
            label, style = 'Not checked', 'pending'
        elif check.get('service_findings'):
            label, style = 'Service findings to review', 'review'
        elif check['status'] == 'unverified':
            label, style = 'Unverified', 'unverified'
        elif check['status'] == 'review':
            label, style = 'Observations to review', 'observation'
        else:
            label, style = 'Read completed', 'verified'
        monogram, category = CATEGORIES[name]
        output += '<article class="system-card ' + style + (' sense-card' if name == 'Sense' else '') + '"><header class="card-heading"><span class="system-icon" aria-hidden="true">' + monogram + '</span><div><h3>' + esc(name) + '</h3></div><span class="status-dot" aria-hidden="true"></span></header><span class="badge">' + label + '</span>'
        if check is None:
            output += '<p class="empty-state">Not checked yet.</p></article>'
            continue
        service, limits = check.get('service_findings', []), check.get('data_limitations', [])
        lines = key_readings(name, check.get('snapshot'))
        output += visuals(name, check.get('snapshot'), lines)
        if lines:
            output += '<div class="metrics">'
            for index, line in enumerate(lines):
                output += '<p class="metric' + (' primary-metric' if index == 0 else '') + '">' + esc(line) + '</p>'
            output += '</div>'
        output += '<p class="collected">Updated ' + esc(display_time(check.get('completed_at'))) + '</p>'
        groups = [('Service findings', service), ('Data limitations', limits),
            ('Observations', check.get('observations', []) + check.get('comparisons', []))]
        output += '<div class="card-details">'
        for title, lines in groups:
            if lines:
                output += '<details><summary>' + title + ' <span class="detail-count">' + str(len(lines)) + '</span></summary>'
                for line in lines: output += '<p>' + esc(line) + '</p>'
                output += '</details>'
        history = check.get('historical_observations', [])
        if history:
            output += '<div class="history-note"><strong>Historical observations</strong>'
            for item in history:
                output += '<p>' + esc(display_time(item.get('recorded_at'))) + ' · ' + esc(item.get('subject', '')) + ': ' + esc(item.get('note', '')) + '</p>'
            output += '<small>Historical context does not dismiss new symptoms or suppress findings.</small></div>'
        output += '</div></article>'
    return output + '</div>'


GROUPS = (('power', 'Power', ('WattBox', 'Sense')),
    ('network', 'Network', ('UniFi', 'Araknis', 'Ruckus')),
    ('av', 'AV & Automation', ('Sonos', 'Bluesound', 'Crestron', 'CP4-R', 'Control4')))


def grouped_cards(report):
    checks = {c['system']: c for c in (report or {}).get('checks', [])}
    output = '<div class="dashboard-groups">'
    for key, title in [('all', 'Overview')] + [(k, t) for k, t, _ in GROUPS]:
        output += '<input class="view-radio" type="radio" name="dashboard-view" id="view-' + key + '"' + (' checked' if key == 'all' else '') + ' aria-label="' + title + '">'
    output += '<div class="group-tabs" aria-label="System categories">'
    for key, title in [('all', 'Overview')] + [(k, t) for k, t, _ in GROUPS]:
        output += '<label for="view-' + key + '">' + title + '</label>'
    output += '</div>'
    for key, title, names in GROUPS:
        output += '<div class="system-group group-' + key + '"><div class="section-label"><h2>' + title + '</h2></div>'
        if key == 'network': output += network_panels(checks)
        output += cards(report, names) + '</div>'
    return output + '</div>'
