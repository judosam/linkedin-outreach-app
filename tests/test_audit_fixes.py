"""Offline regressions for the eight approved audit fixes.
No LinkedIn sessions, sends, email or Google Chat calls leave this fixture.
"""
from unittest.mock import Mock

import json

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine
from app.models import Base, Account, Campaign, CampaignAccount, Lead, RunLog, User
from app import jobs, runner


@pytest.fixture
def audit(monkeypatch):
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    runner._stop_event.clear()
    monkeypatch.setattr(jobs, 'load_session_ref', lambda account: Mock())
    monkeypatch.setattr(jobs.li, 'fetch_inbox', lambda *a, **k: {'elements': []})
    monkeypatch.setattr(jobs.li, 'polite_sleep', lambda *a, **k: True)
    monkeypatch.setattr(jobs.li, 'send_inmail', Mock(return_value=(True, None, 'offline')))
    monkeypatch.setattr(jobs.li, 'send_message', Mock(return_value=(True, None, 'offline')))
    monkeypatch.setattr(jobs.li, 'send_connection_invite', Mock(return_value=(True, None, 'offline')))
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post('/api/login', json={'username': 'test-admin', 'password': 'test-password-only'}).status_code == 200
        with SessionLocal() as db:
            a = Account(name='Audit account', session_ref='offline')
            c = Campaign(name='Audit campaign', campaign_key='audit', invite_text='Hello {first_name}')
            db.add_all([a, c]); db.flush()
            db.add(CampaignAccount(account_id=a.id, campaign_id=c.id))
            db.commit()
        yield client
    runner._stop_event.clear()


def seed_lead(**values):
    data = dict(campaign_id=1, sales_nav_id='ACwAUDIT', full_name='Audit prospect',
                linkedin_url='https://www.linkedin.com/in/audit', opentomsg=False)
    data.update(values)
    with SessionLocal() as db:
        row = Lead(**data); db.add(row); db.commit(); return row.id


def upload(client, csv, campaign=1):
    qs = f'?campaign_id={campaign}' if campaign is not None else ''
    return client.post(f'/api/leads/import-csv{qs}',
                       files={'file': ('audit.csv', csv.encode(), 'text/csv')})


@pytest.mark.parametrize('cached', [False, True])
def test_opentomsg_logging_live_and_saved(audit, monkeypatch, cached):
    seed_lead(opentomsg=False if cached else None)
    live = []
    def profile(*args):
        with SessionLocal() as db:
            rid = db.query(RunLog).one().id
        live.append(audit.get(f'/api/runs/{rid}/log').json()['log_text'])
        return False, 'https://www.linkedin.com/in/audit'
    fetch = Mock(side_effect=profile)
    monkeypatch.setattr(jobs.li, 'get_profile_opentomsg', fetch)
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    with SessionLocal() as db:
        text = db.query(RunLog).one().log_text
    assert 'audit/Audit account' in text
    if cached:
        fetch.assert_not_called()
        assert 'OpenToMsg cached (no fetch): Audit prospect - not open to messages' in text
    else:
        assert 'OpenToMsg check 1/200: Audit prospect' in text
        assert 'checking profile' in live[0]
        assert 'OpenToMsg result: Audit prospect - not open to messages (saved)' in text


def test_csv_two_url_only_leads_in_campaign(audit):
    response = upload(audit, 'full_name,linkedin_url\nOne,https://www.linkedin.com/in/one\nTwo,https://www.linkedin.com/in/two\n')
    assert response.status_code == 200, response.text
    assert response.json()['added'] == 2


def test_creator_auto_gets_access_to_new_campaign(audit):
    """A restricted user who creates a campaign is automatically granted it:
    the new id lands in allowed_campaign_ids and the campaign shows in their
    list (before this fix it was invisible to them)."""
    with SessionLocal() as db:
        user = db.query(User).one()
        user.role = 'campaign_manager'
        user.allowed_campaign_ids = [1]
        db.commit()
    r = audit.post('/api/campaigns', json={'name': 'Creator Camp', 'status': 'active', 'accounts': []})
    assert r.status_code == 200, r.text
    new_id = r.json()['id']
    camps = audit.get('/api/campaigns').json()
    assert any(c['id'] == new_id for c in camps), 'creator must see their new campaign'
    with SessionLocal() as db:
        user = db.query(User).one()
        assert new_id in (user.allowed_campaign_ids or [])


