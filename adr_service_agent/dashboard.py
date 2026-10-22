"""Small server-rendered summary cards; every external label is escaped."""
from ui_icons import icon
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


SYSTEM_ICONS = {'WattBox': 'power', 'Sense': 'energy', 'UniFi': 'network',
    'Araknis': 'switch', 'Ruckus': 'wireless', 'Sonos': 'audio', 'Bluesound': 'audio',
    'Crestron': 'home', 'CP4-R': 'processor', 'Control4': 'home'}


def tile_value(name, snapshot, lines):
    if name == 'WattBox':
        outlets = snapshot.get('outlets', [])
        return str(sum(o.get('on') is True for o in outlets)) + ' / ' + str(len(outlets)) + ' outlets on'
    if name in ('Sonos', 'Bluesound', 'Crestron', 'Control4'):
        readings = snapshot.get('readings', snapshot.get('players', []))
        available = sum(r.get('state') not in ('unknown', 'unavailable', 'read failed') for r in readings)
        return str(available) + ' / ' + str(len(readings)) + ' available'
    if name == 'Ruckus' and snapshot.get('controller_error'):
        return 'AP status unverified'
    if name == 'UniFi':
        for sensor in snapshot.get('sensors', []):
            if sensor.get('entity_id', '').endswith('_state'):
                return str(sensor.get('state', 'Unverified')).capitalize()
    return lines[0] if lines else 'No readings'


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
        short_label = {'Service findings to review': 'Review findings', 'Observations to review': 'Review notes'}.get(label, label)
        snapshot = (check or {}).get('snapshot') or {}
        lines = key_readings(name, snapshot) if check else []
        headline = tile_value(name, snapshot, lines) if check else 'Not checked yet'
        stamp = display_time(check.get('completed_at')) if check else ''
        short_stamp = stamp.split('·')[-1].strip()
        output += '<article class="system-card ' + style + (' sense-card' if name == 'Sense' else '') + '"><details class="system-tile"><summary class="tile-summary" aria-label="' + esc(name + ' readings: ' + short_label) + '">'
        output += '<div class="tile-icon-row"><span class="system-icon">' + icon(SYSTEM_ICONS[name]) + '</span><span class="status-dot" aria-hidden="true"></span></div><h3>' + esc(name) + '</h3><span class="badge" aria-label="' + esc(label) + '">' + short_label + '</span>'
        output += '<p class="tile-value">' + esc(headline) + '</p><span class="tile-footer"><span title="' + esc(stamp) + '">' + esc(short_stamp) + '</span>' + icon('chevron') + '</span></summary><div class="tile-body">'
        if check is None:
            output += '<p class="empty-state">Not checked yet.</p></div></details></article>'
            continue
        output += visuals(name, snapshot, lines)
        if lines:
            output += '<div class="metrics">'
            for index, line in enumerate(lines):
                output += '<p class="metric' + (' primary-metric' if index == 0 else '') + '">' + esc(line) + '</p>'
            output += '</div>'
        output += '<p class="collected">Updated ' + esc(stamp) + '</p><div class="card-details">'
        groups = [('Service findings', check.get('service_findings', [])), ('Data limitations', check.get('data_limitations', [])),
            ('Observations', check.get('observations', []) + check.get('comparisons', []))]
        for title, notes in groups:
            if notes:
                output += '<details><summary>' + title + ' <span class="detail-count">' + str(len(notes)) + '</span></summary>'
                for line in notes: output += '<p>' + esc(line) + '</p>'
                output += '</details>'
        history = check.get('historical_observations', [])
        if history:
            output += '<div class="history-note"><strong>Historical observations</strong>'
            for item in history:
                output += '<p>' + esc(display_time(item.get('recorded_at'))) + ' · ' + esc(item.get('subject', '')) + ': ' + esc(item.get('note', '')) + '</p>'
            output += '</div>'
        output += '</div></div></details></article>'
    return output + '</div>'


GROUPS = (('power', 'Power', ('WattBox', 'Sense')),
    ('network', 'Network', ('UniFi', 'Araknis', 'Ruckus')),
    ('av', 'AV & Automation', ('Sonos', 'Bluesound', 'Crestron', 'CP4-R', 'Control4')))


def grouped_cards(report):
    checks = {c['system']: c for c in (report or {}).get('checks', [])}
    output = '<div class="dashboard-groups" id="systems">'
    for key, title in [('all', 'Overview')] + [(k, t) for k, t, _ in GROUPS]:
        output += '<input class="view-radio" type="radio" name="dashboard-view" id="view-' + key + '"' + (' checked' if key == 'all' else '') + ' aria-label="' + title + '">'
    output += '<div class="category-launcher" aria-label="System categories">'
    for key, title, names in GROUPS:
        review = sum(checks.get(name, {}).get('status') == 'review' for name in names)
        read = sum(checks.get(name, {}).get('status') == 'verified' for name in names)
        status = str(review) + ' review' if review else str(read) + ' read' if read else 'Not checked'
        output += '<label class="category-tile category-' + key + '" for="view-' + key + '"><span>' + icon(key if key != 'av' else 'av') + '</span><strong>' + ('AV / Auto' if key == 'av' else title) + '</strong><small>' + status + '</small></label>'
    output += '</div><nav class="group-tabs" aria-label="System views">'
    for key, title in [('all', 'Overview')] + [(k, t) for k, t, _ in GROUPS]:
        output += '<label for="view-' + key + '" aria-label="' + title + '">' + icon('home' if key == 'all' else key) + '<span>' + ('AV / Auto' if key == 'av' else title) + '</span></label>'
    output += '</nav>'
    for key, title, names in GROUPS:
        output += '<div class="system-group group-' + key + '"><div class="section-label"><h2>' + title + '</h2></div>'
        if key == 'network': output += network_panels(checks)
        output += cards(report, names) + '</div>'
    return output + '</div>'
