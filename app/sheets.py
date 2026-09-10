"""Cached reads of the master Google Sheet for the API layer.

Uses pipeline_common's single gspread client (same service account as the
pipeline) with a short TTL cache so dashboard polling doesn't burn Sheets quota.
"""
import time
import threading

import pipeline_common as pcom

_cache = {}          # name -> {'ts': epoch, 'values': [...]}
_lock = threading.Lock()
TTL_SECONDS = 60


def _fetch_values(name):
    ws = pcom.get_worksheet(name)
    return ws.get_all_values()


def get_values(name, ttl=TTL_SECONDS):
    """Return all values of a worksheet, cached for `ttl` seconds."""
    with _lock:
        hit = _cache.get(name)
        now = time.time()
        if hit and (now - hit['ts']) < ttl:
            return hit['values']
    values = _fetch_values(name)  # network call outside the lock
    with _lock:
        _cache[name] = {'ts': time.time(), 'values': values}
    return values


def invalidate(name=None):
    with _lock:
        if name:
            _cache.pop(name, None)
        else:
            _cache.clear()


def _records_from(values, row_key='sheet_row'):
    """Convert raw values into dict records with original sheet row numbers."""
    if not values:
        return [], []
    headers = values[0]
    records = []
    for i, row in enumerate(values[1:]):
        rec = {h: (row[j] if j < len(row) else '') for j, h in enumerate(headers)}
        rec[row_key] = i + 2  # 1-indexed, +1 for header
        records.append(rec)
    return headers, records


def search_data_records(ttl=TTL_SECONDS):
    headers, records = _records_from(get_values('Search Data', ttl))
    return headers, records


def followup_records(ttl=TTL_SECONDS):
    headers, records = _records_from(get_values('Followup msg', ttl))
    return headers, records