def test_leads_campaign_none_sentinel_filters_unassigned_pool(audit):
    """campaign_id='__none__' returns ONLY leads with no campaign; a numeric
    id still works as before, and the sentinel respects user scope."""
    upload(audit, 'full_name,sales_nav_id\nPool Person,ACwPOOL1\n', campaign=None)
    with SessionLocal() as db:
        db.add(Campaign(name='Tagged', campaign_key='Tagged'))
        db.commit()
        cid = db.query(Campaign).filter_by(campaign_key='Tagged').one().id
        db.add(Lead(sales_nav_id='ACwTAG1', full_name='Tagged Person', campaign_id=cid, source='campaign_search'))
        db.commit()
    r = audit.get('/api/leads?campaign_id=__none__')
    assert r.status_code == 200, r.text
    names = [l['full_name'] for l in r.json()['items']]
    assert 'Pool Person' in names and 'Tagged Person' not in names
    r2 = audit.get(f'/api/leads?campaign_id={cid}')
    assert [l['full_name'] for l in r2.json()['items']] == ['Tagged Person']


def test_campaign_rename_propagates_to_leads_and_threads(audit):
    """Renaming a campaign (name change, campaign_key immutable) must show up
    on its leads in /api/leads and /api/threads immediately — leads are linked
    by campaign_id, so the live campaign_name must follow the campaign row."""
    seed_lead(received_replies=True, reply_message='Sounds good')
    # Rename the campaign's display name; the key stays 'audit'.
    r = audit.get('/api/campaigns/1')
    assert r.status_code == 200
    body = r.json()
    body['name'] = 'Renamed Campaign'
    assert audit.put('/api/campaigns/1', json=body).status_code == 200
    leads = audit.get('/api/leads').json()['items']
    row = next(l for l in leads if l['sales_nav_id'] == 'ACwAUDIT')
    assert row['campaign'] == 'audit', 'immutable key is preserved'
    assert row['campaign_name'] == 'Renamed Campaign', 'live name follows the rename'
    assert row['campaign_id'] == 1
    thread = audit.get('/api/threads').json()['items'][0]
    assert thread['campaign_name'] == 'Renamed Campaign'
    # Delete preview groups by the new name too.
    preview = audit.post('/api/leads/delete-preview', json={'ids': [row['id']]}).json()
    assert preview['campaigns'] == [{'campaign': 'Renamed Campaign', 'count': 1}]


def test_csv_preserves_opentomsg(audit):
    assert upload(audit, 'full_name,sales_nav_id,opentomsg\nOne,ACwONE,true\n').status_code == 200
    with SessionLocal() as db:
        assert db.query(Lead).one().opentomsg is True


def test_csv_rejects_campaign_outside_user_scope(audit):
    with SessionLocal() as db:
        db.add(Campaign(id=2, name='Outside scope', campaign_key='outside'))
        user = db.query(User).one(); user.role = 'campaign_manager'; user.allowed_campaign_ids = [1]
        db.commit()
    assert upload(audit, 'full_name,sales_nav_id\nOne,ACwONE\n', campaign=2).status_code == 403


def test_connections_never_send_to_replied_lead(audit):
    seed_lead(received_replies=True, reply_message='Please stop')
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    jobs.li.send_connection_invite.assert_not_called()


def test_opentomsg_checks_stop_at_200(audit, monkeypatch):
    with SessionLocal() as db:
        db.query(CampaignAccount).one().inmail_limit = 0
        db.add_all([Lead(campaign_id=1, sales_nav_id=f'ACw{i}', full_name=f'Prospect {i}') for i in range(201)])
        db.commit()
    fetch = Mock(return_value=(True, 'https://www.linkedin.com/in/offline'))
    monkeypatch.setattr(jobs.li, 'get_profile_opentomsg', fetch)
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    assert fetch.call_count <= 200, f'{fetch.call_count} profile requests were made'


