"""Imported leads keep their selected sender through campaign execution."""
from unittest.mock import Mock, patch

import pytest
from app import jobs, runner
from app.database import SessionLocal
from app.models import Account, Campaign, CampaignAccount, Lead, RunLog
from tests.test_audit_fixes import audit


@pytest.fixture
def assigned(audit,monkeypatch):
    with SessionLocal() as db:
        db.add(Account(id=2,name='Selected import account',session_ref='offline'))
        db.add(Campaign(id=2,name='Other campaign',campaign_key='other'))
        db.flush()
        db.add_all([CampaignAccount(campaign_id=1,account_id=2,order_index=1,invite_limit=10),
                    CampaignAccount(campaign_id=2,account_id=1)])
        db.commit()
    result=[{'entityUrn':'urn:li:fs_salesProfile:(ACwASSIGNED,NAME_SEARCH,offline)', 'fullName':'Assigned lead','geoRegion':'Chennai'}]
    monkeypatch.setattr(jobs.li,'search_leads',Mock(return_value=result))
    monkeypatch.setattr(jobs.li,'people_search_by_list',Mock(return_value=result))
    return audit


def import_lead(key,account_id=1,**kwargs):
    if key=='sync_leads':jobs.job_sync_leads(account_id=account_id,saved_search_id='123',**kwargs)
    else:jobs.job_import_list(account_id=account_id,list_id='123',**kwargs)


@pytest.mark.parametrize('key',['sync_leads','import_list'])
@pytest.mark.parametrize('pinned',[True,False])
def test_import_assignment_controls_campaign_sender(assigned,monkeypatch,key,pinned):
    import_lead(key,campaign_id=1,outreach_account_id=2 if pinned else None)
    with SessionLocal() as db:
        lead=db.query(Lead).one()
        assert lead.associate_account_id == (2 if pinned else None)
        lead.opentomsg=False;lead.linkedin_url='https://offline.invalid/profile';db.commit()
    fetch = jobs.li.search_leads if key=='sync_leads' else jobs.li.people_search_by_list
    assert fetch.call_args.args[0]._account_id == 1
    with SessionLocal() as db:
        assert db.query(RunLog).one().account_id == 1
    sent=[]
    monkeypatch.setattr(jobs.li,'send_connection_invite',lambda session,*args,**kw: (sent.append(session._account_id) or True,None,''))
    jobs.job_send_connections(campaign_ids=[1],account_ids=[1,2])
    assert sent==[2 if pinned else 1]
    with SessionLocal() as db:
        lead=db.query(Lead).one()
        assert lead.status=='INVITE_SENT' and lead.associate_account_id==sent[0]


@pytest.mark.parametrize('condition',['budget','paused','unmapped','scope'])
def test_assigned_lead_never_rolls_to_another_account(assigned,monkeypatch,condition):
    import_lead('sync_leads',campaign_id=1,outreach_account_id=2)
    with SessionLocal() as db:
        lead=db.query(Lead).one();lead.opentomsg=False;lead.linkedin_url='https://offline.invalid/profile'
        link=db.query(CampaignAccount).filter_by(campaign_id=1,account_id=2).one()
        if condition=='budget':link.invite_limit=0;link.inmail_limit=0
        elif condition=='paused':db.get(Account,2).status='paused'
        elif condition=='unmapped':db.delete(link)
        db.commit()
    send=Mock(return_value=(True,None,''));monkeypatch.setattr(jobs.li,'send_connection_invite',send)
    jobs.job_send_connections(campaign_ids=[1],account_ids=[1] if condition=='scope' else [1,2])
    send.assert_not_called()
    with SessionLocal() as db:
        lead=db.query(Lead).one()
        assert lead.associate_account_id==2 and lead.status==''


@pytest.mark.parametrize('key',['sync_leads','import_list'])
def test_existing_assignment_survives_reimport_and_pool_tagging(assigned,key):
    with SessionLocal() as db:
        db.add(Lead(sales_nav_id='ACwASSIGNED',campaign_id=1,associate_account_id=1,status='INVITE_SENT'))
        db.commit()
    import_lead(key,campaign_id=1,outreach_account_id=2)
    with SessionLocal() as db:
        lead=db.query(Lead).one()
        assert lead.associate_account_id==1 and lead.status=='INVITE_SENT'
        db.delete(lead);db.commit()
    import_lead(key,outreach_account_id=2)
    with SessionLocal() as db:
        lead=db.query(Lead).one();lid=lead.id
        assert lead.campaign_id is None and lead.associate_account_id==2
    assert assigned.put(f'/api/leads/{lid}/assign',json={'campaign_id':2}).status_code==422
    assert assigned.put(f'/api/leads/{lid}/assign',json={'campaign_id':1}).status_code==200
    with SessionLocal() as db:
        lead=db.get(Lead,lid)
        assert lead.campaign_id==1 and lead.associate_account_id==2


