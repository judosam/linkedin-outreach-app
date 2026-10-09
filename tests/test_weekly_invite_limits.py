"""Weekly invitation limits: isolated database and mocked LinkedIn only."""
from datetime import datetime, timedelta
from unittest.mock import Mock
import pytest
from app import jobs
from app.database import SessionLocal
from app.invite_limits import weekly_invite_status, backfill_weekly_invites, week_start_utc
from app.models import Account, AccountInviteSend, Campaign, CampaignAccount, DailySendCount, Lead, LeadEvent, RunLog
from tests.test_audit_fixes import audit


def lead(db, cid=1, open_link=False):
    row=Lead(campaign_id=cid,full_name='Weekly lead',sales_nav_id='ACwWEEKLY',
             linkedin_url='https://offline.invalid/weekly',opentomsg=open_link)
    # Keep each fixture identity unique inside its campaign.
    row.sales_nav_id+=str(db.query(Lead).count())
    db.add(row);db.flush();return row


@pytest.mark.parametrize('cap',[-1,151,1.2,True])
def test_api_rejects_invalid_weekly_caps(audit,cap):
    assert audit.post('/api/accounts',json={'name':'Invalid','weekly_invite_cap':cap}).status_code==422
    assert audit.put('/api/accounts/1',json={'name':'Audit account','weekly_invite_cap':cap}).status_code==422


def test_api_default_zero_and_partial_updates(audit):
    assert audit.get('/api/accounts').json()[0]['weekly_invite_cap']==100
    assert audit.put('/api/accounts/1',json={'name':'Audit account','weekly_invite_cap':150}).status_code==200
    assert audit.get('/api/accounts').json()[0]['weekly_invite_cap']==150
    assert audit.put('/api/accounts/1',json={'name':'Audit account','weekly_invite_cap':40}).status_code==200
    assert audit.put('/api/accounts/1',json={'name':'Renamed'}).status_code==200
    assert audit.get('/api/accounts').json()[0]['weekly_invite_cap']==40
    assert audit.put('/api/accounts/1',json={'name':'Renamed','weekly_invite_cap':0}).status_code==200
    assert audit.get('/api/accounts').json()[0]['weekly_invites']=={'limit':0,'used':0,'remaining':0}


def test_monday_reset_window_and_account_isolation(audit):
    """The budget is a calendar week: it counts sends since Monday 00:00 UTC
    and resets the moment the new week starts. Last Sunday's sends do not
    count, and a send at the exact reset boundary does."""
    from app.invite_limits import week_start_utc
    now = datetime(2026, 9, 23, 12)  # a Wednesday
    monday = week_start_utc(now)
    assert monday == datetime(2026, 9, 21)  # Monday 00:00 of that week
    with SessionLocal() as db:
        db.add(Account(id=2, name='Other'))
        db.flush()
        db.add_all([AccountInviteSend(account_id=1, sent_at=monday - timedelta(seconds=1), count=80),
                    AccountInviteSend(account_id=1, sent_at=monday, count=3),
                    AccountInviteSend(account_id=2, sent_at=now, count=90)])
        db.commit()
        assert weekly_invite_status(db, db.get(Account, 1), now)['used'] == 3
        # Reset moment: next Monday 00:00 shows a fresh budget.
        assert weekly_invite_status(db, db.get(Account, 1), datetime(2026, 9, 28))['used'] == 0


def test_shared_campaign_budget_and_durable_receipts(audit,monkeypatch):
    with SessionLocal() as db:
        db.get(Account,1).weekly_invite_cap=3
        db.add(Campaign(id=2,name='Second',campaign_key='second'));db.flush()
        db.add(CampaignAccount(campaign_id=2,account_id=1,invite_limit=10))
        db.add(AccountInviteSend(account_id=1,sent_at=week_start_utc()+timedelta(hours=1),count=1))
        for cid in (1,1,2,2):lead(db,cid)
        db.commit()
    send=Mock(return_value=(True,None,''));monkeypatch.setattr(jobs.li,'send_connection_invite',send)
    jobs.job_send_connections(campaign_ids=[1,2],account_ids=[1])
    assert send.call_count==2
    jobs.job_send_connections(campaign_ids=[1,2],account_ids=[1])
    assert send.call_count==2
    with SessionLocal() as db:
        assert weekly_invite_status(db,db.get(Account,1))['used']==3
        assert db.query(Lead).filter_by(status='INVITE_SENT').count()==2
        db.query(Lead).delete();db.delete(db.get(Campaign,1));db.delete(db.get(Campaign,2));db.commit()
    with SessionLocal() as db:
        assert weekly_invite_status(db,db.get(Account,1))['used']==3


