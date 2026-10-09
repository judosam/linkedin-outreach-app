"""Full follow-up allowance with shared daily/account caps; all sends mocked."""
from datetime import date, datetime, timedelta
from unittest.mock import Mock

import pytest

from app import jobs
from app.database import SessionLocal
from app.models import Account, Campaign, CampaignAccount, DailySendCount, Lead, LeadEvent
from tests.test_audit_fixes import audit


@pytest.mark.parametrize('limit,account_cap,already_sent,other_sent,expected', [
    (30,60,0,0,30),
    (30,60,12,0,18),
    (31,60,0,0,31),
    (1,60,0,0,1),
    (30,5,2,0,3),
    (30,10,0,7,3),
    (30,10,3,7,0),
    (0,60,0,0,0),
    (30,0,0,0,0),
    (30,60,30,0,0),
])
def test_followups_use_full_remaining_shared_allowance(audit,monkeypatch,limit,account_cap,already_sent,other_sent,expected):
    with SessionLocal() as db:
        db.get(Account,1).daily_message_cap=account_cap
        campaign=db.get(Campaign,1)
        campaign.invite_track=['After acceptance','Follow-up 1','Follow-up 2','Follow-up 3']
        campaign.inmail_track=[{'subject':'Hello','body':'Following up'}]*3
        db.query(CampaignAccount).one().message_limit=limit
        db.add(Campaign(id=2,name='Other budget',campaign_key='other-budget'))
        db.flush()
        db.add_all([DailySendCount(campaign_id=1,account_id=1,date=date.today(),messages_sent=already_sent),
                    DailySendCount(campaign_id=2,account_id=1,date=date.today(),messages_sent=other_sent)])
        for track,status in [('invite','INVITE_AFTER_ACCEPT'),('inmail','INMAIL_SENT')]:
            for i in range(16):
                db.add(Lead(sales_nav_id=f'ACw{track}{i}',full_name=f'Offline {track} {i}',
                            campaign_id=1,associate_account_id=1,status=status,
                            status_changed_at=datetime.utcnow()-timedelta(days=10)))
        db.commit()
    message=Mock(return_value=(True,None,''));inmail=Mock(return_value=(True,None,''))
    monkeypatch.setattr(jobs.li,'send_message',message)
    monkeypatch.setattr(jobs.li,'send_inmail',inmail)
    jobs.job_send_followups(campaign_ids=[1],account_ids=[1])
    assert message.call_count + inmail.call_count == expected
    if expected > 16:
        assert message.call_count == 16 and inmail.call_count == expected-16
    with SessionLocal() as db:
        daily=db.query(DailySendCount).filter_by(campaign_id=1).one()
        assert daily.messages_sent == already_sent+expected
        assert db.query(DailySendCount).filter_by(campaign_id=2).one().messages_sent == other_sent
        assert db.query(LeadEvent).filter_by(kind='outbound').count() == expected
    # Running again cannot reuse today's exhausted shared allowance.
    jobs.job_send_followups(campaign_ids=[1],account_ids=[1])
    assert message.call_count + inmail.call_count == expected


def test_dashboard_uses_full_followup_cap_without_counting_shared_account_twice(audit):
    assert audit.get('/api/dashboard/summary').json()['today']['followups_limit'] == 30
    with SessionLocal() as db:
        db.get(Account,1).daily_message_cap=45
        db.add(Campaign(id=2,name='Second campaign',campaign_key='second-cap'))
        db.flush();db.add(CampaignAccount(campaign_id=2,account_id=1,message_limit=30));db.commit()
    assert audit.get('/api/dashboard/summary').json()['today']['followups_limit'] == 45
    with SessionLocal() as db:
        db.get(Campaign,2).status='paused';db.commit()
    assert audit.get('/api/dashboard/summary').json()['today']['followups_limit'] == 30
    with SessionLocal() as db:
        db.get(Account,1).status='paused';db.commit()
    assert audit.get('/api/dashboard/summary').json()['today']['followups_limit'] == 0
