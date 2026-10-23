"""Read-only Control4 snapshots via the already configured HA integration."""
from crestron import collect as collect_ha, get_json, scalar, read_state
from ruckus import registries


class Control4Error(Exception):
    pass


def entries(token):
    data = get_json(token, 'config/config_entries/entry')
    if not isinstance(data, list):
        raise Control4Error('Unexpected integration list response.')
    return [{'entry_id': item['entry_id'], 'title': scalar(item.get('title')) or item['entry_id'],
        'domain': 'control4', 'state': scalar(item.get('state')) or 'unknown',
        'disabled_by': scalar(item.get('disabled_by'))}
        for item in data if isinstance(item, dict) and item.get('domain') == 'control4'
        and isinstance(item.get('entry_id'), str)]


def collect(entry_id='', token=None, entries_fn=entries, registries_fn=registries, read_fn=read_state):
    try:
        result = collect_ha(entry_id, token=token, entries_fn=entries_fn,
            registries_fn=registries_fn, read_fn=read_fn)
        result['limitations'].append('CORE controller CPU, RAM, uptime, Zigbee health and full device-connectivity diagnostics are not established by this HA state snapshot.')
        return result
    except Exception:
        raise Control4Error('Could not inspect Control4 through Home Assistant. Check the existing integration and API availability.') from None


def report_payload(result):
    return {'format': 'adr-control4-discovery-v1', 'agent_version': '0.19.0',
        'read_only': True, 'source': 'existing_home_assistant_integration', 'snapshot': result}
