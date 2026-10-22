"""Bounded, on-demand Araknis SSH login and CLI-help inspection."""
import re
import time
from datetime import datetime, timezone

import paramiko
from wattbox import ProtocolError


class AraknisError(ProtocolError):
    pass


def settings(options):
    host = options.get('araknis_host', '').strip()
    port = options.get('araknis_ssh_port', 22)
    username = options.get('araknis_username', '')
    password = options.get('araknis_password', '')
    if not host or len(host) > 253 or any(c.isspace() for c in host) or any(c in host for c in '/\\@'):
        raise AraknisError('Set the Araknis host in app Configuration, save, and restart this app.')
    if type(port) is not int or not 1 <= port <= 65535:
        raise AraknisError('Invalid Araknis SSH port.')
    if not isinstance(username, str) or not username.strip() or len(username) > 256:
        raise AraknisError('Set the Araknis username in app Configuration.')
    if not isinstance(password, str) or not password or len(password) > 256:
        raise AraknisError('Set the Araknis password in app Configuration.')
    return {'host': host, 'port': port, 'username': username, 'password': password}


def terminal_text(raw):
    value = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
    value = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', value)
    return ''.join(c for c in value if c in '\n\t' or ord(c) >= 32).strip()


def response_boundary(value):
    return value.rstrip().endswith('--More--') or bool(re.search(
        r'(?:^|\n)[^\n]{0,80}[#>](?:[ \t]+show(?:[ \t]+[A-Za-z0-9-]+)*)?\s*$', value))


