"""Offline regression of actual page events, stop boundaries and batch admission."""
from unittest.mock import patch, Mock
from threading import Event
import time
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine
from app.models import Base, Account, Campaign, CampaignAccount, RunLog, Lead, User
from app import jobs, runner
from notification_format import message


@pytest.fixture
def client():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    runner._stop_event.clear()
    with patch.object(jobs.notify, 'send_gchat'), patch.dict(runner._live, run_id=None, status='idle', progress={}):
        with TestClient(app) as c:
            assert c.post('/api/login',json={'username':'test-admin','password':'test-password-only'}).status_code==200
            with SessionLocal() as db:
                a=Account(name='Offline account',session_ref='offline'); c1=Campaign(name='Offline campaign',campaign_key='offline')
                db.add_all([a,c1]);db.flush();db.add(CampaignAccount(account_id=a.id,campaign_id=c1.id));db.commit()
            yield c
    runner._stop_event.clear()


@pytest.mark.parametrize('key',['sync_leads','import_list'])
def test_multipage_live_counts_and_dedupe(client,key):
    pages=[jobs.li.ResultPage({'elements':[{'entityUrn':f'lead-{i}'} for i in range(25)],'paging':{'total':27}}),
           jobs.li.ResultPage({'elements':[{'entityUrn':'lead-0'},{'entityUrn':'lead-26'}],'paging':{'total':27}})]
    snapshots=[]
    original=jobs._Run.page
    def page(run,*args):
        original(run,*args)
        snapshots.append(client.get('/api/runs/live').json())
    method='search_leads' if key=='sync_leads' else 'people_search_by_list'
    with patch.object(jobs,'load_session_ref'),patch.object(jobs.li,method,side_effect=pages),patch.object(jobs.li,'polite_sleep',return_value=True),patch.object(jobs._Run,'page',page):
        jobs.run_job(key,account_id=1,**({'saved_search_id':'123'} if key=='sync_leads' else {'list_id':'123'}))
    assert [s['progress']['extracted'] for s in snapshots]==[25,27]
    assert [s['progress']['page'] for s in snapshots]==[1,2]
    assert snapshots[1]['progress']['percent']==100
    assert snapshots[1]['active']
    with SessionLocal() as db:
        assert db.query(Lead).count()==26
        assert db.query(RunLog).one().status=='success'


def test_stop_blocks_next_request_and_reports_stopping(client):
    session=Mock(); guarded=jobs._AccountSession(session,1)
    with SessionLocal() as db:
        run=jobs._Run(db,jobs.JobType.IMPORT_LIST,'Offline stop',True)
        rid=run.run.id
        with patch.dict(runner._live,run_id=rid,status='running'),patch.object(runner,'is_running',return_value=True):
            assert client.post('/api/jobs/stop',json={'run_id':rid+1}).status_code==400
            assert client.post('/api/jobs/stop',json={'run_id':rid}).status_code==200
            assert client.get('/api/runs/live').json()['status']=='stopping'
            assert client.get(f'/api/runs/{rid}/log').json()['status']=='stopping'
            assert client.get('/api/runs').json()[0]['status']=='stopping'
            with pytest.raises(jobs.JobStoppedError): guarded.post('https://offline.invalid')
            session.post.assert_not_called()
            run.finish()
            assert client.get('/api/runs/live').json()['status']=='stopped'


def test_batch_validates_everything_before_start(client):
    with patch.object(runner,'start_sequence',return_value=(True,'Started',None)) as start:
        assert client.post('/api/jobs/batch',json={'campaign_ids':[],'dry_run':True}).status_code==422
        assert client.post('/api/jobs/batch',json={'campaign_ids':[1],'connections':False,'followups':False,'dry_run':True}).status_code==422
        assert client.post('/api/jobs/batch',json={'campaign_ids':[999],'dry_run':True}).status_code==422
        start.assert_not_called()
        assert client.post('/api/jobs/batch',json={'campaign_ids':[1],'followups':True,'dry_run':True}).status_code==200
        assert [k for k,_ in start.call_args.args[0]]==['send_connections','send_followups']


