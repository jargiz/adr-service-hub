"""Diagnostics and decision support inside the Service Agent process.

No second server, external command interface or model-driven device actions.
"""
import html
import json
import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from network_diagnostics import DiagnosticError, config, check, discover, retain, save, summary, import_report, tcp
from diagnostic_analysis import ask
from voice_input import transcribe, validate as validate_audio
from presentation import display_text
from dashboard import key_readings
from service_report import redact, assess


def load(path):
    if not path.exists(): return {}
    try:
        if path.stat().st_size > 2*1024*1024: raise ValueError()
        value=json.loads(path.read_text())
        if not isinstance(value,dict): raise ValueError()
        return value
    except (OSError,ValueError):
        raise DiagnosticError('Saved diagnostics could not be read. Inspect app storage; no data was removed.') from None


def evidence(report, options, power=None, native=None, individual=None, usb_ups=None):
    """Allowlist small health fields, never options, identifiers or raw consoles."""
    if not report and not individual and not (power and power.get('enabled')) and not (native and native.get('enabled')) and not (usb_ups and usb_ups.get('enabled')): return {}
    checks=list((report or {}).get('checks',[]))
    def epoch(value):
        try:
            date=datetime.fromisoformat(str(value).replace('Z','+00:00'))
            return date.timestamp() if date.tzinfo else None
        except (ValueError,TypeError):return None
    for name,snapshot in (individual or {}).items():
        if name not in ('Araknis','Internet') or not isinstance(snapshot,dict):continue
        fresh=epoch(snapshot.get('checked_at'))
        old=next((c for c in checks if c.get('system')==name),None)
        previous=epoch(old.get('completed_at')) if old else None
        if fresh is None or (previous is not None and previous>=fresh):continue
        item={'system':name,'snapshot':snapshot,'completed_at':snapshot['checked_at'],
            'evidence_source':'individual_diagnostic'}
        item.update(assess(name,snapshot))
        checks=[c for c in checks if c.get('system')!=name]+[item]
    if not checks and not (power and power.get('enabled')) and not (native and native.get('enabled')) and not (usb_ups and usb_ups.get('enabled')):return {}
    merged=dict(report or {'format':'adr-service-report-v1','completed_at':None},checks=checks)
    out=import_report(merged)
    if power and power.get('enabled'):
        out['power_monitor']={k:power.get(k) for k in ('status','checked_at','current','last_verified','poll_interval_seconds','error','limitations')}
        out['power_monitor']['events']=power.get('events',[])[-12:]
    if native and native.get('enabled'):
        out['native_events']={k:native.get(k) for k in ('listener_running','started_at','error','sources','rate_dropped','limitations')}
        out['native_events']['events']=[{k:v[:400] if k=='message' else v for k,v in e.items()} for e in native.get('events',[])[-12:]]
        out['native_events']['network_events']=[{k:v[:400] if k=='message' else v for k,v in e.items()} for e in native.get('network_events',[])[-16:]]
    if usb_ups and usb_ups.get('enabled'):
        out['usb_ups']={k:usb_ups.get(k) for k in ('status','listener_connected','current','latest','last_state','error','limitations')}
        out['usb_ups']['events']=usb_ups.get('events',[])[-16:]
    out['summaries']=[]
    for item in checks[:20]:
        snapshot=item.get('snapshot') or {}
        out['summaries'].append({'system':item.get('system'), 'status':item.get('status'),
            'checked_at':item.get('post_action_verified_at') or item.get('completed_at'),
            'evidence_source':item.get('evidence_source','combined_report'),
            'responses_received':sum(isinstance(row,dict) and row.get('status')=='response received' for row in snapshot.get('readings',[])),
            'readings':[display_text(str(v)[:250]) for v in key_readings(item.get('system'),snapshot)[:12]],
            'findings':[display_text(str(v)[:250]) for v in item.get('service_findings',[])[:6]],
            'comparisons':[display_text(str(v)[:250]) for v in item.get('comparisons',[])[:8]],
            'limitations':[display_text(str(v)[:250]) for v in item.get('data_limitations',[])[:4]]})
    out['network_health']=[]
    green = next(((item.get('snapshot') or {}) for item in checks if item.get('system')=='Internet'), None)
    if green:
        out['green_network']={k:green.get(k) for k in ('source','checked_at','probes','dns')}
        out['green_network']['readings']=green.get('readings',[])[:12]
        speed=green.get('speed_test')
        if isinstance(speed,dict):
            out['green_network']['speed_test']={k:speed.get(k) for k in ('source','provider','server_id','endpoint','started_at','completed_at','fresh_values_confirmed','limitations')}
    for item in checks:
        network=(item.get('snapshot') or {}).get('network_health')
        if not isinstance(network,dict):continue
        # Fixed normalized fields only, never controller config/console output.
        row={k:network.get(k) for k in ('vendor','checked_at','coverage','multicast') if k in network}
        row['devices']=[]
        for d in network.get('devices',[])[:4]:
            device={k:d[k] for k in ('id','name','type','state','uptime_seconds','stp_priority','stp_protocol','stp_root_id','topology_changes') if k in d}
            device['ports']=[{k:p[k] for k in ('port','name','link','speed_mbps','stp_state','rx_errors','tx_errors','rx_dropped','tx_dropped','rx_broadcast','tx_broadcast','rx_multicast','tx_multicast') if k in p} for p in d.get('ports',[])[:24]]
            row['devices'].append(device)
        row['networks']=network.get('networks',[])[:16]
        row['findings']=network.get('findings',[])[:8]
        row['limitations']=network.get('limitations',[])[:8]
        row['evidence_limited']=len(network.get('devices',[]))>4 or any(len(d.get('ports',[]))>24 for d in network.get('devices',[])[:4])
        out['network_health'].append(row)
    private=[v for k,v in options.items() if any(w in k for w in ('password','api_key','token')) and isinstance(v,str) and v]
    return redact(out,private)


