"""Account-isolated background execution (one application process).

Admission and destructive edits share a short coordinator lock. Each execution
reserves its accounts for the entire sequence and owns its stop event/output.
Connection jobs also reserve their campaign lead pools to prevent double sends.
Deploy with one application worker; reservations are process-local.
"""
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime

from .database import SessionLocal
from .models import Account, Campaign, CampaignAccount, RunLog, RunStatus
from . import jobs as jobmod

_run_lock = threading.Lock()  # admission / destructive-edit gate, never a worker lock
_state_lock = threading.RLock()
_stop_event = threading.Event()  # direct, synchronous job invocations only
execution_context = threading.local()
_log_tail = {'run_id': None, 'log_text': ''}  # direct invocation compatibility
_live = {'run_id': None, 'job': None, 'target': '', 'dry_run': False,
         'started_at': None, 'status': 'idle', 'error': None}
_executions = {}
_tails = {}


def _context_state():
    return _executions.get(getattr(execution_context, 'run_token', None))


def _event():
    return getattr(execution_context, 'stop_event', _stop_event)


def is_stop_requested() -> bool:
    return _event().is_set()


def sleep_or_stop(seconds: float) -> bool:
    return _event().wait(timeout=seconds)


def _visible(state, owner_user_id, admin):
    return admin or (owner_user_id is not None and state.get('owner_user_id') == owner_user_id)


def _snapshot(state):
    return {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
            for k, v in state.items() if k not in ('stop_event', 'resources')}


def live_statuses(owner_user_id=None, admin=True):
    with _state_lock:
        return [{**_snapshot(s), 'running': True} for s in _executions.values()
                if _visible(s, owner_user_id, admin)]


def live_status(owner_user_id=None, admin=True, execution_id=None):
    with _state_lock:
        states = live_statuses(owner_user_id, admin)
        if execution_id:
            states = [s for s in states if s['execution_id'] == execution_id]
        if states:
            return states[0]
        if _visible(_live, owner_user_id, admin) and (not execution_id or _live.get('execution_id') == execution_id):
            return {**_snapshot(_live), 'running': False}
        return {'run_id': None, 'job': None, 'status': 'idle', 'running': False, 'progress': {}}


def stop_job(expected_run_id=None, *, execution_id=None, owner_user_id=None, admin=True):
    """Cancel one visible execution. Never guess when multiple runs are active."""
    with _state_lock:
        states = [s for s in _executions.values() if _visible(s, owner_user_id, admin)]
        if execution_id:
            states = [s for s in states if s['execution_id'] == execution_id]
        if expected_run_id is not None:
            states = [s for s in states if s.get('run_id') == expected_run_id]
        # Synchronous workers are used by offline tools, outside the dispatcher.
        if not _executions and admin and not execution_id and is_running() and _live.get('status') in ('running', 'stopping'):
            if expected_run_id is None or expected_run_id == _live.get('run_id'):
                states = [_live]
        if not states:
            return False, 'No job is currently running for that selection'
        if len(states) != 1:
            return False, 'Select the run you want to stop'
        state = states[0]
        first = state['status'] != 'stopping'
        state.get('stop_event', _stop_event).set()
        state['status'] = 'stopping'
        rid = state.get('run_id')
        if first and rid is not None:
            text = log_tail(rid) or ''
            publish_log(rid, (text + '\n[STOP] Stop requested by user... terminating gracefully.')[-60000:])
    return True, 'Stop requested' if first else 'Stop already requested'


def publish_log(run_id, text):
    with _state_lock:
        state = _context_state() or next((s for s in _executions.values() if s.get('run_id') == run_id), None)
        if state is None:
            _log_tail.update(run_id=run_id, log_text=text[-60000:])
            return
        _tails[run_id] = text[-60000:]
        state['run_id'] = run_id
        state['progress'] = {**state.get('progress', {}), 'action': text.splitlines()[-1][-300:] if text else 'Starting worker'}


