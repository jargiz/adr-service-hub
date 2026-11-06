"""Ingress dashboard panel for recorded ICMP samples; renders no synthetic values."""
import html
import math
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dashboard import display_time, site_timezone_name
from ui_icons import icon
from network_trial import BASELINE, INTERVAL, stamp


def esc(value):
    return html.escape(str(value), quote=True)


def value(raw):
    return raw if type(raw) in (int, float) and math.isfinite(raw) and raw >= 0 else None


def metrics(samples, index):
    sent = received = 0
    latency_sum = replies = 0
    valid = 0
    for sample in samples:
        row = sample['rows'][index]
        tx, rx, latency = row.get('sent'), row.get('received'), value(row.get('latency_ms'))
        if type(tx) is int and tx == 5 and type(rx) is int and 0 <= rx <= tx:
            sent += tx
            received += rx
            valid += 1
            if latency is not None and rx:
                latency_sum += latency * rx
                replies += rx
    return (f'{latency_sum/replies:.1f} ms' if replies else 'Unavailable',
            f'{100*(sent-received)/sent:.1f}%' if sent else 'Unavailable', valid)


def chart(current, samples, key, title, unit):
    output = '<section class="trial-chart"><h4>' + title + '</h4>'
    valid = [value(row.get(key)) for sample in samples for row in sample['rows']]
    valid = [v for v in valid if v is not None]
    if not valid:
        return output + '<p>Awaiting measured results.</p></section>'
    first, last = current['started'], max(sample['time'] for sample in samples)
    span = max(last-first, 1)
    ceiling = 100 if unit == '%' else max(5, math.ceil(max(valid)/5)*5)
    try:zone=ZoneInfo(site_timezone_name())
    except (ZoneInfoNotFoundError,ValueError):zone=ZoneInfo('UTC')
    output += '<svg class="trend-chart" tabindex="0" aria-haspopup="dialog" viewBox="0 0 600 260" role="group" data-trial-chart aria-label="'+title+'; use left and right arrows for sample details"><title>'+title+'</title>'
    for index in range(5):
        yy = 40 + index*40
        output += f'<path d="M64 {yy}H576" class="chart-grid"/><text x="55" y="{yy+4}" text-anchor="end">{ceiling*(4-index)/4:g}</text>'
    for index in range(4):
        at=first+span*index/3
        x=64+512*index/3
        local=datetime.fromtimestamp(at,zone)
        label=local.strftime('%I:%M %p').lstrip('0')
        anchor='start' if index==0 else 'end' if index==3 else 'middle'
        output+=f'<path d="M{x:.2f} 200v7" class="chart-grid"/><text class="trial-time-tick" x="{x:.2f}" y="233" text-anchor="{anchor}">'+esc(label)+'</text>'
    output+='<text x="64" y="255" class="trial-time-zone">Time · '+esc(datetime.fromtimestamp(last,zone).strftime('%Z'))+'</text>'
    # Actual timestamps are used; unobserved periods and failures break paths.
    for index, target in enumerate(current['targets']):
        segments, active, previous = [], [], None
        for sample in samples:
            reading = value(sample['rows'][index].get(key))
            at = sample['time']
            if reading is None or (previous is not None and at-previous > INTERVAL*1.5):
                if active:
                    segments.append(active)
                active = []
            if reading is not None:
                active.append((64+(at-first)/span*512, 200-reading/ceiling*160))
            previous = at
        if active:
            segments.append(active)
        output += '<g class="trend-color-'+str(index)+'">'
        for segment in segments:
            if len(segment) == 1:
                x, y = segment[0]
                output += f'<path d="M{x-1:.2f},{y:.2f}h2" class="trend-line"/>'
            else:
                path = ' '.join(('M' if j == 0 else 'L')+f'{x:.2f},{y:.2f}' for j, (x, y) in enumerate(segment))
                output += '<path d="'+path+'" class="trend-line"/>'
        output += '</g>'
    for sample in samples:
        at=sample['time']
        x=64+(at-first)/span*512
        half=min(8,INTERVAL/span*256)
        left,right=max(64,x-half),min(576,x+half)
        details=datetime.fromtimestamp(at,zone).strftime('%b %d · %I:%M:%S %p %Z')
        for index,target in enumerate(current['targets']):
            reading=value(sample['rows'][index].get(key))
            details+=' · '+str(target[0])+': '+(f'{reading:g} '+unit if reading is not None else 'Unavailable')
        output+=f'<rect x="{left:.3f}" y="40" width="{max(right-left,0.01):.3f}" height="160" class="trial-sample-hit" data-sample-detail="'+esc(details)+'"><title>'+esc(details)+'</title></rect>'
    output += '</svg><div class="trend-legend">'
    for index, target in enumerate(current['targets']):
        output += '<span class="trend-color-'+str(index)+'"><i></i>'+esc(target[0])+'</span>'
    output += '</div><p class="trial-selected-sample" data-trial-detail data-trial-session="'+esc(current.get('id',''))+'" role="status">Tap the graph to enlarge it, zoom, and inspect exact sample times and readings.</p><p class="report-caption">'+esc(display_time(stamp(first)))+' — '+esc(display_time(stamp(last)))+' · '+unit+'</p></section>'
    return output


