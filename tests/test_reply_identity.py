"""Offline inbox regressions: canonical DB IDs versus LinkedIn participant URNs."""
from unittest.mock import Mock

import pytest

from app import jobs, runner
from app.database import engine, SessionLocal
from app.models import Base, Account, Campaign, CampaignAccount, Lead, RunLog, DailySendCount


def urn(identity, context='NAME_SEARCH'):
    return f'urn:li:fs_salesProfile:({identity},{context},offline)'


@pytest.fixture
def inbox_fixture(monkeypatch):
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    runner._stop_event.clear()
    with SessionLocal() as db:
        db.add(Account(id=1, name='Ranganathan fixture', session_ref='offline'))
        db.add(Campaign(id=1, name='GCC fixture', campaign_key='GCC', invite_track=['Hi {first_name}']))
        db.flush(); db.add(CampaignAccount(campaign_id=1, account_id=1, message_limit=30))
        db.commit()
    fetch = Mock(return_value={'elements': []})
    send = Mock(return_value=(True, None, ''))
    monkeypatch.setattr(jobs, 'load_session_ref', Mock())
    monkeypatch.setattr(jobs.li, 'fetch_inbox', fetch)
    monkeypatch.setattr(jobs.li, 'send_message', send)
    monkeypatch.setattr(jobs.li, 'polite_sleep', lambda *a: True)
    monkeypatch.setattr(jobs.notify, 'notify_new_replies', Mock())
    yield fetch, send
    runner._stop_event.clear()


def seed(identity='ACwLEAD', **kw):
    data = dict(sales_nav_id=identity, campaign_id=1, associate_account_id=1,
                full_name='Offline lead', first_name='Offline', status='INVITE_SENT')
    data.update(kw)
    with SessionLocal() as db:
        lead = Lead(**data); db.add(lead); db.commit(); return lead.id


def stats(db):
    return db.query(RunLog).order_by(RunLog.id.desc()).first().stats['GCC/Ranganathan fixture']


def test_four_accepts_match_bare_db_ids_and_send_full_recipient_once(inbox_fixture):
    fetch, send = inbox_fixture
    recipients = [urn(f'ACwLEAD{i}') for i in range(4)]
    for i in range(4): seed(f'ACwLEAD{i}')

    fetch.return_value = {'elements': [{'participants': [p, urn('ACwSELF')],
        'messages': [{'type': 'INVITATION', 'author': p}]} for p in recipients]}
    jobs.job_check_replies([1], [1])
    # Leads without a stored URN fall back to the bare token as recipient.
    assert [c.args[1] for c in send.call_args_list] == [f'ACwLEAD{i}' for i in range(4)]
    with SessionLocal() as db:
        result = stats(db)
        assert (result['records_to_check'], result['pending_invites'], result['threads_matched']) == (4, 4, 4)
        assert (result['accepts_found'], result['accepts_messaged']) == (4, 4)
        assert db.query(Lead).filter_by(status='INVITE_AFTER_ACCEPT').count() == 4
        assert db.query(DailySendCount).one().messages_sent == 4
        assert 'Found 4 invite accepts' in db.query(RunLog).one().log_text
    jobs.job_check_replies([1], [1])
    assert send.call_count == 4


def test_after_accept_recipient_uses_stored_urn_like_raw_scripts(inbox_fixture):
    """Leads with a stored sales_nav_urn (from the xlsx merge / sync) get the
    exact URN as the createMessage recipient — byte-for-byte what the raw
    scripts send from the sheets."""
    fetch, send = inbox_fixture
    lead_id = seed('ACwURN01', sales_nav_urn=urn('ACwURN01', 'NAME_SEARCH'))
    fetch.return_value = {'elements': [{'participants': [urn('ACwURN01'), urn('ACwSELF')],
        'messages': [{'type': 'INVITATION', 'author': urn('ACwURN01')}]}]}
    jobs.job_check_replies([1], [1])
    assert [c.args[1] for c in send.call_args_list] == [urn('ACwURN01', 'NAME_SEARCH')]
    with SessionLocal() as db:
        assert db.get(Lead, lead_id).status == 'INVITE_AFTER_ACCEPT'


