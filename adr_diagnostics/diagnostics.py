"""Bounded diagnostic tools. Never execute model output or device commands."""
import concurrent.futures
import ipaddress
import json
import math
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

RFC1918 = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))


class DiagnosticError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def config(raw):
    subnets = raw.get('allowed_subnets', [])
    targets = raw.get('targets', [])
    if not isinstance(subnets,list) or len(subnets)>4 or not isinstance(targets,list) or len(targets)>16:
        raise DiagnosticError('Configure at most four local subnets and sixteen target addresses.')
    networks=[]
    try:
        for item in subnets:
            n=ipaddress.ip_network(item,strict=True)
            if n.version!=4 or n.prefixlen<24 or not any(n.subnet_of(r) for r in RFC1918):
                raise ValueError()
            networks.append(n)
    except (ValueError,TypeError):
        raise DiagnosticError('Use private IPv4 subnets of /24 or smaller.') from None
    c={'networks':networks}
    c['targets']=list(dict.fromkeys(address(t,c) for t in targets))
    name=raw.get('dns_name','example.com')
    if not isinstance(name,str) or len(name)>253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',name):
        raise DiagnosticError('Set a valid DNS test name.')
    interval=raw.get('monitor_interval_minutes',20)
    if type(interval) is not int or not 5<=interval<=1440:
        raise DiagnosticError('Monitoring interval must be 5–1440 minutes.')
    c.update(dns_name=name,automatic_monitoring=raw.get('automatic_monitoring') is True,interval=interval)
    return c


def address(value, c):
    try:
        a=ipaddress.ip_address(value)
        if a.version!=4 or not any(a in n and a not in (n.network_address,n.broadcast_address) for n in c['networks']):
            raise ValueError()
        return str(a)
    except (ValueError,TypeError):
        raise DiagnosticError('Choose a host address inside a configured local subnet.') from None


