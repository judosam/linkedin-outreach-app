"""Offline imports deduplicate within the destination campaign only."""
from unittest.mock import Mock
import pytest
from app import jobs
from app.database import SessionLocal
from app.models import Campaign, Lead, RunLog
from tests.test_audit_fixes import audit


@pytest.mark.parametrize('method',['csv','sync_leads','import_list'])
@pytest.mark.parametrize('destination',[1,2,None])
def test_import_identity_is_sales_nav_id_and_campaign(audit,monkeypatch,method,destination):
    with SessionLocal() as db:
        db.add(Campaign(id=2,name='Other',campaign_key='other'));db.flush()
        db.add(Lead(sales_nav_id='ACwSAME',campaign_id=1,associate_account_id=1,
                    status='INVITE_SENT',location='Original',reply_message='Keep history'))
        db.commit()
    elements=[{'entityUrn':'urn:li:fs_salesProfile:(ACwSAME,NAME_SEARCH,offline)',
               'fullName':'Same person','geoRegion':'Updated'}]*2
    monkeypatch.setattr(jobs.li,'search_leads',Mock(return_value=elements))
    monkeypatch.setattr(jobs.li,'people_search_by_list',Mock(return_value=elements))
    for _ in range(2):
        if method=='csv':
            query=f'?campaign_id={destination}' if destination is not None else ''
            csv='full_name,sales_nav_id,location\nSame person,"urn:li:fs_salesProfile:(ACwSAME,NAME_SEARCH,offline)",Updated\nSame person,ACwSAME,Updated\n'
            response=audit.post('/api/leads/import-csv'+query,files={'file':('a.csv',csv,'text/csv')})
            assert response.status_code==200,response.text
        elif method=='sync_leads':
            jobs.job_sync_leads(account_id=1,saved_search_id='123',campaign_id=destination)
        else:
            jobs.job_import_list(account_id=1,list_id='123',campaign_id=destination)
    with SessionLocal() as db:
        rows=db.query(Lead).filter_by(sales_nav_id='ACwSAME').all()
        assert len(rows)==(1 if destination==1 else 2)
        original=next(l for l in rows if l.campaign_id==1)
        assert original.status=='INVITE_SENT' and original.associate_account_id==1
        assert original.reply_message=='Keep history'
        if destination!=1:
            assert original.location=='Original'
            imported=next(l for l in rows if l.campaign_id==destination)
            assert imported.status=='' and imported.associate_account_id is None
        assert all(r.status=='success' for r in db.query(RunLog))


def test_csv_url_fallback_never_merges_distinct_ids_or_campaigns(audit):
    with SessionLocal() as db:
        db.add(Campaign(id=2,name='Other',campaign_key='other'));db.flush()
        db.add(Lead(sales_nav_id='ACwFIRST',campaign_id=1,linkedin_url='https://example.com/person'))
        db.commit()
    for cid,snid in [(1,'ACwSECOND'),(2,'ACwFIRST')]:
        csv=f'full_name,sales_nav_id,linkedin_url\nPerson,{snid},https://example.com/person\n'
        response=audit.post(f'/api/leads/import-csv?campaign_id={cid}',files={'file':('a.csv',csv,'text/csv')})
        assert response.json()['added']==1
        response=audit.post(f'/api/leads/import-csv?campaign_id={cid}',files={'file':('a.csv',csv,'text/csv')})
        assert response.json()['skipped']==1
    with SessionLocal() as db:assert db.query(Lead).count()==3


def test_retagging_cannot_create_duplicate_in_campaign(audit):
    with SessionLocal() as db:
        leads=[Lead(sales_nav_id='ACwSAME',campaign_id=cid,status='INVITE_SENT') for cid in (1,None)]
        db.add_all(leads);db.commit();lid=leads[1].id
    response=audit.put(f'/api/leads/{lid}/assign',json={'campaign_id':1})
    assert response.status_code==409
    with SessionLocal() as db:
        assert db.get(Lead,lid).campaign_id is None
        assert db.query(Lead).count()==2
        assert all(l.status=='INVITE_SENT' for l in db.query(Lead))
