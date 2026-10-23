"""Single-outlet controls with fresh mapping checks and single-use confirmation."""
import hashlib
import json
import secrets
import time
from pathlib import Path
from wattbox import ProtocolError


def identity(pilot):
    pilot.ready()
    path=pilot.data/'known_hosts'
    if not path.exists():raise ProtocolError('Approve the WattBox SSH identity in Connections first.')
    return hashlib.sha256(json.dumps([pilot.config['wattbox_host'],pilot.config['ssh_port'],path.read_text()]).encode()).hexdigest()


def enabled(pilot):
    if pilot.araknis_options.get('allow_outlet_control') is not True:
        raise ProtocolError('Enable allow_outlet_control in Configuration to use outlet controls.')
    if any(getattr(pilot,name,False) for name in ('active','service_running','internet_test_running','controller_running','araknis_running','cp4_running','crestron_running','control4_running','bluesound_running','sense_running')):
        raise ProtocolError('Wait for the current operation to finish.')


def prepare(pilot, number, action):
    enabled(pilot)
    if type(number) is not int or not 1<=number<=18 or action not in ('ON','OFF','RESET'):
        raise ProtocolError('Choose one outlet and a supported action.')
    target=identity(pilot)
    with pilot.box() as box: inventory=box.inventory()
    if not inventory['model'].startswith('WB-800') or len(inventory['outlets'])<number:
        raise ProtocolError('Outlet control requires a supported WB-800 and a complete inventory.')
    outlet=inventory['outlets'][number-1]
    if outlet['number']!=number:raise ProtocolError('Outlet inventory is ambiguous.')
    if action=='RESET' and not outlet['on']:raise ProtocolError('Outlet is off. Use On if you intend to power it on.')
    nonce=secrets.token_urlsafe(24)
    pending={'nonce':nonce,'created':time.monotonic(),'target':target,'number':number,'action':action,
        'label':outlet['label'],'on':outlet['on'],'model':inventory['model'],'count':len(inventory['outlets'])}
    pilot.power_pending=pending
    pilot.inventory=inventory
    return pending


def execute(pilot, nonce, confirmed, save_fn):
    enabled(pilot)
    item=pilot.power_pending
    pilot.power_pending=None
    if not confirmed or not item or not secrets.compare_digest(str(nonce),item['nonce']) or time.monotonic()-item['created']>120:
        raise ProtocolError('Outlet confirmation expired or was not confirmed. Select the action again.')
    if identity(pilot)!=item['target']:raise ProtocolError('WattBox target or SSH identity changed. Select the action again.')
    path=pilot.data/'outlet_control_state.json'
    try: state=json.loads(path.read_text()) if path.exists() else {}
    except (OSError,ValueError):raise ProtocolError('Saved outlet action state is unreadable. Controls are blocked pending review.') from None
    if not isinstance(state,dict):raise ProtocolError('Invalid saved outlet action state.')
    key=item['target']+':'+str(item['number'])
    try:last=float(state.get(key,0))
    except (ValueError,TypeError):raise ProtocolError('Invalid saved outlet cooldown.') from None
    if time.time()-last<10:raise ProtocolError('Wait ten seconds before another action on this outlet.')
    with pilot.box() as box:
        fresh=box.inventory()
        if fresh['model']!=item['model'] or len(fresh['outlets'])!=item['count'] or fresh['outlets'][item['number']-1]!={'number':item['number'],'label':item['label'],'on':item['on']}:
            raise ProtocolError('Outlet mapping or power state changed. Select the action again.')
        state[key]=time.time()
        save_fn(path,state)
        pilot.audit('outlet_action_attempt',str(item['number'])+' '+item['action'])
        pilot.result='Outlet action sent; acknowledgement unverified. Do not retry automatically.'
        if pilot.service_report:
            for check in pilot.service_report.get('checks', []):
                if check.get('system')=='WattBox':check.setdefault('snapshot',{})['power_action_pending_read']=True
        box.set_power(item['number'],item['action'])
    pilot.inventory=None
    pilot.result='WattBox accepted '+item['action']+' for outlet '+str(item['number'])+' ('+item['label']+'). Updated power state awaits the next read.'
    # The old combined inventory is explicitly marked stale until a new read.
    if pilot.service_report:
        for check in pilot.service_report.get('checks',[]):
            if check.get('system')=='WattBox':
                check.setdefault('snapshot',{})['power_action_pending_read']=True
