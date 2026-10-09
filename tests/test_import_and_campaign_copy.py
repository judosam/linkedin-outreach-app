"""Offline import regressions for historical duplicates and campaign cloning."""
from datetime import date, datetime
from unittest.mock import Mock

import pytest
from app import jobs
from app.auth import create_session
from app.database import SessionLocal
from app.models import Account, Campaign, CampaignAccount, DailySendCount, Lead, LeadEvent, RunLog, Schedule, User
from tests.test_audit_fixes import audit


@pytest.mark.parametrize('job_key',['sync_leads','import_list','import_list_tagged'])
def test_import_refreshes_location_with_multiple_existing_campaign_and_pool_rows(audit,monkeypatch,job_key):
    with SessionLocal() as db:
        db.add(Campaign(id=2,name='Historical campaign',campaign_key='history'));db.flush()
        original=[]
        for i,cid in enumerate([1,2,None,None]):
            lead=Lead(sales_nav_id='ACwEXISTING',campaign_id=cid,associate_account_id=1,
                      full_name='Existing person',location='Old location',status='INMAIL_SENT',
                      received_replies=i==1,reply_message='History stays' if i==1 else None,
                      first_contacted_at=datetime(2026,1,1))
            db.add(lead);db.flush()
            db.add(LeadEvent(lead_id=lead.id,kind='outbound',detail='Historical message'))
            original.append((lead.id,cid,lead.received_replies,lead.reply_message))
        db.commit()
    result=[{'entityUrn':'urn:li:fs_salesProfile:(ACwEXISTING,NAME_SEARCH,offline)',
             'fullName':'Existing person','geoRegion':'Bengaluru'},
            {'entityUrn':'urn:li:fs_salesProfile:(ACwNEW,NAME_SEARCH,offline)',
             'fullName':'New person','geoRegion':'Chennai'}]
    monkeypatch.setattr(jobs.li,'search_leads',Mock(return_value=result))
    monkeypatch.setattr(jobs.li,'people_search_by_list',Mock(return_value=result))
    if job_key=='sync_leads':
        jobs.job_sync_leads(account_id=1,saved_search_id='123')
    else:
        jobs.job_import_list(account_id=1,list_id='123',campaign_id=1 if job_key=='import_list_tagged' else None)
    with SessionLocal() as db:
        assert db.query(RunLog).one().status=='success'
        assert db.query(Lead).count()==5
        for lid,cid,replied,reply in original:
            lead=db.get(Lead,lid)
            assert (lead.campaign_id,lead.associate_account_id,lead.status,lead.received_replies,lead.reply_message)==(cid,1,'INMAIL_SENT',replied,reply)
            assert lead.first_contacted_at==datetime(2026,1,1)
            refreshed = (job_key=='sync_leads' and cid is None) or (job_key=='import_list_tagged' and cid==1)
            assert lead.location==('Bengaluru' if refreshed else 'Old location')
        assert db.query(LeadEvent).count()==4
        assert db.query(Lead).filter_by(sales_nav_id='ACwNEW').one().location=='Chennai'
        # The older pool helper also treats duplicates as existing, not fatal.
        assert jobs._upsert_lead_untagged(db,{'sales_nav_id':'ACwEXISTING'}) is False
    csv='full_name,sales_nav_id,location\nExisting person,ACwEXISTING,Bengaluru\n'
    response=audit.post('/api/leads/import-csv',files={'file':('existing.csv',csv,'text/csv')})
    assert response.status_code==200,response.text
    with SessionLocal() as db: assert db.query(Lead).count()==5


def test_copy_campaign_clones_settings_only_and_preserves_source(audit):
    with SessionLocal() as db:
        source=db.get(Campaign,1)
        source.search_url='https://www.linkedin.com/sales/search/people?savedSearchId=12'
        source.invite_track=['After {first_name}','First','Second','Third']
        source.inmail_subject='Subject'
        source.inmail_text='Message {first_name}'
        source.inmail_track=[{'subject':'Follow','body':'Hi {first_name}'}]
        a=Account(name='Second account');db.add(a);db.flush()
        first=db.query(CampaignAccount).one()
        first.order_index=3;first.message_limit=45;first.calendar_url='https://example.com/calendar'
        db.add(CampaignAccount(campaign_id=1,account_id=a.id,order_index=7,invite_limit=4,inmail_limit=2,message_limit=11,
                               search_url_override=source.search_url))
        db.add(Lead(sales_nav_id='ACwORIGINAL',campaign_id=1))
        db.add(DailySendCount(campaign_id=1,account_id=1,date=date.today(),messages_sent=6))
        db.add(RunLog(job_type='check_replies',campaign_id=1,status='success'))
        db.add(Schedule(name='Original schedule',run_time='09:00',job_keys=['check_replies'],scopes={'check_replies':{'campaign_ids':[1]}}))
        db.commit()
    source=audit.get('/api/campaigns/1').json()
    response=audit.post('/api/campaigns/1/copy',json={'name':'Copied outreach','campaign_key':'copy-key'})
    assert response.status_code==200,response.text
    cid=response.json()['id']
    copy=audit.get(f'/api/campaigns/{cid}').json()
    assert copy['status']=='paused' and copy['campaign_key']=='copy-key'
    for field in ['search_url','invite_text','invite_track','inmail_subject','inmail_text','inmail_track','accounts']:
        assert copy[field]==source[field],field
    assert audit.get('/api/campaigns/1').json()==source
    with SessionLocal() as db:
        assert db.query(Lead).filter_by(campaign_id=cid).count()==0
        assert db.query(DailySendCount).filter_by(campaign_id=cid).count()==0
        assert db.query(RunLog).filter_by(campaign_id=cid).count()==0
        assert db.query(Schedule).count()==1
    # Copy edits never modify the original's templates or mappings.
    copy['invite_track'][0]='Edited copy';copy['accounts'][0]['message_limit']=9
    assert audit.put(f'/api/campaigns/{cid}',json=copy).status_code==200
    assert audit.get('/api/campaigns/1').json()==source
    assert audit.post('/api/campaigns/1/copy',json={'name':'Again','campaign_key':'copy-key'}).status_code==409
    assert audit.post('/api/campaigns/1/copy',json={'name':'   '}).status_code==422
    assert audit.post('/api/campaigns/999999/copy',json={'name':'Missing'}).status_code==404
    with SessionLocal() as db: assert db.query(Campaign).count()==2


def test_copy_permissions_and_creator_access(audit):
    with SessionLocal() as db:
        db.add(Campaign(id=2,name='Other',campaign_key='other'))
        user=User(username='copy-manager',password_hash='offline',role='campaign_manager',active=True,
                  allowed_campaign_ids=[1],allowed_account_ids=[1])
        db.add(user);db.commit();uid=user.id
    audit.cookies.set('occ_session',create_session(uid))
    assert audit.post('/api/campaigns/2/copy',json={'name':'Forbidden'}).status_code==403
    response=audit.post('/api/campaigns/1/copy',json={'name':'My copy'})
    assert response.status_code==200
    cid=response.json()['id']
    assert audit.get(f'/api/campaigns/{cid}').status_code==200
    assert {r['id'] for r in audit.get('/api/campaigns').json()}=={1,cid}
    with SessionLocal() as db:
        db.get(User,uid).allowed_campaign_ids=[];db.commit()
    assert audit.post('/api/campaigns/1/copy',json={'name':'No grant copy'}).status_code==403
    with SessionLocal() as db: assert db.get(User,uid).allowed_campaign_ids==[]
    audit.cookies.clear()
    assert audit.post('/api/campaigns/1/copy',json={'name':'Anonymous'}).status_code==401
