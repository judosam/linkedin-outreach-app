"""GChat lifecycle: no 'Started' starter messages, one rich summary per run.

Covers the user report: a plain '▶ Campaign Manager · Follow-ups / Started'
arriving at job start. Started notifications are removed; completion summaries
are fancy (headers, duration, metrics, title-cased keys) and sent exactly once,
including for multi-campaign runs (previously double-notified via
notify_run_summary_and_errors + _finish).
"""
import os
import tempfile

import pytest

temp = tempfile.TemporaryDirectory()
os.environ.update(
    OCC_APP_DATA_DIR=temp.name,
    OCC_DB_URL='sqlite:///' + temp.name.replace('\\', '/') + '/ui.db',
    OCC_DISABLE_SCHEDULER='1',
    NOTIFY_SENDER_APP_PASSWORD='x',
)

from fastapi.testclient import TestClient  # noqa: E402

import app.jobs as jobs  # noqa: E402
import app.notify as notify  # noqa: E402
from app.database import engine  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Clean tables per test so unique constraints never collide."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    notify._lifecycle_notified.clear()
    yield


def setUpModule():
    Base.metadata.create_all(engine)


def tearDownModule():
    engine.dispose()


@pytest.fixture()
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture()
def gchat(monkeypatch):
    """Capture every send_gchat payload with a faked webhook."""
    sent = []
    monkeypatch.setattr(notify, '_webhook_url', lambda: 'http://hook.test/abc')
    monkeypatch.setattr(notify, 'send_gchat', lambda text: sent.append(text) or True)
    return sent


def _auth(client):
    r = client.post('/api/login', json={'username': 'test-admin', 'password': 'test-password-only'})
    assert r.status_code == 200, r.text
    return 'cookie'  # session rides on the TestClient cookie jar


def test_no_started_message_on_run_start(gchat):
    """Starting a run must not send the '▶ … Started' starter message."""
    from app.models import Campaign, RunLog
    from app.database import SessionLocal
    from app.jobs import _Run
    from app.models import JobType

    db = SessionLocal()
    db.add(Campaign(name='C1', campaign_key='c1'))
    db.commit()

    run = _Run(db, JobType.SEND_FOLLOWUPS, 'All campaigns/accounts', False)
    assert gchat == [], "a 'Started' message went out at job start"

    run.finish()
    assert len(gchat) == 1, f'expected exactly one completion message, got {len(gchat)}'
    body = gchat[0]
    assert 'Started' not in body
    assert 'Follow-ups' in body
    db.close()


def test_summary_is_fancy(gchat):
    """Completion summary: title-cased metric keys, duration, formatted values."""
    from app.models import RunStatus
    from app.jobs import _Run
    from app.models import JobType
    from app.database import SessionLocal

    db = SessionLocal()
    run = _Run(db, JobType.SEND_FOLLOWUPS, 'All campaigns/accounts', False)
    run.stats['invites_sent'] = 12
    run.stats['messages_sent'] = '5/30'
    run.stats['leads_processed'] = 40
    run.finish()
    body = gchat[-1]
    assert '✅' in body and 'Completed' in body
    assert 'Invites sent: 12' in body          # title-cased key
    assert 'Messages sent: 5/30' in body       # '5/30' not '5 / 30'
    assert 'All campaigns/accounts · ' in body  # compact meta line (context · duration)
    db.close()