@pytest.mark.parametrize('key,id_key',[('sync_leads','saved_search_id'),('import_list','list_id')])
def test_import_api_rejects_unmapped_account_and_passes_choice(assigned,key,id_key):
    with patch.object(runner,'start_job',return_value=(True,'Started','fixture')) as start:
        body={'account_id':1,id_key:'123','campaign_id':2,'dry_run':True}
        # Account is required for importing, but outreach assignment is opt-in.
        assert assigned.post(f'/api/jobs/{key}/run',json=body).status_code==200
        assert start.call_args.kwargs['outreach_account_id'] is None
        start.reset_mock()
        body['outreach_account_id']=2
        assert assigned.post(f'/api/jobs/{key}/run',json=body).status_code==422
        start.assert_not_called()
        body['campaign_id']=1
        assert assigned.post(f'/api/jobs/{key}/run',json=body).status_code==200
        assert start.call_args.kwargs['outreach_account_id'] == 2
        body.update(campaign_id=2,outreach_account_id=None)
        assert assigned.post(f'/api/jobs/{key}/run',json=body).status_code==200
        assert start.call_args.kwargs['outreach_account_id'] is None
        del body['account_id']
        assert assigned.post(f'/api/jobs/{key}/run',json=body).status_code==422



@pytest.mark.parametrize('key',['sync_leads','import_list'])
def test_import_assignment_dry_run_does_not_create_leads(assigned,key):
    import_lead(key,campaign_id=1,dry_run=True)
    with SessionLocal() as db:
        assert db.query(Lead).count()==0
        assert db.query(RunLog).one().status=='success'


@pytest.mark.parametrize('key',['sync_leads','import_list'])
def test_import_account_does_not_assign_outreach_by_default(assigned,key):
    import_lead(key,campaign_id=2)
    with SessionLocal() as db:
        lead=db.query(Lead).one()
        assert lead.campaign_id==2 and lead.associate_account_id is None
        assert db.query(RunLog).one().status=='success'


@pytest.mark.parametrize('key,id_key',[('sync_leads','saved_search_id'),('import_list','list_id')])
@pytest.mark.parametrize('invalid',['missing','paused','out_of_scope'])
def test_invalid_outreach_account_rejected_before_start(assigned,key,id_key,invalid):
    outreach_id=2
    if invalid=='missing':
        outreach_id=999
    elif invalid=='paused':
        with SessionLocal() as db:
            db.get(Account,2).status='paused';db.commit()
    else:
        from tests.test_audit_fixes import _login_restricted
        _login_restricted(assigned,'import-only',[1],[1])
    with patch.object(runner,'start_job') as start:
        response=assigned.post(f'/api/jobs/{key}/run',json={
            'account_id':1,id_key:'123','outreach_account_id':outreach_id,'dry_run':True})
        assert response.status_code==(403 if invalid=='out_of_scope' else 422)
        start.assert_not_called()


@pytest.mark.parametrize('key,id_key',[('sync_leads','saved_search_id'),('import_list','list_id')])
def test_campaign_mapping_uses_outreach_account_not_import_account(assigned,key,id_key):
    # Campaign 2 maps account 1 only; account 2 may still fetch the leads.
    with patch.object(runner,'start_job',return_value=(True,'Started','fixture')) as start:
        response=assigned.post(f'/api/jobs/{key}/run',json={
            'account_id':2,id_key:'123','campaign_id':2,'outreach_account_id':1,'dry_run':True})
        assert response.status_code==200,response.text
        assert start.call_args.kwargs['account_id']==2
        assert start.call_args.kwargs['outreach_account_id']==1
    import_lead(key,account_id=2,campaign_id=2,outreach_account_id=1)
    with SessionLocal() as db:
        assert db.query(Lead).one().associate_account_id==1
