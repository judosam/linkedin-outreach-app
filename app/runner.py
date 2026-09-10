"""Threaded job execution with a single-flight lock and live status sync.

The jobs write their full logs into run_logs; this layer adds:
- non-blocking POST /jobs/... (job runs in a daemon thread)
- one-job-at-a-time enforcement (LinkedIn account safety)
- live status polling for the UI
"""
import threading
import traceback
from datetime import datetime

from sqlalchemy import func

from .database import SessionLocal
from .models import RunLog, RunStatus
from . import jobs as jobmod

_run_lock = threading.Lock()
_state_lock = threading.Lock()

_live = {
    'run_id': None,
    'job': None,
    'target': '',
    'dry_run': False,
    'started_at': None,
    'status': 'idle',
    'error': None,
}


def is_running() -> bool:
    return _run_lock.locked()


def live_status():
    with _state_lock:
        return dict(_live)


def _watch_run(job_key: str, min_run_id: int):
    """Wait for the new RunLog row (id > min_run_id) of this job, then follow it
    until it leaves 'running'. Avoids racing the worker thread's first insert."""
    run_id = None
    for _ in range(30):  # up to ~30s for the row to appear
        with SessionLocal() as db:
            row = db.query(RunLog).filter(
                RunLog.job_type == job_key, RunLog.id > min_run_id
            ).order_by(RunLog.id.desc()).first()
            if row is not None:
                run_id = row.id
                break
        threading.Event().wait(1)
    if run_id is None:
        return
    with _state_lock:
        _live['run_id'] = run_id
    while True:
        with SessionLocal() as db:
            row = db.get(RunLog, run_id)
            status = row.status if row else RunStatus.ERROR.value
        with _state_lock:
            _live['status'] = status
        if status != RunStatus.RUNNING.value:
            with _state_lock:
                if _live['run_id'] == run_id and _live['status'] != 'running':
                    _live['status'] = status  # success | partial | error
            break
        threading.Event().wait(2)


def start_job(job_key: str, dry_run=False, **kwargs):
    """Queue a job into a background thread. Returns (ok, message, run_id|None)."""
    if job_key not in jobmod.JOB_REGISTRY:
        return False, f"Unknown job '{job_key}'", None
    if _run_lock.locked():
        return False, 'Another pipeline job is already running. Try again when it finishes.', None

    kwargs.pop('target_label', None)  # UI-only field, not a job argument
    target = kwargs.get('campaign_ids') or kwargs.get('account_ids') or 'all'

    with SessionLocal() as db:
        min_run_id = db.query(func.max(RunLog.id)).scalar() or 0

    def worker():
        acquired = _run_lock.acquire(timeout=10)
        if not acquired:
            return
        try:
            with _state_lock:
                _live.update({'job': job_key, 'target': str(target), 'dry_run': bool(dry_run),
                              'started_at': datetime.now().isoformat(timespec='seconds'),
                              'status': 'running', 'error': None})
            jobmod.run_job(job_key, dry_run=dry_run, **kwargs)
        except Exception as e:
            traceback.print_exc()
            with _state_lock:
                _live['status'] = 'error'
                _live['error'] = str(e)
        finally:
            _run_lock.release()

    threading.Thread(target=worker, name=f"occ-{job_key}", daemon=True).start()
    threading.Thread(target=_watch_run, args=(job_key, min_run_id), daemon=True).start()

    with _state_lock:
        _live.update({'job': job_key, 'target': str(target), 'dry_run': bool(dry_run),
                      'started_at': datetime.now().isoformat(timespec='seconds'),
                      'status': 'running', 'error': None, 'run_id': None})
    return True, f"Started {job_key}" + (' (dry run)' if dry_run else ''), None