def publish_progress(run_id, **values):
    with _state_lock:
        state = _context_state() or _live
        if state.get('run_id') != run_id:
            state['progress'] = {}
        state['run_id'] = run_id
        state['progress'] = {**state.get('progress', {}), **values}


def publish_account_runs(account_id: int, total_runs: int):
    with _state_lock:
        state = _context_state() or _live
        counts = dict(state.get('progress', {}).get('account_runs', {}))
        counts[str(account_id)] = total_runs
        state['progress'] = {**state.get('progress', {}), 'account_runs': counts}


def live_account_runs(owner_user_id=None, admin=True):
    with _state_lock:
        counts = {}
        for state in _executions.values():
            if _visible(state, owner_user_id, admin):
                counts.update(state.get('progress', {}).get('account_runs', {}))
        return counts


def log_tail(run_id):
    with _state_lock:
        return _tails.get(run_id, _log_tail['log_text'] if _log_tail['run_id'] == run_id else None)


def status_for(run_id, persisted):
    with _state_lock:
        states = list(_executions.values()) + [_live]
        return 'stopping' if persisted == 'running' and any(s.get('run_id') == run_id and s.get('status') == 'stopping' for s in states) else persisted


def is_running() -> bool:
    with _state_lock:
        return bool(_executions) or _run_lock.locked()


@contextmanager
def idle_lease():
    """Keep destructive changes atomic with admission, across every worker."""
    acquired = _run_lock.acquire(blocking=False)
    if acquired:
        with _state_lock:
            if _executions:
                _run_lock.release()
                acquired = False
    try:
        yield acquired
    finally:
        if acquired:
            _run_lock.release()


def _resolve_steps(steps):
    """Freeze actual scope before reserving; workers cannot expand it later."""
    resolved, resources, account_names = [], set(), {}
    with SessionLocal() as db:
        for key, original in steps:
            scope = dict(original)
            if key in ('sync_leads', 'import_list'):
                ids = {scope['account_id']} if scope.get('account_id') else set()
                campaigns = set()
            elif key in ('send_connections', 'check_replies', 'send_followups'):
                query = db.query(CampaignAccount).join(Campaign).join(Account).filter(Campaign.status == 'active', Account.status == 'active')
                if scope.get('campaign_ids') is not None:
                    query = query.filter(CampaignAccount.campaign_id.in_(scope['campaign_ids']))
                if scope.get('account_ids') is not None:
                    query = query.filter(CampaignAccount.account_id.in_(scope['account_ids']))
                links = query.all()
                ids = {link.account_id for link in links}
                campaigns = {link.campaign_id for link in links}
                scope.update(account_ids=sorted(ids), campaign_ids=sorted(campaigns))
            else:
                ids, campaigns = set(), set()
            resources.update(('account', aid) for aid in ids)
            if key == 'send_connections':
                resources.update(('lead_pool', cid) for cid in campaigns)
            for account in db.query(Account).filter(Account.id.in_(ids)):
                account_names[account.id] = account.name
            resolved.append((key, scope))
    if not resources:
        resources.add(('empty', steps[0][0]))
    return resolved, resources, account_names


@contextmanager
def user_deletion_lease(user_id):
    """Prevent ownership ID reuse while that user still has an execution."""
    acquired = _run_lock.acquire(timeout=2)
    try:
        with _state_lock:
            allowed = acquired and not any(s.get('owner_user_id') == user_id for s in _executions.values())
            if allowed and _live.get('owner_user_id') == user_id:
                _live['owner_user_id'] = None
        yield allowed
    finally:
        if acquired:
            _run_lock.release()


def start_job(job_key: str, dry_run=False, owner_user_id=None, **kwargs):
    target_label = kwargs.pop('target_label', None)
    return start_sequence([(job_key, kwargs)], None, target_label, dry_run, owner_user_id)