def test_single_flight_rejects_duplicate_and_stop_skips_next_worker(client):
    entered=Event();release=Event(); calls=[]
    def execute(key,**kwargs):
        calls.append(key);entered.set();release.wait(3)
    try:
        with patch.object(jobs,'run_job',execute):
            assert runner.start_sequence([('send_connections',{}),('send_followups',{})],dry_run=True)[0]
            assert entered.wait(2)
            assert not runner.start_job('send_connections',dry_run=True)[0]
            assert runner.stop_job()[0]
            release.set()
            until=time.monotonic()+3
            while runner.is_running() and time.monotonic()<until: time.sleep(.01)
            assert not runner.is_running()
            assert calls==['send_connections']
            assert runner.live_status()['status']=='stopped'
    finally: release.set()


def test_restricted_default_worker_scope_is_not_all(client):
    with SessionLocal() as db:
        user=db.query(User).first();user.role='campaign_manager';user.allowed_campaign_ids=[1];user.allowed_account_ids=[1];db.commit()
    with patch.object(runner,'start_job',return_value=(True,'Started',None)) as start:
        assert client.post('/api/jobs/send_connections/run',json={'dry_run':True}).status_code==200
        assert start.call_args.kwargs['campaign_ids']==[1]
        assert start.call_args.kwargs['account_ids']==[1]


def test_notification_format_is_bounded_and_hides_zero_metrics():
    text=message('import_list','partial','Campaign / Account',{'extracted':0},['Failure']*10,duration=12.3)
    assert 'Import SavedList' in text and 'Extracted' not in text  # zero metrics hidden
    assert '×10' in text and '12.3s' in text and 'Completed with warnings' in text
    assert len(message('Alert','error',errors=['a'*1000]*100))<=6000


def test_password_change_survives_bootstrap_and_no_plaintext(client):
    from app.main import _ensure_bootstrap_admin
    from app.auth import hash_password, check_password
    with SessionLocal() as db:
        user=db.query(User).first()
        assert user.password_hash.startswith('pbkdf2_sha256$')
        user.password_hash=hash_password('changed-password-only');db.commit()
    _ensure_bootstrap_admin()
    with SessionLocal() as db:
        assert check_password('changed-password-only',db.query(User).first().password_hash)


def test_frozen_selection_and_comment_access(client):
    from app.models import ReplyComment
    with SessionLocal() as db:
        lead=Lead(sales_nav_id='selected',full_name='Selected',campaign_id=1,associate_account_id=1)
        db.add(lead);db.commit()
    selection=client.get('/api/leads?ids_only=true').json()['ids']
    assert len(selection)==1
    with SessionLocal() as db:
        db.add(Lead(sales_nav_id='later',full_name='New import'));db.commit()
    preview=client.post('/api/leads/delete-preview',json={'ids':selection}).json()
    assert preview['existing']==1
    comment=client.post(f'/api/leads/{selection[0]}/comments',json={'body':'Internal note','author':'Spoofed'}).json()
    assert comment['author']=='Administrator'
    with SessionLocal() as db:
        user=db.query(User).first();user.role='campaign_manager';user.allowed_campaign_ids=[999];db.commit()
    assert client.put(f'/api/comments/{comment["id"]}',json={'body':'Wrong scope'}).status_code==404
    assert client.delete(f'/api/comments/{comment["id"]}').status_code==404
    assert client.post('/api/leads/delete-preview',json={'ids':selection}).json()['existing']==0


def test_restricted_schedule_defaults_are_persisted(client):
    with SessionLocal() as db:
        user=db.query(User).first();user.role='campaign_manager';user.allowed_campaign_ids=[1];user.allowed_account_ids=[1];db.commit()
    body={'name':'Scoped offline schedule','run_time':'09:00','days_of_week':['mon'],
          'job_keys':['send_connections'],'timezone':'Asia/Kolkata','active':False}
    with patch('app.schedule_store.refresh'):
        result=client.post('/api/schedules',json=body)
        assert result.status_code==200,result.text
        assert result.json()['scopes']['send_connections']=={'campaign_ids':[1],'account_ids':[1]}
        assert client.post('/api/schedules',json={**body,'scopes':{'send_connections':{'campaign_ids':[999]}}}).status_code==403