def test_single_summary_for_send_followups(gchat, monkeypatch):
    """Multi-campaign send_followups must send ONE summary (was double)."""
    from app.models import Campaign, Account, Lead, CampaignAccount, JobType
    from app.database import SessionLocal

    db = SessionLocal()
    camp = Campaign(name='C1', campaign_key='c1')
    acct = Account(name='A1', session_ref='ref')
    db.add_all([camp, acct])
    db.commit()
    db.add(CampaignAccount(campaign_id=camp.id, account_id=acct.id, order_index=0))
    db.add(Lead(sales_nav_id='u1', campaign_id=camp.id, associate_account_id=acct.id,
                status='invited', last_followup_stage='stage_1', opentomsg=True))
    db.commit()
    camp_id, acct_id = camp.id, acct.id
    db.close()

    import app.runner as runner
    monkeypatch.setattr(runner, 'is_stop_requested', lambda: False)

    class FakeSession:
        def send(self, *a, **k):
            return True, None, 'ok'

    monkeypatch.setattr(jobs, '_AccountSession', lambda *a, **k: FakeSession())
    monkeypatch.setattr(jobs, 'load_session_ref', lambda account: object(), raising=True)

    # Run the job synchronously (no browser, no background thread).
    jobs.job_send_followups([camp_id], [acct_id], dry_run=False)

    summaries = [t for t in gchat if 'Completed' in t]
    assert len(summaries) == 1, f'expected 1 summary, got {len(summaries)}: {gchat}'
    assert 'Follow-ups' in summaries[0]


def test_no_summary_when_stopped_or_dry(gchat):
    """Stopped runs and dry runs stay silent (existing contract preserved)."""
    from app.jobs import notify_run_summary_and_errors
    from app.models import RunLog, RunStatus

    run_row = RunLog(job_type='send_followups', target='t', dry_run=False,
                     status=RunStatus.STOPPED.value, started_at=__import__('datetime').datetime.utcnow())
    notify_run_summary_and_errors(type('R', (), {'run': run_row, 'dry_run': True, 'stats': {}, 'errors': []})(), 'Follow-ups')
    notify_run_summary_and_errors(type('R', (), {'run': run_row, 'dry_run': False, 'stats': {}, 'errors': []})(), 'Follow-ups')
    assert gchat == []


def test_stopped_lifecycle_silent():
    """A stopped run's lifecycle notification is suppressed."""
    from app.models import RunLog, RunStatus
    row = RunLog(job_type='send_followups', target='t', dry_run=False,
                 status=RunStatus.STOPPED.value, started_at=__import__('datetime').datetime.utcnow())
    assert notify.notify_lifecycle(row) is False


@pytest.mark.parametrize('stats', [{}, {'Cxo Podcast/Cynthia David': {'accepts_messaged': 0, 'new_replies': 0}},
    {'c/a': {'accepts_messaged': '0', 'new_replies': None, 'scanned': 30, 'label': 'done'}}])
def test_check_replies_zero_activity_stays_silent(gchat, stats):
    from app.database import SessionLocal
    with SessionLocal() as db:
        run = jobs._Run(db, jobs.JobType.CHECK_REPLIES, 'All campaigns/accounts', False)
        run.stats.update(stats)
        run.finish()
        assert gchat == []


def test_per_account_stats_are_friendly_outcomes(gchat):
    """Per-account lines: bold name + natural verb outcomes. Plumbing and zeros hidden."""
    from notification_format import message
    text = message('check_replies', 'partial', 'All campaigns/accounts', metrics={
        'Cxo Podcast/Kimberly Morrison': {'records_to_check': 177, 'pending_invites': 96,
                                          'threads_fetched': 90, 'threads_matched': 50,
                                          'accepts_found': 1, 'accepts_messaged': 1, 'new_replies': 0},
        'Idle campaign/Account': {'accepts_messaged': 0, 'new_replies': 0},
        'GCC/Ranganathan A': {'contacted': 3, 'invites_sent': 2, 'inmails_sent': 1, 'leftover': 12},
    }, errors=['CXO Podcast/Cynthia David: no Sales Navigator seat'], duration=45.6)
    assert '*Cxo Podcast/Kimberly Morrison* — 🤝 1 invite accept messaged' in text
    assert '*GCC/Ranganathan A* — 👥 Contacted: 3 · ✉️ Invites sent: 2 · ⚡ InMails sent: 1 · ⏳ Left for next run: 12' in text
    assert 'accepts found' not in text.lower()            # accepts_found is plumbing now
    assert 'Idle campaign/Account' not in text            # all-zero account omitted
    assert 'New replies: 0' not in text and ': 0' not in text  # zeros never shown
    assert 'Records To Check' not in text and 'Threads Fetched' not in text
    assert 'Pending Invites' not in text
    assert 'All campaigns/accounts · 45.6s' in text       # compact meta line