def test_profile_errors_do_not_report_success(audit, monkeypatch):
    seed_lead(opentomsg=None)
    monkeypatch.setattr(jobs.li, 'get_profile_opentomsg', Mock(side_effect=jobs.li.LinkedinError('offline HTTP 500', status=500)))
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    with SessionLocal() as db:
        row = db.query(RunLog).one()
        assert row.status in ('partial', 'error'), f'status={row.status}, errors={row.errors}'


def test_manual_search_stop_during_page_wait(audit, monkeypatch):
    monkeypatch.setattr(jobs.li, 'search_leads', lambda *a: jobs.li.ResultPage({'elements': [
        {'entityUrn': f'ACw{i}', 'fullName': f'Offline {i}'} for i in range(25)]}))
    def stop(*args):
        runner._stop_event.set(); return False
    monkeypatch.setattr(jobs.li, 'polite_sleep', stop)
    jobs.job_sync_leads(account_id=1, saved_search_id='123')
    with SessionLocal() as db:
        row = db.query(RunLog).one()
        assert row.status == 'stopped', f'status={row.status}, errors={row.errors}'


def test_rate_limit_rolls_all_remaining_leads_to_next_account(audit, monkeypatch):
    for i in range(5): seed_lead(sales_nav_id=f'ACw{i}', full_name=f'Prospect {i}')
    with SessionLocal() as db:
        a = Account(name='Second offline account', session_ref='offline'); db.add(a); db.flush()
        db.add(CampaignAccount(account_id=a.id, campaign_id=1, order_index=1)); db.commit()
    # 5 consecutive 429s -> account stops; remaining leads roll to account 2.
    send = Mock(side_effect=[(False, 'rate_limited', 'offline 429')] * 5 + [(True, None, 'offline')] * 3)
    monkeypatch.setattr(jobs.li, 'send_connection_invite', send)
    jobs.job_send_connections([1])
    with SessionLocal() as db:
        assert db.query(Lead).filter_by(associate_account_id=2).count() == 3


def test_single_429_does_not_stop_account(audit, monkeypatch):
    """One transient 429 must not halt the account: the lead is retained and
    later leads still get their invites from the same account."""
    for i in range(3): seed_lead(sales_nav_id=f'ACw{i}', full_name=f'Prospect {i}')
    send = Mock(side_effect=[(False, 'rate_limited', 'offline 429')] + [(True, None, 'offline')] * 2)
    monkeypatch.setattr(jobs.li, 'send_connection_invite', send)
    jobs.job_send_connections([1])
    assert send.call_count == 3, 'single 429 stopped the account too early'
    with SessionLocal() as db:
        sent = db.query(Lead).filter(Lead.associate_account_id == 1,
                                     Lead.status == 'INVITE_SENT').count()
        assert sent == 2, f'{sent} invites sent after a transient 429'


def test_non_consecutive_429s_never_stop_account(audit, monkeypatch):
    """429s separated by successful sends must never trip the stop."""
    for i in range(6): seed_lead(sales_nav_id=f'ACw{i}', full_name=f'Prospect {i}')
    send = Mock(side_effect=[(False, 'rate_limited', 'offline 429'), (True, None, 'ok'),
                             (False, 'rate_limited', 'offline 429'), (True, None, 'ok'),
                             (False, 'rate_limited', 'offline 429'), (True, None, 'ok')])
    monkeypatch.setattr(jobs.li, 'send_connection_invite', send)
    jobs.job_send_connections([1])
    assert send.call_count == 6, 'account stopped despite non-consecutive 429s'
    with SessionLocal() as db:
        sent = db.query(Lead).filter(Lead.associate_account_id == 1,
                                     Lead.status == 'INVITE_SENT').count()
        assert sent == 3