def test_zero_invites_still_allows_inmail(audit,monkeypatch):
    with SessionLocal() as db:
        db.get(Account,1).weekly_invite_cap=0
        lead(db);lead(db,open_link=True);db.commit()
    invite=Mock();inmail=Mock(return_value=(True,None,''))
    monkeypatch.setattr(jobs.li,'send_connection_invite',invite)
    monkeypatch.setattr(jobs.li,'send_inmail',inmail)
    jobs.job_send_connections(campaign_ids=[1],account_ids=[1])
    invite.assert_not_called();assert inmail.call_count==1
    with SessionLocal() as db:assert weekly_invite_status(db,db.get(Account,1))['used']==0


def test_failures_and_dry_runs_do_not_consume_weekly_limit(audit,monkeypatch):
    with SessionLocal() as db:
        lead(db);db.commit()
    invite=Mock(return_value=(False,'email_required','Email required'))
    monkeypatch.setattr(jobs.li,'send_connection_invite',invite)
    jobs.job_send_connections(campaign_ids=[1],account_ids=[1],dry_run=True)
    invite.assert_not_called()
    jobs.job_send_connections(campaign_ids=[1],account_ids=[1])
    assert invite.call_count==1
    with SessionLocal() as db:assert db.query(AccountInviteSend).count()==0


def test_cap_rechecked_during_run(audit,monkeypatch):
    with SessionLocal() as db:
        db.get(Account,1).weekly_invite_cap=2
        lead(db);lead(db);db.commit()
    def send(*args,**kwargs):
        with SessionLocal() as db:
            db.get(Account,1).weekly_invite_cap=0;db.commit()
        return True,None,''
    invite=Mock(side_effect=send);monkeypatch.setattr(jobs.li,'send_connection_invite',invite)
    jobs.job_send_connections(campaign_ids=[1],account_ids=[1])
    assert invite.call_count==1


def test_history_backfill_is_idempotent_and_does_not_double_count(audit):
    now=datetime.utcnow();yesterday=now-timedelta(days=1)
    with SessionLocal() as db:
        row=lead(db);row.associate_account_id=1
        db.add(LeadEvent(lead_id=row.id,kind='outbound',job_type='send_connections',
                         detail='Connection invite sent by Audit account',created_at=yesterday))
        db.add(DailySendCount(campaign_id=1,account_id=1,date=yesterday.date(),invite_sent_count=4))
        db.commit()
        backfill_weekly_invites(db,now);backfill_weekly_invites(db,now)
        assert weekly_invite_status(db,db.get(Account,1),now)['used']==4
        assert db.query(AccountInviteSend).count()==2
        assert db.query(Lead).count()==1


def test_existing_database_upgrade_preserves_sends_and_sets_default(tmp_path,monkeypatch):
    from sqlalchemy import create_engine,text,select
    from sqlalchemy.orm import sessionmaker
    from app import database
    from app.models import Base
    bind=create_engine('sqlite:///'+str(tmp_path/'old.db'))
    Base.metadata.create_all(bind)
    factory=sessionmaker(bind=bind,expire_on_commit=False)
    with factory() as db:
        db.add(Account(id=1,name='Existing'))
        db.add(Campaign(id=1,name='Existing',campaign_key='existing'));db.flush()
        db.add(DailySendCount(account_id=1,campaign_id=1,date=datetime.utcnow().date(),invite_sent_count=23))
        db.commit()
    with bind.begin() as conn:
        conn.execute(text('DROP TABLE account_invite_sends'))
        conn.execute(text('ALTER TABLE accounts DROP COLUMN weekly_invite_cap'))
    monkeypatch.setattr(database,'engine',bind)
    monkeypatch.setattr(database,'SessionLocal',factory)
    try:
        database.init_db();database.init_db()
        with factory() as db:
            account=db.get(Account,1)
            assert account.name=='Existing' and account.weekly_invite_cap==100
            assert weekly_invite_status(db,account)['used']==23
            assert db.query(DailySendCount).one().invite_sent_count==23
    finally:
        bind.dispose()


def test_dry_run_shares_weekly_allowance_across_campaigns(audit):
    with SessionLocal() as db:
        db.get(Account,1).weekly_invite_cap=1
        db.add(Campaign(id=2,name='Second',campaign_key='second'));db.flush()
        db.add(CampaignAccount(campaign_id=2,account_id=1,invite_limit=10))
        lead(db,1);lead(db,2);db.commit()
    jobs.job_send_connections(campaign_ids=[1,2],account_ids=[1],dry_run=True)
    with SessionLocal() as db:
        assert db.query(AccountInviteSend).count()==0
        assert db.query(RunLog).one().log_text.count('DRY RUN: invitation skipped')==1