def test_import_rejected_session_updates_account_and_failed_run(client):
    session=Mock();session.get.return_value.status_code=403
    with patch.object(jobs,'load_session_ref',return_value=session):
        jobs.job_import_list(account_id=1,list_id='123')
    with SessionLocal() as db:
        assert db.get(Account,1).status=='needs_reauth'
        row=db.query(RunLog).one()
        assert row.status=='error' and '403' in row.errors[0]


def test_stop_after_first_import_page_preserves_committed_leads(client):
    original=jobs._Run.page
    def page(run,*args):
        original(run,*args);runner._stop_event.set()
    elements=[{'entityUrn':f'lead-{i}'} for i in range(25)]
    with patch.object(jobs,'load_session_ref'),patch.object(jobs.li,'search_leads',return_value=elements) as search,patch.object(jobs.li,'polite_sleep',return_value=True),patch.object(jobs._Run,'page',page):
        jobs.job_sync_leads(account_id=1,saved_search_id='123')
    search.assert_called_once()
    with SessionLocal() as db:
        assert db.query(Lead).count()==25
        assert db.query(RunLog).one().status=='stopped'
    # Without a server total, progress stays indeterminate.
    assert runner.live_status()['progress']['percent'] is None


def test_legacy_delete_uses_same_guard_and_scope(client):
    with SessionLocal() as db:
        db.add(Lead(sales_nav_id='outside',campaign_id=None));db.commit()
    with runner.idle_lease() as acquired:
        assert acquired
        for endpoint in ['bulk-delete','bulk-delete-v2']:
            assert client.post('/api/leads/'+endpoint,json={'ids':[1]}).status_code==409
    with SessionLocal() as db:
        user=db.query(User).first();user.role='campaign_manager';user.allowed_campaign_ids=[1];db.commit()
    assert client.post('/api/leads/bulk-delete',json={'ids':[1]}).status_code==403
    with SessionLocal() as db: assert db.query(Lead).count()==1


def test_batch_does_not_hide_earlier_failure(client):
    def execute(key,**kwargs):
        with SessionLocal() as db:
            r=jobs._Run(db,jobs.JobType(key),'Offline batch',True)
            r.finish(jobs.RunStatus.ERROR if key=='send_connections' else jobs.RunStatus.SUCCESS)
    with patch.object(jobs,'run_job',execute):
        assert runner.start_sequence([('send_connections',{}),('send_followups',{})],dry_run=True)[0]
        until=time.monotonic()+3
        while runner.is_running() and time.monotonic()<until:time.sleep(.01)
        assert not runner.is_running()
        assert client.get('/api/runs/live').json()['batch_status']=='error'


def test_explicit_decline_wins_over_booking_phrase():
    from app.classify import suggest_category
    assert suggest_category('Not interested. Do not schedule a meeting.')[0]=='declined'
    assert suggest_category('Please unsubscribe me; no need to schedule a call.')[0]=='unsubscribe'
    assert suggest_category('Happy to have a call next week.')[0]=='meeting'


