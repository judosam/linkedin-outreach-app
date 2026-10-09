"""Unit tests for the standalone dedupe engine in merge_xlsx_history.py and
the hardened CSV import (urn snid normalization + URL-based dup matching).

Root cause being covered: app/jobs.py stored raw entityUrns as sales_nav_id,
so the same person existed twice (urn vs bare ACw) and never matched the
(sales_nav_id, campaign_id) unique key."""
import csv
import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Campaign, Lead, LeadEvent, ReplyComment  # noqa: E402
from merge_xlsx_history import run_dedupe, run_replace  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _schema():
    init_db()
    yield
    engine.dispose()


@pytest.fixture
def app_client():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with TestClient(app) as c:
        assert c.post('/api/login', json={'username': 'test-admin',
                                          'password': 'test-password-only'}).status_code == 200
        yield c


_camp_counter = iter(range(1, 1000))


def _seed(**kw):
    """Insert a lead with only the given fields populated."""
    fields = dict(sales_nav_id='', full_name='X', campaign_id=None)
    fields.update(kw)
    with SessionLocal() as db:
        # campaign_id references need a real campaign row.
        if 'campaign_id' in fields and fields['campaign_id'] is not None:
            camp = Campaign(name=f'Dedupe campaign {next(_camp_counter)}',
                            campaign_key=f'dedupe-test-{next(_camp_counter)}')
            db.add(camp)
            db.flush()
            fields['campaign_id'] = camp.id
        lead = Lead(**fields)
        db.add(lead)
        db.commit()
        return lead.id


def _get(lead_id):
    with SessionLocal() as db:
        lead = db.get(Lead, lead_id)
        if lead is None:
            return None
        db.refresh(lead)
        db.expunge(lead)
        return lead


def test_dedupe_merges_urn_and_bare_snid_twins():
    bare = _seed(sales_nav_id='ACwTEST01', full_name='Bare Row', status='INVITE_SENT',
                 title='VP Engineering')
    urn = _seed(sales_nav_id='urn:li:fs_salesProfile:(ACwTEST01,NAME_SEARCH,zz9)',
                full_name='Urn Row', campaign_id=1)
    run_dedupe(apply=True)
    assert _get(urn) is None, 'urn twin must be deleted'
    kept = _get(bare)
    assert kept is not None
    assert kept.campaign_id is not None, 'campaign assignment moves to the keeper'
    assert kept.status == 'INVITE_SENT'
    with SessionLocal() as db:
        assert db.query(Lead).filter(Lead.sales_nav_id == 'ACwTEST01').count() == 1


def test_dedupe_rescues_reply_from_twin():
    # The ranking keeps the most engaged row: the replied twin must survive
    # with its reply data intact, the bare twin must be removed.
    bare = _seed(sales_nav_id='ACwTEST02', full_name='Bare Row', status='INVITE_SENT')
    twin = _seed(sales_nav_id='urn:li:fs_salesProfile:(ACwTEST02,NAME_SEARCH,aa)',
                 full_name='Twin With Reply', received_replies=True,
                 reply_message='Interested, ping me Monday', status='INVITE_SENT')
    run_dedupe(apply=True)
    assert _get(bare) is None, 'non-replied twin must be removed'
    kept = _get(twin)
    assert kept is not None
    assert kept.received_replies is True
    assert kept.reply_message == 'Interested, ping me Monday'


def test_dedupe_moves_events_and_comments_to_keeper():
    keep = _seed(sales_nav_id='ACwTEST03', full_name='Keeper')
    twin = _seed(sales_nav_id='urn:li:fs_salesProfile:(ACwTEST03,NAME_SEARCH,bb)',
                 full_name='Twin')
    with SessionLocal() as db:
        db.add(LeadEvent(lead_id=twin, kind='reply', detail='hello from twin'))
        db.add(ReplyComment(lead_id=twin, author='tester', body='note'))
        db.commit()
    run_dedupe(apply=True)
    with SessionLocal() as db:
        assert db.query(LeadEvent).filter(LeadEvent.lead_id == keep).count() == 1
        assert db.query(ReplyComment).filter(ReplyComment.lead_id == keep).count() == 1
        assert db.query(LeadEvent).filter(LeadEvent.lead_id == twin).count() == 0