def receive(channel, duration=4):
    deadline = time.monotonic() + duration
    data = bytearray()
    truncated = False
    last_data = time.monotonic()
    while time.monotonic() < deadline:
        if channel.recv_ready():
            chunk = channel.recv(min(4096, 32769 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            last_data = time.monotonic()
            if len(data) > 32768:
                truncated = True
                break
        elif channel.closed:
            break
        else:
            tail = terminal_text(bytes(data[-2048:]))
            if data and time.monotonic() - last_data >= 0.25 and response_boundary(tail):
                break
            time.sleep(0.05)
    return terminal_text(bytes(data[:32768])), truncated


def show_help(channel, read_fn=receive):
    """Request context help only; advance at most seven explicit pager prompts."""
    channel.sendall(b'show ?')
    return read_pages(channel, read_fn)


def inspect(config, keys_path, client_factory=paramiko.SSHClient, read_fn=receive):
    if not keys_path.exists():
        raise AraknisError('Inspect and approve the Araknis SSH identity first.')
    client = client_factory()
    try:
        client.load_host_keys(str(keys_path))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(config['host'], port=config['port'], username=config['username'],
            password=config['password'], timeout=6, banner_timeout=6, auth_timeout=6,
            allow_agent=False, look_for_keys=False)
        channel = client.invoke_shell(width=160, height=100)
        channel.settimeout(1)
        welcome, first_truncated = read_fn(channel)
        # No newline executes a command. Read context help and bounded pages.
        help_text, help_truncated = show_help(channel, read_fn)
        # Do not display a password even if an unexpected server echoes it.
        def redact(value):
            return value.replace(config['password'], '[redacted]')
        return {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'welcome': redact(welcome), 'help': redact(help_text),
            'truncated': first_truncated or help_truncated}
    except paramiko.BadHostKeyException:
        raise AraknisError('Araknis SSH identity changed. Check the switch identity before reconnecting.') from None
    except paramiko.AuthenticationException:
        raise AraknisError('Araknis SSH login rejected. Check the switch username and password in app Configuration.') from None
    except AraknisError:
        raise
    except Exception:
        raise AraknisError('Araknis SSH connection failed. Check its address, SSH port, credentials and approved identity.') from None
    finally:
        client.close()


# Fixed read-only requests based on help returned by the pilot switch.
# No running configuration, credential, config mode, or control requests.
DIAGNOSTIC_COMMANDS = (
    ('System', 'show system information'),
    ('Environment', 'show env all'),
    ('Interfaces', 'show interfaces'),
    ('Power details', 'show power detail'),
    ('PoE power', 'show power inline'),
    ('PoE ports', 'show poe port'),
)


def read_pages(channel, read_fn=receive, max_pages=8, max_chars=32768):
    parts = []
    total = 0
    deadline = time.monotonic() + 90
    for number in range(max_pages):
        text, truncated = read_fn(channel)
        remaining = max_chars - total
        parts.append(text[:remaining])
        total += len(parts[-1])
        more = text.rstrip().endswith('--More--')
        if truncated or len(text) > remaining or total >= max_chars:
            return '\n'.join(parts), True
        if not more:
            return '\n'.join(parts), False
        if number == max_pages - 1 or time.monotonic() >= deadline:
            return '\n'.join(parts), True
        channel.sendall(b' ')
    return '\n'.join(parts), True


def query(client, command, read_fn=receive, help_only=False):
    if not permitted_request(command):
        raise AraknisError('Unsupported Araknis diagnostic request.')
    channel = client.invoke_shell(width=160, height=100)
    try:
        channel.settimeout(1)
        welcome, truncated = read_fn(channel)
        if truncated or not re.search(r'(?:^|\n)[^\n]{0,80}[#>]\s*$', welcome):
            raise AraknisError('Switch command prompt was not recognized; no diagnostic command sent.')
        request = command + (' ?' if help_only else '\r')
        channel.sendall(request.encode('ascii'))
        if command == 'show interfaces' and not help_only:
            text, truncated = read_pages(channel, read_fn, max_pages=96, max_chars=262144)
        else:
            text, truncated = read_pages(channel, read_fn)
        return text, truncated
    finally:
        channel.close()


def diagnostic_request(config, keys_path, command, client_factory, read_fn, help_only=False):
    """One authenticated SSH connection per request, including help requests."""
    client = client_factory()
    try:
        client.load_host_keys(str(keys_path))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(config['host'], port=config['port'], username=config['username'],
            password=config['password'], timeout=6, banner_timeout=6, auth_timeout=6,
            allow_agent=False, look_for_keys=False)
        return query(client, command, read_fn, help_only=help_only)
    finally:
        client.close()


def parse_interfaces(text):
    """Extract only explicitly reported fields from complete or partial port blocks."""
    text = text.replace('--More--', '')
    headers = list(re.finditer(r'(?m)^\s*(\S+)\s+(administratively down|up|down),\s*line protocol is\s+(up|down)\b', text))
    ports = []
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[match.end():end]
        speed = re.search(r',\s*(Full|Half)\s+duplex,\s*([0-9.]+\s*[MGT]bps)\b', block, re.I)
        rx = re.search(r'Reception Counters(.*?)(?:Transmission Counters|\Z)', block, re.S | re.I)
        tx = re.search(r'Transmission Counters(.*)', block, re.S | re.I)
        def counter(section, label):
            value = re.search(r'(?m)^\s*' + re.escape(label) + r'\s*:\s*([0-9]+)\s*$', section.group(1)) if section else None
            return int(value.group(1)) if value else None
        ports.append({'port': match.group(1), 'link': match.group(2),
            'protocol': match.group(3), 'speed': speed.group(2) if speed else None,
            'duplex': speed.group(1).lower() if speed else None,
            'rx_errors': counter(rx, 'Error Packets'), 'rx_discards': counter(rx, 'Discarded Packets'),
            'rx_crc_errors': counter(rx, 'CRC Errors'),
            'tx_errors': counter(tx, 'Error Packets'), 'tx_discards': counter(tx, 'Discarded Packets')})
    return ports


def snapshot(config, keys_path, client_factory=paramiko.SSHClient, read_fn=receive):
    if not keys_path.exists():
        raise AraknisError('Inspect and approve the Araknis SSH identity first.')
    results = []
    try:
        for name, command in DIAGNOSTIC_COMMANDS:
            item = {'name': name, 'command': command, 'response': '', 'help': '',
                'truncated': False, 'status': 'response received', 'error': ''}
            try:
                text, truncated = diagnostic_request(config, keys_path, command, client_factory, read_fn)
                item['response'] = text.replace(config['password'], '[redacted]')
                item['truncated'] = truncated
                if command == 'show interfaces':
                    item['ports'] = parse_interfaces(item['response'])
                if not text or re.search(r'(?i)(incomplete command|invalid (input|command)|ambiguous command|unrecognized command|unknown command|syntax error|%\s*error)', text):
                    item['status'] = 'command needs verification'
                    try:
                        help_text, help_truncated = diagnostic_request(config, keys_path,
                            command, client_factory, read_fn, help_only=True)
                        item['help'] = help_text.replace(config['password'], '[redacted]')
                        item['truncated'] |= help_truncated
                    except (paramiko.BadHostKeyException, paramiko.AuthenticationException):
                        raise
                    except Exception:
                        item['error'] = 'Syntax-help read failed. The command response above is preserved.'
            except (paramiko.BadHostKeyException, paramiko.AuthenticationException):
                raise
            except Exception:
                item['status'] = 'read failed'
                item['error'] = 'Could not complete this independent SSH request. No automatic retry was made.'
            results.append(item)
        return {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'readings': results}
    except paramiko.BadHostKeyException:
        raise AraknisError('Araknis SSH identity changed. Check the switch identity before reconnecting.') from None
    except paramiko.AuthenticationException:
        raise AraknisError('Araknis SSH login rejected. Check the switch username and password in app Configuration.') from None


# Discovery can only traverse these five show-command families and vocabulary.
# No user-entered command strings or device-supplied arbitrary tokens are run.
DISCOVERY_WORDS = {
    'system': {'information'},
    'env': {'all', 'CPU', 'RAM', 'fan', 'flash', 'power', 'temperature'},
    'interfaces': {'status', 'summary', 'brief', 'counters', 'statistics', 'errors', 'discards'},
    'power': {'detail', 'inline', 'all', 'status', 'summary'},
    'poe': {'port', 'all', 'status', 'summary', 'detail'},
}


def permitted_request(command):
    if command in {command for _, command in DIAGNOSTIC_COMMANDS}:
        return True
    parts = command.split(' ')
    if not 2 <= len(parts) <= 4 or parts[0] != 'show' or parts[1] not in DISCOVERY_WORDS:
        return False
    return all(word in DISCOVERY_WORDS[parts[1]] for word in parts[2:])


def help_options(text, family):
    advertised = re.findall(r'(?m)^\s*([A-Za-z][A-Za-z0-9-]*)[ \t]{2,}\S', text)
    return sorted(set(advertised) & DISCOVERY_WORDS[family])


def discover(config, keys_path, client_factory=paramiko.SSHClient, read_fn=receive,
             progress=None, max_probes=24, max_reads=12, deadline_seconds=180):
    """Bounded help traversal; execute only allowlisted paths advertising <cr>."""
    if not keys_path.exists():
        raise AraknisError('Inspect and approve the Araknis SSH identity first.')
    queue = ['show ' + family for family in ('system', 'env', 'power', 'poe', 'interfaces')]
    deferred = []
    seen = set()
    probes, readings = [], []
    deadline = time.monotonic() + deadline_seconds
    limited = False
    def report(message):
        if progress:
            progress(message)
    priorities = {'show system information': 10, 'show env all': 11,
        'show power detail': 12, 'show power inline': 13, 'show poe port': 14,
        'show interfaces status': 15, 'show env power': 16, 'show env temperature': 17}
    def priority(command):
        return 0 if len(command.split()) == 2 else priorities.get(command, 30)
    try:
        while queue or deferred:
            if len(probes) >= max_probes or time.monotonic() >= deadline:
                limited = True
                break
            # Verbose interface details cannot consume the budget before
            # system, environment, power, and concise port-status discovery.
            if not queue:
                if len(readings) >= max_reads or time.monotonic() >= deadline:
                    limited = True
                    break
                command = deferred.pop(0)
                report('Reading ' + command)
                item = {'name': command[5:], 'command': command,
                    'status': 'response received', 'response': '', 'help': '',
                    'truncated': False, 'error': ''}
                try:
                    response, partial = diagnostic_request(config, keys_path, command,
                        client_factory, read_fn)
                    item['response'] = response.replace(config['password'], '[redacted]')
                    item['truncated'] = partial
                    if command == 'show interfaces':
                        item['ports'] = parse_interfaces(item['response'])
                    if not response or re.search(r'(?i)(incomplete command|invalid (input|command)|ambiguous command|unrecognized command|unknown command|syntax error|%\s*error)', response):
                        item['status'] = 'command needs verification'
                except (paramiko.BadHostKeyException, paramiko.AuthenticationException):
                    raise
                except Exception:
                    item['status'] = 'read failed'
                    item['error'] = 'Independent SSH read failed; no automatic retry.'
                readings.append(item)
                continue
            queue.sort(key=priority)
            command = queue.pop(0)
            if command in seen or not permitted_request(command):
                continue
            seen.add(command)
            report('Inspecting ' + command + ' syntax')
            probe = {'command': command + ' ?', 'response': '', 'truncated': False, 'error': ''}
            try:
                text, truncated = diagnostic_request(config, keys_path, command,
                    client_factory, read_fn, help_only=True)
                probe['response'] = text.replace(config['password'], '[redacted]')
                probe['truncated'] = truncated
                # Only tokens actually advertised by the CLI and also in the
                # local vocabulary enter the queue. Never infer numeric args.
                if len(command.split()) < 4:
                    for option in help_options(text, command.split()[1]):
                        child = command + ' ' + option
                        if child not in seen and child not in queue and permitted_request(child):
                            queue.append(child)
                if re.search(r'(?im)^\s*<cr>(?:\s|$)', text) and not truncated:
                    if command in ('show interfaces', 'show interfaces counters', 'show interfaces statistics'):
                        deferred.append(command)
                        probes.append(probe)
                        continue
                    # env all already contains CPU/RAM/fan/thermal readings.
                    if command.startswith('show env ') and command != 'show env all' and any(
                            item['command'] == 'show env all' and item['status'] == 'response received'
                            for item in readings) and command not in ('show env power', 'show env temperature'):
                        probe['note'] = 'Individual read omitted because env all was captured.'
                        probes.append(probe)
                        continue
                    if len(readings) >= max_reads or time.monotonic() >= deadline:
                        limited = True
                    else:
                        report('Reading ' + command)
                        item = {'name': command[5:], 'command': command,
                            'status': 'response received', 'response': '', 'help': '',
                            'truncated': False, 'error': ''}
                        try:
                            response, partial = diagnostic_request(config, keys_path, command,
                                client_factory, read_fn)
                            item['response'] = response.replace(config['password'], '[redacted]')
                            item['truncated'] = partial
                            if command == 'show interfaces':
                                item['ports'] = parse_interfaces(item['response'])
                            if not response or re.search(r'(?i)(incomplete command|invalid (input|command)|ambiguous command|unrecognized command|unknown command|syntax error|%\s*error)', response):
                                item['status'] = 'command needs verification'
                        except (paramiko.BadHostKeyException, paramiko.AuthenticationException):
                            raise
                        except Exception:
                            item['status'] = 'read failed'
                            item['error'] = 'Independent SSH read failed; no automatic retry.'
                        readings.append(item)
            except (paramiko.BadHostKeyException, paramiko.AuthenticationException):
                raise
            except Exception:
                probe['error'] = 'Syntax-help request failed; no automatic retry.'
            probes.append(probe)
        return {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'report_type': 'read_only_discovery', 'readings': readings,
            'discovery': {'probes': probes, 'limit_reached': limited,
                'remaining_paths': len(queue) + len(deferred), 'max_probes': max_probes, 'max_reads': max_reads,
                'note': 'Unvisited paths and commands needing numeric arguments remain unverified. Resource thresholds are not current utilization. Counters are cumulative.'}}
    except paramiko.BadHostKeyException:
        raise AraknisError('Araknis SSH identity changed. Check the switch identity before reconnecting.') from None
    except paramiko.AuthenticationException:
        raise AraknisError('Araknis SSH login rejected. Check the switch username and password in app Configuration.') from None


def report_payload(result, password):
    def clean(value):
        if isinstance(value, str):
            return value.replace(password, '[redacted]') if password else value
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value
    return {'format': 'adr-araknis-discovery-v1', 'agent_version': '0.17.2',
        'read_only': True, 'snapshot': clean(result),
        'limitations': ['Command syntax and raw values are reported, not a health verdict.',
            'No running configuration, app options, credentials or SSH keys are included.',
            'Switch responses can include network addresses, device names and identifiers.']}
