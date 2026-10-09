"""Offline tests for reporting, reassignment, error restoration and activity access."""
from datetime import datetime, timedelta
from unittest.mock import Mock
import pytest
from sqlalchemy import select
from app import jobs
from app.database import SessionLocal
from app.models import (Account, Campaign, CampaignAccount, DailySendCount, Lead, LeadEvent,
                        RunLog, RunTarget, User, UserActivity)
from tests.test_audit_fixes import audit, seed_lead


def destination():
    with SessionLocal() as db:
        c = Campaign(name='Destination', campaign_key='dest')
        a = Account(name='Destination account', session_ref='offline')
        db.add_all([c, a]); db.flush()
        db.add(CampaignAccount(campaign_id=c.id, account_id=a.id)); db.commit()
        return c.id, a.id


@pytest.mark.parametrize('stage', ['', 'INVITE_SENT', 'INVITE_AFTER_ACCEPT', 'INMAIL_FOLLOWUP_2'])
def test_remove_error_restores_stage_and_age(audit, stage):
    stamp = datetime(2026, 9, 1, 9)
    lid = seed_lead(status=stage, status_changed_at=stamp, received_replies=True, reply_message='Keep me')
    with SessionLocal() as db:
        lead = db.get(Lead, lid)
        jobs._set_status(db, lead, 'BLOCKED_ERROR', 'send_followups')
        jobs._set_status(db, lead, 'BLOCKED_ERROR', 'send_followups')
        lead.last_error = 'Failed'; db.commit()
    response = audit.post('/api/leads/reset-errors', json={'ids': [lid]})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        lead = db.get(Lead, lid)
        assert lead.status == stage and lead.status_changed_at == stamp
        assert lead.last_error == '' and lead.received_replies and lead.reply_message == 'Keep me'


def test_legacy_error_uses_recorded_transition(audit):
    lid = seed_lead(status='BLOCKED_ERROR', contact_channel='inmail')
    with SessionLocal() as db:
        db.add(LeadEvent(lead_id=lid, kind='status_change', detail='INMAIL_FOLLOWUP_1 -> BLOCKED_ERROR: failed'))
        db.commit()
    assert audit.post('/api/leads/reset-errors', json={'ids': [lid]}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Lead, lid).status == 'INMAIL_FOLLOWUP_1'


def test_reassign_preserves_history_and_rejects_duplicates_atomically(audit):
    cid, aid = destination()
    stamp = datetime(2026, 9, 1)
    lid = seed_lead(status='INVITE_AFTER_ACCEPT', associate_account_id=1, first_contacted_at=stamp,
                    last_followup_at=stamp, received_replies=True)
    response = audit.post('/api/leads/reassign', json={'ids': [lid], 'campaign_id': cid, 'account_id': aid})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        lead = db.get(Lead, lid)
        assert (lead.campaign_id, lead.associate_account_id) == (cid, aid)
        assert lead.status == 'INVITE_AFTER_ACCEPT' and lead.first_contacted_at == stamp
        assert lead.received_replies and lead.last_followup_at == stamp
    duplicate = seed_lead()
    unique = seed_lead(sales_nav_id='ACwUNIQUE')
    response = audit.post('/api/leads/reassign', json={'ids': [unique, duplicate], 'campaign_id': cid, 'account_id': aid})
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.get(Lead, unique).campaign_id == 1


def test_reassign_validates_mapping_and_allows_account_only(audit):
    cid, aid = destination()
    lid = seed_lead()
    assert audit.post('/api/leads/reassign', json={'ids': [lid], 'account_id': aid}).status_code == 422
    assert audit.post('/api/leads/reassign', json={'ids': [lid], 'account_id': 1}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Lead, lid).campaign_id == 1
        assert db.get(Lead, lid).associate_account_id == 1


def test_reassign_waits_for_workers(audit, monkeypatch):
    from contextlib import contextmanager
    from app import runner
    @contextmanager
    def busy():
        yield False
    monkeypatch.setattr(runner, 'idle_lease', busy)
    lid = seed_lead()
    assert audit.post('/api/leads/reassign', json={'ids': [lid], 'account_id': 1}).status_code == 409


def test_pair_counts_use_confirmed_counters_with_exact_day_boundaries(audit):
    cid, aid = destination()
    today = datetime.utcnow().date()
    lid = seed_lead()
    with SessionLocal() as db:
        for age, count in [(0, 2), (6, 3), (7, 11), (-1, 99)]:
            db.add(DailySendCount(campaign_id=1, account_id=1, date=today-timedelta(days=age),
                                 invite_sent_count=count, opentomsg_count=count, messages_sent=count))
        # Duplicated/imported event text must not inflate confirmed sends.
        for _ in range(5):
            db.add(LeadEvent(lead_id=lid, kind='outbound', job_type='send_connections', detail='Imported history'))
        db.commit()
    for days, count in [(1, 2), (7, 5), (30, 16), (0, 16)]:
        r = audit.get(f'/api/dashboard/campaign-stats?days={days}')
        assert r.status_code == 200, r.text
        row = next(x for x in r.json()['rows'] if x['campaign_id'] == 1)
        assert row['invites'] == row['inmails'] == row['messages'] == count
    assert audit.post('/api/leads/reassign', json={'ids': [lid], 'campaign_id': cid, 'account_id': aid}).status_code == 200
    rows = audit.get('/api/dashboard/campaign-stats').json()['rows']
    assert next(x for x in rows if x['campaign_id'] == 1)['invites'] == 16
    assert next(x for x in rows if x['campaign_id'] == cid)['invites'] == 0


