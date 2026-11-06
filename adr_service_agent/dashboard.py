"""Small server-rendered summary cards; every external label is escaped."""
from ui_icons import icon
import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dashboard_visuals import visuals, network_panels, history_chart
from network_health import summary as network_summary
from bluesound import zone_rows as bluesound_zones

SYSTEMS = ('WattBox', 'Sonos', 'Bluesound', 'Ruckus', 'UniFi', 'Crestron', 'Control4', 'Araknis', 'CP4-R', 'Sense', 'Internet')


SITE_TIMEZONE = 'America/New_York'


def configure_site_timezone(options):
    global SITE_TIMEZONE
    value=options.get('site_timezone','America/New_York')
    try:
        if not isinstance(value,str) or len(value)>80:raise ValueError()
        ZoneInfo(value)
        SITE_TIMEZONE=value
    except (ValueError,KeyError):
        SITE_TIMEZONE=None


def site_timezone_name():
    return SITE_TIMEZONE or 'invalid'


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
    elif name == 'Internet':
        lines.append('Measured from Green')
        for r in snapshot.get('readings', []):
            lines.append(str(r['name'])+': '+str(r['state'])+' '+str(r['unit']))
        for p in snapshot.get('probes', []):
            lines.append(p['name']+': '+(str(p['loss_percent'])+'% ICMP loss in 5 probes' if p.get('loss_percent') is not None else 'probe unverified'))
        lines.append('DNS: '+snapshot.get('dns',{}).get('status','unverified'))
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
    elif name == 'Bluesound':
        zones=bluesound_zones(snapshot)
        count=snapshot.get('zone_count',len(zones) if zones else None)
        lines.append(str(count)+' zones found' if count is not None else 'Zone count unverified')
        for zone in zones[:7]:
            lines.append(str(zone.get('name','Zone'))+': '+str(zone.get('state','unknown')))
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
    if snapshot.get('network_health'):
        lines = network_summary(snapshot['network_health']) + lines
    return lines[:8]


def display_time(value):
    """Site-local time for the dashboard; raw report timestamps stay intact."""
    if not value:
        return 'Time unreported'
    if SITE_TIMEZONE is None:
        return 'Configure site timezone'
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            return str(value)
        try:
            stamp = stamp.astimezone(ZoneInfo(SITE_TIMEZONE))
        except ZoneInfoNotFoundError:
            return 'Configure site timezone'
        return stamp.strftime('%b %d · %I:%M %p %Z').replace(' 0', ' ')
    except (ValueError, TypeError):
        return str(value)


CATEGORIES = {
    'Internet': ('IN', 'Measured from Green'),
    'WattBox': ('PW', 'Power management'), 'Sonos': ('SO', 'Audio'),
    'Bluesound': ('BL', 'Audio'), 'Ruckus': ('RU', 'Wireless'),
    'UniFi': ('UN', 'Network gateway'), 'Crestron': ('CR', 'Home automation'),
    'Control4': ('C4', 'Home automation'), 'Araknis': ('AR', 'Network switch'),
    'CP4-R': ('CP', 'Control processor'), 'Sense': ('SE', 'Energy & line voltage'),
}


SYSTEM_ICONS = {'Internet': 'network', 'WattBox': 'power', 'Sense': 'energy', 'UniFi': 'network',
    'Araknis': 'switch', 'Ruckus': 'wireless', 'Sonos': 'audio', 'Bluesound': 'audio',
    'Crestron': 'home', 'CP4-R': 'processor', 'Control4': 'home'}


def tile_value(name, snapshot, lines):
    if name == 'Bluesound':
        zones=bluesound_zones(snapshot)
        count=snapshot.get('zone_count',len(zones) if zones else None)
        if count is None:return 'Zone count unverified'
        states=sum(z.get('state') not in (None,'unknown','unavailable','read failed','not read','disabled') for z in zones)
        return str(count)+' zones · '+str(states)+' states available'
    if name == 'Internet':
        values=[]
        for kind in ('download','upload'):
            row=next((r for r in snapshot.get('readings',[]) if kind in r.get('name','').lower() and r.get('unit') in ('Mbit/s','Mbps')),None)
            values.append(kind.capitalize()+': '+(str(row['state'])+' '+row['unit'] if row else 'unverified'))
        return ' · '.join(values)
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