def test_dedupe_clears_junk_urls_and_matches_by_url():
    junk = _seed(sales_nav_id='ACwTEST04', full_name='Junk URL', linkedin_url='0')
    a = _seed(sales_nav_id='ACwTEST05', full_name='URL A',
              linkedin_url='https://www.linkedin.com/in/same-person/')
    b = _seed(sales_nav_id='ACwTEST06', full_name='URL B',
              linkedin_url='https://www.linkedin.com/in/same-person?trk=x')
    run_dedupe(apply=True)
    assert _get(junk).linkedin_url == '', "junk url '0' must be cleared"
    assert _get(b) is None, 'same normalized URL (query stripped) merges'
    kept = _get(a)
    assert kept is not None


def test_dedupe_preview_writes_nothing():
    keep = _seed(sales_nav_id='ACwTEST07', full_name='Keeper')
    twin = _seed(sales_nav_id='urn:li:fs_salesProfile:(ACwTEST07,NAME_SEARCH,cc)',
                 full_name='Twin')
    run_dedupe(apply=False)
    assert _get(keep) is not None
    assert _get(twin) is not None, 'preview mode must not delete anything'


def test_replace_overwrites_db_fields_and_retags(tmp_path):
    """Replace mode: sheet wins on every conflict — fields, stage, campaign.
    Rows in the sheet with no campaign clear the DB tag; unknown campaign
    names are auto-created."""
    import openpyxl
    wb = openpyxl.Workbook()
    pool = wb.active
    pool.title = 'Leads'
    pool.append(['Sales Nav ID', 'FirstName', 'LastName', 'FullName', 'Title',
                 'Company', 'Location', 'Summary', 'Premium', 'PendingInvitation',
                 'Viewed', 'Opentomsg', 'Linkedin URL', 'Updated Date'])
    pool.append(['ACwREPL01', 'Sheet', 'Person', 'Sheet Person', 'Sheet Title',
                 'Sheet Co', 'Sheet City', '', '', '', '', 'true',
                 'https://www.linkedin.com/in/sheet-person/', '2026-01-01'])
    proc = wb.create_sheet('Processed')
    proc.append(['Sales Nav ID', 'FirstName', 'LastName', 'FullName', 'Title',
                 'Company', 'Location', 'Summary', 'Premium', 'Campaigns',
                 'Associate Account', 'Invite or InMail Status', 'Invite or InMail Date',
                 'Received Replies', 'Reply messages', 'Lead Status', 'Linkedin URL'])
    proc.append(['ACwREPL01', '', '', '', '', '', '', '', '', 'Sheet Campaign',
                 'Sheet Account', 'sent invite follow-up 2', '2026-01-05',
                 '✅Yes', 'Fresh reply from sheet', '', ''])
    xlsx = tmp_path / 'replace.xlsx'
    wb.save(xlsx)

    # DB has stale values for the same person.
    keep = _seed(sales_nav_id='ACwREPL01', full_name='DB Name', title='DB Title',
                 status='INVITE_SENT', received_replies=True,
                 reply_message='Old DB reply')
    run_replace(str(xlsx), apply=True)
    row = _get(keep)
    assert row.full_name == 'Sheet Person'
    assert row.title == 'Sheet Title'
    assert row.company == 'Sheet Co'
    assert row.linkedin_url == 'https://www.linkedin.com/in/sheet-person/'
    assert row.opentomsg is True
    assert row.status == 'INVITE_FOLLOWUP_2', 'sheet stage applies even though it is a downgrade'
    assert row.reply_message == 'Fresh reply from sheet', 'sheet reply replaces the stored one'
    with SessionLocal() as db:
        camp = db.get(Campaign, row.campaign_id)
        assert camp is not None and camp.campaign_key == 'Sheet Campaign', 'unknown campaign auto-created + tagged'