def test_connections_card_splits_by_account_with_totals(gchat):
    """Connections runs render one bold line per account plus a campaign Totals
    line — mirroring the Follow-ups card the user asked for. Accounts that sent
    nothing are omitted; the Totals line shows the campaign aggregate."""
    from notification_format import message
    text = message('send_connections', 'partial', 'CXO Podcast · All active campaigns', metrics={
        'CXO Podcast/Andrew Dreger': {'contacted': 62, 'invites_sent': 42, 'inmails_sent': 20},
        'CXO Podcast/Anne Davis': {'contacted': 40, 'invites_sent': 30, 'inmails_sent': 10},
        'CXO Podcast/Cynthia David': {'contacted': 0, 'invites_sent': 0, 'inmails_sent': 0},
        'CXO Podcast · Totals': {'contacted': 102, 'invites_sent': 72, 'inmails_sent': 30, 'leftover': 153},
    }, errors=['CXO Podcast/Andrew Dreger: Invite failed for Taleb Hammad: HTTP 400: {"value":"-1"}'],
        duration=1949.0)
    assert '*CXO Podcast/Andrew Dreger* — 👥 Contacted: 62 · ✉️ Invites sent: 42 · ⚡ InMails sent: 20' in text
    assert '*CXO Podcast/Anne Davis* — 👥 Contacted: 40 · ✉️ Invites sent: 30 · ⚡ InMails sent: 10' in text
    assert '*CXO Podcast · Totals* — 👥 Contacted: 102 · ✉️ Invites sent: 72 · ⚡ InMails sent: 30 · ⏳ Left for next run: 153' in text
    # Send counters always visible, even at zero (user request) — an account
    # that sent nothing still shows its 0/0 line instead of vanishing.
    assert '*CXO Podcast/Cynthia David* — ✉️ Invites sent: 0 · ⚡ InMails sent: 0' in text
    assert 'CXO Podcast · All active campaigns · 32m 29s' in text


def test_zero_top_level_metrics_are_hidden(gchat):
    """Top-level zero metrics (Leads added: 0 …) never render; non-zero and budgets do."""
    from notification_format import message
    text = message('send_followups', 'success', metrics={
        'leads_processed': 0, 'invites_sent': 12, 'messages_sent': '5/30'})
    assert 'Leads processed' not in text
    assert 'Invites sent: 12' in text and 'Messages sent: 5/30' in text


@pytest.mark.parametrize('metric', ['accepts_messaged', 'new_replies'])
def test_check_replies_activity_sends_once_and_omits_idle_accounts(gchat, metric):
    from app.database import SessionLocal
    with SessionLocal() as db:
        run = jobs._Run(db, jobs.JobType.CHECK_REPLIES, 'All campaigns/accounts', False)
        run.stats.update({'Active campaign/Account': {metric: 1},
                          'Idle campaign/Account': {'accepts_messaged': 0, 'new_replies': 0}})
        run.finish()
        notify.notify_lifecycle(run.run)
        assert len(gchat) == 1
        assert 'active campaign/account' in gchat[0].lower()
        assert 'idle campaign/account' not in gchat[0].lower()
        assert 'Idle campaign/Account' in run.run.stats


@pytest.mark.parametrize('http_status,payload,account_status', [
    (200, {'elements': []}, 'active'),
    (403, {'code': 'SALES_SEAT_REQUIRED'}, 'seat_required'),
    (401, {'message': 'Session expired'}, 'needs_reauth'),
])
def test_check_replies_worker_zero_activity_never_sends_chat(gchat, monkeypatch, http_status, payload, account_status):
    from unittest.mock import Mock
    from app.database import SessionLocal
    from app.models import Account, Campaign, CampaignAccount, RunLog
    import app.runner as runner
    monkeypatch.setattr(runner, 'is_stop_requested', lambda: False)
    raw = Mock()
    raw.get.return_value.status_code = http_status
    raw.get.return_value.json.return_value = payload
    monkeypatch.setattr(jobs, 'load_session_ref', lambda account: raw)
    with SessionLocal() as db:
        account = Account(name='Offline Nandhini', session_ref='mocked')
        campaign = Campaign(name='Offline campaign', campaign_key='offline')
        db.add_all([account, campaign]); db.flush()
        db.add(CampaignAccount(account_id=account.id, campaign_id=campaign.id))
        db.commit()
        account_id, campaign_id = account.id, campaign.id
    jobs.job_check_replies([campaign_id], [account_id], dry_run=False)
    with SessionLocal() as db:
        assert db.get(Account, account_id).status == account_status
        assert db.query(RunLog).one().status in ('success', 'partial')
    assert gchat == []


