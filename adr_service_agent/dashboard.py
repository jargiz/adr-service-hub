"""Small server-rendered summary cards; every external label is escaped."""
import html
import re

SYSTEMS = ('WattBox', 'Sonos', 'Bluesound', 'Ruckus', 'UniFi', 'Crestron', 'Control4', 'Araknis', 'CP4-R')


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
    elif name == 'UniFi':
        lines.append(str((snapshot.get('device') or {}).get('name', 'Device not selected')))
        for sensor in snapshot.get('sensors', []):
            if sensor.get('state') not in ('unknown', 'unavailable', 'read failed'):
                lines.append(str(sensor.get('name', 'Sensor')) + ': ' + str(sensor.get('state')) + (' ' + str(sensor['unit']) if sensor.get('unit') else ''))
    elif name == 'Ruckus':
        aps = [d for d in snapshot.get('devices', []) if str(d.get('manufacturer', '')).casefold() == 'ruckus']
        lines.append(str(len(aps)) + ' Ruckus devices in HA registry; AP health unverified')
        lines.append(str(len(snapshot.get('entities', []))) + ' HA readings')
    else:
        readings = snapshot.get('readings', snapshot.get('players', []))
        available = sum(r.get('state') not in ('unknown', 'unavailable', 'read failed') for r in readings)
        lines.append(str(available) + '/' + str(len(readings)) + ' usable HA states')
        if name == 'Crestron':
            lights = [r for r in readings if r.get('entity_id', '').startswith('light.')]
            lines.append(str(sum(r.get('state') == 'on' for r in lights)) + '/' + str(len(lights)) + ' lights reported on')
        elif name in ('Bluesound', 'Sonos'):
            for reading in readings[:8]:
                lines.append(str(reading.get('name', 'Player')) + ': ' + str(reading.get('state', 'unknown')))
    return lines[:8]


def cards(report):
    esc = lambda x: html.escape(str(x), quote=True)
    checks = {c['system']: c for c in (report or {}).get('checks', [])}
    output = '<div class="system-grid">'
    for name in SYSTEMS:
        check = checks.get(name)
        if check is None:
            output += '<article class="system-card"><h3>' + esc(name) + '</h3><span class="badge">Not checked</span><p>Run All Checks to collect a snapshot.</p></article>'
            continue
        service, limits = check.get('service_findings', []), check.get('data_limitations', [])
        if service:
            label, style = 'Service findings to review', 'review'
        elif check['status'] == 'unverified':
            label, style = 'Unverified', 'unverified'
        elif check['status'] == 'review':
            label, style = 'Observations to review', 'observation'
        else:
            label, style = 'Read completed', 'verified'
        output += '<article class="system-card ' + style + '"><h3>' + esc(name) + '</h3><span class="badge">' + label + '</span>'
        for line in key_readings(name, check.get('snapshot')):
            output += '<p class="metric">' + esc(line) + '</p>'
        output += '<p><small>Collected ' + esc(check.get('completed_at') or 'Time unreported') + '</small></p>'
        groups = [('Service findings', service), ('Data limitations', limits),
            ('Observations and comparisons', check.get('observations', []) + check.get('comparisons', []))]
        for title, lines in groups:
            if lines:
                output += '<details><summary>' + title + ' (' + str(len(lines)) + ')</summary>'
                for line in lines: output += '<p>' + esc(line) + '</p>'
                output += '</details>'
        history = check.get('historical_observations', [])
        if history:
            output += '<div class="history-note"><strong>Historical observations</strong>'
            for item in history:
                output += '<p>' + esc(item.get('recorded_at', '')) + ' · ' + esc(item.get('subject', '')) + ': ' + esc(item.get('note', '')) + '</p>'
            output += '<small>Historical context does not dismiss new symptoms or suppress findings.</small></div>'
        output += '</article>'
    return output + '</div>'