def test_existing_database_index_upgrade_preserves_rows(tmp_path):
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError
    from app.database import migrate_lead_identity_index
    old = create_engine('sqlite:///' + str(tmp_path / 'old.db'))
    try:
        with old.begin() as conn:
            conn.execute(text('CREATE TABLE leads (id INTEGER PRIMARY KEY, sales_nav_id TEXT, campaign_id INTEGER)'))
            conn.execute(text('CREATE UNIQUE INDEX uq_lead_snid_campaign ON leads (sales_nav_id,campaign_id)'))
            conn.execute(text("INSERT INTO leads VALUES (1,'',1),(2,'ACwONE',1)"))
        migrate_lead_identity_index(old)
        migrate_lead_identity_index(old)
        with old.begin() as conn:
            assert conn.execute(text('SELECT * FROM leads ORDER BY id')).all() == [(1, '', 1), (2, 'ACwONE', 1)]
            conn.execute(text("INSERT INTO leads VALUES (3,'',1),(4,'ACwONE',2)"))
        with pytest.raises(IntegrityError), old.begin() as conn:
            conn.execute(text("INSERT INTO leads VALUES (5,'ACwONE',1)"))
    finally:
        old.dispose()


def test_csv_tristate_validation_and_duplicate_gap_fill(audit):
    csv = 'full_name,sales_nav_id,opentomsg\nOne,ACwONE,false\nTwo,ACwTWO,unknown\nThree,ACwTHREE,maybe\n'
    result = upload(audit, csv).json()
    assert (result['added'], result['skipped']) == (2, 1)
    assert 'row 4: opentomsg' in result['errors'][0]
    result = upload(audit, 'full_name,sales_nav_id,opentomsg\nOne,ACwONE,true\nTwo,ACwTWO,yes\n').json()
    assert (result['added'], result['skipped']) == (0, 2)
    with SessionLocal() as db:
        assert db.query(Lead).filter_by(sales_nav_id='ACwONE').one().opentomsg is False
        assert db.query(Lead).filter_by(sales_nav_id='ACwTWO').one().opentomsg is True


@pytest.mark.parametrize('campaign,account_scope,expected', [(1, [], 200), (None, [], 403), (1, [1], 200)])
def test_csv_scope_matches_unassigned_lead_visibility(audit, campaign, account_scope, expected):
    # OR scope: importing into an allowed campaign is allowed even though the
    # lead starts unassigned (campaign-1 pool leads are visible to this user).
    with SessionLocal() as db:
        user = db.query(User).one()
        user.role = 'campaign_manager'; user.allowed_campaign_ids = [1]; user.allowed_account_ids = account_scope
        db.commit()
    url = '/api/leads/import-csv' + (f'?campaign_id={campaign}' if campaign is not None else '')
    response = audit.post(url, files={'file': ('a.csv', b'full_name,sales_nav_id\nOne,ACwONE\n', 'text/csv')})
    assert response.status_code == expected
    with SessionLocal() as db:
        assert db.query(Lead).count() == (1 if expected == 200 else 0)


def test_missing_sales_id_is_never_contacted(audit):
    seed_lead(sales_nav_id='')
    jobs.job_send_connections([1])
    jobs.li.send_connection_invite.assert_not_called()
    with SessionLocal() as db:
        assert 'no valid Sales Nav ID' in db.query(RunLog).one().log_text


@pytest.mark.parametrize('state,reason', [('paused', 'paused by user'), ('needs_reauth', 'session needs refresh'),
                                       ('seat_required', 'saved session requires Sales Navigator access')])
def test_connections_logs_actual_skip_reason(audit, state, reason):
    seed_lead()
    with SessionLocal() as db:
        db.get(Account, 1).status = state; db.commit()
    jobs.job_send_connections([1])
    jobs.li.send_connection_invite.assert_not_called()
    with SessionLocal() as db:
        assert f'skipped: {reason}' in db.query(RunLog).one().log_text


@pytest.mark.parametrize('open_flag', [False, True])
def test_send_attempt_failure_and_success_are_logged_separately(audit, monkeypatch, open_flag):
    seed_lead(opentomsg=open_flag)
    seed_lead(sales_nav_id='ACwSECOND', full_name='Second prospect', opentomsg=open_flag)
    method = 'send_inmail' if open_flag else 'send_connection_invite'
    channel = 'InMail' if open_flag else 'Invite'
    monkeypatch.setattr(jobs.li, method, Mock(side_effect=[(False, 'http', 'HTTP 409: offline rejection'), (True, None, '')]))
    jobs.job_send_connections([1])
    with SessionLocal() as db:
        row = db.query(RunLog).one()
        assert f'{channel} attempt -> Audit prospect' in row.log_text
        assert f'{channel} failed for Audit prospect: HTTP 409: offline rejection' in row.log_text
        assert f'{channel} sent -> Audit prospect' not in row.log_text
        assert f'{channel} sent -> Second prospect (confirmed)' in row.log_text
        assert row.status == 'partial'
        assert db.query(Lead).filter_by(full_name='Audit prospect').one().associate_account_id is None
        assert row.stats['audit/Audit account']['contacted'] == 1
        assert row.stats['audit · Totals']['contacted'] == 1