def test_verify_missing_seat_persists_and_requires_success_to_reactivate(client):
    raw = Mock()
    raw.get.return_value.status_code = 403
    raw.get.return_value.json.return_value = {'code':'SALES_SEAT_REQUIRED'}
    with patch.object(jobs, 'load_session_ref', return_value=raw):
        response = client.post('/api/accounts/1/verify-session')
    assert response.status_code == 422 and 'Sales Navigator seat' in response.json()['detail']
    account = client.get('/api/accounts').json()[0]
    assert account['status'] == account['session_state'] == 'seat_required'
    assert account['last_cookie_refresh_at'] is None
    raw.close.assert_called_once()
    # A stale settings form cannot accidentally reactivate failed access.
    assert client.put('/api/accounts/1', json={'name':account['name'],'status':'active'}).status_code == 422
    assert client.put('/api/accounts/1', json={'name':account['name'],'status':'paused'}).status_code == 422
    assert client.put('/api/accounts/1', json={'name':account['name'],'status':'seat_required','daily_invite_cap':12}).status_code == 200
    assert client.put('/api/accounts/1', json={'name':account['name'],'daily_invite_cap':14}).status_code == 200
    assert client.get('/api/accounts').json()[0]['status'] == 'seat_required'
    raw.get.return_value.status_code = 200
    raw.get.return_value.json.return_value = {'elements':[]}
    with patch.object(jobs, 'load_session_ref', return_value=raw):
        assert client.post('/api/accounts/1/verify-session').status_code == 200
    account = client.get('/api/accounts').json()[0]
    assert account['status'] == 'active' and account['session_state'] == 'ok'
    assert account['last_cookie_refresh_at'] is not None


@pytest.mark.parametrize('code',[401,403])
def test_verify_auth_failure_persists_reauth(client, code):
    raw = Mock(); raw.get.return_value.status_code = code
    raw.get.return_value.json.return_value = {'message':'Access denied'}
    with patch.object(jobs, 'load_session_ref', return_value=raw):
        assert client.post('/api/accounts/1/verify-session').status_code == 422
    assert client.get('/api/accounts').json()[0]['status'] == 'needs_reauth'


def test_verify_missing_file_persists_reauth(client):
    with patch.object(jobs, 'load_session_ref', side_effect=jobs.li.LinkedinError('No session file')):
        assert client.post('/api/accounts/1/verify-session').status_code == 422
    assert client.get('/api/accounts').json()[0]['status'] == 'needs_reauth'


def test_verify_transient_error_does_not_revoke_account(client):
    raw = Mock(); raw.get.side_effect = TimeoutError('Temporary timeout')
    with patch.object(jobs, 'load_session_ref', return_value=raw):
        assert client.post('/api/accounts/1/verify-session').status_code == 422
    assert client.get('/api/accounts').json()[0]['status'] == 'active'


def test_verify_never_resumes_a_paused_account(client):
    with SessionLocal() as db:
        db.get(Account,1).status = 'paused'; db.commit()
    raw = Mock(); raw.get.return_value.status_code = 403
    raw.get.return_value.json.return_value = {'code':'SALES_SEAT_REQUIRED'}
    with patch.object(jobs, 'load_session_ref', return_value=raw):
        assert client.post('/api/accounts/1/verify-session').status_code == 422
        assert client.get('/api/accounts').json()[0]['status'] == 'paused'
        raw.get.return_value.status_code = 200
        raw.get.return_value.json.return_value = {'elements':[]}
        assert client.post('/api/accounts/1/verify-session').status_code == 200
    assert client.get('/api/accounts').json()[0]['status'] == 'paused'


def test_verify_persists_fallback_resolved_session(client):
    """A session found via the filename guess (no DB session_ref) must be written
    back to the account, so the UI reports session_configured=true right after a
    successful Verify instead of continuing to show 'Session missing'."""
    import json as _json
    from pathlib import Path as _Path
    from app.config import PROJECT_ROOT
    with SessionLocal() as db:
        db.get(Account, 1).session_ref = ''
        db.commit()
    cookies_dir = _Path(PROJECT_ROOT) / 'cookies_files'
    cookies_dir.mkdir(exist_ok=True)
    cookies_file = cookies_dir / 'offline_cookies.json'
    cookies_file.write_text(_json.dumps({'headers': {}, 'cookies': {}}), encoding='utf-8')
    raw = Mock()
    raw.get.return_value.status_code = 200
    raw.get.return_value.json.return_value = {'elements': []}
    try:
        with patch.object(jobs, '_session_from_files', return_value=raw):
            assert client.post('/api/accounts/1/verify-session').status_code == 200
        row = client.get('/api/accounts').json()[0]
        assert row['session_configured'] is True and row['session_state'] == 'ok'
        assert row['last_cookie_refresh_at'] is not None
        with SessionLocal() as db:
            assert db.get(Account, 1).session_ref.endswith('offline_cookies.json')
    finally:
        cookies_file.unlink(missing_ok=True)


