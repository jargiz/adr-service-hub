"""Private, bounded network measurement history separated by gateway identity."""
import math
from datetime import datetime, timezone


def append(store, target, readings, now=None):
    now=now or datetime.now(timezone.utc)
    series=store.setdefault(target,{})
    for reading in readings:
        if reading.get('unit') not in ('ms','Mbit/s','Mbps'):continue
        name=str(reading.get('name',''))[:120]
        try:
            n=float(reading['state']); stamp=datetime.fromisoformat(reading['last_updated'].replace('Z','+00:00'))
        except (ValueError,TypeError,KeyError,AttributeError):continue
        if not math.isfinite(n) or n<0 or n==1800000 or stamp.tzinfo is None or (stamp-now).total_seconds()>60:continue
        retention=7*86400 if reading['unit']!='ms' or 'speed test' in name.lower() else 86400
        if (now-stamp).total_seconds()>retention:continue
        item=series.setdefault(name,{'name':name,'unit':reading['unit'],'points':[], 'max_gap_seconds':43200 if 'speed test' in name.lower() else 3600})
        points={p['time']:p for p in item['points'] if (now-datetime.fromisoformat(p['time'])).total_seconds()<=retention}
        points[stamp.isoformat()]={'time':stamp.isoformat(),'value':n}
        item['points']=[points[k] for k in sorted(points)][-512:]
    # Retain only the active gateway; never merge installations.
    for previous in list(store):
        if previous!=target:del store[previous]
    return list(series.values())
