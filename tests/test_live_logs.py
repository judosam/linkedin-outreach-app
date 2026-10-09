"""Offline coverage for live logging, run switches, history and activity."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine
from app.models import Base, RunLog, Lead, LeadEvent, Account, Campaign
from app import jobs, runner


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with patch.dict(runner._live, run_id=None, status='idle'), patch.dict(runner._log_tail, run_id=None, log_text=''):
        with TestClient(app) as c:
            assert c.post('/api/login', json={'username':'test-admin','password':'test-password-only'}).status_code == 200
            yield c


def test_callable_logger_updates_before_completion_without_committing_leads(client):
    with SessionLocal() as db:
        run = jobs._Run(db, jobs.JobType.CHECK_REPLIES, 'Offline worker', False)
        pending = Lead(sales_nav_id='pending', full_name='Not committed')
        db.add(pending)
        run.log('First live line')
        run.log('Second live line')
        with patch.dict(runner._live, run_id=run.run.id, status='running'):
            live = client.get('/api/runs/live').json()
            assert live['active'] and 'Second live line' in live['log_text']
            full = client.get(f'/api/runs/{run.run.id}/log').json()
            assert full['log_text'] == live['log_text']
            with SessionLocal() as observer:
                assert observer.query(Lead).count() == 0
            run.log('Final line')
            run.finish()
            done = client.get('/api/runs/live').json()
            assert not done['active'] and done['status'] == 'success'
            assert 'Final line' in done['log_text']


def test_switch_reset_and_rolling_buffer_snapshot(client):
    with SessionLocal() as db:
        old = RunLog(job_type='sync_leads',status='success',log_text='old\n' * 50)
        new = RunLog(job_type='check_replies',status='running',log_text='')
        db.add_all([old,new]);db.commit()
        with patch.dict(runner._live, run_id=new.id, status='running'):
            runner.publish_log(new.id, 'new first\nnew second')
            result=client.get(f'/api/runs/live?after=50&run_id={old.id}').json()
            assert result['reset'] and result['lines'] == ['new first','new second']
            runner.publish_log(new.id, 'replacement first\nreplacement second')
            result=client.get(f'/api/runs/live?after=2&run_id={new.id}').json()
            assert result['log_text'] == 'replacement first\nreplacement second'


def test_history_pagination_and_combined_filters(client):
    with SessionLocal() as db:
        db.add_all([RunLog(job_type='check_replies',status='success',dry_run=True) for _ in range(230)])
        db.add(RunLog(job_type='sync_leads',status='error',started_at=datetime.utcnow()-timedelta(days=60)))
        db.commit()
    page=client.get('/api/runs?paginated=true&limit=25&offset=225').json()
    assert page['total']==231 and len(page['items'])==6
    filtered=client.get('/api/runs?paginated=true&job=check_replies&status=success&dry_run=true&since_days=1').json()
    assert filtered['total']==230
    assert isinstance(client.get('/api/runs?limit=5').json(),list)
    assert client.get('/api/runs?offset=-1').status_code==422


def test_activity_joins_real_context_and_requires_auth(client):
    with SessionLocal() as db:
        a=Account(name='Test operator'); c=Campaign(name='Test campaign',campaign_key='test')
        db.add_all([a,c]);db.flush()
        lead=Lead(sales_nav_id='123', full_name='Test prospect',company='Test company',campaign_id=c.id,associate_account_id=a.id)
        db.add(lead);db.flush()
        db.add_all([LeadEvent(lead_id=lead.id,kind='reply',detail='Interested in a conversation'),LeadEvent(lead_id=lead.id,kind='status_change',detail='hidden duplicate')]);db.commit()
    events=client.get('/api/dashboard/activity').json()
    assert len(events)==1 and events[0]['account']=='Test operator'
    assert events[0]['campaign']=='Test campaign' and events[0]['lead_name']=='Test prospect'
    with TestClient(app) as anonymous:
        for url in ['/api/runs/live','/api/runs','/api/dashboard/activity','/api/runs/1/log','/api/runs/live/stream']:
            assert anonymous.get(url).status_code==401
