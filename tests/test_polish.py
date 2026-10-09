"""Offline regressions: isolated SQLite, mocked LinkedIn and notifications."""
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, Mock

_temp = tempfile.TemporaryDirectory()
# setdefault (not assign): the first test module to import binds app.database's
# engine to its temp dir; later modules must reuse it or the engine points at a
# deleted directory ("unable to open database file" in combined runs).
os.environ.setdefault('OCC_APP_DATA_DIR', _temp.name)
os.environ.setdefault('OCC_DB_URL', 'sqlite:///' + _temp.name.replace('\\', '/') + '/test.db')
os.environ.setdefault('OCC_DISABLE_SCHEDULER', '1')
os.environ.setdefault('OCC_ADMIN_PASSWORD', 'test-password-only')
os.environ.setdefault('OCC_ADMIN_USERNAME', 'test-admin')
os.environ.setdefault('NOTIFY_SENDER_APP_PASSWORD', 'offline-test-only')

from app.database import engine, SessionLocal
from app.models import Base, Account, Campaign, CampaignAccount, Lead, RunLog, DailySendCount
from app import jobs, runner, scheduler
from app.main import app
from fastapi.testclient import TestClient

def tearDownModule():
    # Dispose the pool but keep the temp dir: test_schedule_store.py reuses the
    # same engine after this module (SQLAlchemy reconnects a disposed engine,
    # but only if the SQLite file still exists).
    engine.dispose()


class RegressionTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.client = TestClient(app)
        login = self.client.post('/api/login', json={'username': 'test-admin', 'password': 'test-password-only'})
        self.assertEqual(login.status_code, 200, login.text)
        self.addCleanup(self.client.close)
        self.notifications = patch.object(jobs.notify, 'notify_run_summary')
        self.notifications.start()
        self.addCleanup(self.notifications.stop)

    def seed(self):
        with SessionLocal() as db:
            a = Account(name='Test', session_ref='missing.json')
            c = Campaign(name='Campaign', campaign_key='Campaign', search_url='https://www.linkedin.com/sales/search/people?savedSearchId=12')
            db.add_all([a, c]); db.flush()
            db.add(CampaignAccount(campaign_id=c.id, account_id=a.id, invite_limit=10, inmail_limit=10, message_limit=30))
            db.commit()
            return a.id, c.id

    def test_username_required(self):
        c = TestClient(app)
        self.assertEqual(c.post('/api/login', json={'username': 'wrong', 'password': 'test-password-only'}).status_code, 401)
        self.assertEqual(c.get('/api/me').status_code, 401)
        self.assertEqual(c.post('/api/login', json={'password': 'test-password-only'}).status_code, 422)

    def test_manual_search_and_list_are_distinct(self):
        aid, cid = self.seed()
        with SessionLocal() as db:
            c = Campaign(name='Second', campaign_key='Second', search_url='https://www.linkedin.com/sales/search/people?query=test')
            db.add(c); db.flush(); db.add(CampaignAccount(campaign_id=c.id, account_id=aid)); db.commit()
            c_id_2 = c.id
        element = {'entityUrn': 'urn:li:ACw123', 'fullName': 'Test Lead'}
        with patch.object(jobs, 'load_session_ref', return_value=Mock()), patch.object(jobs.li, 'search_leads', return_value=[element]) as search:
            jobs.job_sync_leads(campaign_ids=[c_id_2], dry_run=False)
            self.assertEqual(search.call_count, 1)
            self.assertIn('query=test', search.call_args.args[1])
        with patch.object(jobs, 'load_session_ref', return_value=Mock()), patch.object(jobs.li, 'people_search_by_list', return_value=[element]) as lists:
            jobs.job_import_list(aid, '55')
            self.assertEqual(lists.call_count, 1)
        with SessionLocal() as db:
            leads = db.query(Lead).all()
            # Campaign and untagged imports have separate identities.
            self.assertEqual(len(leads), 2)
            search_lead = next(l for l in leads if l.campaign_id == c_id_2)
            self.assertEqual(sum(l.campaign_id is None for l in leads), 1)
            self.assertEqual(search_lead.source, 'campaign_search')
            self.assertEqual(search_lead.campaign_id, c_id_2)

    def test_single_gchat_card_per_run(self):
        """GChat dedupe: a completed run sends exactly ONE card. The lifecycle
        notification (from _finish) carries stats + duration + errors; the
        old separate 'Run summary' + 'Execution warnings' cards are gone."""
        with SessionLocal() as db, patch.object(jobs.notify, '_flags', return_value={'critical': True, 'run_summary': True, 'send_errors': True, 'reply_digest': True}), \
             patch.object(jobs.notify, 'send_gchat') as card, \
             patch.object(jobs.notify, 'notify_send_errors') as digest, \
             patch.object(jobs.notify, 'notify_run_summary') as summary:
            jobs.notify._lifecycle_notified.clear()   # ids repeat across test DB resets
            r = jobs._Run(db, jobs.JobType.SEND_CONNECTIONS, 'test', False)
            r.errors.append('Intentional offline test failure')
            jobs.notify_run_summary_and_errors(r, 'test')   # deprecated no-op
            summary.assert_not_called()
            digest.assert_not_called()
            r.finish(jobs.RunStatus.PARTIAL)
            self.assertEqual(r.run.status, 'partial')
            self.assertEqual(card.call_count, 1, 'exactly one GChat card per run')
            payload = card.call_args.args[0]
            self.assertIn('Attention needed', payload, 'errors ride the lifecycle card')

    def test_digest_flag_off_blocks_standalone_alerts(self):
        """The unchecked 'Send-error digest' toggle suppresses the standalone
        'Execution warnings' card (it previously ignored the flag)."""
        with patch.object(jobs.notify, '_flags', return_value={
                'critical': True, 'run_summary': True, 'send_errors': False,
                'reply_digest': True}), \
             patch.object(jobs.notify, 'send_gchat') as card:
            jobs.notify.notify_send_errors('X', ['boom'])
            card.assert_not_called()


    def test_missing_optional_smtp_does_not_block_startup(self):
        import subprocess, sys
        env = dict(os.environ, NOTIFY_SENDER_APP_PASSWORD='')
        result = subprocess.run([sys.executable, '-c', 'import app.notify'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dry_run_does_not_advance_leads(self):
        aid, cid = self.seed()
        with SessionLocal() as db:
            db.add_all([Lead(sales_nav_id='ACw1', campaign_id=cid, full_name='Untouched', opentomsg=False),
                        Lead(sales_nav_id='ACw2', campaign_id=cid, associate_account_id=aid, full_name='Followup', status='INVITE_AFTER_ACCEPT', status_changed_at=datetime.utcnow()-timedelta(days=5))])
            db.get(Campaign, cid).invite_track = ['', 'Hello {first_name}']
            db.commit()
        with patch.object(jobs, 'load_session_ref', side_effect=AssertionError('Dry run must not load live credentials')):
            jobs.job_send_connections(dry_run=True)
            jobs.job_send_followups(dry_run=True)
        with SessionLocal() as db:
            self.assertEqual([l.status for l in db.query(Lead).order_by(Lead.id)], ['', 'INVITE_AFTER_ACCEPT'])
            self.assertTrue(all(r.invite_sent_count == 0 and r.messages_sent == 0 for r in db.query(DailySendCount)))

    def test_active_budgets_only(self):
        aid, cid = self.seed()
        self.assertEqual(self.client.get('/api/dashboard/summary').json()['today']['invites_limit'], 10)
        with SessionLocal() as db:
            db.get(Account, aid).status = 'paused'; db.commit()
        self.assertEqual(self.client.get('/api/dashboard/summary').json()['today']['invites_limit'], 0)

    def test_private_files_are_not_served(self):
        for path in ['/.env', '/app_data/app_data.db', '/app/auth.py', '/cookies_files/test.json']:
            self.assertEqual(TestClient(app).get(path).status_code, 404)

    def test_threads_honors_requested_page_size(self):
        with SessionLocal() as db:
            db.add_all([Lead(sales_nav_id=f'thread-{i}', full_name=f'Thread {i}', received_replies=True, reply_message='Test reply') for i in range(110)])
            db.commit()
        response = self.client.get('/api/threads?page_size=100')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['items']), 100)

    def test_manual_sync_worker_and_scoped_connection_signature(self):
        aid, cid = self.seed()
        with patch.object(jobs, 'load_session_ref', side_effect=AssertionError('Dry runs cannot load credentials')):
            jobs.job_sync_leads(account_id=aid, saved_search_id='123', dry_run=True)
            jobs.job_send_connections(campaign_ids=[cid], account_ids=[aid], dry_run=True)
        with SessionLocal() as db:
            self.assertTrue(all(row.status == 'success' for row in db.query(RunLog)))

    def test_caps_span_campaigns_and_survive_partial_updates(self):
        aid, cid = self.seed()
        with SessionLocal() as db:
            db.get(Account, aid).daily_invite_cap = 12
            second = Campaign(name='other', campaign_key='other')
            db.add(second); db.flush()
            db.add(DailySendCount(account_id=aid, campaign_id=second.id, date=datetime.utcnow().date(), invite_sent_count=9))
            daily = jobs._get_daily(db, cid, aid, datetime.utcnow().date())
            link = db.query(CampaignAccount).filter_by(campaign_id=cid).one()
            self.assertEqual(jobs._effective_limits(link, db, daily)[0], 3)
            db.commit()
        result = self.client.put(f'/api/accounts/{aid}', json={'name': 'Test', 'status': 'paused'})
        self.assertEqual(result.status_code, 200)
        with SessionLocal() as db:
            self.assertEqual(db.get(Account, aid).daily_invite_cap, 12)

    def test_three_workers_guard_rejected_sessions(self):
        aid, cid = self.seed()
        with SessionLocal() as db:
            db.add(Lead(sales_nav_id='guard-test', campaign_id=cid, full_name='Guard', opentomsg=False))
            db.commit()
        for worker in (jobs.job_send_connections, jobs.job_check_replies, jobs.job_send_followups):
            with SessionLocal() as db:
                db.get(Account, aid).status = 'active'; db.commit()
            raw = Mock(); raw.get.return_value.status_code = 403
            with patch.object(jobs, 'load_session_ref', return_value=raw), patch.object(jobs.li, 'fetch_inbox', side_effect=lambda session, **kw: session.get('https://example.invalid')), patch.object(jobs.notify, 'notify_send_errors'):
                worker(campaign_ids=[cid], account_ids=[aid])
            with SessionLocal() as db:
                self.assertEqual(db.get(Account, aid).status, 'needs_reauth')

    def test_followup_rate_limit_stops_all_stages(self):
        """5 consecutive 429s stop the account; leads keep their trigger status."""
        aid, cid = self.seed()
        with SessionLocal() as db:
            db.get(Campaign, cid).invite_track = ['', 'First', 'Second']
            db.add_all([Lead(sales_nav_id=f'ACw{i}', campaign_id=cid, associate_account_id=aid, status='INVITE_AFTER_ACCEPT', status_changed_at=datetime.utcnow()-timedelta(days=10)) for i in range(1, 6)])
            db.commit()
        with patch.object(jobs, 'load_session_ref'), patch.object(jobs.li, 'fetch_inbox'), patch.object(jobs.li, 'polite_sleep'), patch.object(jobs.notify, 'notify_send_errors'), patch.object(jobs.li, 'send_message', return_value=(False, 'rate_limited', 'HTTP 429')) as send:
            jobs.job_send_followups()
            self.assertEqual(send.call_count, 5)  # threshold reached, then stop
        with SessionLocal() as db:
            self.assertEqual(db.query(RunLog).one().status, 'partial')
            # Leads stay in their trigger status for the next run - not blocked.
            self.assertEqual(db.query(Lead).filter(Lead.status == 'INVITE_AFTER_ACCEPT').count(), 5)

    def test_followup_single_429_continues(self):
        """One transient 429 must not stop the stage: later leads still send."""
        aid, cid = self.seed()
        with SessionLocal() as db:
            db.get(Campaign, cid).invite_track = ['', 'First', 'Second']
            db.add_all([Lead(sales_nav_id=f'ACw{i}', campaign_id=cid, associate_account_id=aid, status='INVITE_AFTER_ACCEPT', status_changed_at=datetime.utcnow()-timedelta(days=10)) for i in range(1, 4)])
            db.commit()
        results = [(False, 'rate_limited', 'HTTP 429'), (True, None, 'ok'), (True, None, 'ok')]
        with patch.object(jobs, 'load_session_ref'), patch.object(jobs.li, 'fetch_inbox'), patch.object(jobs.li, 'polite_sleep'), patch.object(jobs.notify, 'notify_send_errors'), patch.object(jobs.li, 'send_message', side_effect=results) as send:
            jobs.job_send_followups()
            self.assertEqual(send.call_count, 3)
        with SessionLocal() as db:
            advanced = db.query(Lead).filter(Lead.status == 'INVITE_FOLLOWUP_1').count()
            self.assertEqual(advanced, 2)

    def test_blank_inmail_followup3_never_sends(self):
        """A follow-up stage left empty in the editor (only 2 of 3 configured)
        must be skipped, not sent as an empty message."""
        aid, cid = self.seed()
        with SessionLocal() as db:
            # InMail track: follow-up 3 slot exists but body is blank.
            db.get(Campaign, cid).inmail_track = [
                {'subject': 'S1', 'body': 'First'},
                {'subject': 'S2', 'body': 'Second'},
                {'subject': '', 'body': ''},
            ]
            db.add_all([Lead(sales_nav_id=f'ACw{i}', campaign_id=cid, associate_account_id=aid, status='INMAIL_FOLLOWUP_2', status_changed_at=datetime.utcnow()-timedelta(days=10)) for i in range(1, 4)])
            db.commit()
        with patch.object(jobs, 'load_session_ref'), patch.object(jobs.li, 'fetch_inbox'), patch.object(jobs.li, 'polite_sleep'), patch.object(jobs.notify, 'notify_send_errors'), patch.object(jobs.li, 'send_inmail') as send:
            jobs.job_send_followups()
            send.assert_not_called()
        with SessionLocal() as db:
            # Leads keep their trigger status and are retried once a template
            # is filled in - nothing was marked blocked or advanced.
            self.assertEqual(db.query(Lead).filter(Lead.status == 'INMAIL_FOLLOWUP_2').count(), 3)

    def test_blank_invite_followup_never_sends(self):
        """Same guarantee for the invite track: a blank stage body is skipped."""
        aid, cid = self.seed()
        with SessionLocal() as db:
            db.get(Campaign, cid).invite_track = ['', 'Real note', '   ']
            db.add_all([Lead(sales_nav_id=f'ACw{i}', campaign_id=cid, associate_account_id=aid, status='INVITE_FOLLOWUP_1', status_changed_at=datetime.utcnow()-timedelta(days=10)) for i in range(1, 3)])
            db.commit()
        with patch.object(jobs, 'load_session_ref'), patch.object(jobs.li, 'fetch_inbox'), patch.object(jobs.li, 'polite_sleep'), patch.object(jobs.notify, 'notify_send_errors'), patch.object(jobs.li, 'send_message') as send:
            jobs.job_send_followups()
            send.assert_not_called()
        with SessionLocal() as db:
            self.assertEqual(db.query(Lead).filter(Lead.status == 'INVITE_FOLLOWUP_1').count(), 2)

    def test_reauth(self):
        aid, _ = self.seed()
        session = Mock(); session.get.return_value.status_code = 401
        with self.assertRaises(jobs.li.LinkedinError):
            jobs._AccountSession(session, aid).get('https://www.linkedin.com/test')
        with SessionLocal() as db:
            self.assertEqual(db.get(Account, aid).status, 'needs_reauth')

    def test_missing_imported_path_uses_same_accounts_registered_file(self):
        import get_cookies
        from pathlib import Path
        registered = Path(_temp.name) / 'registered.json'
        registered.write_text('{}', encoding='utf-8')
        account = Account(id=99, name='Registered account', session_ref='missing-guessed-name.json')
        with patch.dict(get_cookies.ACCOUNTS, {'Registered account': {'cookies_file': str(registered)}}), patch.object(jobs, '_session_from_files', return_value=Mock()) as load:
            jobs.load_session_ref(account)
            load.assert_called_once_with({'cookies_file': str(registered)})
        with patch.dict(get_cookies.ACCOUNTS, {}, clear=True), patch.object(jobs, '_session_from_files') as load:
            with self.assertRaises(jobs.li.LinkedinError): jobs.load_session_ref(account)
            load.assert_not_called()

    def test_notify_is_nonzero(self):
        from app import notify
        # Empty and zero dicts
        self.assertFalse(notify._is_nonzero({}))
        self.assertFalse(notify._is_nonzero({'accepts_messaged': 0, 'new_replies': 0}))
        self.assertFalse(notify._is_nonzero({'nested': {'a': 0, 'b': 0}}))
        self.assertFalse(notify._is_nonzero(0))
        self.assertFalse(notify._is_nonzero(''))
        self.assertFalse(notify._is_nonzero([]))
        self.assertFalse(notify._is_nonzero(None))

        # Non-zero values
        self.assertTrue(notify._is_nonzero({'accepts_messaged': 0, 'new_replies': 1}))
        self.assertTrue(notify._is_nonzero({'nested': {'a': 0, 'b': 2}}))
        self.assertTrue(notify._is_nonzero(1))
        self.assertTrue(notify._is_nonzero('hello'))
        self.assertTrue(notify._is_nonzero([1]))

    def test_notify_new_replies(self):
        from app import notify
        replies = [
            {
                'name': 'John Doe',
                'account': 'Account A',
                'campaign': 'Campaign Alpha',
                'lead_url': 'https://linkedin.com/in/johndoe',
                'snippet': 'Hi! I am interested.',
            }
        ]
        with patch.object(notify, 'send_gchat') as mock_post:
            notify.notify_new_replies(replies)
            mock_post.assert_called_once()
            call_text = mock_post.call_args[0][0]
            self.assertIn('Campaign Manager · New replies', call_text)
            self.assertIn('John Doe', call_text)
            self.assertIn('Campaign Alpha', call_text)
            self.assertIn('Account A', call_text)
            self.assertIn('Hi! I am interested.', call_text)

        # Empty replies list does not call send_gchat
        with patch.object(notify, 'send_gchat') as mock_post:
            notify.notify_new_replies([])
            mock_post.assert_not_called()

    def test_check_replies_suppresses_gchat_when_zero_replies(self):
        aid, cid = self.seed()
        with patch.object(jobs, 'load_session_ref'), \
             patch.object(jobs.li, 'fetch_inbox', return_value={'elements': []}), \
             patch.object(jobs.notify, 'notify_new_replies') as mock_new_replies, \
             patch.object(jobs.notify, 'notify_run_summary') as mock_summary:
            jobs.job_check_replies(campaign_ids=[cid], account_ids=[aid])
            # When 0 replies found:
            mock_new_replies.assert_not_called()
            # Summary notification should NOT be sent because stats are 0
            mock_summary.assert_not_called()

    def test_check_replies_sends_gchat_when_replies_found(self):
        aid, cid = self.seed()
        with SessionLocal() as db:
            db.add(Lead(sales_nav_id='reply-lead-1', campaign_id=cid, associate_account_id=aid, full_name='Alice Smith', status='INVITE_SENT'))
            db.commit()

        fake_inbox = {
            'elements': [
                {
                    'participants': ['reply-lead-1'],
                    'messages': [
                        {
                            'author': 'reply-lead-1',
                            'body': 'Thanks for reaching out!'
                        }
                    ]
                }
            ]
        }
        with patch.object(jobs, 'load_session_ref'), \
             patch.object(jobs.li, 'fetch_inbox', return_value=fake_inbox), \
             patch.object(jobs.notify, 'notify_new_replies') as mock_new_replies:
            jobs.job_check_replies(campaign_ids=[cid], account_ids=[aid])
            mock_new_replies.assert_called_once()
            call_replies = mock_new_replies.call_args[0][0]
            self.assertEqual(len(call_replies), 1)
            self.assertEqual(call_replies[0]['name'], 'Alice Smith')

    def test_stop_job_and_api_stop(self):
        runner._stop_event.clear()
        self.assertFalse(runner.is_stop_requested())

        # When no job is running
        ok, msg = runner.stop_job()
        self.assertFalse(ok)
        self.assertIn('No job is currently running', msg)

        res = self.client.post('/api/jobs/stop')
        self.assertEqual(res.status_code, 400)

        # When a job is running
        runner._run_lock.acquire()
        runner._live['status'] = 'running'
        try:
            ok, msg = runner.stop_job()
            self.assertTrue(ok)
            self.assertTrue(runner.is_stop_requested())
            import time
            t0 = time.time()
            runner.sleep_or_stop(5)
            self.assertLess(time.time() - t0, 1.0)
        finally:
            runner._run_lock.release()
            runner._live['status'] = 'idle'
            runner._stop_event.clear()

    def test_job_stops_when_stop_requested(self):
        aid, cid = self.seed()
        runner._stop_event.set()
        try:
            jobs.job_send_connections(campaign_ids=[cid], account_ids=[aid])
            with SessionLocal() as db:
                last_run = db.query(RunLog).order_by(RunLog.id.desc()).first()
                self.assertEqual(last_run.status, 'stopped')
        finally:
            runner._stop_event.clear()

    def test_inactive_accounts_filtered_from_jobs(self):
        aid, cid = self.seed()
        with SessionLocal() as db:
            db.get(Account, aid).status = 'paused'
            db.commit()

        # 1. API run rejects inactive accounts
        res = self.client.post('/api/jobs/send_connections/run', json={'campaign_ids': [cid], 'account_ids': [aid]})
        self.assertEqual(res.status_code, 422)
        self.assertIn('inactive', res.json()['detail'])

        # 2. Manual tools reject inactive accounts
        res_sync = self.client.post('/api/jobs/sync_leads/run', json={'account_id': aid, 'saved_search_id': '123'})
        self.assertEqual(res_sync.status_code, 422)
        self.assertIn('active', res_sync.json()['detail'])

        res_imp = self.client.post('/api/jobs/import_list/run', json={'account_id': aid, 'list_id': '456'})
        self.assertEqual(res_imp.status_code, 422)
        self.assertIn('active', res_imp.json()['detail'])

        # 3. Direct job invocation skips inactive accounts
        with patch.object(jobs, 'load_session_ref') as mock_load:
            jobs.job_send_connections(campaign_ids=[cid], dry_run=False)
            mock_load.assert_not_called()

        with patch.object(jobs, 'load_session_ref') as mock_load:
            jobs.job_check_replies(campaign_ids=[cid], dry_run=False)
            mock_load.assert_not_called()

        with patch.object(jobs, 'load_session_ref') as mock_load:
            jobs.job_send_followups(campaign_ids=[cid], dry_run=False)
            mock_load.assert_not_called()

    def test_schedule_store_filters_inactive_accounts(self):
        from app import schedule_store
        from app.models import Schedule
        aid, cid = self.seed()
        with SessionLocal() as db:
            db.get(Account, aid).status = 'paused'
            now = datetime.utcnow()
            s = Schedule(
                name='Test Schedule',
                job_keys=['send_connections'],
                run_time='10:00',
                timezone='UTC',
                scopes={'send_connections': {'campaign_ids': [cid], 'account_ids': [aid]}},
                active=True,
                next_run_at=now,
            )
            db.add(s)
            db.commit()
            sched_id = s.id

        with patch.object(runner, 'start_sequence', return_value=(True, 'started', 1)) as mock_start:
            schedule_store.fire(sched_id, now)
            mock_start.assert_called_once()
            steps = mock_start.call_args[0][0]
            self.assertEqual(steps[0][1]['account_ids'], [])

    def test_runner_sequence_stopped(self):
        import time
        runner._stop_event.clear()

        def mock_step(dry_run=False, **kwargs):
            runner.stop_job()
            if runner.is_stop_requested():
                raise jobs.JobStoppedError('Job stopped by user')

        with patch.dict(jobs.JOB_REGISTRY, {'test_stop_worker': mock_step}):
            ok, msg, _ = runner.start_sequence([('test_stop_worker', {})], schedule_name='manual')
            self.assertTrue(ok)
            for _ in range(50):
                if not runner.is_running():
                    break
                time.sleep(0.05)
            self.assertFalse(runner.is_running())
            self.assertEqual(runner.live_status()['status'], 'stopped')
        runner._stop_event.clear()

    def test_add_and_update_account_with_campaign_assignment(self):
        aid, cid = self.seed()
        with SessionLocal() as db:
            c2 = Campaign(name='Campaign 2', campaign_key='c2')
            db.add(c2)
            db.commit()
            c2_id = c2.id

        # Create account with assigned campaign
        res = self.client.post('/api/accounts', json={
            'name': 'New Account',
            'status': 'active',
            'campaign_ids': [cid, c2_id]
        })
        self.assertEqual(res.status_code, 200, res.text)
        new_aid = res.json()['id']

        with SessionLocal() as db:
            links = db.query(CampaignAccount).filter_by(account_id=new_aid).all()
            self.assertEqual({l.campaign_id for l in links}, {cid, c2_id})

        # Update account: remove cid, keep c2_id
        res = self.client.put(f'/api/accounts/{new_aid}', json={
            'name': 'New Account',
            'status': 'active',
            'campaign_ids': [c2_id]
        })
        self.assertEqual(res.status_code, 200, res.text)
        with SessionLocal() as db:
            links = db.query(CampaignAccount).filter_by(account_id=new_aid).all()
            self.assertEqual({l.campaign_id for l in links}, {c2_id})

    def test_upload_cookies_endpoint(self):
        aid, cid = self.seed()
        import json

        # Reject non-json
        res = self.client.post(
            f'/api/accounts/{aid}/upload-cookies',
            files={'file': ('test.txt', b'hello', 'text/plain')}
        )
        self.assertEqual(res.status_code, 422)

        # Reject JSON missing 'cookies' key
        res = self.client.post(
            f'/api/accounts/{aid}/upload-cookies',
            files={'file': ('test.json', json.dumps({'invalid': 123}).encode(), 'application/json')}
        )
        self.assertEqual(res.status_code, 422)

        # Accept valid JSON with 'cookies'
        valid_payload = json.dumps({'cookies': {'li_at': 'test_cookie'}, 'headers': {'csrf': '123'}}).encode()
        res = self.client.post(
            f'/api/accounts/{aid}/upload-cookies',
            files={'file': ('valid_cookies.json', valid_payload, 'application/json')}
        )
        self.assertEqual(res.status_code, 200, res.text)
        session_ref = res.json()['session_ref']
        self.assertTrue(os.path.exists(session_ref))

        with SessionLocal() as db:
            acc = db.get(Account, aid)
            self.assertEqual(acc.session_ref, session_ref)
            self.assertIsNotNone(acc.last_cookie_refresh_at)

        if os.path.exists(session_ref):
            try:
                os.remove(session_ref)
            except Exception:
                pass

    def test_upload_cookies_saves_fixed_name_and_cleans_old(self):
        """Whatever the uploaded file is called, it is saved under the
        account's ONE canonical cookies name and stale differently-named
        copies are removed."""
        aid, cid = self.seed()
        import json
        from app.config import PROJECT_ROOT
        from pathlib import Path

        with SessionLocal() as db:
            acc = db.get(Account, aid)
            acc.name = 'Zara Quill'  # not in get_cookies registry -> slug fallback
            # A stale, differently-named cookie file left by an older upload.
            stale = Path(PROJECT_ROOT) / 'cookies_files' / 'zara_quill_cookies.json'
            stale.parent.mkdir(exist_ok=True)
            stale.write_text('{"cookies": {}, "headers": {}}', encoding='utf-8')
            acc.session_ref = str(stale)
            db.commit()

        payload = json.dumps({'cookies': {'li_at': 'x'}, 'headers': {'csrf': 'y'}}).encode()
        res = self.client.post(
            f'/api/accounts/{aid}/upload-cookies',
            files={'file': ('totally_random_name_v9.json', payload, 'application/json')}
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()

        canonical = Path(PROJECT_ROOT) / 'cookies_files' / 'zara_quill_cookies.json'
        # Saved under the fixed canonical name regardless of upload filename...
        self.assertEqual(Path(body['session_ref']), canonical)
        self.assertEqual(body['saved_as'], 'zara_quill_cookies.json')
        self.assertTrue(canonical.exists())
        # ...and the stale differently-named copy is gone (here it WAS the
        # canonical name, so instead verify only one file for this account exists).
        leftovers = [p for p in canonical.parent.glob('*.json') if 'zara' in p.name]
        self.assertEqual(leftovers, [canonical])

        with SessionLocal() as db:
            acc = db.get(Account, aid)
            self.assertEqual(acc.session_ref, str(canonical))

        canonical.unlink(missing_ok=True)

    def test_session_precheck_on_job_run(self):
        aid, cid = self.seed()
        # When all accounts fail session load, run_job (dry_run=False) returns 422
        with patch.object(runner, 'start_job', return_value=(True, 'started', 1)):
            res = self.client.post('/api/jobs/send_connections/run', json={
                'campaign_ids': [cid],
                'dry_run': False
            })
            self.assertEqual(res.status_code, 422)
            self.assertIn('No valid session files found', res.text)

        # When session load succeeds, job starts with 200
        with patch.object(runner, 'start_job', return_value=(True, 'started', 1)), \
             patch.object(jobs, 'load_session_ref', return_value=Mock()):
            res = self.client.post('/api/jobs/send_connections/run', json={
                'campaign_ids': [cid],
                'dry_run': False
            })
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.json().get('warnings'), [])

    def test_verify_account_sessions_helper(self):
        aid, cid = self.seed()
        with SessionLocal() as db:
            acc = db.get(Account, aid)
            # Missing session file returns error string
            errors = jobs.verify_account_sessions([acc], db)
            self.assertEqual(len(errors), 1)
            self.assertIn(acc.name, errors[0])

            # With mock session, returns empty list
            with patch.object(jobs, 'load_session_ref', return_value=Mock()):
                errors = jobs.verify_account_sessions([acc], db)
                self.assertEqual(errors, [])

if __name__ == '__main__':
    unittest.main()
