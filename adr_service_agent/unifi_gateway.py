"""Bounded UniFi OS gateway speed-test reads and one explicitly scheduled test.

The local Network API key is sent only over HTTPS to the pinned gateway.
Routes are controller APIs used by UniFi's own dashboard; firmware compatibility
must be verified on installation. No fallback to a different measurement source.
"""
import hashlib
import http.client
import json
import math
import re
import ssl
import time
from datetime import datetime, timezone
from ruckus_controller import inspect_certificate
from wattbox import ProtocolError


class GatewayError(ProtocolError):
    pass


def settings(options):
    host = str(options.get('unifi_gateway_host', '')).strip()
    port = options.get('unifi_gateway_port', 443)
    key = options.get('unifi_gateway_api_key', '')
    site = str(options.get('unifi_gateway_site', 'default'))
    wan = str(options.get('unifi_gateway_wan', 'WAN'))
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}', host):
        raise GatewayError('Set the UniFi gateway address and local API key in Configuration.')
    if type(port) is not int or not 1 <= port <= 65535:
        raise GatewayError('Invalid UniFi gateway HTTPS port.')
    if not isinstance(key, str) or not key or len(key) > 1024 or any(c.isspace() for c in key):
        raise GatewayError('Set a local UniFi Network API key in Configuration.')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', site) or not re.fullmatch(r'WAN\d*', wan):
        raise GatewayError('Invalid UniFi site or WAN selection.')
    return {'host':host, 'port':port, 'api_key':key, 'site':site, 'wan':wan}


def target(config, pin):
    return hashlib.sha256(json.dumps([config['host'],config['port'],config['site'],config['wan'],pin.get('sha256')]).encode()).hexdigest()


def request(config, pin, method, operation):
    routes = {'results':('GET', '/proxy/network/v2/api/site/' + config['site'] + '/speedtest'),
        'start':('POST', '/proxy/network/api/s/' + config['site'] + '/cmd/devmgr')}
    if operation not in routes or method != routes[operation][0]:
        raise GatewayError('Unsupported gateway operation.')
    if pin.get('host') != config['host'] or pin.get('port') != config['port'] or not re.fullmatch(r'[a-f0-9]{64}', str(pin.get('sha256',''))):
        raise GatewayError('Inspect and approve the UniFi gateway certificate in Connections first.')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = http.client.HTTPSConnection(config['host'],config['port'],context=context,timeout=12)
    try:
        connection.connect()
        digest = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        if digest != pin['sha256']:
            raise GatewayError('UniFi gateway certificate changed. API key was not sent.')
        body = json.dumps({'cmd':'speedtest'}) if operation == 'start' else None
        connection.request(method,routes[operation][1],body=body,
            headers={'X-API-KEY':config['api_key'],'Accept':'application/json','Content-Type':'application/json'})
        response = connection.getresponse()
        raw = response.read(1024*1024+1)
        if response.status != 200 or len(raw)>1024*1024:
            raise GatewayError('UniFi gateway API request failed (HTTP ' + str(response.status) + '). Check local API-key access and firmware compatibility; no retry was made.')
        result = json.loads(raw)
        if not isinstance(result,dict) or result.get('meta',{}).get('rc') not in (None,'ok'):
            raise GatewayError('UniFi gateway did not confirm the request.')
        return result
    except GatewayError: raise
    except Exception:
        raise GatewayError('UniFi gateway request could not complete. No automatic retry was made.') from None
    finally: connection.close()


def value(raw):
    if isinstance(raw,bool): return None
    try:
        n=float(raw)
        return n if math.isfinite(n) and n>=0 else None
    except (ValueError,TypeError): return None