def start_sequence(steps, schedule_id=None, schedule_name=None, dry_run=False, owner_user_id=None):
    if not steps or any(key not in jobmod.JOB_REGISTRY for key, _ in steps):
        return False, 'Unknown or empty worker selection', None
    if not _run_lock.acquire(timeout=2):
        return False, 'Lead data is being updated. Try again shortly.', None
    token = uuid.uuid4().hex
    try:
        if owner_user_id is not None:
            from .models import User
            with SessionLocal() as db:
                user = db.get(User, owner_user_id)
                if user is None or not user.active:
                    return False, 'Your user account is no longer available. Sign in again.', None
        steps, resources, names = _resolve_steps(steps)
        with _state_lock:
            for existing in _executions.values():
                overlap = resources & existing['resources']
                if overlap:
                    busy = [names[aid] for kind, aid in overlap if kind == 'account' and aid in names]
                    reason = ('Account already running: ' + ', '.join(sorted(busy))) if busy else 'This campaign lead pool already has a connection job running'
                    return False, reason + '. Choose another account or wait for it to finish.', None
            state = dict(execution_id=token, owner_user_id=owner_user_id, run_id=None,
                         job=steps[0][0], target=schedule_name or ', '.join(names.values()) or 'No active accounts',
                         account_ids=sorted(names), dry_run=bool(dry_run), started_at=datetime.utcnow().isoformat(),
                         status='running', error=None, progress={}, batch_jobs=[key for key, _ in steps],
                         resources=resources, stop_event=threading.Event())
            _executions[token] = state
    finally:
        _run_lock.release()

    def worker():
        current_key = steps[0][0]
        try:
            execution_context.schedule_id = schedule_id
            execution_context.schedule_name = schedule_name
            execution_context.dry_run = bool(dry_run)
            execution_context.run_token = token
            execution_context.owner_user_id = owner_user_id
            execution_context.stop_event = state['stop_event']
            for key, scope in steps:
                if is_stop_requested():
                    break
                current_key = key
                with _state_lock:
                    state.update(job=key, run_id=None, progress={})
                jobmod.run_job(key, dry_run=dry_run, **scope)
            with SessionLocal() as db:
                rows = db.query(RunLog).filter_by(execution_id=token).order_by(RunLog.id).all()
                statuses = [r.status for r in rows]
                errors = [error for r in rows for error in (r.errors or [])]
                final = 'stopped' if is_stop_requested() else 'error' if 'error' in statuses or not rows else 'partial' if 'partial' in statuses else rows[-1].status
                with _state_lock:
                    state.update(run_id=rows[-1].id if rows else None, status=final,
                                 error=errors[0] if errors else None if rows or is_stop_requested() else 'Job ended without a run record')
        except jobmod.JobStoppedError:
            with SessionLocal() as db:
                for row in db.query(RunLog).filter_by(execution_id=token, status=RunStatus.RUNNING.value):
                    row.status = RunStatus.STOPPED.value
                    row.finished_at = datetime.utcnow()
                    row.duration_s = (row.finished_at - row.started_at).total_seconds() if row.started_at else 0
                    row.log_text = log_tail(row.id) or row.log_text
                db.commit()
            with _state_lock:
                state.update(status='stopped', error=None)
        except Exception as exc:
            try:
                with SessionLocal() as db:
                    jobmod._fatal(db, jobmod.JobType(current_key), exc, schedule_id=schedule_id, schedule_name=schedule_name)
            finally:
                with _state_lock:
                    state.update(status='error', error=str(exc))
        finally:
            with _state_lock:
                _live.clear()
                _live.update(_snapshot(state))
                _executions.pop(token, None)
                for rid in getattr(execution_context, 'run_ids', []):
                    _tails.pop(rid, None)
            execution_context.__dict__.clear()

    try:
        threading.Thread(target=worker, name=f'occ-{steps[0][0]}-{token[:8]}', daemon=True).start()
    except Exception:
        with _state_lock:
            _executions.pop(token, None)
        raise
    return True, f'Started {steps[0][0]}', token