def test_import_savedsearch_consolidated_summary():
    """Import runs collapse repetitive scraper progress into a clean 2-line summary."""
    from notification_format import message
    text = message('sync_leads', 'success', 'NZ - Kimberly - I/O / Kimberly Morrison · SavedSearch 1999474756',
                   metrics={'page': 20, 'page_extracted': 20, 'extracted': 495, 'added': 495,
                            'total': 495, 'total_pages': 20, 'percent': 100, 'action': 'Importing leads',
                            'new_leads': 495}, duration=378.0)
    assert '📥 *Campaign Manager* • *Import Completed*' in text
    assert 'NZ - Kimberly - I/O / Kimberly Morrison' in text
    assert '📊 *Import Summary:*' in text
    assert '👥 *New Leads Added:* 495 leads' in text
    assert '📄 *Pages Processed:* 20 / 20 (100% complete)' in text
    assert 'Page: 20' not in text  # no ugly repetitive raw keys


def test_standby_zero_send_card():
    """Zero-send runs clearly indicate standby status and safety budget holding."""
    from notification_format import message
    text = message('send_connections', 'success', 'NZ-David-VAEcom / Cindy Smith · All active campaigns',
                   metrics={'NZ-David-VAEcom · Totals': {'invites_sent': 0, 'inmails_sent': 0, 'leftover': 354}},
                   duration=0.0)
    assert '🛡️ *Campaign Manager* • *Connections Standby*' in text
    assert '🔒 *Budget Status:* Weekly limit or safety interval active' in text
    assert '⏳ Left for next run: 354' in text


def test_friendly_error_cleaning():
    """Cryptic errors like HTTP 400 JSON and seat errors are formatted cleanly."""
    from notification_format import message
    text = message('send_connections', 'partial', 'NZ-David-VAEcom',
                   errors=['Invite failed for Sanghamitra Pati: HTTP 400: {"value":"-1"} (request rejected)',
                           'CXO Podcast/David Bodiford: no Sales Navigator seat'])
    assert '⚠️ *Attention needed:*' in text
    assert 'Invite rejected by LinkedIn (weekly limit or profile privacy)' in text
    assert 'No Sales Navigator seat assigned' in text
    assert '{"value":"-1"}' not in text


def test_notify_new_replies_card_format(gchat):
    """Inbound lead replies format into modern quotation cards."""
    from app.notify import notify_new_replies
    replies = [
        {'name': 'Pravin Dsouza', 'campaign': 'GCC', 'account': 'Ranganathan A',
         'message': "Hi Ranganathan, Thanks for reaching out, but I'm not interested."},
        {'name': 'Rajeev Purohit', 'campaign': 'GCC', 'account': 'Ranganathan A',
         'snippet': "Hi, I am on a business travel and headed back home by 20 September"}
    ]
    notify_new_replies(replies)
    assert len(gchat) == 1
    body = gchat[0]
    assert '📬 *Campaign Manager · New replies* • *2 New Replies Received!*' in body
    assert '🎯 *Account:* GCC / Ranganathan A' in body
    assert '👤 *Pravin Dsouza*' in body
    assert '💬 _"Hi Ranganathan, Thanks for reaching out, but I\'m not interested."_' in body or '💬 _Hi Ranganathan' in body
    assert '👉 *Action:* Reply directly in Sales Navigator' in body

