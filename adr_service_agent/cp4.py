"""On-demand CP4-R console reads with a fixed command allowlist."""
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko
from araknis import terminal_text
from wattbox import ProtocolError


class CP4Error(ProtocolError):
    pass


HELP_COMMANDS = ('UPTIME ?', 'CPULOAD ?', 'RAMFREE ?', 'IPTABLE ?', 'PROGUPTIME ?', 'SYSTEMREADY ?', 'REPORTCRESNET ?', 'TOP ?')
READ_COMMANDS = ('VER -V', 'HELP ALL', 'IPTABLE', 'UPTIME', 'CPULOAD', 'RAMFREE', 'PROGUPTIME', 'SYSTEMREADY', 'REPORTCRESNET', 'TOP')
ALLOWED = frozenset(READ_COMMANDS + HELP_COMMANDS)


def settings(options):
    host = options.get('cp4_host', '').strip()
    port = options.get('cp4_ssh_port', 22)
    user = options.get('cp4_username', '')
    password = options.get('cp4_password', '')
    if not host or len(host) > 253 or any(char.isspace() for char in host) or any(char in host for char in '/\\@'):
        raise CP4Error('Set the CP4-R address in app Configuration, save, and restart this app.')
    if type(port) is not int or not 1 <= port <= 65535:
        raise CP4Error('Invalid CP4-R SSH port.')
    if not isinstance(user, str) or not user.strip() or len(user) > 256 or not isinstance(password, str) or not password or len(password) > 256:
        raise CP4Error('Set the CP4-R SSH username and password in app Configuration.')
    return {'host': host, 'port': port, 'username': user, 'password': password}


