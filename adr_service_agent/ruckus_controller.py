"""Pinned-HTTPS Unleashed statistics. No configuration or device commands."""
import asyncio
import hashlib
import re
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from crestron import scalar
from wattbox import ProtocolError


class ControllerError(ProtocolError):
    pass


def settings(options):
    host = options.get('ruckus_controller_host', '').strip()
    port = options.get('ruckus_controller_port', 443)
    user = options.get('ruckus_controller_username', '')
    password = options.get('ruckus_controller_password', '')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}', host):
        raise ControllerError('Set the Ruckus controller host in app Configuration.')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ControllerError('Invalid Ruckus controller HTTPS port.')
    if not isinstance(user, str) or not user.strip() or len(user) > 256 or not isinstance(password, str) or not password or len(password) > 256:
        raise ControllerError('Set the Ruckus controller username and password in app Configuration.')
    return {'host': host, 'port': port, 'username': user, 'password': password}


def inspect_certificate(config):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((config['host'], config['port']), timeout=5) as connection:
        with context.wrap_socket(connection, server_hostname=config['host']) as secure:
            cert = secure.getpeercert(binary_form=True)
    if not cert:
        raise ControllerError('Controller did not provide a certificate.')
    return hashlib.sha256(cert).hexdigest()


class BoundedResponse:
    def __init__(self, context, method):
        self.context, self.method, self.response = context, method, None

    async def __aenter__(self):
        self.response = await self.context.__aenter__()
        if self.method == 'POST' and self.response.status != 200:
            await self.context.__aexit__(None, None, None)
            raise ControllerError('Controller statistics request failed; no automatic retry.')
        return self

    async def __aexit__(self, *args):
        return await self.context.__aexit__(*args)

    def __getattr__(self, name):
        return getattr(self.response, name)

    async def read(self):
        chunks, total = [], 0
        while True:
            chunk = await self.response.content.read(min(65536, 1024*1024 + 1-total))
            if not chunk: break
            total += len(chunk)
            if total > 1024*1024:
                raise ControllerError('Controller response exceeded the size limit.')
            chunks.append(chunk)
        return b''.join(chunks)

    async def text(self, errors='replace', **_):
        return (await self.read()).decode('utf-8', errors=errors)


class StatisticsSession:
    """Constrain the SDK to one HTTPS origin and read-statistics POSTs."""
    def __init__(self, session, config, pin):
        self.session, self.config, self.pin = session, config, pin

    @property
    def headers(self):
        return self.session.headers

    def request(self, method, url, **kwargs):
        if method not in ('GET', 'POST'):
            raise ControllerError('Only controller authentication and statistics reads are permitted.')
        target = urlsplit(str(url))
        if target.scheme != 'https' or target.hostname != self.config['host'].lower() or (target.port or 443) != self.config['port'] or target.username or target.password:
            raise ControllerError('Controller redirected outside the approved HTTPS target.')
        if method == 'POST':
            data = kwargs.get('data', '')
            if not isinstance(data, str) or len(data) > 4096 or not target.path.endswith('/_cmdstat.jsp'):
                raise ControllerError('Only controller statistics requests are permitted.')
            try: root = ET.fromstring(data)
            except ET.ParseError: raise ControllerError('Invalid statistics request.') from None
            if root.tag != 'ajax-request' or root.get('action') != 'getstat' or root.get('comp') not in ('cluster', 'stamgr') or any(child.tag not in ('ap', 'client') for child in root):
                raise ControllerError('Controller changes are not permitted.')
        kwargs['allow_redirects'] = False
        kwargs['ssl'] = self.pin
        return BoundedResponse(self.session.request(method, url, **kwargs), method)

    def get(self, url, **kwargs): return self.request('GET', url, **kwargs)
    def post(self, url, **kwargs): return self.request('POST', url, **kwargs)


def normalize(aps):
    if not isinstance(aps, list):
        raise ControllerError('Unexpected access point response.')
    output = []
    for ap in aps[:128]:
        if not isinstance(ap, dict): continue
        raw_count = ap.get('num-sta')
        count = int(raw_count) if re.fullmatch(r'\d{1,5}', str(raw_count)) else None
        state = str(ap.get('state', 'unknown')).strip()
        # Unknown numeric controller enums remain raw until live verification.
        online = True if state.casefold() in ('connected', 'operational', 'online', 'up') else False if state.casefold() in ('disconnected', 'offline', 'down') else None
        output.append({'name': scalar(ap.get('devname') or ap.get('ap-name')) or 'Access point',
            'model': scalar(ap.get('model')), 'mac': scalar(ap.get('mac')), 'ip': scalar(ap.get('ip')),
            'controller_state': scalar(state), 'online': online, 'connected_clients': count})
    return {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source': 'direct_ruckus_controller', 'access_points': output, 'truncated': len(aps) > 128,
        'limitations': ['Controller-reported snapshot. Unknown state codes remain unverified; missing counts are not zero.']}


async def _read(config, digest):
    import aiohttp
    from aioruckus import AjaxSession
    pin = aiohttp.Fingerprint(bytes.fromhex(digest))
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10),
            cookie_jar=aiohttp.CookieJar(unsafe=True), trust_env=False) as http:
        guard = StatisticsSession(http, config, pin)
        session = AjaxSession(guard, f"https://{config['host']}:{config['port']}", config['username'], config['password'])
        try:
            await session.login()
            return normalize(await session.api.get_ap_stats())
        finally:
            try: await session.close()
            except Exception: pass


def collect(config, pin):
    if pin.get('host') != config['host'] or pin.get('port') != config['port'] or not re.fullmatch(r'[a-f0-9]{64}', str(pin.get('sha256', ''))):
        raise ControllerError('Inspect and approve this Ruckus controller certificate first.')
    try:
        result = asyncio.run(asyncio.wait_for(_read(config, pin['sha256']), timeout=40))
        verified = pin.get('verified_online_codes', [])
        if isinstance(verified, list):
            for ap in result['access_points']:
                if ap.get('controller_state') in verified:
                    ap['online'] = True
                    ap['status_basis'] = 'Controller code verified against the local Ruckus dashboard'
        return result
    except Exception:
        raise ControllerError('Ruckus controller read failed. Check the controller address, credentials and approved certificate. No configuration commands were sent.') from None
