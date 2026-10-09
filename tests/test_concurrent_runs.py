"""Offline concurrency and log-ownership regressions: never contact LinkedIn."""
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import jobs, runner
from app.auth import create_session
from app.database import SessionLocal, engine
from app.main import app
from app.models import Account, Base, Campaign, CampaignAccount, RunLog, User


@pytest.fixture
def clients():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    runner._live.clear()
    runner._live.update(run_id=None, status='idle')
    runner._stop_event.clear()
    with TestClient(app) as admin:
        assert admin.post('/api/login', json={'username':'test-admin','password':'test-password-only'}).status_code == 200
        with SessionLocal() as db:
            users = [User(username=f'manager{i}', password_hash='offline', role='campaign_manager', active=True,
                          allowed_campaign_ids=[1,2,3], allowed_account_ids=[1,2,3]) for i in (1,2)]
            db.add_all(users)
            db.add_all([Account(id=i, name=f'Account {i}', status='active') for i in (1,2,3)])
            db.add_all([Campaign(id=i, name=f'Campaign {i}', campaign_key=f'campaign{i}') for i in (1,2,3)])
            db.flush()
            db.add_all([CampaignAccount(campaign_id=i, account_id=i) for i in (1,2,3)])
            db.commit()
            ids = [u.id for u in users]
        one, two = TestClient(app), TestClient(app)
        one.cookies.set('occ_session', create_session(ids[0]))
        two.cookies.set('occ_session', create_session(ids[1]))
        yield admin, one, two, ids
        # Always stop/join all fixture workers before resetting the shared database.
        for live in runner.live_statuses():
            runner.stop_job(execution_id=live['execution_id'])
        wait_for(lambda: not runner.is_running())
        one.close(); two.close()