def panel(trial, csrf):
    data = trial.snapshot()
    current, samples = data['current'], data['samples']
    running = bool(current and current.get('state') == 'running')
    output = '<article class="system-card network-trial-card" id="network-monitoring"><details class="system-tile"><summary class="tile-summary"><div class="tile-icon-row"><span class="system-icon">'+icon('network')+'</span></div><h3>Network Monitoring</h3><span class="badge">'
    label = 'Baseline' if running and data['now'] < current['started']+BASELINE else 'Running' if running else str(current.get('state', 'Ready')).capitalize() if current else 'Ready'
    output += esc(label)+'</span><p class="tile-value">Latency &amp; packet-loss monitoring</p><div class="tile-footer">Open monitoring</div></summary><div class="tile-body">'
    output += '<p>Five pings per target every minute from the Green. The first five minutes form the baseline. Stops automatically after 24 hours.</p>'
    output += '<div class="toolbar">'
    for action, title, disabled in (('network-trial-start', 'Start monitoring', running or data['busy'] or bool(data['error'])), ('network-trial-stop', 'Stop monitoring', not running)):
        output += '<form method="post" action="'+action+'"><input type="hidden" name="csrf" value="'+esc(csrf)+'"><button'+(' disabled' if disabled else '')+'>'+title+'</button></form>'
    output += '</div>'
    if data['error']:
        output += '<p class="measurement-warning">'+esc(data['error'])+'</p>'
    if current:
        output += '<p>Started '+esc(display_time(stamp(current['started'])))+' · Auto-stop '+esc(display_time(stamp(current['deadline'])))+'</p>'
        if current.get('ended'):
            output += '<p>Ended '+esc(display_time(stamp(current['ended'])))+'</p>'
        if running:
            output += '<p role="status">'+str(max(0, math.ceil((current['deadline']-data['now'])/60)))+' minutes remaining · '+str(len(samples))+' recorded samples</p>'
        output += '<div class="trial-table"><table><thead><tr><th>Target</th><th>Latest latency</th><th>Packet loss</th><th>Baseline latency / loss</th><th>Measured samples</th></tr></thead><tbody>'
        baseline = [s for s in samples if s.get('baseline') is True]
        for index, target in enumerate(current['targets']):
            _, loss, count = metrics(samples, index)
            base_latency, base_loss, _ = metrics(baseline, index)
            latest = value(samples[-1]['rows'][index].get('latency_ms')) if samples else None
            output += '<tr><th>'+esc(target[0])+'<small>'+esc(target[1])+'</small></th><td>'+(f'{latest:g} ms' if latest is not None else 'Unavailable')+'</td><td>'+loss+'</td><td>'+base_latency+' / '+base_loss+'</td><td>'+str(count)+' / '+str(len(samples))+'</td></tr>'
        output += '</tbody></table></div>'
        output += chart(current, samples, 'latency_ms', 'Ping latency history', 'ms')
        output += chart(current, samples, 'loss_percent', 'Sampled packet-loss history', '%')
        output += '<p>Latest sample: '+(esc(display_time(stamp(samples[-1]['time']))) if samples else 'Awaiting first sample')+'. Missing measurements remain gaps. Loss is based only on confirmed packet counts.</p>'
        output += '<form method="post" action="network-trial-report"><input type="hidden" name="csrf" value="'+esc(csrf)+'"><button>Download monitoring history</button></form>'
    output += '<p class="report-caption">History: 7 days. Stop keeps recorded results. Updating or restarting the app stops monitoring.</p>'
    output += '<p class="report-caption">Speed tests pause during monitoring. System checks continue.</p>'
    return output+'</div></details></article>'