def test_stop_during_profile_wait_prevents_outbound_send(audit, monkeypatch):
    seed_lead(opentomsg=None)
    monkeypatch.setattr(jobs.li, 'get_profile_opentomsg', Mock(return_value=(False, 'https://www.linkedin.com/in/audit')))
    def stop(*args):
        runner._stop_event.set(); return False
    monkeypatch.setattr(jobs.li, 'polite_sleep', stop)
    jobs.job_send_connections([1])
    jobs.li.send_connection_invite.assert_not_called()
    with SessionLocal() as db:
        assert db.query(RunLog).one().status == 'stopped'


@pytest.mark.parametrize('body, expected', [
    ('{"value":"-1"}', 'bad_request'),
    ('{"message":"invalid request"}', 'bad_request'),
    ('{"message":"Email is not required"}', 'bad_request'),
    ('{"code":"EMAIL_REQUIRED"}', 'email_required'),
    ('{"message":"An email address is required to connect"}', 'email_required'),
    ('[]', 'bad_request'), ('null', 'bad_request'), ('"rejected"', 'bad_request'),
    ('', 'bad_request'), ('<html>Bad request</html>', 'bad_request')])
def test_http_400_only_reports_email_when_provider_confirms(body, expected):
    response = Mock(status_code=400, text=body)
    try:
        response.json.return_value = json.loads(body)
    except ValueError:
        response.json.side_effect = ValueError('no json')
    ok, error, detail = jobs.li._interpret(response, expect_validation=False)
    assert ok is False and error == expected
    if expected == 'email_required':
        assert detail == 'Email is required to connect'
    else:
        assert detail.startswith('HTTP 400: ')
        assert (body or 'No response details') in detail
        assert 'Email is required to connect' not in detail


@pytest.mark.parametrize('open_to_msg', [False, True])
def test_unknown_400_preserves_provider_detail_without_email_claim(audit, monkeypatch, open_to_msg):
    lid = seed_lead(opentomsg=open_to_msg)
    response = Mock(status_code=400, text='{"value":"-1"}')
    response.json.return_value = {'value': '-1'}
    failure = jobs.li._interpret(response, expect_validation=False)
    target = 'send_inmail' if open_to_msg else 'send_connection_invite'
    monkeypatch.setattr(jobs.li, target, Mock(return_value=failure))
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    with SessionLocal() as db:
        lead = db.get(Lead, lid)
        assert 'HTTP 400' in lead.last_error and '-1' in lead.last_error
        row = db.query(RunLog).one()
        assert 'Email is required' not in row.log_text
        assert 'lead retained for rollover' not in row.log_text
        assert 'not counted as sent' in row.log_text


# ---- Lead blocking on send errors (HTTP 400 "Email is required" etc.) ----

def test_invite_400_email_required_blocks_lead(audit, monkeypatch):
    """HTTP 400 Email-required: lead is marked BLOCKED_ERROR + last_error and
    is NOT retried by the next run."""
    lid = seed_lead()
    monkeypatch.setattr(jobs.li, 'send_connection_invite',
                        Mock(return_value=(False, 'email_required', 'Email is required to connect')))
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    with SessionLocal() as db:
        lead = db.get(Lead, lid)
        assert lead.status == 'BLOCKED_ERROR'
        assert 'Email is required' in lead.last_error
        kinds = [e.kind for e in lead.events]
        assert 'error' in kinds
    # Second run: the blocked lead is not picked up again.
    jobs.li.send_connection_invite.reset_mock()
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    jobs.li.send_connection_invite.assert_not_called()


