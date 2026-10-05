"""Allowlisted power/timing report; never print headers, identifiers or raw bodies."""
import base64
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from har_inventory import normalize_path, list_value

FIELDS = ('pvPower', 'minPower', 'battPower', 'loadOrEpsPower',
          'gridOrMeterPower', 'toBat', 'batTo', 'toGrid', 'gridTo', 'updateAt', 'pac')

def main():
    entries = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))['log']['entries']
    times = [datetime.fromisoformat(e['startedDateTime'].replace('Z', '+00:00')) for e in entries]
    print('capture_seconds', (max(times)-min(times)).total_seconds())
    devices = {}
    for e in entries:
        path = urlsplit(e['request']['url']).path
        route = normalize_path(path)
        content = e['response'].get('content', {})
        body = content.get('text', '')
        if content.get('encoding') == 'base64':
            body = base64.b64decode(body).decode('utf-8', errors='replace')
        if not path.startswith('/api/'):
            if path.endswith('.js'):
                # Fixed patterns only, without emitting potentially embedded data.
                intervals = Counter(re.findall(r'setInterval\([^;]{0,100}?,(\d{4,7})\)', body))
                if intervals: print('js_interval_constants_ms', dict(intervals))
                print('js_chart_smooth_constants', dict(Counter(re.findall(r'smooth:(true|false|!0|!1)', body))))
            continue
        try: data = json.loads(body).get('data')
        except (ValueError, AttributeError): continue
        if '/inverter/' in path and re.search(r'/\d+', path):
            identifier = re.search(r'/\d+', path)[0]
            devices.setdefault(identifier, f'inverter_{len(devices)+1}')
            label = devices[identifier]
        else: label = 'plant'
        if route.endswith('/flow') or route.endswith('/realtime'):
            if isinstance(data, dict):
                print(e['startedDateTime'], route, label, 'latency_ms', e['time'],
                      {k: data[k] for k in FIELDS if k in data})
                print('cache_header_names', sorted(h.get('name', '').lower() for h in e['response'].get('headers', [])
                                                   if h.get('name', '').lower() in ('age', 'cache-control', 'expires', 'etag', 'last-modified')))
                policy = next((h.get('value', '').lower() for h in e['response'].get('headers', [])
                               if h.get('name', '').lower() == 'cache-control'), '')
                print('cache_policy', {key: key in policy for key in ('no-cache', 'no-store', 'must-revalidate')},
                      'max_age_seconds', re.findall(r'max-age=(\d+)', policy))
        if route.endswith('/inverters'):
            rows = list_value(data.get('infos', data) if isinstance(data, dict) else data)
            print('inverter_list_count', len(rows), 'status_counts', dict(Counter(r.get('status') for r in rows)))
        if route.endswith('/day') and isinstance(data, dict):
            print('history', route, label, 'keys', sorted(data))
            for s in list_value(data.get('infos')):
                records = list_value(s.get('records'))
                numeric = []
                for r in records:
                    try: numeric.append(float(r.get('value')))
                    except (TypeError, ValueError): pass
                ts = [r.get('time') for r in records]
                print('series', s.get('id'), 'unit', s.get('unit'), 'count', len(records),
                      'record_keys', sorted(records[0]) if records else [],
                      'time_first_last', ts[:2], ts[-2:],
                      'value_range', [min(numeric), max(numeric)] if numeric else [])

if __name__ == '__main__': main()