def test_reply_author_normalized_and_prevents_after_accept_send(inbox_fixture):
    fetch, send = inbox_fixture
    identity = 'ACwLEAD'
    lead_id = seed(urn(identity, 'OLD_CONTEXT'))
    fetch.return_value = {'elements': [{'participants': [urn(identity), urn('ACwSELF')], 'messages': [
        {'type': 'INVITATION', 'author': urn('ACwSELF')},
        {'type': 'MESSAGE', 'author': urn(identity, 'NEW_CONTEXT'), 'body': 'Please stop'},
        {'type': 'MESSAGE', 'author': urn('ACwSELF'), 'body': 'Our own message'},
    ]}]}
    jobs.job_check_replies([1], [1])
    send.assert_not_called()
    with SessionLocal() as db:
        lead = db.get(Lead, lead_id)
        assert lead.received_replies is True and lead.reply_message == 'Please stop'
        assert stats(db)['new_replies'] == 1
        assert stats(db)['accepts_messaged'] == 0


def test_own_messages_and_other_campaign_account_never_match(inbox_fixture):
    fetch, send = inbox_fixture
    lead_id = seed()
    with SessionLocal() as db:
        db.add(Account(id=2, name='Other owner', session_ref='offline')); db.commit()
    seed('ACwOTHER', associate_account_id=2)
    fetch.return_value = {'elements': [
        {'participants': [urn('ACwLEAD'), urn('ACwSELF')], 'messages': [
            {'type': 'MESSAGE', 'author': urn('ACwSELF'), 'body': 'Own message'}]},
        {'participants': [urn('ACwOTHER'), urn('ACwSELF')], 'messages': [{'type': 'INVITATION'}]},
    ]}
    jobs.job_check_replies([1], [1])
    send.assert_not_called()
    with SessionLocal() as db:
        assert db.get(Lead, lead_id).received_replies is False
        assert stats(db)['records_to_check'] == 1 and stats(db)['new_replies'] == 0


@pytest.mark.parametrize('error', ['http', 'rate_limited'])
def test_failed_after_accept_retains_status_and_records_error(inbox_fixture, error):
    fetch, send = inbox_fixture
    lead_id = seed()
    fetch.return_value = {'elements': [{'participants': [urn('ACwLEAD')], 'messages': [{'type': 'INVITATION'}]}]}
    send.return_value = (False, error, 'offline rejection')
    jobs.job_check_replies([1], [1])
    with SessionLocal() as db:
        assert db.get(Lead, lead_id).status == 'INVITE_SENT'
        assert db.query(DailySendCount).one().messages_sent == 0
        row = db.query(RunLog).one()
        assert row.status == 'partial' and 'Offline lead' in row.errors[0]


def test_exhausted_budget_still_counts_accepts_and_detects_replies(inbox_fixture):
    fetch, send = inbox_fixture
    seed('ACwACCEPT'); seed('ACwREPLY')
    with SessionLocal() as db:
        db.query(CampaignAccount).one().message_limit = 0; db.commit()
    fetch.return_value = {'elements': [
        {'participants': [urn('ACwACCEPT')], 'messages': [{'type': 'INVITATION'}]},
        {'participants': [urn('ACwREPLY')], 'messages': [{'type': 'MESSAGE', 'author': urn('ACwREPLY'), 'body': 'Hello'}]},
    ]}
    jobs.job_check_replies([1], [1]); send.assert_not_called()
    with SessionLocal() as db:
        assert stats(db)['accepts_found'] == 1 and stats(db)['new_replies'] == 1


