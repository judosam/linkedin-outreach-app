"""Persistent schedules. All dates in storage are UTC; recurrence uses India Standard Time."""
import json
import random
import re
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .database import SessionLocal
from .models import Schedule, Setting, Campaign, Account, RunLog

SCHEDULE_TIMEZONE = 'Asia/Kolkata'

DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
WORKERS = ['send_connections', 'check_replies', 'send_followups']
_guard = threading.RLock()
_engine = None


def validate(data):
    if not isinstance(data.get('name'), str) or not data['name'].strip() or len(data['name']) > 120:
        raise ValueError('Enter a schedule name of up to 120 characters')
    for value in [data.get('run_time'), data.get('window_end')]:
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value)):
            raise ValueError('Time must use HH:MM')
    if not data.get('run_time'):
        raise ValueError('Choose a time')
    if data.get('window_end') and data['window_end'] <= data['run_time']:
        raise ValueError('Window end must be after start')
    for field, allowed in [('days_of_week', DAYS), ('job_keys', WORKERS)]:
        values = data.get(field, [])
        if not isinstance(values, list) or any(v not in allowed for v in values) or len(set(values)) != len(values):
            raise ValueError(f'Invalid {field}')
    if not data.get('job_keys'):
        raise ValueError('Select at least one worker; search and list imports are manual only')
    if data.get('timezone', SCHEDULE_TIMEZONE) != SCHEDULE_TIMEZONE:
        raise ValueError('Schedules use India Standard Time (Asia/Kolkata) only')
    if type(data.get('active', True)) is not bool:
        raise ValueError('Active must be true or false')
    jitter = data.get('jitter_minutes', 0)
    if type(jitter) is not int or not 0 <= jitter <= 60:
        raise ValueError('Jitter must be from 0 to 60 minutes')
    scopes = data.get('scopes', {})
    if not isinstance(scopes, dict) or any(k not in data['job_keys'] for k in scopes):
        raise ValueError('Scope must belong to a selected worker')
    with SessionLocal() as db:
        for scope in scopes.values():
            validate_scope(scope, db)


def validate_scope(scope, db):
    if not isinstance(scope, dict) or set(scope) - {'campaign_ids', 'account_ids'}:
        raise ValueError('Invalid run scope')
    for key, model in [('campaign_ids', Campaign), ('account_ids', Account)]:
        ids = scope.get(key)
        if ids is None:
            continue
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids):
            raise ValueError(f'Select at least one {key.replace("_ids", "")} or choose all')
        if db.query(model).filter(model.id.in_(ids)).count() != len(ids):
            raise ValueError(f'A selected {key.replace("_ids", "")} no longer exists')
    campaign_ids = scope.get('campaign_ids')
    account_ids = scope.get('account_ids')
    if campaign_ids and account_ids:
        from .models import CampaignAccount
        mapped_acc_ids = {
            row[0] for row in db.query(CampaignAccount.account_id)
            .filter(CampaignAccount.campaign_id.in_(campaign_ids))
            .all()
        }
        unmapped = set(account_ids) - mapped_acc_ids
        if unmapped:
            raise ValueError(f'Account(s) {sorted(unmapped)} not mapped to the selected campaign(s)')


def next_time(row, after=None):
    """Compute the next UTC fire instant for *row* after the given UTC moment.

    Skips DST-gap wall times (clocks spring forward) so we never schedule
    a nonexistent local instant.  Ambiguous repeated times (fall-back) are
    accepted as-is; the first occurrence is preferred because Python's
    zoneinfo uses fold=0 by default.
    """
    after = after or datetime.utcnow()
    utc = after.replace(tzinfo=timezone.utc)
    zone = ZoneInfo(row.timezone)
    local = utc.astimezone(zone)
    hour, minute = map(int, row.run_time.split(':'))
    days = row.days_of_week or DAYS
    for offset in range(9):
        day = local.date() + timedelta(days=offset)
        if DAYS[day.weekday()] not in days:
            continue
        # Build the target local wall time.
        start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        # DST gap detection: if converting to UTC and back doesn't round-trip
        # to the same wall time, this instant doesn't exist — skip it.
        try:
            roundtripped = start.astimezone(timezone.utc).astimezone(zone)
        except Exception:
            continue
        if roundtripped.replace(tzinfo=None) != start.replace(tzinfo=None):
            continue
        # Must be strictly in the future.
        if start <= utc:
            continue
        # Jitter / window: compute the latest permissible delay in seconds.
        if row.window_end:
            eh, em = map(int, row.window_end.split(':'))
            max_delay = (eh * 60 + em - hour * 60 - minute) * 60
        else:
            max_delay = row.jitter_minutes * 60
        delay = random.randint(0, max(0, max_delay))
        return (start + timedelta(seconds=delay)).astimezone(timezone.utc).replace(tzinfo=None)
    raise ValueError('Cannot compute next run')