def cards(report, names=SYSTEMS, outlet_controls=""):
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
        stamp = display_time(check.get('post_action_verified_at') or check.get('completed_at')) if check else ''
        short_stamp = stamp.split('·')[-1].strip()
        status = check.get('status', 'unverified') if check else 'pending'
        output += '<article id="system-' + esc(name.lower()) + '" data-check-status="' + esc(status) + '" class="system-card ' + style + (' sense-card' if name == 'Sense' else '') + '"><details class="system-tile"'+(' open' if name=='Internet' else '')+'><summary class="tile-summary" aria-label="' + esc(name + ' readings: ' + short_label) + '">'
        output += '<div class="tile-icon-row"><span class="system-icon">' + icon(SYSTEM_ICONS[name]) + '</span></div><h3>' + esc(name) + '</h3><span class="badge" aria-label="' + esc(label) + '">' + short_label + '</span>'
        output += '<p class="tile-value">' + esc(headline) + '</p><span class="tile-footer"><span title="' + esc(stamp) + '">' + esc(short_stamp) + '</span>' + icon('chevron') + '</span></summary><div class="tile-body">'
        if check is None:
            output += '<p class="empty-state">Not checked yet.</p></div></details></article>'
            continue
        output += visuals(name, snapshot, lines)
        if name == 'WattBox': output += outlet_controls
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
    ('network', 'Network', ('Internet', 'UniFi', 'Araknis', 'Ruckus')),
    ('av', 'AV/Automation', ('Sonos', 'Bluesound', 'Crestron', 'CP4-R', 'Control4')))


def ups_panel(status):
    esc = lambda value: html.escape(str(value), quote=True)
    labels = {'line_power':'Utility power reported', 'on_battery':'Running on battery', 'unverified':'Power status unverified'}
    kinds = {'baseline':'Monitoring baseline', 'on_battery':'Switched to battery',
        'line_power_restored':'Returned to utility power', 'status_unverified':'Power status unverified',
        'monitoring_gap':'Monitoring gap', 'low_battery':'Low battery reported',
        'replace_battery':'Replace battery reported', 'forced_shutdown':'Forced shutdown reported',
        'shutdown':'Shutdown reported', 'communications_restored':'Communication restored'}
    output = '<section id="ups-results" class="ups-panel"><header class="ups-heading"><span class="system-icon">'+icon('power')+'</span><h3>UPS</h3></header>'
    if not status.get('enabled'):
        return output+'<p class="report-caption">USB UPS monitoring is not configured. Select the UPS status reading in Configuration.</p></section>'
    current = status.get('current') if status.get('status') == 'reported' else 'unverified'
    tone = 'utility' if current == 'line_power' else 'battery' if current == 'on_battery' else 'unknown'
    output += '<div class="ups-status ups-status-'+tone+'"><span class="ups-status-label">Latest reported state</span><strong>'+esc(labels.get(current, labels['unverified']))+'</strong>'
    last = status.get('last_state') or {}
    if last:
        output += '<span>Last status report: '+esc(display_time(last.get('reported_at') or last.get('received_at')))+'</span>'
    output += '</div><p class="ups-monitor-note">'+('Monitor connected · Last report shown above.' if status.get('listener_connected') else 'Monitor disconnected · Current power status is unverified.')+'</p>'
    if status.get('error'):
        output += '<p class="measurement-warning">'+esc(status['error'])+'</p>'
    events = status.get('events', [])[-12:]
    significant = [item for item in events if item.get('kind') not in ('baseline', 'communications_restored')]
    baseline = [item for item in events if item.get('kind') in ('baseline', 'communications_restored')]
    def event_row(item):
        kind = item.get('kind', '')
        tone = 'battery' if kind in ('on_battery','low_battery','replace_battery','forced_shutdown','shutdown') else 'utility' if kind == 'line_power_restored' else 'unknown'
        row = '<li class="ups-event ups-event-'+tone+'"><div><strong>'+esc(kinds.get(kind, 'UPS observation'))+'</strong>'
        if kind == 'baseline':
            row += '<span>'+esc(labels.get(item.get('state'), labels['unverified']))+'; this is not an outage or restoration.</span>'
        if item.get('reported_at'):
            row += '<span>Reported '+esc(display_time(item['reported_at']))+'</span>'
        else:
            row += '<span>Event time unreported</span>'
        return row+'<small>Received '+esc(display_time(item.get('received_at')))+'</small></div></li>'
    output += '<div class="ups-event-heading"><h4>Power events</h4><span>Latest recorded</span></div>'
    if significant:
        output += '<ol class="ups-event-list">'+''.join(event_row(item) for item in reversed(significant))+'</ol>'
    elif not events:
        output += '<p class="ups-empty">No UPS events recorded yet.</p>'
    else:
        output += '<p class="ups-empty">No battery transfers or power restorations recorded in the displayed history.</p>'
    if baseline:
        output += '<details class="ups-events"><summary>Monitoring activity · '+str(len(baseline))+'</summary><ol class="ups-event-list">'+''.join(event_row(item) for item in reversed(baseline))+'</ol></details>'
    output += '<p class="report-caption">Monitoring gaps and brief events can be missed. Times are reported events, not continuous power measurements.</p></section>'
    return output



