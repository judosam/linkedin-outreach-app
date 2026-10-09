"""Campaign grants cannot be bypassed through shared LinkedIn accounts."""
from unittest.mock import patch

import pytest
from app import runner
from app.database import SessionLocal
from app.models import Account, Campaign, CampaignAccount, Lead, LeadEvent, ReplyComment, User
from tests.test_audit_fixes import audit, _login_restricted


@pytest.fixture
def privacy(audit):
    with SessionLocal() as db:
        db.add(Campaign(id=2,name='Other campaign',campaign_key='other'))
        db.add(Account(id=2,name='Other account'))
        db.flush()
        db.add(CampaignAccount(campaign_id=2,account_id=1))
        leads=[
            Lead(id=1,campaign_id=1,associate_account_id=1,full_name='Own assigned'),
            Lead(id=2,campaign_id=1,full_name='Own untouched'),
            Lead(id=3,campaign_id=2,associate_account_id=1,full_name='Private shared account'),
            Lead(id=4,campaign_id=2,full_name='Private untouched'),
            Lead(id=5,associate_account_id=1,full_name='Own pool'),
            Lead(id=6,associate_account_id=2,full_name='Private pool'),
            Lead(id=7,full_name='Unowned pool'),
        ]
        for lead in leads:
            lead.sales_nav_id=f'ACw{lead.id}'
            lead.received_replies=True
            lead.reply_message=lead.full_name
            lead.status='BLOCKED_ERROR'
        db.add_all(leads);db.flush()
        db.add(ReplyComment(id=1,lead_id=3,author='Other',body='Private note'))
        db.add(LeadEvent(lead_id=3,kind='outbound',detail='Private event'))
        db.commit()
    _login_restricted(audit,'prabhu',[1],[1])
    return audit


def test_shared_account_never_exposes_another_campaign(privacy):
    for route in ('/api/leads','/api/threads'):
        result=privacy.get(route).json()
        assert {item['id'] for item in result['items']}=={1,2,5}
        assert result['total']==3
        assert privacy.get(route+'?campaign_ids=2').json()['total']==0
    for query in ('?campaign_id=2','?account_id=1&campaign_id=2','?q=Private'):
        assert privacy.get('/api/leads'+query).json()['total']==0
    assert privacy.get('/api/leads?ids_only=true').json()['ids']==[1,2,5]
    csv=privacy.get('/api/leads/export').text
    assert 'Own assigned' in csv and 'Own untouched' in csv and 'Own pool' in csv
    assert 'Private' not in csv and 'Unowned pool' not in csv
    assert privacy.get('/api/dashboard/summary').json()['totals']['leads_total']==3
    assert [c['id'] for c in privacy.get('/api/campaigns').json()]==[1]
    assert privacy.get('/api/campaigns/2').status_code==403
    assert privacy.put('/api/campaigns/2/pause',json={'status':'paused'}).status_code==403
    assert privacy.put('/api/campaigns/2',json={'name':'Changed','accounts':[{'account_id':1}]}).status_code==403
    assert privacy.delete('/api/campaigns/2').status_code==403
    assert privacy.post('/api/campaigns/2/copy',json={'name':'Stolen'}).status_code==403


def test_direct_urls_and_mutations_cannot_bypass_campaign_scope(privacy):
    for path in ('timeline','comments'):
        assert privacy.get(f'/api/leads/3/{path}').status_code==404
    assert privacy.put('/api/leads/3/category',json={'category':'interested'}).status_code==404
    assert privacy.post('/api/leads/3/review',json={'review_status':'reviewed'}).status_code==404
    assert privacy.post('/api/leads/3/comments',json={'body':'Changed'}).status_code==404
    assert privacy.put('/api/leads/3/assign',json={'campaign_id':1}).status_code==404
    assert privacy.put('/api/leads/1/assign',json={'campaign_id':2}).status_code==403
    assert privacy.put('/api/comments/1',json={'body':'Changed'}).status_code==404
    assert privacy.delete('/api/comments/1').status_code==404
    with patch.object(runner,'start_job') as start:
        assert privacy.post('/api/jobs/check_replies/run',json={
            'campaign_ids':[2],'account_ids':[1],'dry_run':True}).status_code==403
        start.assert_not_called()
    with SessionLocal() as db:
        assert db.get(Lead,3).campaign_id==2
        assert db.get(ReplyComment,1).body=='Private note'