def _raw_session(status=200, payload=None):
    raw = Mock()
    raw.get.return_value.status_code = status
    raw.get.return_value.json.return_value = payload if payload is not None else {'elements': []}
    return raw


def _cleanup_cookie_files(*names):
    from pathlib import Path
    from app.config import PROJECT_ROOT
    for name in names:
        (Path(PROJECT_ROOT) / 'cookies_files' / name).unlink(missing_ok=True)


def test_upload_cookies_activates_needs_reauth_account(client):
    """Uploading fresh cookies into a needs_reauth account live-checks them
    immediately and clears the flag - the UI must not show 'Needs re-auth'
    after a refresh when the new cookies passed the inbox check."""
    with SessionLocal() as db:
        db.get(Account, 1).status = 'needs_reauth'
        db.get(Account, 1).session_ref = ''
        db.commit()
    raw = _raw_session()
    payload = __import__('json').dumps({'cookies': {'li_at': 'fresh'}, 'headers': {}}).encode()
    try:
        with patch.object(jobs, 'load_session_ref', return_value=raw) as load:
            res = client.post('/api/accounts/1/upload-cookies',
                              files={'file': ('cynthia_fresh.json', payload, 'application/json')})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body['session_ok'] is True and body['status'] == 'active'
        load.assert_called_once()  # the NEWLY saved file was what got checked
        row = client.get('/api/accounts').json()[0]
        assert row['status'] == 'active' and row['session_configured'] is True
        assert row['session_state'] == 'ok'
    finally:
        _cleanup_cookie_files('offline_account_cookies.json')


def test_upload_cookies_transient_error_keeps_file_and_prior_state(client):
    """A timeout/5xx during the post-upload check must NOT flip the account to
    needs_reauth on the strength of a bad network moment (this re-flagged
    accounts right after a good upload). Cookies stay saved; re-Verify works
    without re-uploading."""
    with SessionLocal() as db:
        db.get(Account, 1).status = 'needs_reauth'
        db.commit()
    raw = _raw_session(502)
    raw.get.return_value.json.side_effect = ValueError('not json')
    payload = __import__('json').dumps({'cookies': {'li_at': 'x'}, 'headers': {}}).encode()
    try:
        with patch.object(jobs, 'load_session_ref', return_value=raw):
            res = client.post('/api/accounts/1/upload-cookies',
                              files={'file': ('x.json', payload, 'application/json')})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body['session_ok'] is None  # not proven either way
        assert body['status'] == 'needs_reauth'  # prior state preserved
        assert body['session_ref']  # upload itself was still saved
    finally:
        _cleanup_cookie_files('offline_account_cookies.json')


def test_upload_cookies_maps_seat_required_distinctly(client):
    """New cookies cannot fix a missing seat: SALES_SEAT_REQUIRED must land
    the account in seat_required, not needs_reauth."""
    with SessionLocal() as db:
        db.get(Account, 1).status = 'needs_reauth'
        db.commit()
    raw = _raw_session(403, {'code': 'SALES_SEAT_REQUIRED'})
    payload = __import__('json').dumps({'cookies': {'li_at': 'x'}, 'headers': {}}).encode()
    try:
        with patch.object(jobs, 'load_session_ref', return_value=raw):
            res = client.post('/api/accounts/1/upload-cookies',
                              files={'file': ('x.json', payload, 'application/json')})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body['session_ok'] is False
        assert body['status'] == 'seat_required'
        assert client.get('/api/accounts').json()[0]['status'] == 'seat_required'
    finally:
        _cleanup_cookie_files('offline_account_cookies.json')