def daily_limit(options,key):
    value=options.get(key,100)
    return value if type(value) is int and 0<=value<=10000 else 100


class Hub:
    def __init__(self, data, options, report_provider, identity_provider=None):
        self.identity_provider=identity_provider
        self.data=Path(data)/'diagnostics'; self.options=options;self.report_provider=report_provider
        self.lock=threading.Lock();self.busy=False;self.progress='Ready';self.answer='';self.last_started=0;self.answer_id=''
        self.transcript='';self.transcript_id='';self.voice_quota={};self.last_voice_started=0
        self.error='';self.settings={'networks':[],'targets':[]};self.history={};self.quota={};self.result={}
        self.discovery={};self.discovery_subnet='';self.discovery_last_attempt=0;self.discovery_ready_at=time.time()+60
        try:
            self.data.mkdir(parents=True,exist_ok=True)
            self.settings=config(options)
            self.history=retain(load(self.data/'history.json'))
            self.quota=load(self.data/'analysis_attempts.json')
            self.voice_quota=load(self.data/'voice_attempts.json')
            self.result=(self.history.get('samples') or [{}])[-1].get('result',{})
            self.discovery=next((s['result'] for s in reversed(self.history.get('samples',[])) if s.get('result',{}).get('kind')=='discovery'),{})
            schedule=load(self.data/'discovery_schedule.json')
            candidate=schedule.get('subnet',self.discovery.get('subnet',''))
            if candidate in [str(n) for n in self.settings['networks']]:self.discovery_subnet=candidate
            attempt=schedule.get('last_attempt',0)
            if type(attempt) in (int,float) and 0<=attempt<=time.time()+60:self.discovery_last_attempt=attempt
        except DiagnosticError as exc:self.error=str(exc)
        except Exception:self.error='Diagnostic storage or configuration needs attention. No data was removed.'

    def status(self):
        with self.lock:
            return {'busy':self.busy,'blocked':bool(self.error),'progress':self.error or self.progress,
                'transcript':self.transcript,'transcript_id':self.transcript_id,
                'voice_enabled':self.options.get('voice_enabled') is True,
                'answer':self.answer,'answer_id':self.answer_id,'result':self.result,'observed':self.history.get('observed',[]),
                'discovery':self.discovery,'discovery_subnet':self.discovery_subnet,
                'summary':summary(self.result) if self.result else 'No local checks yet.',
                'enabled':self.options.get('diagnostics_enabled') is True,
                'cloud_enabled':self.options.get('cloud_analysis_enabled') is True}

    def start_voice(self,audio,mime,confirmed,request_id,thread_factory=threading.Thread):
        with self.lock:
            if self.error:raise DiagnosticError(self.error)
            if self.busy:raise DiagnosticError('Diagnostics are already running.')
            if self.options.get('voice_enabled') is not True or self.options.get('cloud_analysis_enabled') is not True or not confirmed:
                raise DiagnosticError('Enable voice and confirm sending this recording.')
            if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',request_id):
                raise DiagnosticError('Invalid recording request.')
            mime=validate_audio(audio,mime)
            if time.time()-self.last_voice_started<10:raise DiagnosticError('Wait ten seconds between diagnostic requests.')
            day=time.strftime('%Y-%m-%d',time.gmtime())
            count=self.voice_quota.get('count',0) if self.voice_quota.get('day')==day else 0
            limit=daily_limit(self.options,'daily_voice_limit')
            if type(count) is not int or count<0:raise DiagnosticError('Saved voice counter is invalid. Inspect app storage.')
            if limit and count>=limit:
                raise DiagnosticError('Daily voice limit reached ('+str(limit)+' attempts, UTC day). Increase daily_voice_limit in Configuration.')
            quota={'day':day,'count':count+1}
            save(self.data/'voice_attempts.json',quota);self.voice_quota=quota
            self.busy=True;self.last_voice_started=time.time();self.progress='Transcribing question'
            self.transcript='';self.transcript_id=request_id
        def run():
            try:
                text=transcribe(self.options,audio,mime,True)
                with self.lock:self.transcript=text;self.progress='Review your question, then tap Ask ADR.'
            except DiagnosticError as exc:
                with self.lock:self.progress=str(exc)
            except Exception:
                with self.lock:self.progress='Transcription could not finish. Type your question or try again.'
            finally:
                with self.lock:self.busy=False
        try:thread_factory(target=run,daemon=True).start()
        except Exception:
            with self.lock:self.busy=False;self.progress='Recording job could not start.'
            raise DiagnosticError('Recording job could not start.') from None

    def record(self,result):
        with self.lock:
            history=retain(dict(self.history),result)
            save(self.data/'history.json',history)
            self.history=history;self.result=result

    def scheduled_check(self):
        if self.error:raise DiagnosticError(self.error)
        if self.options.get('diagnostics_enabled') is not True or not self.settings['targets']:
            raise DiagnosticError('Enable diagnostics and configure target addresses first.')
        result=check(self.settings)
        self.record(result)
        return result

    def discovery_tick(self):
        # Pilot serializes this with other operations. No new subnet is inferred.
        if (self.error or self.busy or self.options.get('automatic_monitoring',True) is not True
                or self.options.get('diagnostics_enabled') is not True or not self.discovery_subnet
                or time.time()<max(self.discovery_ready_at,self.discovery_last_attempt+1200)
                or time.time()-self.last_started<10):return
        self.start('discover',{'subnet':self.discovery_subnet})

    def start(self,action,fields,thread_factory=threading.Thread):
        with self.lock:
            if self.error:raise DiagnosticError(self.error)
            if self.busy:raise DiagnosticError('Diagnostics are already running.')
            if time.time()-self.last_started<10:raise DiagnosticError('Wait ten seconds between diagnostic requests.')
            if action not in ('check','discover','ask'):raise DiagnosticError('Unsupported diagnostic request.')
            if action!='ask' and self.options.get('diagnostics_enabled') is not True:
                raise DiagnosticError('Enable diagnostics in Configuration first.')
            if action=='check' and not self.settings['targets']:raise DiagnosticError('Configure target addresses first.')
            if action=='discover' and fields.get('subnet') not in [str(n) for n in self.settings['networks']]:
                raise DiagnosticError('Choose a configured subnet.')
            if action=='discover':
                attempted=time.time()
                save(self.data/'discovery_schedule.json',{'subnet':fields['subnet'],'last_attempt':attempted})
                self.discovery_subnet=fields['subnet'];self.discovery_last_attempt=attempted
            if action=='ask':
                if self.options.get('cloud_analysis_enabled') is not True or fields.get('confirm')!='yes':
                    raise DiagnosticError('Enable cloud analysis and confirm sending readings.')
                if not 1<=len(fields.get('question','').strip())<=1000:raise DiagnosticError('Enter a question of 1–1000 characters.')
                # Caller holds the app lock: capture a consistent, sanitized report.
                service=self.report_provider()
                if not service and not self.result:raise DiagnosticError('Run checks first.')
                previous=[s['result'] for s in self.history.get('samples',[])[:-1] if s.get('result',{}).get('kind')=='target_checks']
                latest=self.result
                if latest.get('kind')=='discovery':
                    latest=dict(latest,devices=latest.get('devices',[])[:16],responding=latest.get('responding',[])[:64],
                        discovered_count=len(latest.get('responding',[])),identity_rows_omitted=max(0,len(latest.get('devices',[]))-16))
                collected={'latest_checks':latest,'previous_checks':previous[-1:],'service_report':service}
                # Fail before charging the local attempt quota if evidence is too large.
                if len(json.dumps(collected,allow_nan=False).encode())>40000:
                    raise DiagnosticError('Readings exceed the analysis limit. Run a focused local check first.')
                day=time.strftime('%Y-%m-%d',time.gmtime())
                count=self.quota.get('count',0) if self.quota.get('day')==day else 0
                limit=daily_limit(self.options,'daily_analysis_limit')
                if type(count) is not int or count<0:raise DiagnosticError('Saved analysis counter is invalid. Inspect app storage.')
                if limit and count>=limit:raise DiagnosticError('Daily analysis limit reached ('+str(limit)+' attempts, UTC day). Increase daily_analysis_limit in Configuration.')
                quota={'day':day,'count':count+1};save(self.data/'analysis_attempts.json',quota);self.quota=quota
            self.busy=True;self.last_started=time.time();self.progress='Starting'
        def progress(text):
            with self.lock:self.progress=text
        def run():
            try:
                if action=='ask':
                    progress('Reviewing readings')
                    answer=ask(self.options,fields['question'],collected,True)
                    with self.lock:self.answer=display_text(answer);self.answer_id=secrets.token_urlsafe(12)
                else:
                    result=check(self.settings,progress=progress) if action=='check' else discover(self.settings,fields['subnet'],progress=progress,identify=self.identity_provider,web_probe=tcp)
                    self.record(result)
                    if action=='discover':
                        with self.lock:self.discovery=result
                progress('Complete')
            except DiagnosticError as exc:progress(str(exc))
            except Exception:progress('Request could not finish. Previous readings retained; no retry was made.')
            finally:
                with self.lock:self.busy=False
        try:thread_factory(target=run,daemon=True).start()
        except Exception:
            with self.lock:self.busy=False;self.progress='Job could not start.'
            raise DiagnosticError('Job could not start.') from None