def test_bulk_operations_only_affect_accessible_leads(privacy):
    ids={'ids':[1,3,4,5,6,7]}
    assert privacy.post('/api/leads/count',json=ids).json()['existing']==2
    preview=privacy.post('/api/leads/delete-preview',json=ids).json()
    assert preview['existing']==2
    assert 'Other campaign' not in str(preview)
    assert preview['comments_to_remove']==0 and preview['events_to_remove']==0
    assert privacy.post('/api/leads/reset-errors',json=ids).json()['reset']==2
    assert privacy.post('/api/leads/bulk-delete-v2',json=ids).json()['deleted']==2
    with SessionLocal() as db:
        assert {l.id for l in db.query(Lead)}=={2,3,4,6,7}
        assert db.get(Lead,3).status=='BLOCKED_ERROR'


def test_empty_grants_never_mean_all(privacy):
    with SessionLocal() as db:
        user=db.query(User).filter_by(username='prabhu').one()
        user.allowed_campaign_ids=[];user.allowed_account_ids=[];db.commit()
    assert privacy.get('/api/campaigns').json()==[]
    assert privacy.get('/api/accounts').json()==[]
    assert privacy.get('/api/leads').json()['total']==0
    assert privacy.get('/api/threads').json()['total']==0
    assert privacy.get('/api/leads/1/timeline').status_code==404
    assert privacy.get('/api/campaigns/1').status_code==403
    assert privacy.post('/api/jobs/check_replies/run',json={
        'campaign_ids':[1],'account_ids':[1],'dry_run':True}).status_code==403


def test_admin_still_sees_all(privacy):
    assert privacy.post('/api/login',json={'username':'test-admin','password':'test-password-only'}).status_code==200
    assert privacy.get('/api/leads').json()['total']==7
    assert privacy.get('/api/leads/3/timeline').status_code==200
    assert len(privacy.get('/api/campaigns').json())==2



def test_csv_cannot_modify_duplicate_in_other_campaign(privacy):
    response=privacy.post('/api/leads/import-csv?campaign_id=1',files={
        'file':('leads.csv',b'full_name,sales_nav_id,location\nPrivate shared account,ACw3,Changed\n','text/csv')})
    assert response.status_code==200
    with SessionLocal() as db:
        assert db.get(Lead,3).location!='Changed'


def test_shared_account_mapping_cannot_expose_or_change_other_campaigns(privacy):
    account=privacy.get('/api/accounts').json()[0]
    assert account['campaign_ids']==[1]
    assert account['campaigns']==['audit']
    assert privacy.delete('/api/accounts/1').status_code==403
    assert privacy.put('/api/accounts/1',json={
        'name':'Audit account','campaign_ids':[2]}).status_code==403
    assert privacy.put('/api/accounts/1',json={
        'name':'Audit account','campaign_ids':[1]}).status_code==200
    with SessionLocal() as db:
        assert {r.campaign_id for r in db.query(CampaignAccount).filter_by(account_id=1)}=={1,2}


def test_creator_with_empty_grants_keeps_access_to_new_resources(privacy):
    with SessionLocal() as db:
        user=db.query(User).filter_by(username='prabhu').one()
        user.allowed_campaign_ids=[];user.allowed_account_ids=[];db.commit()
    created=privacy.post('/api/accounts',json={'name':'New own account'})
    assert created.status_code==200
    aid=created.json()['id']
    created=privacy.post('/api/campaigns',json={'name':'New own campaign','accounts':[{'account_id':aid}]})
    assert created.status_code==200
    cid=created.json()['id']
    assert [a['id'] for a in privacy.get('/api/accounts').json()]==[aid]
    assert [c['id'] for c in privacy.get('/api/campaigns').json()]==[cid]