def serialize(row):
    result = {key: getattr(row, key) for key in ['id', 'name', 'run_time', 'days_of_week', 'job_keys', 'scopes', 'timezone', 'active', 'jitter_minutes', 'window_end']}
    for key in ['created_at', 'last_run_at', 'next_run_at']:
        value = getattr(row, key)
        result[key] = value.isoformat() + 'Z' if value else None
    return result


def migrate():
    normalized = False
    with _guard, SessionLocal() as db:
        if not db.get(Setting, 'schedule_rows_migrated'):
            old = db.get(Setting, 'named_jobs_schedule')
            entries = json.loads(old.value_json) if old else []
            if old is None:
                fixed = db.get(Setting, 'jobs_schedule')
                campaigns = [c.id for c in db.query(Campaign).filter_by(status='active')]
                for key, slots in (json.loads(fixed.value_json) if fixed else {}).items():
                    for index, slot in enumerate(slots):
                        if slot:
                            start, _, end = slot.partition('-')
                            entries.append(dict(name=f'{key} {index + 1}', job=key, time=start, days=DAYS, timezone=SCHEDULE_TIMEZONE, campaign_ids=campaigns, enabled=bool(campaigns), window_end=end or None, jitter_minutes=0 if end else 15))
            for entry in entries:
                key = entry.get('job')
                if key not in WORKERS:
                    continue
                row = Schedule(name=entry['name'], run_time=entry['time'], days_of_week=entry.get('days', []),
                               job_keys=[key], scopes={key: {'campaign_ids': entry.get('campaign_ids') or None}},
                               timezone=SCHEDULE_TIMEZONE, active=entry.get('enabled', False),
                               jitter_minutes=entry.get('jitter_minutes', 0), window_end=entry.get('window_end'))
                row.next_run_at = next_time(row) if row.active else None
                db.add(row)
            db.add(Setting(key='schedule_rows_migrated', value_json='true'))
        # Preserve selected wall-clock times/days while fixing existing rows to IST.
        # Recompute future triggers once; historical run timestamps remain UTC.
        for row in db.query(Schedule).filter(Schedule.timezone != SCHEDULE_TIMEZONE):
            row.timezone = SCHEDULE_TIMEZONE
            row.next_run_at = next_time(row) if row.active else None
            normalized = True
        db.commit()
    if normalized:
        refresh()


def listing():
    migrate()
    with SessionLocal() as db:
        return [serialize(row) for row in db.query(Schedule).order_by(Schedule.id)]


def save(data, schedule_id=None):
    with _guard, SessionLocal() as db:
        row = db.get(Schedule, schedule_id) if schedule_id is not None else Schedule()
        if row is None:
            raise LookupError('Schedule not found')
        defaults = dict(name='', run_time='', days_of_week=[], job_keys=[], scopes={}, timezone=SCHEDULE_TIMEZONE, active=True, jitter_minutes=0, window_end=None)
        editable = set(defaults)
        if set(data) - editable:
            raise ValueError('Unknown schedule field')
        if 'timezone' in data and data['timezone'] != SCHEDULE_TIMEZONE:
            raise ValueError('Schedules use India Standard Time (Asia/Kolkata) only')
        merged = {**(serialize(row) if schedule_id is not None else defaults), **data, 'timezone': SCHEDULE_TIMEZONE}
        validate(merged)
        recurrence_changed = schedule_id is None or any(merged[key] != getattr(row, key) for key in ['run_time', 'days_of_week', 'timezone', 'active', 'jitter_minutes', 'window_end'])
        for key in editable:
            setattr(row, key, merged[key])
        row.name = row.name.strip()
        if recurrence_changed:
            row.next_run_at = next_time(row) if row.active else None
        db.add(row)
        db.commit()
        result = serialize(row)
        refresh()
        return result


def delete(schedule_id):
    with _guard, SessionLocal() as db:
        row = db.get(Schedule, schedule_id)
        if not row:
            raise LookupError('Schedule not found')
        db.delete(row)
        db.commit()
        refresh()