def test_replace_clears_campaign_when_sheet_has_none(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    pool = wb.active
    pool.title = 'Leads'
    pool.append(['Sales Nav ID', 'FirstName', 'LastName', 'FullName'])
    pool.append(['ACwREPL02', 'No', 'Camp', 'No Camp'])
    proc = wb.create_sheet('Processed')
    proc.append(['Sales Nav ID', 'Campaigns', 'Associate Account',
                 'Invite or InMail Status', 'Invite or InMail Date',
                 'Received Replies', 'Reply messages', 'Linkedin URL'])
    proc.append(['ACwREPL02', '', '', '', '', '', '', ''])
    xlsx = tmp_path / 'replace2.xlsx'
    wb.save(xlsx)

    keep = _seed(sales_nav_id='ACwREPL02', full_name='No Camp')
    with SessionLocal() as db:
        camp = Campaign(name='Old Camp', campaign_key='old-camp')
        db.add(camp)
        db.flush()
        db.get(Lead, keep).campaign_id = camp.id
        db.commit()

    run_replace(str(xlsx), apply=True)
    row = _get(keep)
    assert row.campaign_id is None, 'sheet with no campaign clears the DB tag'


def test_replace_leaves_db_only_leads_alone(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    pool = wb.active
    pool.title = 'Leads'
    pool.append(['Sales Nav ID', 'FirstName', 'LastName', 'FullName'])
    pool.append(['ACwREPL03', 'In', 'Sheet', 'In Sheet'])
    proc = wb.create_sheet('Processed')
    proc.append(['Sales Nav ID', 'Campaigns', 'Associate Account',
                 'Invite or InMail Status', 'Invite or InMail Date',
                 'Received Replies', 'Reply messages', 'Linkedin URL'])
    proc.append(['ACwREPL03', '', '', '', '', '', '', ''])
    xlsx = tmp_path / 'replace3.xlsx'
    wb.save(xlsx)

    db_only = _seed(sales_nav_id='ACwDBONLY', full_name='DB Only Lead',
                    status='INMAIL_FOLLOWUP_3', campaign_id=None)
    run_replace(str(xlsx), apply=True)
    row = _get(db_only)
    assert row is not None
    assert row.status == 'INMAIL_FOLLOWUP_3', 'leads absent from the sheet stay untouched'


def test_replace_preview_writes_nothing(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    pool = wb.active
    pool.title = 'Leads'
    pool.append(['Sales Nav ID', 'FirstName', 'LastName', 'FullName'])
    pool.append(['ACwREPL04', 'Prev', 'View', 'Prev View'])
    proc = wb.create_sheet('Processed')
    proc.append(['Sales Nav ID', 'Campaigns', 'Associate Account',
                 'Invite or InMail Status', 'Invite or InMail Date',
                 'Received Replies', 'Reply messages', 'Linkedin URL'])
    proc.append(['ACwREPL04', '', '', '', '', '', '', ''])
    xlsx = tmp_path / 'replace4.xlsx'
    wb.save(xlsx)

    keep = _seed(sales_nav_id='ACwREPL04', full_name='Original Name')
    run_replace(str(xlsx), apply=False)
    assert _get(keep).full_name == 'Original Name', 'preview must not write'


def test_csv_import_dedupes_by_url_and_normalizes_urn(app_client):
    # Row 1: urn-format snid of an existing bare row -> must gap-fill, not duplicate.
    _seed(sales_nav_id='ACwTEST08', full_name='Existing', company='Acme')
    # Row 1: urn-format snid, different casing -> must gap-fill, not duplicate.
    csv1 = io.BytesIO(
        b"full_name,sales_nav_id,company\n"
        b"Existing,urn:li:fs_salesProfile:(ACwTEST08,NAME_SEARCH,q1),Acme HQ\n")
    r = app_client.post('/api/leads/import-csv', files={'file': ('l.csv', csv1, 'text/csv')})
    assert r.status_code == 200
    assert r.json()['skipped'] == 1
    # Row 2: no snid at all, but a URL matching an existing lead -> skip.
    _seed(sales_nav_id='ACwTEST09', full_name='Has URL',
          linkedin_url='https://www.linkedin.com/in/urlmatch/')
    csv2 = io.BytesIO(
        b"full_name,linkedin_url\n"
        b"Has URL, https://www.linkedin.com/in/urlmatch?trk=1 \n")
    r = app_client.post('/api/leads/import-csv', files={'file': ('l.csv', csv2, 'text/csv')})
    assert r.status_code == 200
    assert r.json()['skipped'] == 1
    with SessionLocal() as db:
        assert db.query(Lead).filter(Lead.sales_nav_id == 'ACwTEST08').count() == 1
        assert db.query(Lead).filter(Lead.sales_nav_id == 'ACwTEST09').count() == 1


def test_csv_campaign_and_pool_imports_are_separate(app_client):
    lid=_seed(sales_nav_id='ACwGLOB01', full_name='In Campaign', company='OldCo',campaign_id=1)
    csv=b"full_name,sales_nav_id,company\nIn Campaign,ACwGLOB01,NewCo\n"
    response=app_client.post('/api/leads/import-csv',files={'file':('a.csv',csv,'text/csv')})
    assert response.status_code==200
    assert response.json()['added']==1
    response=app_client.post('/api/leads/import-csv',files={'file':('a.csv',csv,'text/csv')})
    assert response.json()['skipped']==1
    with SessionLocal() as db:
        assert db.query(Lead).filter_by(sales_nav_id='ACwGLOB01').count()==2
        assert db.get(Lead,lid).company=='OldCo'
        assert db.get(Lead,lid).campaign_id is not None


def test_csv_import_stores_aco_snid_and_sales_nav_urn_column(app_client):
    """The user's CSV shape: ACo flagship tokens in sales_nav_id plus a
    dedicated sales_nav_urn column. Both must land on the lead — the bare ACo
    id so the outreach validity gate passes, the decorated URN so message
    recipients match the sheets format. Re-import stays a dedupe skip."""
    csv = (b"full_name,sales_nav_id,linkedin_url,sales_nav_urn\n"
           b"Prasad Acharya,ACoAAAFtXGIB0Kc5d6uJ1eYORalkpzZGt_yHrYU,"
           b"http://www.linkedin.com/in/prasad-acharya-7960288,"
           b"\"urn:li:fs_salesProfile:(ACoAAAFtXGIB0Kc5d6uJ1eYORalkpzZGt_yHrYU,NAME_SEARCH,Bj-9)\"\n")
    r = app_client.post('/api/leads/import-csv', files={'file': ('l.csv', io.BytesIO(csv), 'text/csv')})
    assert r.status_code == 200, r.text
    assert r.json()['added'] == 1 and r.json()['skipped'] == 0
    with SessionLocal() as db:
        lead = db.query(Lead).one()
        assert lead.sales_nav_id == 'ACoAAAFtXGIB0Kc5d6uJ1eYORalkpzZGt_yHrYU'
        assert lead.sales_nav_urn == 'urn:li:fs_salesProfile:(ACoAAAFtXGIB0Kc5d6uJ1eYORalkpzZGt_yHrYU,NAME_SEARCH,Bj-9)'
    # Same file again: identity (snid, campaign) still dedupes it.
    r = app_client.post('/api/leads/import-csv', files={'file': ('l.csv', io.BytesIO(csv), 'text/csv')})
    assert r.json()['added'] == 0 and r.json()['skipped'] == 1
    with SessionLocal() as db:
        assert db.query(Lead).count() == 1


def test_import_template_downloads_and_imports_cleanly(app_client):
    """The downloadable template must list the required + optional columns and
    round-trip through the import endpoint untouched (both sample rows added,
    zero errors) so the template can never drift from the CSV parser."""
    r = app_client.get('/api/leads/import-template')
    assert r.status_code == 200
    assert 'text/csv' in r.headers['content-type']
    assert 'attachment' in r.headers['content-disposition']
    body = r.content.decode('utf-8-sig')
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0] == ['full_name', 'sales_nav_id', 'linkedin_url', 'sales_nav_urn',
                       'first_name', 'last_name', 'title', 'company', 'location', 'opentomsg']
    assert len(rows) == 3 and all(row[0] for row in rows[1:]), 'two named sample rows'
    # Round-trip: importing the template adds both sample leads with no errors.
    up = app_client.post('/api/leads/import-csv',
                         files={'file': ('leads_import_template.csv', io.BytesIO(r.content), 'text/csv')})
    assert up.status_code == 200, up.text
    assert up.json() == {'ok': True, 'added': 2, 'skipped': 0, 'errors': []}
    with SessionLocal() as db:
        leads = db.query(Lead).all()
        assert {l.full_name for l in leads} == {'Jane Sample', 'John Sample'}
        for lead in leads:
            assert lead.sales_nav_id == '' and lead.sales_nav_urn == ''
            assert lead.linkedin_url == '' and lead.opentomsg is None



def test_jobs_pool_then_campaign_import_are_separate():
    from app.jobs import _upsert_lead_untagged, _upsert_lead
    with SessionLocal() as db:
        campaign=Campaign(name='New destination',campaign_key='new-destination')
        db.add(campaign);db.flush()
        data=dict(sales_nav_id='ACwGLOB02',full_name='P Q',company='Co',campaign_id=None)
        assert _upsert_lead_untagged(db,data) is True
        data2=dict(data,campaign_id=campaign.id,company='NewerCo')
        assert _upsert_lead(db,data2) is True
        assert _upsert_lead(db,data2) is False
        assert _upsert_lead_untagged(db,data) is False
        db.commit()
        rows=db.query(Lead).filter_by(sales_nav_id='ACwGLOB02').all()
        assert len(rows)==2
        assert next(l for l in rows if l.campaign_id is None).company=='Co'
        assert next(l for l in rows if l.campaign_id==campaign.id).company=='NewerCo'