def normalize(body, wan='WAN', now=None):
    now = now or datetime.now(timezone.utc)
    entries=body.get('data')
    if not isinstance(entries,list) or len(entries)>4096:
        raise GatewayError('Unexpected UniFi speed-test response.')
    output=[]
    groups={str(e.get('wan_networkgroup') or e.get('wan_group')) for e in entries if isinstance(e,dict) and (e.get('wan_networkgroup') or e.get('wan_group'))}
    interfaces={str(e.get('interface_name') or e.get('interface') or e.get('ifname')) for e in entries if isinstance(e,dict) and (e.get('interface_name') or e.get('interface') or e.get('ifname'))}
    for e in entries:
        if not isinstance(e,dict):continue
        group=e.get('wan_networkgroup') or e.get('wan_group')
        if group and str(group).upper()!=wan:continue
        if not group and (wan!='WAN' or len(groups)>1 or len(interfaces)>1):continue
        if str(e.get('status_text',e.get('status','completed'))).lower() not in ('completed','complete','success','ok'):
            continue
        stamp=value(e.get('time'))
        if stamp is None:continue
        try: dt=datetime.fromtimestamp(stamp/1000,timezone.utc)
        except (ValueError,OverflowError,OSError):continue
        if dt.year<2020 or (dt-now).total_seconds()>60:continue
        down=value(e.get('download_mbps',e.get('xput_down')))
        up=value(e.get('upload_mbps',e.get('xput_up')))
        ping=value(e.get('latency_ms',e.get('speedtest_ping')))
        if down is None or up is None:continue
        output.append({'time':dt.isoformat(timespec='seconds'),'download':down,'upload':up,'ping':ping,'wan':wan})
    output.sort(key=lambda x:x['time'])
    # Duplicate reads never create new speed-test samples.
    return list({x['time']:x for x in output}.values())[-256:]


def collect(options, pin, request_fn=request):
    config=settings(options)
    records=normalize(request_fn(config,pin,'GET','results'),config['wan'])
    readings=[]
    if records:
        last=records[-1]
        for label,field,unit in [('Download','download','Mbit/s'),('Upload','upload','Mbit/s'),('Ping','ping','ms')]:
            if last[field] is not None:
                readings.append({'name':'UniFi speed test '+label,'state':str(last[field]),'unit':unit,'last_updated':last['time'],'source':'unifi_gateway'})
    return {'source':'unifi_gateway','target_id':target(config,pin),'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'readings':readings,'records':records,'wan':config['wan'], 'limitations':[] if records else ['UniFi returned no completed speed-test result for the selected WAN.']}


def run(options, pin, request_fn=request, wait_fn=time.sleep):
    config=settings(options)
    # Explicit single-WAN start semantics only. Never silently test another WAN.
    if config['wan']!='WAN':raise GatewayError('Automatic gateway tests currently support the primary WAN only.')
    before=collect(options,pin,request_fn)
    previous=before['records'][-1]['time'] if before['records'] else ''
    started=datetime.now(timezone.utc)
    acknowledged=request_fn(config,pin,'POST','start')
    if acknowledged.get('meta',{}).get('rc')!='ok' and acknowledged.get('result') not in ('ok','success','started','queued'):
        raise GatewayError('Gateway did not acknowledge the speed-test request; no retry was made.')
    result=before
    for _ in range(12):
        wait_fn(10)
        result=collect(options,pin,request_fn)
        if result['records'] and result['records'][-1]['time']>previous and datetime.fromisoformat(result['records'][-1]['time'])>=started:
            return {'started_at':started.isoformat(),'completed_at':datetime.now(timezone.utc).isoformat(),
                'readings':result['readings'],'fresh_values_confirmed':True,'quality_issues':[], 'source':'unifi_gateway',
                'measurement_quality':'no issue established','note':'Measured by the UniFi gateway on the primary WAN.','limitations':[],'gateway':result}
    return {'started_at':started.isoformat(),'completed_at':datetime.now(timezone.utc).isoformat(),'readings':result['readings'],
        'fresh_values_confirmed':False,'quality_issues':[],'source':'unifi_gateway','gateway':result,
        'measurement_quality':'unverified','note':'UniFi accepted the request; a new completed result was not confirmed.',
        'limitations':['A new UniFi result was not confirmed within two minutes. The test may still be running; no second test was started.']}
