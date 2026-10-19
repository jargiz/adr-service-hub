"""Bounded SSH implementation of Snap One WattBox ASCII protocol v2.4.

Never uses a shell command, Telnet, or automatic command retries.
"""
import base64
import hashlib
import re
import socket
import time
from pathlib import Path

import paramiko


class ProtocolError(Exception):
    pass


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def host_id(host, port):
    return host if port == 22 else f"[{host}]:{port}"


def inspect_key(host, port):
    """Fetch server key before authentication, for explicit first-use approval."""
    sock = socket.create_connection((host, port), timeout=6)
    transport = paramiko.Transport(sock)
    try:
        transport.start_client(timeout=6)
        return transport.get_remote_server_key()
    finally:
        transport.close()
        sock.close()


def pin_key(path, host, port, key):
    keys = paramiko.HostKeys()
    if Path(path).exists():
        keys.load(str(path))
    identity = host_id(host, port)
    # A changed key is never silently replaced.
    if identity in keys and not keys.check(identity, key):
        raise ProtocolError("SSH identity changed. Investigate before replacing the saved key.")
    keys.add(identity, key.get_name(), key)
    keys.save(str(path))
    Path(path).chmod(0o600)


def parse_inventory(model, firmware, count, labels, states):
    try:
        count = int(count)
    except ValueError as exc:
        raise ProtocolError("Invalid outlet count") from exc
    if not 1 <= count <= 64:
        raise ProtocolError("Unexpected outlet count")
    names = re.findall(r"\{([^{}]*)\}", labels)
    remainder = re.sub(r"\{[^{}]*\}", "", labels).replace(",", "").strip()
    values = states.split(",")
    if remainder or len(names) != count or len(values) != count or any(v not in ("0", "1") for v in values):
        raise ProtocolError("Incomplete or ambiguous outlet response; no power action permitted")
    return {"model": model, "firmware": firmware, "outlets": [
        {"number": i + 1, "label": name, "on": values[i] == "1"}
        for i, name in enumerate(names)
    ]}


class WattBox:
    def __init__(self, config, keys_path):
        self.config = config
        self.keys_path = keys_path
        self.client = None
        self.channel = None
        self.buffer = b""

    def __enter__(self):
        self.client = paramiko.SSHClient()
        try:
            self.client.load_host_keys(str(self.keys_path))
            self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
            self.client.connect(
                self.config["wattbox_host"], port=self.config["ssh_port"],
                username=self.config["username"], password=self.config["password"],
                timeout=6, banner_timeout=6, auth_timeout=6,
                allow_agent=False, look_for_keys=False,
            )
            # WattBox supplies an interactive command channel rather than exec.
            self.channel = self.client.invoke_shell()
            self.channel.settimeout(1)
            return self
        except Exception:
            self.client.close()
            raise

    def __exit__(self, *_):
        if self.client:
            self.client.close()

    def _line(self, deadline):
        while b"\n" not in self.buffer:
            if time.monotonic() >= deadline:
                raise ProtocolError("Timed out waiting for WattBox response")
            try:
                chunk = self.channel.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise ProtocolError("WattBox connection closed")
            self.buffer += chunk
            if len(self.buffer) > 65536:
                raise ProtocolError("Unexpectedly large WattBox response")
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode("ascii", errors="replace").strip()

    def query(self, name):
        if name not in ("Model", "Firmware", "OutletCount", "OutletName", "OutletStatus"):
            raise ValueError("Unsupported query")
        self.channel.sendall(f"?{name}\n".encode("ascii"))
        deadline = time.monotonic() + 8
        while True:
            line = self._line(deadline)
            if line.startswith("#"):
                raise ProtocolError("WattBox rejected the status query")
            # Accept documented response marker only; unsolicited updates cannot
            # satisfy a fresh query and command echoes contain no equals sign.
            prefix = f"?{name}="
            if line.startswith(prefix):
                return line[len(prefix):]

    def inventory(self):
        return parse_inventory(*(self.query(n) for n in
            ("Model", "Firmware", "OutletCount", "OutletName", "OutletStatus")))

    def reset(self, outlet):
        if type(outlet) is not int or not 1 <= outlet <= 18:
            raise ValueError("Only one explicit outlet from 1 to 18 is permitted")
        # Drain complete buffered lines so an unrelated old OK cannot acknowledge
        # the reset. All inventory queries have completed before this call.
        self.buffer = b""
        while self.channel.recv_ready():
            self.channel.recv(4096)
        self.channel.sendall(f"!OutletSet={outlet},RESET\n".encode("ascii"))
        deadline = time.monotonic() + 8
        while True:
            line = self._line(deadline)
            if line.startswith("#"):
                raise ProtocolError("WattBox rejected the reboot; no automatic retry")
            if line == "OK":
                return