def grouped_cards(report, outlet_controls="", diagnostics_markup="", ups_status=None, monitoring_markup=""):
    checks = {c['system']: c for c in (report or {}).get('checks', [])}
    output = '<div class="dashboard-groups" id="systems">'
    for key, title in [('all', 'Overview')] + [(k, t) for k, t, _ in GROUPS] + [('connections', 'Connections')]:
        output += '<input class="view-radio" type="radio" name="dashboard-view" id="view-' + key + '"' + (' checked' if key == 'all' else '') + ' aria-label="' + title + '">'
    output += '<div class="category-launcher" aria-label="System categories">'
    for key, title, names in GROUPS:
        review = sum(checks.get(name, {}).get('status') == 'review' for name in names)
        read = sum(checks.get(name, {}).get('status') == 'verified' for name in names)
        status = str(review) + ' review' if review else str(read) + ' read' if read else 'Not checked'
        output += '<label class="category-tile category-' + key + '" for="view-' + key + '"><span>' + icon(key if key != 'av' else 'av') + '</span><strong>' + ('AV/Automation' if key == 'av' else title) + '</strong><small>' + status + '</small></label>'
    output += '<a class="category-tile ask-tile" href="#ask-adr" data-ask-shortcut><span>'+icon('ask')+'</span><strong>Ask ADR</strong><small>Speak or ask about this site</small></a>'
    output += '</div><nav class="group-tabs" aria-label="System views">'
    for key, title in [('all', 'Overview')] + [(k, t) for k, t, _ in GROUPS] + [('connections', 'Connections')]:
        output += '<label for="view-' + key + '" aria-label="' + title + '">' + icon('home' if key == 'all' else 'settings' if key == 'connections' else key) + '<span>' + ('AV/Automation' if key == 'av' else title) + '</span></label>'
    output += '</nav>'
    for key, title, names in GROUPS:
        output += '<div class="system-group group-' + key + '"><div class="section-label"><h2>' + title + '</h2></div>'
        if key == 'power': output += ups_panel(ups_status or {})
        if key == 'network':
            output += '<div class="system-grid">'+monitoring_markup+'</div>' if monitoring_markup else ''
            output += cards(report,('Internet',)).replace('class="system-grid"','class="system-grid internet-feature"',1)
            output += network_panels(checks, include_internet=False)
            diagnostic_check=checks.get('Network diagnostics')
            if diagnostic_check:
                status=html.escape(str(diagnostic_check.get('status','unverified')),quote=True)
                notes=diagnostic_check.get('service_findings',[])
                output += '<div id="network-diagnostic-check" data-check-status="'+status+'">'
                output += ''.join('<p>'+html.escape(str(note))+'</p>' for note in notes[:6])
                output += diagnostics_markup+'</div>'
            else:
                output += diagnostics_markup
        output += cards(report, tuple(n for n in names if n!='Internet'), outlet_controls=outlet_controls) + '</div>'
    return output + '</div>'



