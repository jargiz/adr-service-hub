"""Read-only snapshot charts. Missing measurements never become zero or online."""
from internet_quality import quality_issues, failed_latency
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
    angle=math.pi*(1-value/100)
    x,y=80+math.cos(angle)*53,88-math.sin(angle)*53
    return ('<div class="gauge"><svg tabindex="0" aria-haspopup="dialog" viewBox="0 0 160 145" role="img" aria-label="' + esc(label + ': ' + text) + '">'
        '<title>' + esc(label + ': ' + text) + '</title><path d="M18 88 A62 62 0 0 1 142 88" class="gauge-track"/>'
        '<path d="M18 88 A62 62 0 0 1 142 88" class="gauge-fill" pathLength="100" stroke-dasharray="' + str(value) + ' 100"/>'
        f'<path d="M80 88L{x:.2f} {y:.2f}" class="gauge-needle"/>'
        '<text x="16" y="105" class="gauge-scale">0</text><text x="144" y="105" text-anchor="end" class="gauge-scale">100</text>'
        '<text x="80" y="113" class="gauge-value" text-anchor="middle">' + text + '</text>'
        '<text x="80" y="135" class="gauge-label" text-anchor="middle">' + esc(label) + '</text></svg></div>')


def managed_device_cards(network):
    devices=network.get('devices',[])[:64]
    if not devices:return ''
    output='<section class="managed-inventory"><header><h4>UniFi devices</h4><span>'+str(len(devices))+' reported</span></header>'
    for title,types in (('Gateways',('ugw','udm','uxg')),('Switches',('usw',)),('Access points',('uap',))):
        rows=[d for d in devices if d.get('type') in types]
        if not rows:continue
        output+='<h5>'+title+'</h5><div class="managed-device-grid">'
        for device in rows:
            state=device.get('state') if device.get('state') in ('online','offline') else 'unverified'
            uptime=device.get('uptime_seconds')
            detail='Uptime unreported'
            if type(uptime) is int and uptime>=0:
                detail='Up '+(str(uptime//86400)+'d' if uptime>=86400 else str(uptime//3600)+'h' if uptime>=3600 else str(uptime//60)+'m')
            ports=device.get('ports',[])
            known=[p for p in ports if p.get('link') in ('up','down')]
            if known:detail+=' · '+str(sum(p['link']=='up' for p in known))+'/'+str(len(known))+' ports linked'
            output+='<div class="managed-device device-'+state+'"><div><strong>'+esc(device.get('name','Unnamed device'))+'</strong><span class="device-status">'+{'online':'Online','offline':'Offline','unverified':'Unverified'}[state]+'</span></div><small>'+esc(detail)+'</small></div>'
        output+='</div>'
    return output+'<p class="report-caption">Controller-reported inventory and state · managed devices only</p></section>'


def visuals(name, snapshot, lines):
    if not snapshot:
        return ''
    output = ''
    if name == 'Bluesound':
        from bluesound import zone_rows
        zones=zone_rows(snapshot)
        output+='<section class="bluesound-zones"><h4>Audio zones</h4><div class="managed-device-grid">'
        for zone in zones:
            state=str(zone.get('state') or 'unknown')
            output+='<div class="managed-device"><div><strong>'+esc(zone.get('name','Unnamed zone'))+'</strong><span class="device-status">'+esc(state.capitalize())+'</span></div></div>'
        output+='</div><p class="report-caption">Individual players reported by the Bluesound integration. Playback state does not verify audio output or physical connectivity.</p></section>'
    if name == 'Internet':
        return network_panels({'Internet':{'snapshot':snapshot}},include_access_points=False)
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
        metering=snapshot.get('electrical') or {}
        output += '<div class="wattbox-metering"><h4>Voltage and amperage</h4><div class="internet-metrics">'
        for key,label,unit in (('voltage_v','Voltage','V'),('current_a','Current','A')):
            value=number(metering.get(key))
            output+='<div><span>'+label+'</span><strong>'+(f'{value:g} '+unit if value is not None else 'Unavailable')+'</strong></div>'
        output+='</div><p class="report-caption">Total for this WattBox · latest system check</p>'
        if snapshot.get('electrical_error'):output+='<p class="measurement-warning">'+esc(snapshot['electrical_error'])+'</p>'
        history=snapshot.get('electrical_history',{})
        for series in history.get('series',[])[:2]:
            output+=trend_chart([series],series.get('name','WattBox')+' history',series.get('unit',''))
        if not history.get('series'):output+='<p class="empty-state">Voltage and amperage history starts with the next successful metered reading.</p>'
        if history.get('error'):output+='<p class="measurement-warning">'+esc(history['error'])+'</p>'
        output+='<small>'+esc(history.get('note','Whole-WattBox readings; unavailable measurements remain gaps.'))+'</small></div>'
    if name == 'UniFi' and snapshot.get('gateway_speedtest'):
        output += network_panels({'UniFi':{'snapshot':snapshot}},include_access_points=False)
    if name == 'UniFi':
        output += managed_device_cards(snapshot.get('network_health') or {})
    if name == 'Sense':
        series = snapshot.get('history', {}).get('series', [])
        output += '<div class="sense-history"><h4>Past 24 hours</h4>'
        if not series:
            output += '<p class="empty-state">No recorded Sense history received yet.</p>'
        for item in series[:6]:
            output += history_chart(item)
        output += '<small>Recorded history · Missing samples remain gaps. Sampled voltage does not establish transient power quality.</small></div>'
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
    full_title = str(series.get('name', 'Sense sensor'))
    title = esc(re.sub(r'^Sense\s+\d+\s+', '', full_title))
    unit = esc(series.get('unit', ''))
    output = '<div class="sense-series"><h4 title="' + esc(full_title) + '">' + title + ' <small>' + unit + '</small></h4>'
    if not valid:
        return output + '<p class="empty-state">' + esc(series.get('status', 'History unavailable')) + '</p></div>'
    low, high = min(v for _, v in valid), max(v for _, v in valid)
    state_labels=series.get('state_labels')
    if state_labels:low,high=0,1
    xmin, xmax = min(t for t, _ in parsed), max(t for t, _ in parsed)
    span = high - low
    ymin, ymax = (low - span * .1, high + span * .1) if span else (low - max(abs(low)*.01, .1), high + max(abs(high)*.01, .1))
    segments, active = [], []
    previous = None
    for stamp, value in parsed:
        # Do not draw across explicit unavailable states or long sampling gaps.
        if value is None or (previous is not None and stamp - previous > min(86400, max(900, int(series.get('max_gap_seconds', 900))))):
            if active: segments.append(active)
            active = []
        if value is not None:
            x = 38 + (stamp-xmin) / max(xmax-xmin, 1) * 250
            y = 95 - (value-ymin) / (ymax-ymin) * 72
            active.append((x, y))
        previous = stamp
    if active: segments.append(active)
    output += '<svg class="history-chart" tabindex="0" aria-haspopup="dialog" viewBox="0 0 308 136" role="img" aria-label="' + title + ' history, ' + f'{low:g} to {high:g} ' + unit + '"><title>' + title + ' history</title>'
    output += '<path d="M38 18V102H290" class="chart-axis"/>'
    if series.get('observation_ticks'):
        output += '<path d="M38 23H288M38 95H288" class="state-unknown-rail"/>'
    for segment in segments:
        if series.get('observation_ticks'):
            for x,y in segment:output += f'<path d="M{x:.2f} {y-7:.2f}v14" class="state-observation"/>'
        elif series.get('points_only'):
            for x,y in segment:output += f'<path d="M{x-4:.2f} {y:.2f}h8" class="chart-sample-bar"/>'
        elif len(segment) == 1:
            x, y = segment[0]
            output += f'<path d="M{x-4:.2f} {y:.2f}h8" class="chart-sample-bar"/>'
        else:
            coords = ' '.join(('M' if i == 0 else 'L') + f'{x:.2f},{y:.2f}' for i, (x, y) in enumerate(segment))
            output += '<path d="' + coords + '" class="chart-line"/>'
    high_label=esc(state_labels.get(str(int(high)),str(high))) if state_labels else f'{high:.3g}'
    low_label=esc(state_labels.get(str(int(low)),str(low))) if state_labels else f'{low:.3g}'
    output += '<text x="33" y="27" text-anchor="end">' + high_label + '</text><text x="33" y="99" text-anchor="end">' + low_label + '</text>'
    from dashboard import site_timezone_name
    try:zone = ZoneInfo(site_timezone_name())
    except (ZoneInfoNotFoundError,ValueError):
        return output+'</svg><small>Configure the client site timezone to display history dates.</small></div>'
    first = datetime.fromtimestamp(xmin, zone)
    last = datetime.fromtimestamp(xmax, zone)
    format_time = '%m/%d %H:%M' if first.date() != last.date() else '%H:%M'
    start, end = first.strftime(format_time), last.strftime(format_time)
    for at, reading in parsed:
        x = 38 + (at-xmin) / max(xmax-xmin, 1) * 250
        measured = state_labels.get(str(int(reading)), str(reading)) if state_labels and reading is not None else (f'{reading:g} '+str(series.get('unit', '')) if reading is not None else 'Unavailable')
        caption = datetime.fromtimestamp(at, zone).strftime('%b %d · %I:%M:%S %p %Z') + ' · ' + str(measured)
        output += f'<rect x="{x-2:.3f}" y="18" width="4" height="84" class="trend-hit" data-sample-detail="' + esc(caption) + '"><title>' + esc(caption) + '</title></rect>'
    output += '<text x="38" y="122">' + start + '</text><text x="288" y="122" text-anchor="end">' + end + '</text></svg>'
    summary = (str(len(valid)) + ' reported observations') if series.get('observation_ticks') else ('Range ' + f'{low:g}–{high:g} ' + unit + ' · ' + str(len(valid)) + ' samples')
    output += '<small>' + summary + ' · ' + last.strftime('%Z') + (' · partial history' if series.get('truncated') else '') + '</small></div>'
    return output


def trend_chart(series_list, title, unit, timeline=False):
    """Shared axes for scheduled tests; line joins indicate trends between tests."""
    from dashboard import site_timezone_name
    try: zone = ZoneInfo(site_timezone_name())
    except (ZoneInfoNotFoundError, ValueError):
        return '<p>Configure the client site timezone to display history dates.</p>'
    rows=[]
    for series in series_list:
        points=[]
        for item in series.get('points', [])[:2000]:
            try:
                stamp=datetime.fromisoformat(str(item.get('time','')).replace('Z','+00:00'))
                if stamp.tzinfo is not None: points.append((stamp.timestamp(),number(item.get('value'))))
            except (ValueError,TypeError): pass
        points.sort()
        label=str(series.get('name','Reading'))
        for prefix in ('Green Ookla speed test ', 'Green speed test ', 'UniFi speed test '):
            if label.startswith(prefix): label=label[len(prefix):]
        rows.append((label,points))
    valid=[(t,v) for _,points in rows for t,v in points if v is not None]
    default='day' if timeline else 'week'
    output='<section class="trend-card'+(' speed-timeline' if timeline else '')+'" data-trend-card="'+esc(title)+'"><header><h4>'+esc('Internet speed' if timeline else title)+'</h4>'+('<small class="trend-source">'+esc(title.removesuffix(' Internet test history'))+'</small>' if timeline else '')+'<div class="trend-controls">'+('<select data-trend-series hidden aria-label="Both speed series">' if timeline else '<label>Show <select data-trend-series>')+'<option value="all">All readings</option>'
    for i,(label,_) in enumerate(rows):output+='<option value="'+str(i)+'">'+esc(label)+'</option>'
    output+='</select>'+('' if timeline else '</label>')+'<label>Period <select data-trend-range><option value="week">Week</option><option value="day"'+(' selected' if timeline else '')+'>24 hours</option><option value="all">All recorded</option></select></label></div></header>'
    if not valid:return output+'<p class="empty-state">Awaiting recorded '+esc(title.lower())+' results.</p></section>'
    last=max(t for t,_ in valid);first=min(t for t,_ in valid)
    for key,seconds in (('week',7*86400),('day',86400),('all',max(last-first,1))):
        start=max(first,last-seconds); selected=[(t,v) for t,v in valid if start<=t<=last]
        maximum=max([v for _,v in selected]+[1]); ceiling=math.ceil(maximum/5)*5 if maximum<=20 else math.ceil(maximum/100)*100
        def x(t):return 320 if last==start else 64+(t-start)/(last-start)*512
        def y(v):return 200-v/ceiling*160
        output+='<div data-trend-window="'+key+'"'+(' hidden' if key!=default else '')+'>'
        window_rows = [(label, [(t,v) for t,v in points if start<=t<=last and v is not None]) for label,points in rows]
        if timeline and all(len(points)<=1 for _,points in window_rows):
            output += '<div class="speed-latest">'
            for i,(label,points) in enumerate(window_rows):
                output += '<div class="speed-reading trend-color-'+str(i%4)+'"><span>'+esc(label)+'</span>'
                if points:
                    at,reading = points[-1]
                    output += '<strong>'+f'{reading:g}'+'<small> Mbps</small></strong><time>'+esc(datetime.fromtimestamp(at,zone).strftime('%b %d · %I:%M %p %Z'))+'</time>'
                else:
                    output += '<strong class="speed-missing">Unavailable</strong>'
                output += '</div>'
            output += '</div><p class="speed-hint">More recorded tests will add a timeline.</p></div>'
            continue
        output+='<div class="trend-legend">'
        for i,(label,_) in enumerate(rows):output+='<span data-trend-item="'+str(i)+'" class="trend-color-'+str(i%4)+'"><i></i>'+esc(label)+'</span>'
        output+='</div><svg class="trend-chart" tabindex="0" aria-haspopup="dialog" viewBox="0 0 600 280" role="img" aria-label="'+esc(title)+'"><title>'+esc(title)+'</title><text x="64" y="22">'+esc(unit)+'</text>'
        for i in range(6):
            yy=40+i*32;value=ceiling*(5-i)/5
            output+=f'<path d="M64 {yy}H576" class="chart-grid"/><text x="55" y="{yy+4}" text-anchor="end">{value:g}</text>'
        for i in (range(4) if last>start else (0,)):
            t=start+(last-start)*i/3;xx=x(t);local=datetime.fromtimestamp(t,zone)
            anchor='middle' if last==start else 'start' if i==0 else 'end' if i==3 else 'middle'
            output+=f'<path d="M{xx:.2f} 40V200" class="chart-grid"/><text class="timeline-time" x="{xx:.2f}" y="226" text-anchor="'+anchor+'">'+local.strftime('%I:%M %p').lstrip('0')+'</text>'
            if datetime.fromtimestamp(start,zone).date()!=datetime.fromtimestamp(last,zone).date():
                output+=f'<text class="timeline-date" x="{xx:.2f}" y="250" text-anchor="'+anchor+'">'+local.strftime('%b %d')+'</text>'
        for i,(label,points) in enumerate(rows):
            # Throughput is discrete: connect daily tests, but break missed daily runs.
            # Latency uses a shorter bound and explicit unknowns always break a path.
            speed=unit=='Mbit/s' or label.lower()=='ping';gap=36*3600 if speed else 3600
            segments=[];active=[];previous=None
            for t,v in points:
                if t<start or t>last:continue
                if v is None or (previous is not None and t-previous>gap):
                    if active:segments.append(active)
                    active=[]
                if v is not None:active.append((t,v))
                previous=t
            if active:segments.append(active)
            output+='<g data-trend-item="'+str(i)+'" class="trend-color-'+str(i%4)+'">'
            for segment in segments:
                if len(segment)>1:
                    path=' '.join(('M' if j==0 else 'L')+f'{x(t):.2f},{y(v):.2f}' for j,(t,v) in enumerate(segment))
                    output+='<path d="'+path+'" class="trend-line"/>'
                for t,v in segment:
                    caption=label+': '+f'{v:g} '+unit+' · '+datetime.fromtimestamp(t,zone).strftime('%b %d, %I:%M %p %Z')
                    # Transparent hit rectangles preserve exact sample tooltips
                    # without drawing point markers over the trend line.
                    output+=f'<rect x="{x(t)-9:.2f}" y="{y(v)-12:.2f}" width="18" height="24" class="trend-hit" data-sample-detail="'+esc(caption)+'"><title>'+esc(caption)+'</title></rect>'
                    if len(segment)==1:
                        output+=f'<path d="M{x(t)-5:.2f},{y(v):.2f}h10" class="trend-isolated"/>'
            output+='</g>'
        output+='</svg><small>'+esc(unit)+' · '+str(len(selected))+' recorded readings · '+esc(datetime.fromtimestamp(last,zone).strftime('%Z'))+'</small></div>'
    output+='<p class="trial-selected-sample" data-trial-detail data-trial-session="'+esc(title)+'" role="status">Tap the graph to enlarge it, zoom, and inspect measured values and test times.</p>'
    if timeline:
        output+='<p class="report-caption">Latest reading · '+esc(datetime.fromtimestamp(last,zone).strftime('%b %d · %I:%M %p %Z'))+'</p></section>'
    else:
        output+='<p class="report-caption">Periods end at the latest recorded reading: '+esc(datetime.fromtimestamp(last,zone).strftime('%b %d · %I:%M %p %Z'))+'. Lines show trends between tests; long gaps and unavailable readings remain breaks.</p></section>'
    return output


def network_history_charts(history, source):
    candidates=[s for s in history if s.get('unit') in ('Mbps','Mbit/s') and any(w in str(s.get('name','')).lower() for w in ('download','upload'))]
    speed=[]
    for direction in ('download','upload'):
        matches=[s for s in candidates if str(s.get('name','')).lower().endswith(direction)]
        if matches:speed.append(next((s for s in matches if s.get('points')),matches[0]))
    latency=[s for s in history if s.get('unit')=='ms' and any(w in str(s.get('name','')).lower() for w in ('latency','ping'))][:4]
    used={id(s) for s in candidates+latency}
    output=trend_chart(speed,source+' Internet test history','Mbit/s',timeline=True)
    if latency:output+=trend_chart(latency,source+' latency history','ms')
    for series in [s for s in history if id(s) not in used][:4]:output+=history_chart(series)
    return output


def network_panels(checks, include_internet=True, include_access_points=True):
    uni = (checks.get('UniFi') or {}).get('snapshot') or {}
    ruckus = (checks.get('Ruckus') or {}).get('snapshot') or {}
    green = (checks.get('Internet') or {}).get('snapshot') or {}
    internet = green.get('readings', []) if green else uni.get('internet_readings', [])
    issues = quality_issues(internet)
    sensors = internet if green else uni.get('sensors', []) + internet
    def metric(words, unit, speed=False):
        for sensor in sensors:
            label = str(sensor.get('name', '')).lower()
            if all(word in label for word in words) and (not speed or 'speedtest' in label or 'speed test' in label):
                value = number(sensor.get('state'))
                if value is not None and value >= 0 and sensor.get('unit') in unit:
                    return f'{value:g} ' + esc(sensor['unit']) + (' <small>Needs verification</small>' if speed and issues else '')
        return 'Unverified'
    output = '<div class="network-panels"><section class="internet-panel"><h3>Internet</h3><div class="internet-metrics">'
    for label, value in [('Download speed test', metric(('download',), ('Mbps', 'Mbit/s'), True)),
        ('Upload speed test', metric(('upload',), ('Mbps', 'Mbit/s'), True)),
        ('Cloudflare latency', metric(('cloudflare', 'latency'), ('ms',))),
        ('Google latency', metric(('google', 'latency'), ('ms',)))]:
        output += '<div><span>' + label + '</span><strong>' + value + '</strong></div>'
    output += '</div>'
    for issue in issues:
        output += '<p class="measurement-warning"><strong>Speed-test result needs verification.</strong> ' + esc(issue) + '</p>'
    latency = []
    for sensor in sensors:
        if sensor in internet and failed_latency(sensor):
            continue
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
    if green:
        from dashboard import display_time
        output += '<p class="report-caption">Measured from Green · Probes '+esc(display_time(green.get('checked_at')))+'</p>'
        for probe in green.get('probes', []):
            loss=probe.get('loss_percent')
            output += '<p>'+esc(probe['name'])+': '+(esc(loss)+'% ICMP loss in 5 probes' if loss is not None else 'probe unverified')+'</p>'
        output += '<p>DNS: '+esc(green.get('dns',{}).get('status','unverified'))+'</p>'
        speed=green.get('speed_test')
        if speed:
            output += '<p class="report-caption">Last Green throughput attempt '+esc(display_time(speed.get('completed_at')))+'</p>'
            for note in speed.get('limitations',[]):
                output += '<p class="report-caption">'+esc(note)+'</p>'
        else:
            output += '<p class="report-caption">Run Green Speed Test under Network tools. No router API key is needed.</p>'
    # Green and gateway readings have their own tiles. A Green-only snapshot
    # cannot populate a gateway disclosure, so do not render an empty control.
    if not green and uni.get('internet_error'):
        output += '<p class="measurement-warning">' + esc(uni['internet_error']) + '</p>'
    if not green and uni.get('gateway_speedtest', {}).get('readings'):
        from dashboard import display_time
        output += '<p class="report-caption">UniFi gateway · Tested ' + esc(display_time(uni['gateway_speedtest']['readings'][0]['last_updated'])) + '</p>'
    output += '<div class="network-history-grid">'
    history = list((green or uni).get('network_history', []))
    source = ('Green Ookla' if (green.get('speed_test') or {}).get('provider')=='ookla_addon' else 'Green') if green else 'UniFi'
    for name in (source+' speed test Download', source+' speed test Upload'):
        if not any(series.get('name')==name for series in history):
            history.insert(0, {'name':name,'unit':'Mbit/s','points':[],'status':'Awaiting '+source+' results'})
    output += network_history_charts(history[:8], source)
    output += '</div></section>'
    if not include_access_points:return output+'</div>'
    if not include_internet:output='<div class="network-panels">'
    output += '<h3 class="ap-heading">Access points</h3><div class="ap-grid">'

    controller = ruckus.get('controller')
    if controller is not None:
        aps = controller.get('access_points', [])
        output += '<p class="report-caption">Direct controller snapshot · ' + esc(controller.get('checked_at', 'Time unreported')) + '</p>'
        if not aps:
            output += '<p class="empty-state">The controller returned no access points.</p>'
        for ap in aps[:128]:
            state = 'Online' if ap.get('online') is True else 'Offline' if ap.get('online') is False else 'Unverified'
            count = ap.get('connected_clients')
            output += '<div class="ap-card"><h4 title="' + esc(ap.get('name', 'Access point')) + '">' + esc(ap.get('name', 'Access point')) + '</h4><small>' + esc(ap.get('model') or 'Model unreported') + '</small><p>Status: <strong>' + state + '</strong></p><p>Connected devices: <strong>' + esc(count if type(count) is int and count >= 0 else 'Unverified') + '</strong></p><small>Controller state: ' + esc(ap.get('controller_state', 'Unreported')) + '</small></div>'
    else:
        aps = [d for d in ruckus.get('devices', []) if str(d.get('manufacturer', '')).casefold() == 'ruckus' and re.fullmatch(r'r\d+[a-z]*', str(d.get('model', '')).lower())]
        if ruckus.get('controller_error'):
            output += '<p class="empty-state">Controller unavailable.</p>'
            output += '<p class="measurement-warning">' + esc(ruckus['controller_error']) + '</p>'
            if ruckus['controller_error'] == 'Inspect and approve this Ruckus controller certificate first.':
                output += '<p>Open <a href="#connections">Connections</a>, inspect and approve the controller certificate, then select Read Access Points.</p>'
        if not aps:
            output += '<p class="empty-state">No access points collected.</p>'
        for ap in aps[:32]:
            output += '<div class="ap-card"><h4 title="' + esc(ap.get('name', 'Access point')) + '">' + esc(ap.get('name', 'Access point')) + '</h4><small>' + esc(ap.get('model', '')) + '</small><p>Status: <strong>Unverified</strong></p><p>Connected devices: <strong>Unverified</strong></p></div>'
    return output + '</div></div>'



