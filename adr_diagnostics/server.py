"""Ingress-only prototype: one diagnostic job at a time, no device controls."""
import base64
import hashlib
import html
import json
import resource
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from diagnostics import DiagnosticError, config, check, discover, import_report, retain, save, summary
from analysis import ask

ROOT=Path(__file__).parent
TEMPLATE=(ROOT/'ui.html').read_text()
SCRIPT=TEMPLATE.split('<script>',1)[1].split('</script>',1)[0]
SCRIPT_HASH=base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()


def load(path, limit=2*1024*1024):
    if not path.exists():return {}
    if path.stat().st_size>limit:raise DiagnosticError('Saved diagnostic data exceeds its limit.')
    result=json.loads(path.read_text())
    if not isinstance(result,dict):raise DiagnosticError('Saved diagnostic data is invalid.')
    return result


class State:
    def __init__(self, data, options):
        self.data=Path(data);self.data.mkdir(parents=True,exist_ok=True)
        self.options=options;self.settings=config(options)
        self.lock=threading.Lock();self.csrf=secrets.token_urlsafe(32)
        self.busy=False;self.progress='Ready';self.last_started=0;self.answer=''
        self.history=retain(load(self.data/'history.json'))
        self.imported=load(self.data/'report.json')
        self.quota=load(self.data/'analysis_attempts.json')
        self.result=(self.history.get('samples') or [{}])[-1].get('result',{})
        self.stop=threading.Event()

    def status(self):
        with self.lock:
            return {'busy':self.busy,'progress':self.progress,'result':self.result,'answer':self.answer,
                'summary':summary(self.result) if self.result else 'No checks yet.',
                'observed':self.history.get('observed',[]),'imported':bool(self.imported),
                'cloud_enabled':self.options.get('cloud_analysis_enabled') is True,
                'peak_memory_mb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1)}

    def start(self, action, fields, thread_factory=threading.Thread):
        with self.lock:
            if self.busy:raise DiagnosticError('A check is already running.')
            if time.time()-self.last_started<10:raise DiagnosticError('Wait ten seconds between requests.')
            if action not in ('check','discover','ask','import'):raise DiagnosticError('Unsupported request.')
            if action=='check' and not self.settings['targets']:raise DiagnosticError('Configure target addresses first.')
            if action=='discover' and fields.get('subnet') not in [str(n) for n in self.settings['networks']]:
                raise DiagnosticError('Choose a configured subnet.')
            if action=='ask':
                if self.options.get('cloud_analysis_enabled') is not True or fields.get('confirm')!='yes':
                    raise DiagnosticError('Enable cloud analysis and confirm sending evidence.')
                if not self.result and not self.imported:raise DiagnosticError('Run checks or import a service report first.')
                if not 1<=len(fields.get('question','').strip())<=1000:raise DiagnosticError('Enter a question of 1–1000 characters.')
                # Reserve before the request, including failed attempts. No retry loop.
                day=time.strftime('%Y-%m-%d',time.gmtime())
                count=self.quota.get('count',0) if self.quota.get('day')==day else 0
                if type(count) is not int or count<0 or count>=10:raise DiagnosticError('Daily analysis limit reached (10 attempts, UTC day).')
                self.quota={'day':day,'count':count+1};save(self.data/'analysis_attempts.json',self.quota)
            if action=='import':
                try:parsed=json.loads(fields.get('report',''))
                except (ValueError,TypeError):raise DiagnosticError('Choose a valid JSON service report.') from None
                imported=import_report(parsed)
            else:imported=None
            self.busy=True;self.answer='';self.progress='Starting';self.last_started=time.time()
        def progress(message):
            with self.lock:self.progress=message
        def run():
            try:
                if action=='ask':
                    progress('Analyzing collected evidence')
                    previous=[s['result'] for s in self.history.get('samples',[])[:-1] if s.get('result',{}).get('kind')=='target_checks']
                    evidence={'latest_checks':self.result,'previous_checks':previous[-1:] , 'imported_report':self.imported}
                    answer=ask(self.options,fields['question'],evidence,True)
                    with self.lock:self.answer=answer
                elif action=='import':
                    save(self.data/'report.json',imported)
                    with self.lock:self.imported=imported
                else:
                    result=check(self.settings,progress=progress) if action=='check' else discover(self.settings,fields['subnet'],progress=progress)
                    with self.lock:
                        self.history=retain(self.history,result);save(self.data/'history.json',self.history)
                        self.result=result
                progress('Complete')
            except DiagnosticError as exc:progress(str(exc))
            except Exception:progress('Request could not finish. Previous readings retained; no automatic retry.')
            finally:
                with self.lock:self.busy=False
        try:thread_factory(target=run,daemon=True).start()
        except Exception:
            with self.lock:self.busy=False;self.progress='Job could not start.'
            raise DiagnosticError('Job could not start.') from None

    def monitor(self):
        if not self.settings['automatic_monitoring'] or not self.settings['targets']:return
        # Separate app; no scanning or model requests on this schedule.
        while not self.stop.wait(120):
            if time.time()-self.last_started>=self.settings['interval']*60:
                try:self.start('check',{})
                except DiagnosticError:pass


def page(state):
    esc=lambda s:html.escape(str(s),quote=True)
    subnets=''.join('<option value="'+esc(n)+'">'+esc(n)+'</option>' for n in state.settings['networks'])
    logo=(ROOT/'adr-logo.b64').read_text().strip()
    return TEMPLATE.replace('__CSRF__',esc(state.csrf)).replace('__SUBNETS__',subnets).replace('__LOGO__',logo)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass

    def authorized(self):
        # Forwarded headers are not a trusted substitute for the actual peer.
        if self.client_address[0]!='172.30.32.2':
            self.send_error(403);return False
        return True

    def respond(self,body,content_type='text/html; charset=utf-8',status=200):
        encoded=body.encode();self.send_response(status)
        self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(encoded)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'sha256-"+SCRIPT_HASH+"'; connect-src 'self'; form-action 'self'; base-uri 'none'")
        self.end_headers();self.wfile.write(encoded)

    def do_GET(self):
        if not self.authorized():return
        path=urlsplit(self.path).path
        if path in ('','/'):
            self.respond(page(self.server.state))
        elif path=='/state':
            self.respond(json.dumps(self.server.state.status()),'application/json')
        else:self.send_error(404)

    def do_POST(self):
        if not self.authorized():return
        try:
            if urlsplit(self.path).path!='/action':raise DiagnosticError('Unsupported request.')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=2*1024*1024:raise DiagnosticError('Request is too large.')
            self.connection.settimeout(10)
            fields=parse_qs(self.rfile.read(length).decode(),keep_blank_values=True,max_num_fields=8)
            if any(len(v)!=1 for v in fields.values()):raise DiagnosticError('Duplicate request fields.')
            fields={k:v[0] for k,v in fields.items()}
            if not secrets.compare_digest(fields.pop('csrf',''),self.server.state.csrf):
                self.respond('Invalid request.','text/plain',403);return
            action=fields.pop('action','')
            self.server.state.start(action,fields)
            self.respond(json.dumps({'accepted':True}),'application/json',202)
        except DiagnosticError as exc:self.respond(json.dumps({'error':str(exc)}),'application/json',400)
        except Exception:self.respond(json.dumps({'error':'Invalid request.'}),'application/json',400)


def main():
    options=load(Path('/data/options.json'),65536)
    try:state=State('/data',options)
    except Exception:
        raise SystemExit('ADR Diagnostics configuration or saved data is invalid; inspect locally.') from None
    server=ThreadingHTTPServer(('0.0.0.0',8099),Handler);server.state=state
    threading.Thread(target=state.monitor,daemon=True).start()
    print('ADR Diagnostics Preview 0.1.0 ready. Checks are bounded; cloud analysis is on request only.')
    try:server.serve_forever()
    finally:state.stop.set();server.server_close()


if __name__=='__main__':main()