def ping(ip, count=3, runner=subprocess.run):
    """Fixed argument vector; timeout bounds each process, no shell or raw output."""
    if count not in (1,3):
        raise DiagnosticError('Unsupported ping count.')
    try:
        result=runner(['ping','-n','-c',str(count),'-W','1','-w',str(count+1),'--',str(ip)],
            capture_output=True,text=True,timeout=count+2,env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
        out=(result.stdout or '')[:4096]
        match=re.search(r'(\d+) packets transmitted, (\d+) received',out)
        if not match or int(match[1])!=count or int(match[2])>count:
            return {'status':'unverified','sent':None,'received':None,'loss_percent':None,'average_ms':None}
        sent,received=int(match[1]),int(match[2])
        timing=re.search(r'(?:rtt|round-trip).*?=\s*[\d.]+/([\d.]+)/',out)
        avg=float(timing[1]) if timing else None
        if avg is not None and not math.isfinite(avg):avg=None
        return {'status':'responded' if received else 'no_reply','sent':sent,'received':received,
            'loss_percent':round((sent-received)*100/sent,1),'average_ms':avg}
    except (OSError,subprocess.SubprocessError,ValueError):
        return {'status':'unverified','sent':None,'received':None,'loss_percent':None,'average_ms':None}


def tcp(ip, port, connector=socket.create_connection):
    if port not in (80,443):raise DiagnosticError('Unsupported service port.')
    try:
        with connector((ip,port),timeout=1):pass
        return {'port':port,'status':'reachable'}
    except ConnectionRefusedError:
        return {'port':port,'status':'refused'}
    except OSError:
        return {'port':port,'status':'unverified'}


def dns(name, runner=subprocess.run):
    # Isolate getaddrinfo in a bounded child process; a resolver outage cannot hang a job.
    code='import json,socket,sys;print(json.dumps(sorted({r[4][0] for r in socket.getaddrinfo(sys.argv[1],None,socket.AF_INET)})))'
    started=time.monotonic()
    try:
        import sys
        p=runner([sys.executable,'-c',code,name],capture_output=True,text=True,timeout=5)
        values=json.loads((p.stdout or '')[:4096])
        if p.returncode or not isinstance(values,list) or not values or len(values)>64:raise ValueError()
        addresses=[str(ipaddress.IPv4Address(v)) for v in values]
        return {'name':name,'status':'resolved','addresses':addresses,'elapsed_ms':round((time.monotonic()-started)*1000,1)}
    except (OSError,subprocess.SubprocessError,ValueError,TypeError):
        return {'name':name,'status':'unverified','addresses':[],'elapsed_ms':None}


def check(c, probe=ping, connect=tcp, resolve=dns, progress=lambda _:None):
    result={'kind':'target_checks','checked_at':now(),'targets':[],
        'limitations':['No ICMP reply does not establish that a device is offline.',
            'Three probes are a short sample, not a sustained packet-loss assessment.',
            'TCP reachability does not verify login, playback or device operation.',
            'DNS is tested through this app’s configured resolver; its cache can affect timing.']}
    for i,ip in enumerate(c['targets']):
        progress('Checking target '+str(i+1)+' of '+str(len(c['targets'])))
        result['targets'].append({'ip':ip,'ping':probe(ip),'services':[connect(ip,80),connect(ip,443)]})
    progress('Checking DNS')
    result['dns']=resolve(c['dns_name'])
    return result


def discover(c, subnet, probe=ping, progress=lambda _:None):
    selected=next((n for n in c['networks'] if str(n)==subnet),None)
    if selected is None:raise DiagnosticError('Choose a configured subnet.')
    ips=[str(ip) for ip in selected.hosts()]
    rows=[]
    # Four workers, one bounded ICMP probe per host, no port sweep or subnet inference.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures={executor.submit(probe,ip,1):ip for ip in ips}
        for i,future in enumerate(concurrent.futures.as_completed(futures)):
            try:r=future.result()
            except Exception:r={'status':'unverified'}
            rows.append({'ip':futures[future],'status':r['status']})
            progress('Discovery '+str(i+1)+' / '+str(len(ips)))
    return {'kind':'discovery','checked_at':now(),'subnet':subnet,'tested':len(rows),
        'responding':[r['ip'] for r in sorted(rows,key=lambda x:ipaddress.ip_address(x['ip'])) if r['status']=='responded'],
        'unverified_count':sum(r['status']=='unverified' for r in rows),
        'limitations':['Only ICMP responders are listed; this is not a complete device inventory.',
            'MAC addresses, names and Wi-Fi associations are not established by this scan.',
            'A missing reply is not an Offline diagnosis.']}


def save(path, value):
    path=Path(path);tmp=path.with_suffix('.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(value,f);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()


def retain(history, result=None):
    cutoff=time.time()-7*86400
    samples=[r for r in history.get('samples',[]) if isinstance(r,dict) and type(r.get('saved_at')) in (int,float) and r['saved_at']>=cutoff]
    if result is not None:samples.append({'saved_at':time.time(),'result':result})
    history['samples']=samples[-96:]
    observed={}
    for sample in history['samples']:
        data=sample['result'];stamp=data.get('checked_at')
        ips=data.get('responding',[]) if data.get('kind')=='discovery' else [r['ip'] for r in data.get('targets',[]) if r.get('ping',{}).get('status')=='responded']
        for ip in ips:
            old=observed.get(ip,{'ip':ip,'first_seen':stamp})
            observed[ip]={**old,'last_seen':stamp}
    history['observed']=list(observed.values())[-256:]
    return history


def summary(result):
    if result.get('kind')=='discovery':
        return str(len(result['responding']))+' addresses replied to this discovery. Nonresponders remain unverified.'
    if result.get('kind')!='target_checks':return 'Imported readings; see their original timestamps.'
    replies=sum(r['ping']['status']=='responded' for r in result['targets'])
    return str(replies)+' / '+str(len(result['targets']))+' targets replied. DNS '+result['dns']['status']+'.'


def import_report(raw):
    """Copy small, fixed health fields only; exclude raw console responses and credentials."""
    if not isinstance(raw,dict) or raw.get('format')!='adr-service-report-v1' or not isinstance(raw.get('checks'),list) or len(raw['checks'])>20:
        raise DiagnosticError('Choose an ADR combined service report.')
    output={'kind':'service_report','imported_at':now(),'completed_at':str(raw.get('completed_at',''))[:64],'systems':[]}
    def scalar(v):
        return v if type(v) in (bool,int,float) and (type(v)!=float or math.isfinite(v)) else str(v)[:120] if isinstance(v,str) else None
    for c in raw['checks']:
        if not isinstance(c,dict) or c.get('system') not in ('UniFi','Ruckus','WattBox'):continue
        s=c.get('snapshot') or {}
        if not isinstance(s,dict):continue
        system={'system':c['system'],'checked_at':scalar(c.get('post_action_verified_at') or c.get('completed_at')),'readings':[]}
        fields={'WattBox':('outlets',('number','label','on')),
            'UniFi':('sensors',('name','state','unit','last_updated')),
            'Ruckus':('access_points',('name','model','ip','online','connected_clients','controller_state'))}
        key,allowed=fields[c['system']]
        source=s.get('controller') if c['system']=='Ruckus' else s
        source=source if isinstance(source,dict) else {}
        rows=source.get(key,[])
        if isinstance(rows,list):
            system['readings']=[{k:scalar(row.get(k)) for k in allowed} for row in rows[:64] if isinstance(row,dict)]
        if c['system']=='UniFi' and isinstance(s.get('internet_readings'),list):
            system['readings'] += [{k:scalar(row.get(k)) for k in ('name','state','unit','last_updated')} for row in s['internet_readings'][:16] if isinstance(row,dict)]
        output['systems'].append(system)
    return output