def wait_for(check, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return
        time.sleep(.01)
    assert check(), 'fixture worker did not reach the expected state'


def blocking_worker(key, dry_run=False, **scope):
    aid = scope.get('account_id') or scope['account_ids'][0]
    with SessionLocal() as db:
        run = jobs._Run(db, jobs.JobType(key), f'Account {aid} private output', dry_run, account_id=aid)
        run.log(f'SECRET-{aid}')
        runner.publish_progress(run.run.id, account=aid)
        runner.sleep_or_stop(15)
        run.finish()


def start(client, aid, key='check_replies'):
    return client.post(f'/api/jobs/{key}/run', json={'campaign_ids':[aid], 'account_ids':[aid], 'dry_run':True})


def test_two_accounts_run_together_and_stop_is_private(clients):
    admin, one, two, ids = clients
    with patch.object(jobs, 'run_job', blocking_worker):
        a, b = start(one,1), start(two,2)
        assert a.status_code == b.status_code == 200, (a.text,b.text)
        token_a, token_b = a.json()['execution_id'], b.json()['execution_id']
        wait_for(lambda: all(s.get('run_id') for s in runner.live_statuses()) and len(runner.live_statuses()) == 2)
        assert start(one,1,'send_followups').status_code == 409
        with runner.idle_lease() as acquired:
            assert not acquired
        for client, aid, token in [(one,1,token_a),(two,2,token_b)]:
            j = client.get('/api/jobs').json()
            assert len(j['running']) == 1 and j['running'][0]['account_ids'] == [aid]
            live = client.get('/api/runs/live').json()
            assert live['running_count'] == 1 and live['execution_id'] == token
            assert f'SECRET-{aid}' in live['log_text'] and f'SECRET-{3-aid}' not in str(live)
            history = client.get('/api/runs').json()
            assert len(history) == 1
            assert client.get('/api/dashboard/summary').status_code == 200
        all_live = admin.get('/api/runs/live').json()
        assert all_live['running_count'] == 2
        rid_b = two.get('/api/runs/live').json()['run_id']
        for url in [f'/api/runs/{rid_b}/log', f'/api/runs/live?execution_id={token_b}', f'/api/runs/live/stream?execution_id={token_b}']:
            assert one.get(url).status_code == 404, url
        assert one.post('/api/jobs/stop',json={'run_id':rid_b}).status_code == 400
        assert one.post('/api/jobs/stop',json={'execution_id':token_b}).status_code == 400
        assert admin.post('/api/jobs/stop').status_code == 400  # ambiguous
        assert one.post('/api/jobs/stop',json={'execution_id':token_a}).status_code == 200
        wait_for(lambda: len(runner.live_statuses()) == 1)
        other = two.get('/api/runs/live').json()
        assert other['status'] == 'running' and 'SECRET-2' in other['log_text']
        assert one.get('/api/runs/live').json()['status'] == 'stopped'
        assert admin.get(f'/api/runs/live?execution_id={token_b}').json()['progress']['account'] == 2
        assert admin.post('/api/jobs/stop',json={'execution_id':token_b}).status_code == 200
        wait_for(lambda: not runner.is_running())
        with SessionLocal() as db:
            rows = db.scalars(select(RunLog).order_by(RunLog.id)).all()
            assert {r.owner_user_id for r in rows} == set(ids)
            assert {r.status for r in rows} == {'stopped'}
            assert len({r.execution_id for r in rows}) == 2
            assert 'SECRET-2' not in next(r.log_text for r in rows if r.owner_user_id == ids[0])
        with runner.idle_lease() as acquired:
            assert acquired


def test_shared_account_and_lead_pool_reservations(clients):
    admin, one, two, ids = clients
    with SessionLocal() as db:
        db.add_all([CampaignAccount(campaign_id=3, account_id=1), CampaignAccount(campaign_id=1, account_id=2)])
        db.commit()
    with patch.object(jobs, 'run_job', blocking_worker):
        assert start(one,1,'send_connections').status_code == 200
        wait_for(lambda: len(runner.live_statuses()) == 1)
        # Same physical account is protected across campaigns, worker types and imports.
        for payload,key in [({'campaign_ids':[3],'account_ids':[1]},'check_replies'),
                            ({'account_id':1,'saved_search_id':'123'},'sync_leads')]:
            response=two.post(f'/api/jobs/{key}/run',json={**payload,'dry_run':True})
            assert response.status_code == 409, response.text
        # Different accounts cannot claim the same untouched campaign pool twice.
        assert two.post('/api/jobs/send_connections/run',json={'campaign_ids':[1],'account_ids':[2],'dry_run':True}).status_code == 409
        assert start(two,2,'send_connections').status_code == 200


def test_legacy_and_scheduler_logs_are_admin_only(clients):
    admin, one, two, ids = clients
    with SessionLocal() as db:
        db.add(RunLog(job_type='check_replies',status='success',log_text='FLEET SECRET'))
        db.commit()
        rid=db.scalar(select(RunLog.id))
    assert len(admin.get('/api/runs').json()) == 1
    for client in (one,two):
        assert client.get('/api/runs').json() == []
        assert client.get(f'/api/runs/{rid}/log').status_code == 404
        assert client.get('/api/runs/live').json()['log_text'] == ''
        assert all(j['last_run'] is None for j in client.get('/api/jobs').json()['jobs'])
        assert 'FLEET SECRET' not in client.get('/api/dashboard/summary').text


def test_scope_frozen_and_failure_does_not_finish_other_run(clients):
    admin, one, two, ids = clients
    held = threading.Event()
    proceed = threading.Event()
    observed = []
    def worker(key, dry_run=False, **scope):
        if scope['account_ids'] == [1]:
            observed.append(scope)
            held.set()
            proceed.wait(5)
            raise RuntimeError('Only account 1 failed')
        blocking_worker(key,dry_run,**scope)
    with patch.object(jobs, 'run_job', worker):
        assert start(two,2).status_code == 200
        a=start(one,1)
        assert a.status_code == 200
        assert held.wait(3)
        assert observed[0]['campaign_ids'] == [1] and observed[0]['account_ids'] == [1]
        proceed.set()
        wait_for(lambda: len(runner.live_statuses()) == 1)
        assert two.get('/api/runs/live').json()['status'] == 'running'
        assert one.get('/api/runs/live').json()['status'] == 'error'
        assert 'Only account 1 failed' not in two.get('/api/runs/live').text


def test_disabled_user_cannot_read_live_logs(clients):
    _, one, _, ids = clients
    with SessionLocal() as db:
        db.get(User,ids[0]).active=False
        db.commit()
    assert one.get('/api/runs/live').status_code == 401
    assert one.get('/api/runs').status_code == 401


def test_real_connection_workers_release_database_before_network(clients):
    """Both actual workers must reach their network phase before either returns."""
    from unittest.mock import Mock
    from app.models import Lead
    _, _, _, ids = clients
    barrier = threading.Barrier(2, timeout=4)
    reached = set()
    with SessionLocal() as db:
        for aid in (1,2):
            db.add(Lead(sales_nav_id=f'ACwOFFLINE{aid}', full_name=f'Lead {aid}',
                        campaign_id=aid, opentomsg=False, linkedin_url=f'https://offline.invalid/{aid}'))
        db.commit()
    def inbox(session, **kwargs):
        reached.add(session._account_id)
        barrier.wait()
        return {'elements':[]}
    with patch.object(jobs,'load_session_ref',return_value=Mock()), patch.object(jobs.li,'fetch_inbox',inbox), \
         patch.object(jobs.li,'send_connection_invite',return_value=(True,None,'')) as send, \
         patch.object(jobs.li,'polite_sleep',return_value=True):
        for aid in (1,2):
            assert runner.start_job('send_connections',campaign_ids=[aid],account_ids=[aid],owner_user_id=ids[aid-1])[0]
        wait_for(lambda: not runner.is_running(),timeout=8)
        assert reached == {1,2}
        assert send.call_count == 2
        with SessionLocal() as db:
            assert {r.status for r in db.query(RunLog)} == {'success'}
            assert {l.associate_account_id for l in db.query(Lead)} == {1,2}


def test_batch_keeps_accounts_reserved_between_steps(clients):
    _, _, _, ids = clients
    entered = threading.Event()
    release = threading.Event()
    def execute(key, **scope):
        with SessionLocal() as db:
            run = jobs._Run(db,jobs.JobType(key),'Batch fixture',True)
            if key == 'send_followups':
                entered.set()
                release.wait(3)
            run.finish()
    try:
        with patch.object(jobs,'run_job',execute):
            steps=[('check_replies',{'campaign_ids':[1],'account_ids':[1]}),
                   ('send_followups',{'campaign_ids':[2],'account_ids':[2]})]
            assert runner.start_sequence(steps,dry_run=True,owner_user_id=ids[0])[0]
            assert entered.wait(3)
            assert not runner.start_job('check_replies',campaign_ids=[1],account_ids=[1],dry_run=True)[0]
            assert not runner.start_job('check_replies',campaign_ids=[2],account_ids=[2],dry_run=True)[0]
            release.set()
            wait_for(lambda: not runner.is_running())
    finally:
        release.set()

def test_deleted_user_logs_cannot_transfer_to_reused_user_id(clients):
    admin, one, two, ids = clients
    with SessionLocal() as db:
        row=RunLog(job_type='check_replies',status='success',owner_user_id=ids[1],log_text='Former user private log')
        db.add(row);db.commit();rid=row.id
    assert admin.delete(f'/api/users/{ids[1]}').status_code == 200
    with SessionLocal() as db:
        assert db.get(RunLog,rid).owner_user_id is None
        replacement=User(id=ids[1],username='replacement',password_hash='offline',role='campaign_manager',active=True)
        db.add(replacement);db.commit()
    two.cookies.set('occ_session',create_session(ids[1]))
    assert two.get('/api/runs').json()==[]
    assert two.get(f'/api/runs/{rid}/log').status_code==404
    with patch.object(jobs,'run_job',blocking_worker):
        assert start(one,1).status_code==200
        assert admin.delete(f'/api/users/{ids[0]}').status_code==409


def test_existing_database_migration_preserves_unattributed_logs(tmp_path,monkeypatch):
    from sqlalchemy import create_engine, text, inspect
    from app import database
    legacy=create_engine('sqlite:///'+str(tmp_path/'legacy.db'))
    from sqlalchemy import event
    @event.listens_for(legacy,'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(legacy)
    try:
        with legacy.begin() as connection:
            connection.execute(text('DROP TABLE run_logs'))
            connection.execute(text('''CREATE TABLE run_logs (
                id INTEGER PRIMARY KEY, job_type VARCHAR(40) NOT NULL,
                schedule_id INTEGER, campaign_id INTEGER, account_id INTEGER,
                target VARCHAR(255), dry_run BOOLEAN, status VARCHAR(20),
                started_at DATETIME, finished_at DATETIME, duration_s FLOAT,
                stats JSON, errors JSON, log_text TEXT)'''))
            connection.execute(text("INSERT INTO run_logs (job_type,status,dry_run,target,log_text,started_at) VALUES ('check_replies','success',0,'Legacy','Retained output',CURRENT_TIMESTAMP)"))
        monkeypatch.setattr(database,'engine',legacy)
        database.init_db()
        database.init_db()  # safe on every startup
        assert {'owner_user_id','execution_id'} <= {c['name'] for c in inspect(legacy).get_columns('run_logs')}
        with legacy.connect() as connection:
            row=connection.execute(text('SELECT log_text,owner_user_id,execution_id FROM run_logs')).one()
            assert tuple(row)==('Retained output',None,None)
        from sqlalchemy.orm import Session
        with Session(legacy) as db:
            user=User(username='former',password_hash='offline',role='campaign_manager',active=True)
            db.add(user);db.commit()
            row=db.query(RunLog).one();row.owner_user_id=user.id;db.commit()
            db.delete(user);db.commit();db.refresh(row)
            assert row.owner_user_id is None
    finally:
        legacy.dispose()