def test_dry_run_reports_not_checked_without_inbox_or_send(inbox_fixture):
    fetch, send = inbox_fixture
    seed()
    jobs.job_check_replies([1], [1], dry_run=True)
    fetch.assert_not_called(); send.assert_not_called()
    with SessionLocal() as db:
        assert 'not checked' in stats(db)['note']


def test_inactive_account_skip_is_visible(inbox_fixture):
    fetch, send = inbox_fixture
    seed()
    with SessionLocal() as db:
        db.get(Account, 1).status = 'seat_required'; db.commit()
    jobs.job_check_replies([1], [1])
    fetch.assert_not_called(); send.assert_not_called()
    with SessionLocal() as db:
        assert 'reply check skipped: account status seat_required' in db.query(RunLog).one().log_text


def test_inbox_network_wait_does_not_hold_database_write_lock(inbox_fixture):
    fetch, _ = inbox_fixture
    seed()
    def concurrent_ui_write(*args, **kwargs):
        with SessionLocal() as db:
            db.get(Account, 1).total_runs = 7
            db.commit()
        return {'elements': []}
    fetch.side_effect = concurrent_ui_write
    jobs.job_check_replies([1], [1])
    with SessionLocal() as db:
        assert db.get(Account, 1).total_runs == 7


def test_seat_error_on_after_accept_send_keeps_run_alive(inbox_fixture):
    """Regression: the inbox fetch succeeded, but the seat was rejected on the
    first after-acceptance SEND. That exception used to escape the whole job
    -> run marked 'error' -> 'Failed' worker alert, even though earlier
    accounts had already messaged their accepts. It must instead stop this
    account and finish the run as partial (errors recorded, run alive)."""
    fetch, send = inbox_fixture
    p = urn('ACwLEAD')
    seed('ACwLEAD')
    fetch.return_value = {'elements': [{'participants': [p, urn('ACwSELF')],
        'messages': [{'type': 'INVITATION', 'author': p}]}]}
    send.side_effect = jobs.li.SeatRequiredError('Account does not have a Sales Navigator seat')
    jobs.job_check_replies([1], [1])
    run = _last_run()
    assert run.status == 'partial', f'run must survive the seat error, got {run.status}'
    assert any('no Sales Navigator seat' in (e or '') for e in (run.errors or []))
    with SessionLocal() as db:
        lead = db.query(Lead).one()
        assert lead.status == 'INVITE_SENT', 'lead must be retried next run, not marked sent'


def test_seat_error_on_send_connections_invite_keeps_run_alive(inbox_fixture):
    """Same mid-run seat loss on the invites worker: the account stops, the
    run completes as partial instead of dying with a fatal alert."""
    _fetch, _send = inbox_fixture
    with SessionLocal() as db:
        link = db.query(CampaignAccount).one()
        link.invite_limit = 10; db.commit()
        db.add(Lead(sales_nav_id='ACwINVITE', campaign_id=1, associate_account_id=1,
                    full_name='Invite lead', first_name='Invite', opentomsg=False))
        db.commit()
    monkeypatch_local = inbox_fixture  # reuse mocks already installed
    jobs.li.get_profile_opentomsg = Mock(return_value=(False, ''))
    jobs.li.send_connection_invite = Mock(
        side_effect=jobs.li.SeatRequiredError('Account does not have a Sales Navigator seat'))
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    run = _last_run()
    assert run.status == 'partial', f'run must survive the seat error, got {run.status}'
    assert any('no Sales Navigator seat' in (e or '') for e in (run.errors or []))