def test_run_counts_deduplicate_targets_and_exclude_simulations(audit):
    with SessionLocal() as db:
        for dry in (False, True):
            r = RunLog(job_type='send_connections', campaign_id=1, account_id=1, dry_run=dry,
                       owner_user_id=1, status='success')
            db.add(r); db.flush()
            db.add(RunTarget(run_id=r.id, campaign_id=1, account_id=1))
        db.commit()
    row = audit.get('/api/dashboard/campaign-stats').json()['rows'][0]
    assert row['runs'] == 1


def test_activity_logs_login_worker_lifecycle_and_changes(audit):
    lid = seed_lead()
    assert audit.post('/api/leads/reassign', json={'ids': [lid], 'account_id': 1}).status_code == 200
    with SessionLocal() as db:
        run = RunLog(job_type='check_replies', owner_user_id=1, status='running', target='Fixture')
        db.add(run); db.commit()
        run.status = 'success'; db.commit()
        run.stats = {'unrelated': 'update'}; db.commit()
    events = audit.get('/api/user-activity').json()['items']
    assert any(x['action'] == 'login' for x in events)
    assert any(x['action'] == 'reassign_leads' for x in events)
    assert sorted(x['result'] for x in events if x['action'] == 'check_replies') == ['running', 'success']
    assert 'test-password-only' not in str(events)
    assert audit.get('/api/user-activity?action=login').json()['total'] == 1


def test_restricted_user_sees_only_own_activity_and_allowed_pairs(audit):
    cid, aid = destination()
    hidden = seed_lead(campaign_id=cid)
    with SessionLocal() as db:
        other = User(username='other', password_hash='unused', role='campaign_manager')
        db.add(other); db.flush()
        db.add(UserActivity(user_id=other.id, username='other', action='login'))
        user = db.get(User, 1); user.role='campaign_manager'
        user.allowed_campaign_ids=[1]; user.allowed_account_ids=[1]; db.commit()
    events = audit.get('/api/user-activity').json()['items']
    assert events and all(x['username'] == 'test-admin' for x in events)
    rows = audit.get('/api/dashboard/campaign-stats').json()['rows']
    assert all(x['campaign_id'] == 1 and x['account_id'] == 1 for x in rows)
    assert audit.post('/api/leads/reassign', json={'ids': [hidden], 'account_id': 1}).status_code == 403
    lid = seed_lead(sales_nav_id='ACwACCESS')
    assert audit.post('/api/leads/reassign', json={'ids': [lid], 'campaign_id': cid, 'account_id': aid}).status_code == 403



def test_additive_stage_migration_preserves_existing_leads(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text
    from app import database
    engine = create_engine('sqlite:///' + str(tmp_path / 'old.db'))
    try:
        with engine.begin() as c:
            c.execute(text('CREATE TABLE leads (id INTEGER PRIMARY KEY, status VARCHAR(40), last_error VARCHAR(255))'))
            c.execute(text("INSERT INTO leads VALUES (1, 'BLOCKED_ERROR', 'Keep existing error')"))
        monkeypatch.setattr(database, 'engine', engine)
        for _ in range(2):
            database._ensure_columns('leads', {'status_before_error': 'VARCHAR(40)', 'stage_time_before_error': 'DATETIME'})
        with engine.connect() as c:
            row = c.execute(text('SELECT * FROM leads')).one()
            assert tuple(row) == (1, 'BLOCKED_ERROR', 'Keep existing error', None, None)
    finally:
        engine.dispose()


def test_worker_records_each_visited_pair_once(audit, monkeypatch):
    seed_lead()
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    with SessionLocal() as db:
        target = db.scalars(select(RunTarget)).one()
        assert (target.campaign_id, target.account_id) == (1, 1)
    row = audit.get('/api/dashboard/campaign-stats').json()['rows'][0]
    assert row['runs'] == 1 and row['invites'] == 1


def test_activity_and_reporting_require_login(audit):
    audit.post('/api/logout')
    for path in ['/api/user-activity', '/api/dashboard/campaign-stats']:
        assert audit.get(path).status_code == 401


def test_activity_write_failure_does_not_report_completed_action_as_failed(audit, monkeypatch):
    from app import operations
    lid = seed_lead(status='BLOCKED_ERROR')
    monkeypatch.setattr(operations, 'record_activity', Mock(side_effect=RuntimeError('Audit storage unavailable')))
    response = audit.post('/api/leads/reset-errors', json={'ids': [lid]})
    assert response.status_code == 200 and response.json()['reset'] == 1
    with SessionLocal() as db:
        assert db.get(Lead, lid).status == ''


def test_active_campaign_report_excludes_paused_counts_and_keeps_empty_campaigns(audit):
    cid, aid = destination()
    with SessionLocal() as db:
        db.get(Campaign, cid).status = 'paused'
        db.add(Campaign(name='Empty active campaign', campaign_key='empty-active'))
        db.add(DailySendCount(campaign_id=1, account_id=1, date=datetime.utcnow().date(), invite_sent_count=3))
        db.add(DailySendCount(campaign_id=cid, account_id=aid, date=datetime.utcnow().date(), invite_sent_count=99))
        db.commit()
    response = audit.get('/api/dashboard/campaign-stats?days=1&active_only=true')
    assert response.status_code == 200
    rows = response.json()['rows']
    assert sum(r['invites'] for r in rows) == 3
    assert all(r['campaign_id'] != cid for r in rows)
    assert any(r['campaign'] == 'Empty active campaign' and r['account_id'] is None for r in rows)