def test_inmail_400_email_required_blocks_lead(audit, monkeypatch):
    lid = seed_lead(opentomsg=True)
    monkeypatch.setattr(jobs.li, 'send_inmail',
                        Mock(return_value=(False, 'email_required', 'Email is required to connect')))
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    with SessionLocal() as db:
        lead = db.get(Lead, lid)
        assert lead.status == 'BLOCKED_ERROR'
        assert 'Email is required' in lead.last_error


@pytest.mark.parametrize('error_kind', ['email_required', 'bad_request'])
def test_invite_400_streak_stops_account_and_releases_leads(audit, monkeypatch, error_kind):
    """Live incident: LinkedIn rejected EVERY connectV2 with an opaque 400 and
    each one burned a lead into BLOCKED_ERROR. A streak means the account is
    the problem (invitation cap / session), so after the 3rd consecutive
    rejection sending stops, the leads blocked during the streak are released
    back to '', and remaining leads are never attempted this run."""
    l1, l2, l3, l4 = (seed_lead(sales_nav_id=f'ACwSTREAK{i}') for i in range(4))
    invite = Mock(return_value=(False, error_kind, 'HTTP 400: rejection'))
    monkeypatch.setattr(jobs.li, 'send_connection_invite', invite)
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    assert invite.call_count == 3, 'streak limit reached, 4th lead untouched'
    with SessionLocal() as db:
        for lid in (l1, l2, l3):
            lead = db.get(Lead, lid)
            assert lead.status == '', 'streak-blocked leads must be released for retry'
            assert lead.last_error == ''
        assert db.get(Lead, l4).status == '', 'lead after the streak stop is never attempted'
        row = db.query(RunLog).order_by(RunLog.id.desc()).first()
        assert any('consecutive connect rejections' in (e or '') for e in (row.errors or []))
    # Next run retries them all — the 3 released leads plus l4, which was
    # never blocked (it rolled over untouched).
    invite.reset_mock()
    invite.return_value = (True, None, '')
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    assert invite.call_count == 4
    with SessionLocal() as db:
        assert [db.get(Lead, l).status for l in (l1, l2, l3, l4)] == ['INVITE_SENT'] * 4


@pytest.mark.parametrize('error_kind', ['email_required', 'bad_request'])
def test_inmail_400_streak_stops_account_and_releases_leads(audit, monkeypatch, error_kind):
    """Same circuit breaker on the first-touch InMail path: three consecutive
    400s stop the account and release the leads blocked during the streak."""
    l1, l2, l3 = (seed_lead(sales_nav_id=f'ACwSTREAKM{i}', opentomsg=True) for i in range(3))
    inmail = Mock(return_value=(False, error_kind, 'HTTP 400: rejection'))
    monkeypatch.setattr(jobs.li, 'send_inmail', inmail)
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    assert inmail.call_count == 3
    with SessionLocal() as db:
        for lid in (l1, l2, l3):
            lead = db.get(Lead, lid)
            assert lead.status == '' and lead.last_error == ''


def test_single_400_still_blocks_lead(audit, monkeypatch):
    """Isolated HTTP 400s (lead-specific problems) keep the existing pinned
    behavior: the lead is blocked and NOT retried, and the next lead after a
    400 succeeds so the streak never trips."""
    bad = seed_lead(sales_nav_id='ACwBAD400')
    good = seed_lead(sales_nav_id='ACwGOOD400')
    invite = Mock(side_effect=[(False, 'email_required', 'Email is required to connect'),
                               (True, None, '')])
    monkeypatch.setattr(jobs.li, 'send_connection_invite', invite)
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    assert invite.call_count == 2, 'good lead attempted after the isolated 400'
    with SessionLocal() as db:
        assert db.get(Lead, bad).status == 'BLOCKED_ERROR'
        assert db.get(Lead, good).status == 'INVITE_SENT'


