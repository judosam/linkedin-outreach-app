"""Named campaign schedules — dispatcher and lifecycle.

Schedule management (CRUD, recurrence, DB persistence) lives entirely in
schedule_store.py.  This module owns only:
  - SCHEDULED_JOBS / DAYS constants used by validation
  - APScheduler lifecycle (init / shutdown)
"""
from apscheduler.schedulers.background import BackgroundScheduler

SCHEDULED_JOBS = {'send_connections', 'check_replies', 'send_followups'}
DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

_scheduler = None


def init_scheduler():
    global _scheduler
    if _scheduler is None:
        instance = BackgroundScheduler(timezone='UTC')
        from .schedule_store import initialize
        initialize(instance)
        instance.start()
        _scheduler = instance
    return _scheduler


def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