def fire(schedule_id, expected):
    """Claim and execute a scheduled batch.

    *last_run_at* is set only after the runner lock is obtained (execution
    admitted).  An overlap-skip leaves *last_run_at* unchanged so the UI
    correctly shows when the schedule last ran something.

    Crash window: if the server dies between launching the worker thread and
    committing *next_run_at*, the schedule will fire again at the same instant
    on restart — the runner lock prevents a true duplicate, but an extra
    'skipped' record will appear.  This is intentional: correctness over
    invisibility.

    This implementation assumes a single server process.  A distributed lock
    (e.g. SELECT … FOR UPDATE) would be required for multi-process safety.
    """
    from . import runner
    with _guard, SessionLocal() as db:
        row = db.get(Schedule, schedule_id)
        if not row or not row.active or row.next_run_at != expected:
            return
        now = datetime.utcnow()
        active_account_ids = {a.id for a in db.query(Account).filter_by(status='active')}
        steps = []
        for key in row.job_keys:
            scope = dict(row.scopes.get(key, {}))
            if 'account_ids' in scope and scope['account_ids'] is not None:
                scope['account_ids'] = [aid for aid in scope['account_ids'] if aid in active_account_ids]
            steps.append((key, scope))
        ok, message, _ = runner.start_sequence(steps, row.id, row.name)
        if ok:
            # Execution was admitted — record that this schedule ran.
            row.last_run_at = now
        else:
            # Overlap-skip or lock contention — do NOT update last_run_at.
            for key in row.job_keys:
                db.add(RunLog(
                    job_type=key, schedule_id=row.id, target=row.name,
                    status='skipped', started_at=now, finished_at=now,
                    duration_s=0, errors=[message], log_text=message,
                ))
        row.next_run_at = next_time(row, max(now, expected))
        db.commit()
        refresh()


def refresh():
    if _engine is None:
        return
    with _guard, SessionLocal() as db:
        wanted = set()
        for row in db.query(Schedule).filter_by(active=True):
            if row.next_run_at is None or row.next_run_at < datetime.utcnow() - timedelta(minutes=15):
                row.next_run_at = next_time(row)
            jid = f'schedule-row-{row.id}'
            wanted.add(jid)
            job = _engine.get_job(jid)
            if job and job.args == (row.id, row.next_run_at):
                continue
            _engine.add_job(fire, 'date', run_date=row.next_run_at.replace(tzinfo=timezone.utc), args=(row.id, row.next_run_at), id=jid, replace_existing=True, misfire_grace_time=900)
        db.commit()
        for job in _engine.get_jobs():
            if job.id.startswith('schedule-row-') and job.id not in wanted:
                _engine.remove_job(job.id)


def initialize(engine):
    global _engine
    migrate()
    _engine = engine
    refresh()
    engine.add_job(refresh, 'interval', seconds=20, id='schedule-row-refresh', replace_existing=True)


def run_now(schedule_id):
    """Manually execute a schedule immediately on demand."""
    from . import runner
    with _guard, SessionLocal() as db:
        row = db.get(Schedule, schedule_id)
        if not row:
            raise LookupError('Schedule not found')
        now = datetime.utcnow()
        active_account_ids = {a.id for a in db.query(Account).filter_by(status='active')}
        steps = []
        for key in row.job_keys:
            scope = dict(row.scopes.get(key, {}))
            if 'account_ids' in scope and scope['account_ids'] is not None:
                scope['account_ids'] = [aid for aid in scope['account_ids'] if aid in active_account_ids]
            steps.append((key, scope))
        ok, message, _ = runner.start_sequence(steps, row.id, f"{row.name}")
        if ok:
            row.last_run_at = now
            db.commit()
            refresh()
            return True, f"Started {row.name}"
        return False, message


def tick(wait_completion=True, max_wait=850):
    """Trigger any active schedules that are due or overdue.
    If wait_completion is True, holds the request open until the triggered job completes
    so Cloud Run allocates CPU throughout execution in serverless mode.
    """
    import time
    now = datetime.utcnow()
    executed = []
    tokens = []
    with _guard, SessionLocal() as db:
        for row in db.query(Schedule).filter_by(active=True):
            if row.next_run_at and row.next_run_at <= now:
                if row.next_run_at >= now - timedelta(hours=2):
                    executed.append(row.name)
                    from . import runner
                    active_account_ids = {a.id for a in db.query(Account).filter_by(status='active')}
                    steps = []
                    for key in row.job_keys:
                        scope = dict(row.scopes.get(key, {}))
                        if 'account_ids' in scope and scope['account_ids'] is not None:
                            scope['account_ids'] = [aid for aid in scope['account_ids'] if aid in active_account_ids]
                        steps.append((key, scope))
                    ok, message, token = runner.start_sequence(steps, row.id, row.name)
                    if ok:
                        row.last_run_at = now
                        if token:
                            tokens.append(token)
                    else:
                        for key in row.job_keys:
                            db.add(RunLog(
                                job_type=key, schedule_id=row.id, target=row.name,
                                status='skipped', started_at=now, finished_at=now,
                                duration_s=0, errors=[message], log_text=message,
                            ))
                    row.next_run_at = next_time(row, max(now, row.next_run_at))
                else:
                    row.next_run_at = next_time(row)
        db.commit()

    if wait_completion and tokens:
        from . import runner
        start_wait = time.time()
        for tok in tokens:
            while time.time() - start_wait < max_wait:
                with runner._state_lock:
                    if tok not in runner._executions:
                        break
                time.sleep(2)

    refresh()
    return executed