def test_successful_send_resets_400_streak(audit, monkeypatch):
    """Two 400s then a success: the success resets the streak, so the guard
    never trips and the lead-specific blocks stand."""
    l1, l2, l3 = (seed_lead(sales_nav_id=f'ACwRS{i}') for i in range(3))
    invite = Mock(side_effect=[(False, 'email_required', 'Email is required to connect'),
                               (False, 'email_required', 'Email is required to connect'),
                               (True, None, '')])
    monkeypatch.setattr(jobs.li, 'send_connection_invite', invite)
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    assert invite.call_count == 3, 'streak reset by the success, guard never tripped'
    with SessionLocal() as db:
        assert db.get(Lead, l1).status == 'BLOCKED_ERROR'
        assert db.get(Lead, l2).status == 'BLOCKED_ERROR'
        assert db.get(Lead, l3).status == 'INVITE_SENT'


def test_rate_limit_does_not_block_lead(audit, monkeypatch):
    """429 is account-level: leads stay untouched for the next account/run."""
    lid = seed_lead()
    monkeypatch.setattr(jobs.li, 'send_connection_invite',
                        Mock(return_value=(False, 'rate_limited', 'HTTP 429')))
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    with SessionLocal() as db:
        lead = db.get(Lead, lid)
        assert lead.status == ''
        assert lead.last_error == ''


def test_reset_errors_endpoint_requeues_lead(audit, monkeypatch):
    lid = seed_lead()
    monkeypatch.setattr(jobs.li, 'send_connection_invite',
                        Mock(return_value=(False, 'email_required', 'Email is required to connect')))
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    with SessionLocal() as db:
        assert db.get(Lead, lid).status == 'BLOCKED_ERROR'
    r = audit.post('/api/leads/reset-errors', json={'ids': [lid]})
    assert r.status_code == 200, r.text
    assert r.json()['reset'] == 1
    with SessionLocal() as db:
        lead = db.get(Lead, lid)
        assert lead.status == ''
        assert lead.last_error == ''


def test_reset_errors_is_a_worker_guarded_noop_for_clean_leads(audit):
    lid = seed_lead()
    r = audit.post('/api/leads/reset-errors', json={'ids': [lid]})
    assert r.status_code == 200
    assert r.json() == {'ok': True, 'reset': 0, 'skipped': 1}


def test_pause_campaign_endpoint_toggles_status(audit):
    r = audit.put('/api/campaigns/1/pause', json={'status': 'paused'})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(Campaign, 1).status == 'paused'
    r = audit.put('/api/campaigns/1/pause', json={'status': 'active'})
    assert r.status_code == 200
    with SessionLocal() as db:
        assert db.get(Campaign, 1).status == 'active'
    assert audit.put('/api/campaigns/1/pause', json={'status': 'bogus'}).status_code == 422


def test_leads_api_reports_last_error_and_error_filter(audit, monkeypatch):
    lid = seed_lead()
    monkeypatch.setattr(jobs.li, 'send_connection_invite',
                        Mock(return_value=(False, 'email_required', 'Email is required to connect')))
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    items = audit.get('/api/leads').json()['items']
    row = next(i for i in items if i['id'] == lid)
    assert row['status'] == 'BLOCKED_ERROR'
    assert 'Email is required' in row['last_error']
    assert audit.get('/api/leads?error=only').json()['total'] == 1
    assert audit.get('/api/leads?error=none').json()['total'] == 0


def _login_restricted(client, username, campaigns, accounts):
    """Create + login a restricted user; returns nothing (cookie stays on client)."""
    with SessionLocal() as db:
        db.add(User(username=username, password_hash='x', display_name=username.title(),
                    role='viewer', allowed_campaign_ids=campaigns,
                    allowed_account_ids=accounts, active=True))
        db.commit()
    # The app hashes bootstrap passwords at startup; set a known one directly.
    from app.auth import hash_password
    with SessionLocal() as db:
        u = db.query(User).filter_by(username=username).one()
        u.password_hash = hash_password('pw-scoped')
        db.commit()
    r = client.post('/api/login', json={'username': username, 'password': 'pw-scoped'})
    assert r.status_code == 200, r.text


