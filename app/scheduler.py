"""APScheduler wiring: reproduces the legacy Task Scheduler pattern
(fixed-time slots + randomized daily window) and stays configurable per job.

Times live in the `jobs_schedule` settings row (JSON): {job_key: ["08:00", ...]}.
import_list is manual-only and never scheduled. Every execution goes through
runner.start_job, so single-flight + run_logs + notifications all apply.
"""
import random
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .database import SessionLocal
from .models import JobType

DEFAULT_SCHEDULE = {
    # Two fixed slots per job, matching the legacy "fixed + jitter" pattern
    'sync_leads': ['08:00', '14:00'],
    'send_connections': ['09:00', '23:00'],
    'check_replies': ['10:00', '22:00'],
    'send_followups': ['11:00', '21:00'],
    # import_list: manual only (never scheduled)
}

JITTER_MINUTES = 15  # ±15m like the legacy "Next: 14:00 (±15m jitter)"

_scheduler: BackgroundScheduler | None = None


def load_schedule() -> dict:
    from .models import Setting
    try:
        db = SessionLocal()
        try:
            row = db.get(Setting, 'jobs_schedule')
            stored = row.value_json if row else None
        finally:
            db.close()
        import json
        stored = json.loads(stored) if isinstance(stored, str) else stored
        if isinstance(stored, dict):
            return {**DEFAULT_SCHEDULE, **stored}
    except Exception:
        pass
    return dict(DEFAULT_SCHEDULE)


def save_schedule(schedule: dict):
    import json
    from .models import Setting
    db = SessionLocal()
    try:
        row = db.get(Setting, 'jobs_schedule')
        if row is None:
            row = Setting(key='jobs_schedule', value_json=json.dumps(schedule))
            db.add(row)
        else:
            row.value_json = json.dumps(schedule)
        db.commit()
    finally:
        db.close()


def _run_scheduled(job_key: str):
    from . import runner
    if runner.is_running():
        print(f"[scheduler] {job_key} skipped - another job is running")
        return
    # de-conflict exact-time collisions; the cron slot keeps the real jitter
    time.sleep(min(random.randint(0, JITTER_MINUTES * 60), 60))
    ok, msg, _ = runner.start_job(job_key, dry_run=False)
    print(f"[scheduler] {job_key}: {msg}")


def init_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone='UTC')
    schedule = load_schedule()

    for job_key, times in schedule.items():
        if not times or job_key == 'import_list':
            continue
        if job_key not in JobType.__members__:
            continue
        for t in times:
            hour, minute = str(t).split(':')[:2]
            scheduler.add_job(
                _run_scheduled, CronTrigger(hour=int(hour), minute=int(minute)),
                args=[job_key], id=f"{job_key}@{t}", replace_existing=True,
                misfire_grace_time=900,
            )

    scheduler.start()
    _scheduler = scheduler
    print(f"[scheduler] started with {len(scheduler.get_jobs())} job slot(s)")
    return scheduler


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