def test_upload_cookies_really_rejected_stays_needs_reauth(client):
    """Genuine 401 rejection: the flag stays, but the uploaded file is still
    saved and linked so a later Verify uses it without a re-upload."""
    with SessionLocal() as db:
        db.get(Account, 1).status = 'needs_reauth'
        db.commit()
    raw = _raw_session(401, {'message': 'denied'})
    payload = __import__('json').dumps({'cookies': {'li_at': 'stale'}, 'headers': {}}).encode()
    try:
        with patch.object(jobs, 'load_session_ref', return_value=raw):
            res = client.post('/api/accounts/1/upload-cookies',
                              files={'file': ('x.json', payload, 'application/json')})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body['session_ok'] is False and body['status'] == 'needs_reauth'
        with SessionLocal() as db:
            acc = db.get(Account, 1)
            assert acc.session_ref.endswith('offline_account_cookies.json')
            assert acc.last_cookie_refresh_at is not None
    finally:
        _cleanup_cookie_files('offline_account_cookies.json')


def test_cookie_load_prefers_newest_file_and_persists_it(client):
    """Path-handling regression: a stale DB session_ref must not shadow a
    freshly captured/uploaded conventional file; the newest file wins and the
    resolution is persisted back onto the account."""
    import json as _json
    import os as _os
    import time as _time
    from pathlib import Path
    from app.config import PROJECT_ROOT
    cookies_dir = Path(PROJECT_ROOT) / 'cookies_files'
    cookies_dir.mkdir(exist_ok=True)
    old = cookies_dir / 'old_stale_copy.json'
    new = cookies_dir / 'offline_account_cookies.json'
    old.write_text(_json.dumps({'cookies': {}, 'headers': {}}), encoding='utf-8')
    new.write_text(_json.dumps({'cookies': {'li_at': 'new'}, 'headers': {}}), encoding='utf-8')
    _os.utime(old, (_time.time() - 3600,) * 2)
    try:
        with SessionLocal() as db:
            acc = db.get(Account, 1)
            acc.session_ref = str(old)
            db.commit()
            session = jobs.load_session_ref(acc, persist=True)
            db.commit()
            assert acc.session_ref.endswith('offline_account_cookies.json')
            assert session is not None
    finally:
        old.unlink(missing_ok=True)
        new.unlink(missing_ok=True)


def test_worker_seat_required_is_distinct_and_stops_session(client):
    raw = Mock(); raw.get.return_value.status_code = 403
    raw.get.return_value.json.return_value = {'code':'SALES_SEAT_REQUIRED'}
    session = jobs._AccountSession(raw,1)
    with pytest.raises(jobs.li.SeatRequiredError):
        session.get('https://example.invalid/inbox')
    with pytest.raises(jobs.li.SeatRequiredError):
        session.get('https://example.invalid/another')
    assert raw.get.call_count == 1
    assert client.get('/api/accounts').json()[0]['status'] == 'seat_required'


def test_workers_skip_accounts_without_seat(client):
    with SessionLocal() as db:
        db.get(Account,1).status='seat_required'; db.commit()
    with patch.object(jobs, 'load_session_ref') as load:
        for worker in [jobs.job_send_connections,jobs.job_check_replies,jobs.job_send_followups]:
            worker(campaign_ids=[1],account_ids=[1])
        load.assert_not_called()


def test_frontend_assets_versioned_and_account_responses_not_cached(client):
    from app.main import STATIC_DIR
    # Both entry points must version every relevant asset. The home page is
    # now React; the preserved classic assets are served by /legacy.
    for path, assets in [('/', ['dist/app.js', 'dist/app.css']),
                         ('/legacy', ['app.js', 'views.js', 'workspace.js'])]:
        response = client.get(path)
        assert response.headers['cache-control'] == 'no-store'
        for filename in assets:
            stat = (STATIC_DIR / filename).stat()
            assert f'/static/{filename}?v={stat.st_mtime_ns}-{stat.st_size}' in response.text
            assert client.get(f'/static/{filename}').headers['cache-control'] == 'no-cache'
    assert client.get('/api/accounts').headers['cache-control'] == 'no-store'