def test_dashboard_summary_scoped_for_restricted_user(audit):
    """A restricted user's dashboard counts only their allocated campaign/account."""
    with SessionLocal() as db:
        c2 = Campaign(name='Other campaign', campaign_key='other')
        a2 = Account(name='Other account', session_ref='offline')
        db.add_all([c2, a2]); db.flush()
        db.add(CampaignAccount(account_id=a2.id, campaign_id=c2.id))
        db.add(Lead(campaign_id=c2.id, associate_account_id=a2.id,
                    sales_nav_id='ACwOTHER', full_name='Out of scope'))
        db.commit()
        other_c, other_a = c2.id, a2.id
    seed_lead(associate_account_id=1)  # campaign 1 / account 1 = the restricted user's allocation
    _login_restricted(audit, 'scope-user', [1], [1])
    s = audit.get('/api/dashboard/summary').json()
    assert s['totals']['leads_total'] == 1, s['totals']
    assert s['totals']['campaigns_active'] == 1
    assert s['totals']['accounts_active'] == 1
    assert all(row['id'] != other_c for row in s['campaign_rates'])


def test_scoped_user_sees_untouched_pool_leads_of_their_campaigns(audit):
    """OR scope: a campaign manager sees every lead of their campaigns,
    INCLUDING untouched pool leads that no account owns yet."""
    with SessionLocal() as db:
        c2 = Campaign(name='Not mine', campaign_key='not-mine')
        db.add(c2); db.flush()
        db.add(Lead(campaign_id=1, sales_nav_id='ACwPOOL', full_name='Pool prospect'))  # untouched
        db.add(Lead(campaign_id=c2.id, sales_nav_id='ACwTHEIRS', full_name='Hidden prospect'))
        db.commit()
        other_c = c2.id
    _login_restricted(audit, 'scope-pool', [1], [1])
    leads = audit.get('/api/leads?page_size=50').json()
    names = {r['full_name'] for r in leads['items'] if 'items' in leads} or set()
    if not names:  # older payload shape: rows directly
        names = {r['full_name'] for r in leads.get('rows', [])}
    assert 'Pool prospect' in names, leads
    assert 'Hidden prospect' not in names
    assert leads['total'] == 1
    # CSV export matches the list
    csv = audit.get('/api/leads/export').text
    assert 'Pool prospect' in csv and 'Hidden prospect' not in csv
    assert other_c  # silence unused when payload shape differs


def test_scoped_user_account_access_does_not_cover_other_campaign_leads(audit):
    """Account access never grants access to another campaign's leads."""
    with SessionLocal() as db:
        c2 = Campaign(name='Other campaign', campaign_key='other-2')
        db.add(c2); db.flush()
        db.add(Lead(campaign_id=c2.id, associate_account_id=1,
                    sales_nav_id='ACwACCT', full_name='Account lead'))
        db.commit()
    _login_restricted(audit, 'scope-acct', [], [1])  # no campaigns, account 1 only
    total = audit.get('/api/leads?page_size=50').json()['total']
    assert total == 0


def test_runs_and_run_log_scoped_for_restricted_user(audit):
    """Run ownership hides other users and unattributed fleet output."""
    with SessionLocal() as db:
        if db.get(Campaign, 2) is None:
            c2 = Campaign(id=2, name='Runs other', campaign_key='runs-other')
            a2 = Account(id=2, name='Runs other account', session_ref='offline')
            db.add_all([c2, a2]); db.commit()
        mine = RunLog(job_type='send_connections', target='mine', dry_run=False,
                      status='success', campaign_id=1, account_id=1, started_at=__import__('datetime').datetime.utcnow())
        theirs = RunLog(job_type='send_connections', target='theirs', dry_run=False,
                        status='success', campaign_id=2, account_id=2, started_at=__import__('datetime').datetime.utcnow())
        fleet = RunLog(job_type='send_followups', target='fleet', dry_run=False,
                       status='success', started_at=__import__('datetime').datetime.utcnow())
        db.add_all([mine, theirs, fleet]); db.commit()
        theirs_id = theirs.id
    _login_restricted(audit, 'scope-user-runs', [1], [1])
    with SessionLocal() as db:
        db.get(RunLog, mine.id).owner_user_id = db.query(User).filter_by(username='scope-user-runs').one().id
        db.commit()
    items = audit.get('/api/runs').json()
    ids = {i['id'] for i in items}
    assert mine.id in ids and fleet.id not in ids and theirs.id not in ids
    assert audit.get(f'/api/runs/{theirs_id}/log').status_code == 404
    assert audit.get(f'/api/runs/{mine.id}/log').status_code == 200