def receive(channel, prompt=None, duration=20, limit=262144):
    """Normalize controls before recognizing a bounded prompt or explicit pager."""
    deadline = time.monotonic() + duration
    data = bytearray()
    last_data = time.monotonic()
    pages = 0
    while time.monotonic() < deadline:
        if channel.recv_ready():
            chunk = channel.recv(min(4096, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            last_data = time.monotonic()
            if len(data) > limit:
                return terminal_text(bytes(data[:limit])), True
        elif channel.closed:
            break
        else:
            text = terminal_text(bytes(data))
            tail = text.splitlines()[-1].strip() if text else ''
            if time.monotonic() - last_data >= 0.3:
                if prompt and tail == prompt:
                    return text, False
                if prompt is None and re.fullmatch(r'[^\n]{1,96}[>#]', tail):
                    return text, False
                if tail.endswith('--More--'):
                    if pages >= 64:
                        return text, True
                    channel.sendall(b' ')
                    pages += 1
                    # Remove the consumed marker so it cannot advance twice.
                    data = bytearray((text[:-8] + '\n').encode('utf-8'))
                    last_data = time.monotonic()
            time.sleep(0.05)
    return terminal_text(bytes(data[:limit])), True


class Console:
    def __init__(self, client, read_fn=receive):
        self.channel = client.invoke_shell(width=160, height=100)
        self.channel.settimeout(1)
        self.read_fn = read_fn
        welcome, partial = read_fn(self.channel)
        lines = welcome.splitlines()
        self.prompt = lines[-1].strip() if lines else ''
        if partial or not re.fullmatch(r'[^\n]{1,96}[>#]', self.prompt):
            raise CP4Error('CP4-R console prompt was not recognized. No diagnostic commands were sent.')
        self.welcome = welcome
        self.ready = True

    def query(self, command):
        if command not in ALLOWED:
            raise CP4Error('Unsupported CP4-R diagnostic request.')
        if not self.ready:
            raise CP4Error('Previous console response was incomplete. A new on-demand check is required.')
        self.channel.sendall((command + '\r').encode('ascii'))
        text, partial = self.read_fn(self.channel, prompt=self.prompt)
        self.ready = not partial
        return text, partial


def advertised(text, command):
    return bool(re.search(r'(?im)^\s*' + re.escape(command) + r'\b', text))


def rejected(text):
    return bool(re.search(r'(?i)(invalid command|unknown command|unrecognized command|bad(?: or incomplete)? command|invalid application id|command not found|access denied)', text))


def display_command(help_all, command):
    line = re.search(r'(?im)^\s*' + re.escape(command) + r'\b[^\n]*', help_all)
    return bool(line and re.search(r'(?i)\b(display|displays|show|shows|print|prints|list|lists|report|reports)\b', line.group())
        and not re.search(r'(?i)\b(set|change|configure|clear|reset|reboot|erase|restart|write|start|stop|enable|disable)\b', line.group()))


def versions(text):
    patterns = {'hardware_version': r'(?:Hardware Version:\s*|HW Ver )(\d+)',
        'control_engine_version': r'Cntrl Eng \[v([^\s,\]]+)',
        'home_setup_program_version': r'(?m)^PYNG-HUB-SetupProgram:\s*(\S+)'}
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        result[key] = match.group(1) if match else None
    return result


def collect(config, keys_path, client_factory=paramiko.SSHClient, read_fn=receive):
    if not Path(keys_path).exists():
        raise CP4Error('Inspect and approve the CP4-R SSH identity first.')
    client = client_factory()
    result = {'checked_at': None, 'ssh_authenticated': False, 'model_verified': False,
        'readings': [], 'not_attempted': [], 'limitations': [
            'SSH authentication is a fresh communication check, not proof of all Crestron Home functions.',
            'IP-table and main Cresnet results cover only those device lists; this is not the full Crestron Home Device Health dashboard.',
            'Resource reads require advertised display-command semantics and acceptable help syntax. TOP may return a bounded partial process sample; it is not a sustained CPU assessment.',
            'Missing, unsupported or partial results remain unverified. No automatic retries, restarts, resets or configuration writes.']}
    try:
        client.load_host_keys(str(keys_path))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(config['host'], port=config['port'], username=config['username'],
            password=config['password'], timeout=6, banner_timeout=6, auth_timeout=6,
            allow_agent=False, look_for_keys=False)
        result['ssh_authenticated'] = True
        console = Console(client, read_fn)
        def run(name, command):
            text, partial = console.query(command)
            item = {'name': name, 'command': command,
                'response': text.replace(config['password'], '[redacted]'),
                'truncated': partial, 'status': 'partial response' if partial else ('unsupported or denied' if rejected(text) else 'response received')}
            result['readings'].append(item)
            return text, partial
        version, partial = run('Processor version', 'VER -V')
        result['versions'] = versions(version)
        result['model_verified'] = bool(re.search(r'(?i)\bCP4[- ]?R\b', console.welcome + '\n' + version))
        if partial or not result['model_verified']:
            result['not_attempted'].append('Further checks stopped: incomplete version response or CP4-R model not identified.')
        else:
            commands, partial = run('Available console commands', 'HELP ALL')
            if partial:
                result['not_attempted'].append('Further checks stopped after incomplete console help.')
            else:
                for name, title in (
                        ('SYSTEMREADY', 'System-ready status'),
                        ('UPTIME', 'System uptime'),
                        ('PROGUPTIME', 'Home program uptime'),
                        ('RAMFREE', 'Available RAM'),
                        ('IPTABLE', 'IP-table connectivity'),
                        ('REPORTCRESNET', 'Main Cresnet devices'),
                        ('CPULOAD', 'CPU load'),
                        ('TOP', 'Process/CPU snapshot')):
                    if not console.ready:
                        result['not_attempted'].append(name + ': earlier response incomplete.')
                        continue
                    if not advertised(commands, name):
                        result['not_attempted'].append(name + ': not advertised by this processor.')
                        continue
                    if not display_command(commands, name):
                        result['not_attempted'].append(name + ': command purpose needs verification.')
                        continue
                    if name in ('IPTABLE', 'SYSTEMREADY', 'REPORTCRESNET'):
                        # These no-argument display queries are documented or
                        # explicitly described by this processor's HELP ALL.
                        text, partial = run(title, name)
                        if not partial and rejected(text):
                            run(name + ' syntax', name + ' ?')
                        continue
                    help_text, partial = run(name + ' syntax', name + ' ?')
                    controls = re.search(r'(?i)\b(clear|reset|reboot|erase|restart|write|start|stop|enable|disable)\b', help_text)
                    required = re.search(r'(?i)(arguments? required|parameters? required|mandatory|must specify)', help_text)
                    if not partial and not rejected(help_text) and not controls and not required:
                        run(title, name)
                    else:
                        result['not_attempted'].append(name + ': query syntax needs verification; help captured.')
        result['checked_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        return result
    except paramiko.BadHostKeyException:
        raise CP4Error('CP4-R SSH identity changed. Verify the processor before reconnecting.') from None
    except paramiko.AuthenticationException:
        raise CP4Error('CP4-R SSH login was rejected. Check its SSH/Toolbox account credentials. No automatic retry was made.') from None
    except CP4Error:
        raise
    except Exception:
        raise CP4Error('CP4-R diagnostic connection failed. Check its address, SSH access and saved identity. No automatic retry was made.') from None
    finally:
        client.close()


def report_payload(result):
    return {'format': 'adr-cp4-diagnostics-v1', 'agent_version': '0.17.0',
        'read_only': True, 'source': 'direct_processor_ssh', 'snapshot': result}