def panels(hub, csrf):
    esc=lambda s:html.escape(str(s),quote=True)
    subnets=''.join('<option value="'+esc(n)+'"'+(' selected' if str(n)==hub.discovery_subnet else '')+'>'+esc(n)+'</option>' for n in hub.settings['networks'])
    network='''<section id="diagnostics"><h2>Diagnostics</h2><p id="diag-progress" role="status" aria-live="polite">Ready</p>
<div class="toolbar"><button type="button" data-diagnostic="check">Check connectivity</button><select id="diag-subnet" aria-label="Discovery subnet">'''+subnets+'''</select><button type="button" data-diagnostic="discover">Discover devices</button></div>
<p id="diag-summary"></p><div class="diagnostic-table"><table><thead><tr><th>Target</th><th>Ping</th><th>Latency</th></tr></thead><tbody id="diag-targets"></tbody></table></div><p id="diag-discovery"></p>
<div class="diagnostic-table discovered-devices"><table><thead><tr><th>Manufacturer</th><th>IP address</th><th>Hostname</th><th>MAC address</th><th>Device type</th><th>Identity source</th><th>Web interface</th></tr></thead><tbody id="diag-devices"></tbody></table></div>
<p class="report-caption">Refreshes every 20 minutes while automatic monitoring is enabled.</p>
<details id="diagnostic-observed"><summary>Observed devices</summary><div class="diagnostic-table"><table><thead><tr><th>Manufacturer</th><th>IP address</th><th>Hostname</th><th>MAC address</th><th>Identity checked</th><th>Last reply</th></tr></thead><tbody id="diag-observed"></tbody></table></div></details></section>'''
    assistant='''<section id="ask-adr"><h2>Ask ADR</h2><p id="adr-native-status" role="status"></p><details id="adr-native-history"><summary>Native device events</summary><div id="adr-native-sources"></div><div id="adr-native-list"></div><label for="adr-native-source">Log source</label><select id="adr-native-source"></select><input id="adr-native-file" type="file" accept="text/plain,.txt,.log"><button type="button" id="adr-native-import">Import log</button><p id="adr-native-import-status" role="status"></p></details><form id="adr-question-form"><input type="hidden" id="diag-csrf" value="'''+esc(csrf)+'''">
<label for="adr-question">Question</label><textarea id="adr-question" maxlength="1000" placeholder="What needs attention?" rows="3"></textarea>
<p class="report-caption">Ask ADR sends your question and collected readings to OpenAI.</p>
<div class="toolbar"><button type="button" id="adr-record">Speak</button><button type="button" id="adr-record-cancel" hidden>Cancel</button><button type="button" data-diagnostic="ask">Ask ADR</button></div>
<p class="report-caption">Speak sends your recording to OpenAI. API usage applies.</p>
<p id="adr-transcript"></p><button type="button" id="adr-use-transcript" hidden>Use transcript</button><p id="adr-voice-status" role="status" aria-live="polite"></p></form>
<div class="toolbar voice-output"><button type="button" id="adr-read-answer">Read answer</button><button type="button" id="adr-stop-reading">Stop reading</button></div><p id="adr-analysis-progress" role="status"></p><div id="adr-answer" aria-live="polite"></div></section>'''
    return network,assistant


