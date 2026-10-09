"""Campaign/account mapping and hidden-field preservation regressions."""
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine
from app.models import Base, Account, Campaign, CampaignAccount, RunLog
from app import jobs, runner


@pytest.fixture
def mapping():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with SessionLocal() as db:
        a=Account(name='Shared account'); b=Account(name='Other account')
        c=Campaign(name='First',campaign_key='first',search_url='https://www.linkedin.com/sales/search/people?savedSearchId=12')
        d=Campaign(name='Second',campaign_key='second')
        paused=Campaign(name='Paused',campaign_key='paused',status='paused')
        db.add_all([a,b,c,d,paused]);db.flush()
        db.add_all([CampaignAccount(campaign_id=c.id,account_id=a.id),
                    CampaignAccount(campaign_id=d.id,account_id=a.id),
                    CampaignAccount(campaign_id=d.id,account_id=b.id),
                    CampaignAccount(campaign_id=paused.id,account_id=b.id)])
        db.commit()
        ids=dict(a=a.id,b=b.id,c=c.id,d=d.id)
    with TestClient(app) as client, patch.object(jobs.notify,'notify_run_summary'):
        client.post('/api/login',json={'username':'test-admin','password':'test-password-only'})
        yield client,ids


def test_unmapped_scope_rejected_and_shared_account_allowed(mapping):
    client,i=mapping
    with patch.object(runner,'start_job',return_value=(True,'Started',None)) as start:
        response=client.post('/api/jobs/check_replies/run',json={'campaign_ids':[i['c']],'account_ids':[i['b']],'dry_run':True})
        assert response.status_code==422 and 'not mapped' in response.text
        start.assert_not_called()
        response=client.post('/api/jobs/check_replies/run',json={'campaign_ids':[i['c'],i['d']],'account_ids':[i['a']],'dry_run':True})
        assert response.status_code==200
        assert start.call_args.kwargs['account_ids']==[i['a']]


def test_campaign_edit_keeps_hidden_url_and_rejects_bad_links(mapping):
    client,i=mapping
    payload=dict(name='Renamed',accounts=[dict(account_id=i['a'])])
    assert client.put(f"/api/campaigns/{i['c']}",json=payload).status_code==200
    assert 'savedSearchId=12' in client.get(f"/api/campaigns/{i['c']}").json()['search_url']
    payload['accounts'].append(dict(account_id=i['a']))
    assert client.put(f"/api/campaigns/{i['c']}",json=payload).status_code==422
    payload['accounts']=[dict(account_id=9999)]
    assert client.put(f"/api/campaigns/{i['c']}",json=payload).status_code==422
    assert client.get(f"/api/campaigns/{i['c']}").json()['accounts'][0]['account_id']==i['a']


@pytest.mark.parametrize('worker',[jobs.job_check_replies,jobs.job_send_followups,jobs.job_send_connections])
def test_empty_explicit_scope_never_expands_and_paused_campaigns_stay_out(mapping,worker):
    _,i=mapping
    worker(campaign_ids=[],dry_run=True)
    with SessionLocal() as db:
        row=db.query(RunLog).order_by(RunLog.id.desc()).first()
        assert not row.stats
    worker(account_ids=[i['a']],dry_run=True)
    with SessionLocal() as db:
        row=db.query(RunLog).order_by(RunLog.id.desc()).first()
        assert 'Other account' not in (row.log_text or '')
        assert 'paused' not in str(row.stats).lower()

    worker(dry_run=True)
    with SessionLocal() as db:
        row=db.query(RunLog).order_by(RunLog.id.desc()).first()
        assert 'paused' not in str(row.stats).lower()
        assert '[paused/' not in (row.log_text or '').lower()


@pytest.mark.parametrize('key',['send_connections','check_replies','send_followups'])
@pytest.mark.parametrize('all_campaigns',[False,True])
@pytest.mark.parametrize('dry_run',[False,True])
def test_all_mapped_ignores_other_granted_accounts(mapping,key,all_campaigns,dry_run):
    client,i=mapping
    from app.models import User
    from app.auth import create_session
    with SessionLocal() as db:
        user=User(username='mapped-manager',password_hash='offline',role='campaign_manager',
                  allowed_campaign_ids=[i['c']],allowed_account_ids=[i['a'],i['b']])
        db.add(user);db.commit();uid=user.id
    client.cookies.set('occ_session',create_session(uid))
    body={'dry_run':dry_run}
    if not all_campaigns:body['campaign_ids']=[i['c']]
    with patch.object(runner,'start_job',return_value=(True,'Started','fixture')) as start, patch.object(jobs,'load_session_ref') as session:
        response=client.post(f'/api/jobs/{key}/run',json=body)
        assert response.status_code==200,response.text
        assert start.call_args.kwargs['account_ids']==[i['a']]
        assert start.call_args.kwargs['campaign_ids']==[i['c']]
        if dry_run:
            session.assert_not_called()
        else:
            assert [call.args[0].id for call in session.call_args_list]==[i['a']]
        # An explicit invalid selection is still rejected, never silently dropped.
        body.update(campaign_ids=[i['c']],account_ids=[i['b']])
        start.reset_mock()
        assert client.post(f'/api/jobs/{key}/run',json=body).status_code==422
        start.assert_not_called()


@pytest.mark.parametrize('grants,active',[(False,True),(True,False)])
def test_all_mapped_cannot_expand_empty_or_inactive_account_scope(mapping,grants,active):
    client,i=mapping
    from app.models import User
    from app.auth import create_session
    with SessionLocal() as db:
        db.get(Account,i['a']).status='active' if active else 'paused'
        user=User(username='no-mapped',password_hash='offline',role='campaign_manager',
                  allowed_campaign_ids=[i['c']],allowed_account_ids=[i['b']]+([i['a']] if grants else []))
        db.add(user);db.commit();uid=user.id
    client.cookies.set('occ_session',create_session(uid))
    with patch.object(runner,'start_job') as start:
        response=client.post('/api/jobs/send_connections/run',json={'campaign_ids':[i['c']],'dry_run':True})
        assert response.status_code==422
        assert 'No active mapped accounts' in response.text
        start.assert_not_called()


def test_batch_all_mapped_uses_selected_campaigns(mapping):
    client,i=mapping
    from app.models import User
    from app.auth import create_session
    with SessionLocal() as db:
        user=User(username='batch-mapped',password_hash='offline',role='campaign_manager',
                  allowed_campaign_ids=[i['c']],allowed_account_ids=[i['a'],i['b']])
        db.add(user);db.commit();uid=user.id
    client.cookies.set('occ_session',create_session(uid))
    with patch.object(runner,'start_sequence',return_value=(True,'Started','fixture')) as start:
        response=client.post('/api/jobs/batch',json={
            'campaign_ids':[i['c']],'connections':True,'followups':True,'dry_run':True})
        assert response.status_code==200,response.text
        steps=start.call_args.args[0]
        assert len(steps)==2
        assert all(scope['account_ids']==[i['a']] and scope['campaign_ids']==[i['c']] for _,scope in steps)