def test_extract_profile_id_accepts_aco_and_acw_tokens():
    """CSV people exports carry ACo flagship member tokens, not Sales Nav
    ACw tokens. Both shapes must resolve; the trailing NAME_SEARCH context of
    a decorated URN must never be captured."""
    from app.linkedin import extract_profile_id
    aco = 'ACoAAAFtXGIB0Kc5d6uJ1eYORalkpzZGt_yHrYU'
    acw = 'ACwAAA0pQn1ABCdef123-_x'
    assert extract_profile_id(aco) == aco
    assert extract_profile_id(f'urn:li:fs_salesProfile:({aco},NAME_SEARCH,Bj-9)') == aco
    assert extract_profile_id(acw) == acw
    assert extract_profile_id(f'urn:li:fs_salesProfile:({acw},NAME_SEARCH,z)') == acw
    assert extract_profile_id('(ACwX,NAME_SEARCH,z)') == 'ACwX'
    assert extract_profile_id('') is None
    assert extract_profile_id('no id here') is None


def test_aco_lead_with_urn_gets_invited_not_skipped(inbox_fixture):
    """The user's CSV leads (ACo ids) were all logged as 'has no valid Sales
    Nav ID - outreach skipped' because extract_profile_id only matched ACw.
    A seeded ACo lead must now go through the invite path exactly like the
    legacy salesApiConnection.py did (connectV2 member = the ACo token)."""
    _fetch, _send = inbox_fixture
    aco = 'ACoAAAFtXGIB0Kc5d6uJ1eYORalkpzZGt_yHrYU'
    with SessionLocal() as db:
        link = db.query(CampaignAccount).one()
        link.invite_limit = 10; db.commit()
        db.add(Lead(sales_nav_id=aco,
                    sales_nav_urn=f'urn:li:fs_salesProfile:({aco},NAME_SEARCH,Bj-9)',
                    campaign_id=1, associate_account_id=1,
                    full_name='Prasad Acharya', first_name='Prasad', opentomsg=False))
        db.commit()
    orig_opentomsg, orig_invite = jobs.li.get_profile_opentomsg, jobs.li.send_connection_invite
    jobs.li.get_profile_opentomsg = Mock(return_value=(False, 'http://www.linkedin.com/in/prasad-acharya-7960288'))
    jobs.li.send_connection_invite = Mock(return_value=(True, None, ''))
    try:
        jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
        jobs.li.send_connection_invite.assert_called_once()
        assert jobs.li.send_connection_invite.call_args.args[1] == aco
    finally:
        jobs.li.get_profile_opentomsg, jobs.li.send_connection_invite = orig_opentomsg, orig_invite
    with SessionLocal() as db:
        lead = db.query(Lead).one()
        assert lead.status == 'INVITE_SENT'
        assert lead.associate_account_id == 1
        assert 'no valid Sales Nav ID' not in db.query(RunLog).one().log_text


def test_aco_lead_inmail_uses_stored_urn_recipient(inbox_fixture):
    """First-touch InMail to an imported ACo lead must pass the stored
    decorated URN verbatim as the createMessage recipient — same byte-for-byte
    payload the sheets pipeline sent."""
    _fetch, _send = inbox_fixture
    aco = 'ACoAAAQsc1wBOhbRvYJ0SiIP9stahLae-WWnMTE'
    full_urn = f'urn:li:fs_salesProfile:({aco},NAME_SEARCH,4ohj)'
    seed(aco, sales_nav_urn=full_urn, opentomsg=True,
         linkedin_url='http://www.linkedin.com/in/ushasrikanth', status='')
    orig_inmail = jobs.li.send_inmail
    jobs.li.send_inmail = Mock(return_value=(True, None, ''))
    try:
        jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
        jobs.li.send_inmail.assert_called_once()
        assert jobs.li.send_inmail.call_args.args[1] == full_urn
    finally:
        jobs.li.send_inmail = orig_inmail
    with SessionLocal() as db:
        assert db.query(Lead).one().status == 'INMAIL_SENT'


def _last_run():
    from app.database import SessionLocal as _SL
    from app.models import RunLog as _RL
    with _SL() as db:
        row = db.query(_RL).order_by(_RL.id.desc()).first()
        row.errors = list(row.errors or [])
        return row
        assert db.query(RunLog).one().status == 'success'
