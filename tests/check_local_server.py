"""Explicit local-data sanity check. Blocks live jobs and all notifications."""
import os
import sys
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['OCC_DISABLE_SCHEDULER'] = '1'
from app.config import APP_DATA_DIR, ADMIN_USERNAME, ADMIN_PASSWORD

database = APP_DATA_DIR / 'app_data.db'
if database.exists():
    backup = database.with_name('app_data.before-verification-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.db')
    with sqlite3.connect(database) as source, sqlite3.connect(backup) as target:
        source.backup(target)

from app.main import app
from app import jobs, runner, scheduler, schedule_store
from app.database import SessionLocal
from app.models import Lead
import uvicorn
import httpx

server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8767, log_level='error'))
original = runner.start_sequence
def guarded(steps, schedule_id=None, schedule_name=None, dry_run=False):
    if not dry_run:
        return False, 'Live jobs blocked during verification', None
    return original(steps, schedule_id, schedule_name, dry_run)

with patch.object(schedule_store, 'fire'), patch.object(runner, 'start_sequence', side_effect=guarded), \
     patch.object(jobs, 'load_session_ref', side_effect=AssertionError('Live session blocked')), \
     patch.object(jobs.notify, 'notify_run_summary'), patch.object(jobs.notify, 'notify_send_errors'), \
     patch.object(jobs.notify, 'notify_critical'), patch.object(jobs.notify, 'send_reply_digest'):
    try:
        scheduler.init_scheduler()
        assert scheduler._scheduler.running
        thread = threading.Thread(target=server.run, daemon=True); thread.start()
        for _ in range(100):
            if server.started: break
            time.sleep(.1)
        with httpx.Client(base_url='http://127.0.0.1:8767', timeout=20) as client:
            assert client.get('/').status_code == 200
            for path in ['style.css', 'app.js', 'views.js']:
                assert client.get('/static/' + path).status_code == 200
            assert client.post('/api/login', json={'username':ADMIN_USERNAME,'password':ADMIN_PASSWORD}).status_code == 200
            summary = client.get('/api/dashboard/summary').json()
            with SessionLocal() as db:
                assert summary['totals']['leads_total'] == db.query(Lead).count()
            response = client.post('/api/jobs/send_connections/run', json={'dry_run':True})
            assert response.status_code == 200, response.status_code
            for _ in range(300):
                if not runner.is_running(): break
                time.sleep(.1)
            assert not runner.is_running(), 'Dry run did not finish in 30 seconds'
            run = client.get('/api/runs?job=send_connections&limit=1').json()[0]
            assert run['dry_run'] and run['status'] == 'success', run['status']
            log = client.get(f'/api/runs/{run["id"]}/log').json()
            assert isinstance(log['log_text'], str)
            print('PASS: local Uvicorn, scheduler initialization, static files, authenticated DB totals, dry-run history/log endpoint')
    finally:
        server.should_exit = True
        if 'thread' in locals(): thread.join(timeout=10)
        scheduler.shutdown_scheduler()
