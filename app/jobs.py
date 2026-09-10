"""The five pipeline jobs, re-implemented on the database with the exact
Part-A behavior:

- Budget model: (campaign, account, day) holds invite_sent_count +
  opentomsg_count (enforced by send_connections) and the SHARED
  messages_sent counter consumed by check_replies (after-accept sends) and
  send_followups, each capped at round(message_limit / 2).
- Status machine: INVITE_SENT -> INVITE_AFTER_ACCEPT -> INVITE_FOLLOWUP_1..3
  (+3/+5/+7 days) and INMAIL_SENT -> INMAIL_FOLLOWUP_1..3 (+3/+5/+7).
- received_replies excludes a lead from ALL further automated sends.
- send_connections rolls unhandled leads to the NEXT account in the
  campaign's ordered list; leftovers stay unassigned for the next run.
- Distinct failure handling: 400 -> mark reason, no auto-retry; 429 -> stop
  account's loop, keep lead; validation error -> stop InMail sends for run.

Every run is recorded in run_logs; every outbound action appends a LeadEvent.
"""
import json
import random
import time as _time
import traceback
from datetime import datetime, date, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import Session as OrmSession

from .database import SessionLocal
from .models import (
    Account, Campaign, CampaignAccount, Lead, LeadEvent, DailySendCount,
    RunLog, JobType, RunStatus, LeadStatus, LeadSource,
)
from . import linkedin as li
from . import notify


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.utcnow()


def _template_format(text, first_name, calendar_url):
    if not text:
        return ''
    return text.format(first_name=first_name or '', calendar_url=calendar_url or '')


def _add_event(db: OrmSession, lead_id: int, kind: str, detail: str, job_type: str | None):
    db.add(LeadEvent(lead_id=lead_id, kind=kind, detail=detail[:2000], job_type=job_type))


def _get_daily(db: OrmSession, campaign_id: int, account_id: int, day: date) -> DailySendCount:
    row = db.execute(
        select(DailySendCount).where(
            DailySendCount.campaign_id == campaign_id,
            DailySendCount.account_id == account_id,
            DailySendCount.date == day,
        )
    ).scalar_one_or_none()
    if row is None:
        row = DailySendCount(campaign_id=campaign_id, account_id=account_id, date=day)
        db.add(row)
        db.flush()
    return row


def _set_status(db: OrmSession, lead: Lead, new_status: str, job_type: str, detail: str = ''):
    if lead.status != new_status:
        old = lead.status or '(none)'
        lead.status = new_status
        lead.status_changed_at = _now()
        _add_event(db, lead.id, 'status_change', f"{old} -> {new_status}" + (f": {detail}" if detail else ''), job_type)


def _runner_logger(run: RunLog):
    """Collect log lines into the run record (kept in memory until finish)."""
    lines = []

    def log(message):
        line = f"[{_now().strftime('%H:%M:%S')}] {message}"
        lines.append(line)
        print(message)  # also visible in server console

    log.lines = lines
    return log


def _finish(run, db, status, stats, errors=None):
    run.status = status.value if hasattr(status, 'value') else status
    run.finished_at = _now()
    run.duration_s = (run.finished_at - run.started_at).total_seconds()
    run.stats = stats
    run.errors = errors or []
    run.log_text = '\n'.join(run._log_lines)[-60000:]
    db.commit()


class _Run:
    """Context manager wrapping one run_log row + logger."""

    def __init__(self, db: OrmSession, job_type: JobType, target: str, dry_run: bool,
                 campaign_id=None, account_id=None):
        self.db = db
        self.run = RunLog(
            job_type=job_type.value, campaign_id=campaign_id, account_id=account_id,
            target=target, dry_run=dry_run, status=RunStatus.RUNNING.value, started_at=_now(),
        )
        db.add(self.run)
        db.commit()
        self.log = _runner_logger(self.run)
        self.run._log_lines = self.log.lines  # attach for _finish
        self.dry_run = dry_run
        self.stats = {}
        self.errors = []

    def finish(self, status: RunStatus = RunStatus.SUCCESS):
        _finish(self.run, self.db, status, self.stats, self.errors)

    def abort(self, exc: Exception):
        """Finalize THIS run's row as errored (self-healing on fatal exceptions)."""
        try:
            self.run.status = RunStatus.ERROR.value
            self.run.finished_at = _now()
            self.run.duration_s = (self.run.finished_at - self.run.started_at).total_seconds()
            self.run.errors = [str(exc)[:1000]]
            self.run.log_text = '\n'.join(getattr(self.run, '_log_lines', []))[-60000:]
            self.db.commit()
        except Exception:
            self.db.rollback()


def _has_session_files(account: Account) -> bool:
    return bool(account.session_ref)


# ---------------------------------------------------------------------------
# JOB 1 — SYNC CAMPAIGN LEADS (batch: all campaigns, all search URLs)
# ---------------------------------------------------------------------------

def _lead_from_element(element, campaign_id, source=LeadSource.CAMPAIGN_SEARCH, list_id=None):
    current_position = (element.get('currentPositions') or [{}])[0]
    return dict(
        sales_nav_id=element.get('entityUrn', ''),
        first_name=element.get('firstName', ''),
        last_name=element.get('lastName', ''),
        full_name=element.get('fullName', ''),
        title=current_position.get('title', ''),
        summary=element.get('summary', ''),
        location=element.get('geoRegion', ''),
        company=current_position.get('companyName', ''),
        premium=str(element.get('premium', '')),
        pending_invitation=str(element.get('pendingInvitation', '')),
        viewed=str(element.get('viewed', '')),
        opentomsg=None,
        source=source.value if hasattr(source, 'value') else source,
        list_id=str(list_id) if list_id is not None else None,
        campaign_id=campaign_id,
    )


def _upsert_lead(db: OrmSession, data: dict) -> bool:
    """Insert unless (sales_nav_id, campaign_id) already exists. Returns True if new."""
    existing = db.execute(
        select(Lead).where(
            Lead.sales_nav_id == data['sales_nav_id'],
            Lead.campaign_id == data['campaign_id'],
        )
    ).scalar_one_or_none()
    if existing is not None:
        # refresh profile fields but never touch engagement state
        for field in ('full_name', 'title', 'summary', 'location', 'company',
                      'premium', 'pending_invitation', 'viewed', 'linkedin_url'):
            if data.get(field):
                setattr(existing, field, data[field])
        return False
    db.add(Lead(**data))
    return True


def job_sync_leads(campaign_ids: list[int] | None = None, dry_run=False):
    """JOB 1: one BATCH run over every active campaign. Campaign-level search_url
    runs with the first account's session; per-account overrides run with their
    own session. New leads are tagged with the campaign and added to the pool."""
    run = None
    db = SessionLocal()
    try:
        run = _Run(db, JobType.SYNC_LEADS, 'All active campaigns', dry_run)
        log = run.log
        campaigns = db.execute(
            select(Campaign).where(Campaign.status == 'active')
            .order_by(Campaign.id)
        ).scalars().all()
        if campaign_ids:
            campaigns = [c for c in campaigns if c.id in campaign_ids]

        sessions = {}  # account_id -> curl_cffi session (reused across campaigns)

        def _session_for(account: Account):
            if account.id not in sessions:
                sessions[account.id] = load_session_ref(account)
            return sessions[account.id]

        any_error = False
        for campaign in campaigns:
            if campaign.status != 'active':
                continue
            found_for_campaign = 0
            searches = []  # (account, url)
            if campaign.search_url:
                if campaign.account_links:
                    searches.append((campaign.account_links[0].account, campaign.search_url))
            for link in campaign.account_links:
                if link.search_url_override:
                    searches.append((link.account, link.search_url_override))

            for account, url in searches:
                log(f"[{campaign.campaign_key}] Searching via {account.name}")
                if dry_run:
                    log(f"[{campaign.campaign_key}] DRY RUN - search POST skipped, simulating 0 new leads")
                    continue
                try:
                    session = _session_for(account)
                    total_pages = 0
                    new_leads = 0
                    for start in range(0, li.MAX_START, li.PAGE_SIZE):
                        elements = li.search_leads(session, url, start)
                        if not elements:
                            break
                        added = 0
                        for element in elements:
                            data = _lead_from_element(element, campaign.id)
                            if data['sales_nav_id'] and _upsert_lead(db, data):
                                added += 1
                        new_leads += added
                        total_pages += 1
                        db.commit()
                        if len(elements) < li.PAGE_SIZE:
                            break
                        _time.sleep(random.uniform(10, 15))
                    found_for_campaign += new_leads
                    log(f"[{campaign.campaign_key}] {url[:60]}...: {new_leads} new lead(s) across {total_pages} page(s)")
                except Exception as e:
                    any_error = True
                    run.errors.append(f"[{campaign.campaign_key}] search failed: {e}")
                    log(f"[{campaign.campaign_key}] 🚫 search failed: {e}")

            run.stats[campaign.campaign_key] = {'leads_added': found_for_campaign}
            db.commit()

        notify_run_summary_and_errors(run, 'Sync Campaign Leads')
        run.finish(RunStatus.PARTIAL if any_error else RunStatus.SUCCESS)
    except Exception as e:
        db.rollback()
        _fatal(db, JobType.SYNC_LEADS, e, run_row=run.run if run else None)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# JOB 2 — IMPORT FROM LIST (manual one-off, untagged leads)
# ---------------------------------------------------------------------------

def job_import_list(account_id: int, list_id: str, dry_run=False):
    """JOB 2: separate manual tool - imports a numeric Sales Navigator List ID
    via the List-pivot people-search endpoint. Leads land UNTAGGED
    (campaign_id NULL, source=list_import); assignment happens later manually."""
    run = None
    db = SessionLocal()
    try:
        account = db.get(Account, account_id)
        run = _Run(db, JobType.IMPORT_LIST, f"{account.name} · list {list_id}", dry_run,
                   account_id=account_id)
        log = run.log
        if account is None:
            run.errors.append(f"Account {account_id} not found")
            run.finish(RunStatus.ERROR)
            return

        if dry_run:
            run.stats['leads_added'] = 0
            log(f"DRY RUN - list import skipped for {account.name}")
            run.finish()
            return

        session = load_session_ref(account)
        new_total = 0
        for start in range(0, li.MAX_START, li.PAGE_SIZE):
            elements = li.people_search_by_list(session, int(list_id), start)
            if not elements:
                break
            added = 0
            for element in elements:
                data = _lead_from_element(element, campaign_id=None,
                                          source=LeadSource.LIST_IMPORT, list_id=list_id)
                # Untagged imports: dedupe on (sales_nav_id, campaign NULL)
                if data['sales_nav_id'] and not _upsert_lead_untagged(db, data):
                    continue
                added += 1
            new_total += added
            db.commit()
            if len(elements) < li.PAGE_SIZE:
                break
            _time.sleep(random.uniform(10, 15))

        run.stats['leads_added'] = new_total
        log(f"Imported {new_total} new untagged lead(s) from list {list_id}")
        notify_run_summary_and_errors(run, 'Import from List')
        run.finish()
    except Exception as e:
        db.rollback()
        _fatal(db, JobType.IMPORT_LIST, e, run_row=run.run if run else None)
    finally:
        db.close()


def _upsert_lead_untagged(db: OrmSession, data: dict) -> bool:
    existing = db.execute(
        select(Lead).where(
            Lead.sales_nav_id == data['sales_nav_id'],
            Lead.campaign_id.is_(None),
            Lead.source == LeadSource.LIST_IMPORT.value,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    db.add(Lead(**data))
    return True


# ---------------------------------------------------------------------------
# JOB 3 — SEND CONNECTIONS
# ---------------------------------------------------------------------------

def job_send_connections(campaign_ids: list[int] | None = None, dry_run=False):
    """JOB 3: for each campaign, fill leads through the campaign's accounts IN
    ORDER; an account sends until its own budgets are exhausted, then leftovers
    roll to the next account. OpenLink -> InMail (needs inmail budget);
    otherwise invite (needs invite budget)."""
    run = None
    db = SessionLocal()
    today = date.today()
    try:
        run = _Run(db, JobType.SEND_CONNECTIONS, 'All active campaigns', dry_run)
        log = run.log
        campaigns = db.execute(
            select(Campaign).where(Campaign.status == 'active').order_by(Campaign.id)
        ).scalars().all()
        if campaign_ids:
            campaigns = [c for c in campaigns if c.id in campaign_ids]

        for campaign in campaigns:
            links = sorted(campaign.account_links, key=lambda l: l.order_index)
            if not links:
                continue

            # Today's untouched leads for this campaign (no status, not pending).
            untouched = db.execute(
                select(Lead).where(
                    Lead.campaign_id == campaign.id,
                    Lead.status == '',
                    Lead.pending_invitation != 'True',
                ).order_by(Lead.id)
            ).scalars().all()

            remaining = list(untouched)
            if not remaining:
                run.stats[campaign.campaign_key] = {'note': 'no untouched leads'}
                continue
            log(f"[{campaign.campaign_key}] {len(remaining)} untouched lead(s)")

            campaign_stats = {'contacted': 0, 'leftover': 0}

            for link in links:
                if not remaining:
                    break
                account = link.account
                if account.status != 'active':
                    log(f"[{campaign.campaign_key}/{account.name}] paused - rolling leads to next account")
                    continue

                daily = _get_daily(db, campaign.id, account.id, today)
                invite_count = daily.invite_sent_count
                inmail_count = daily.opentomsg_count

                log(f"[{campaign.campaign_key}/{account.name}] "
                    f"budget: InMail {inmail_count}/{link.inmail_limit}, Invite {invite_count}/{link.invite_limit}")

                if invite_count >= link.invite_limit and inmail_count >= link.inmail_limit:
                    log(f"[{campaign.campaign_key}/{account.name}] both budgets exhausted - rolling to next account")
                    continue

                # Seat check via inbox fetch (same probe the legacy script used)
                session = load_session_ref(account)
                if not dry_run:
                    try:
                        li.fetch_inbox(session, count=10)
                    except li.SeatRequiredError:
                        log(f"[{campaign.campaign_key}/{account.name}] no Sales Nav seat - skipping account")
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: no Sales Navigator seat")
                        continue
                    except li.LinkedinError as e:
                        log(f"[{campaign.campaign_key}/{account.name}] inbox probe failed: {e}")
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: {e}")
                        continue

                account_contacted = 0
                leftover = []
                inmail_stopped = False  # MESSAGE_VALIDATION_PLUGIN_ERROR trips this

                for i, lead in enumerate(remaining, 1):
                    if inmail_count >= link.inmail_limit and invite_count >= link.invite_limit:
                        leftover.extend(remaining[i - 1:])
                        break

                    open_flag = lead.opentomsg
                    if open_flag is None:
                        if dry_run:
                            log(f"[{campaign.campaign_key}/{account.name}] DRY RUN: would fetch OpenLink for {lead.full_name}")
                            leftover.append(lead)
                            continue
                        try:
                            open_flag, profile_url = li.get_profile_opentomsg(session, lead.sales_nav_id)
                            lead.opentomsg = open_flag
                            lead.linkedin_url = profile_url
                            db.commit()
                            li.polite_sleep(5, 10)
                        except li.LinkedinError as e:
                            log(f"[{campaign.campaign_key}/{account.name}] OpenLink fetch failed for {lead.full_name}: {e}")
                            leftover.append(lead)
                            continue

                    calendar_url = link.calendar_url or ''
                    first_name = lead.first_name or lead.full_name or ''

                    if open_flag and inmail_count < link.inmail_limit and not inmail_stopped:
                        body = _template_format(campaign.inmail_text, first_name, calendar_url)
                        subject = _template_format(campaign.inmail_subject, first_name, calendar_url) or f"A quick note for {first_name}"
                        log(f"[{campaign.campaign_key}/{account.name}] InMail -> {lead.full_name}")
                        if dry_run:
                            ok, err_kind, detail = True, None, 'dry-run'
                        else:
                            ok, err_kind, detail = li.send_inmail(session, lead.sales_nav_id, subject, body)
                            li.polite_sleep()
                        if ok:
                            inmail_count += 1
                            daily.opentomsg_count = inmail_count
                            _set_status(db, lead, LeadStatus.INMAIL_SENT.value, JobType.SEND_CONNECTIONS.value)
                            lead.associate_account_id = account.id
                            _add_event(db, lead.id, 'outbound', f"InMail sent by {account.name}", JobType.SEND_CONNECTIONS.value)
                            campaign_stats['contacted'] += 1
                            account_contacted += 1
                            db.commit()
                        else:
                            if err_kind == 'validation':
                                log(f"[{campaign.campaign_key}/{account.name}] InMail validation error: {detail} - stopping InMails for this account this run")
                                inmail_stopped = True
                                leftover.append(lead)
                            elif err_kind == 'rate_limited':
                                log(f"[{campaign.campaign_key}/{account.name}] rate-limited - stopping this account")
                                run.errors.append(f"{campaign.campaign_key}/{account.name}: HTTP 429")
                                leftover.append(lead)
                                break
                            else:
                                lead_reason = 'InMail send failed' if err_kind != 'email_required' else 'Email is required to connect'
                                _set_status(db, lead, LeadStatus.NONE.value, JobType.SEND_CONNECTIONS.value,
                                            detail=f"blocked: {lead_reason}")
                                _add_event(db, lead.id, 'error', f"InMail failed: {detail}", JobType.SEND_CONNECTIONS.value)
                                db.commit()
                                leftover.append(lead)
                                li.polite_sleep(10, 20)

                    elif not open_flag and invite_count < link.invite_limit:
                        note = _template_format(campaign.invite_text, first_name, calendar_url)
                        profile_id = li.extract_profile_id(lead.sales_nav_id)
                        log(f"[{campaign.campaign_key}/{account.name}] Invite -> {lead.full_name}")
                        if dry_run:
                            ok, err_kind, detail = True, None, 'dry-run'
                        else:
                            ok, err_kind, detail = li.send_connection_invite(session, profile_id, note)
                            li.polite_sleep()
                        if ok:
                            invite_count += 1
                            daily.invite_sent_count = invite_count
                            _set_status(db, lead, LeadStatus.INVITE_SENT.value, JobType.SEND_CONNECTIONS.value)
                            lead.associate_account_id = account.id
                            _add_event(db, lead.id, 'outbound', f"Connection invite sent by {account.name}", JobType.SEND_CONNECTIONS.value)
                            campaign_stats['contacted'] += 1
                            account_contacted += 1
                            db.commit()
                        else:
                            if err_kind == 'rate_limited':
                                log(f"[{campaign.campaign_key}/{account.name}] rate-limited - stopping this account")
                                run.errors.append(f"{campaign.campaign_key}/{account.name}: HTTP 429")
                                leftover.append(lead)
                                break
                            reason = 'Email is required to connect' if err_kind == 'email_required' else 'Connection request failed'
                            _set_status(db, lead, LeadStatus.NONE.value, JobType.SEND_CONNECTIONS.value,
                                        detail=f"blocked: {reason}")
                            _add_event(db, lead.id, 'error', f"Invite failed: {detail}", JobType.SEND_CONNECTIONS.value)
                            db.commit()
                            leftover.append(lead)
                            li.polite_sleep(10, 20)
                    else:
                        # No budget for this lead's path on this account
                        leftover.append(lead)

                db.commit()
                log(f"[{campaign.campaign_key}/{account.name}] done: contacted {account_contacted}, "
                    f"final InMail {inmail_count}/{link.inmail_limit}, Invite {invite_count}/{link.invite_limit}")
                remaining = leftover

            campaign_stats['leftover'] = len(remaining)
            if remaining:
                log(f"[{campaign.campaign_key}] {len(remaining)} lead(s) left over - all accounts exhausted")
            run.stats[campaign.campaign_key] = campaign_stats
            db.commit()

        notify_run_summary_and_errors(run, 'Send Connections')
        run.finish()
    except Exception as e:
        db.rollback()
        _fatal(db, JobType.SEND_CONNECTIONS, e, run_row=run.run if run else None)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Shared: sessions + notifications plumbing
# ---------------------------------------------------------------------------

def load_session_ref(account: Account):
    """Resolve an Account row to a live curl_cffi session via get_cookies."""
    from get_cookies import ACCOUNTS as LEGACY_ACCOUNTS, load_session
    # Map by account name; fall back to the legacy default mapping.
    config = LEGACY_ACCOUNTS.get(account.name) or {
        'cookies_file': account.session_ref or f"./cookies_files/{account.name.split()[0].lower()}_cookies.json",
        'user_data_dir': f"./user_data/user_data_{account.name.split()[0].lower()}",
    }
    return load_session(account.name) if account.name in LEGACY_ACCOUNTS else _session_from_files(config)


def _session_from_files(config):
    import curl_cffi
    session = curl_cffi.Session()
    try:
        with open(config['cookies_file'], 'r', encoding='utf-8') as f:
            data = json.load(f)
        session.headers.update(data.get('headers', {}))
        session.cookies.update(data.get('cookies', {}))
    except Exception as e:
        raise li.LinkedinError(f"Could not load session for {config}: {e}")
    return session


def notify_run_summary_and_errors(run, label):
    """GChat summary + per-target error digests for one finished run."""
    try:
        notify.notify_run_summary({label: run.stats})
    except Exception as e:
        print(f"⚠️ run summary notification failed: {e}")


def _fatal(db: OrmSession, job_type: JobType, exc: Exception, run_row: RunLog | None = None):
    """Finalize the job's own run row (preferred), else the latest stuck 'running'
    row, else a fresh '(fatal)' row — then alert immediately."""
    traceback.print_exc()
    try:
        row = run_row
        if row is None:
            row = db.query(RunLog).filter_by(
                job_type=job_type.value, status=RunStatus.RUNNING.value
            ).order_by(RunLog.id.desc()).first()
        if row is not None:
            row.status = RunStatus.ERROR.value
            row.finished_at = _now()
            row.duration_s = (row.finished_at - row.started_at).total_seconds() if row.started_at else 0
            row.errors = [str(exc)[:1000]]
        else:
            db.add(RunLog(
                job_type=job_type.value, target='(fatal)', status=RunStatus.ERROR.value,
                started_at=_now(), finished_at=_now(), duration_s=0, errors=[str(exc)[:1000]],
            ))
        db.commit()
    except Exception:
        db.rollback()
        pass
    try:
        notify.notify_critical(str(job_type.value), exc)
    except Exception:
        pass


def recover_stuck_runs():
    """On startup, mark rows left 'running' by a crash as errored."""
    db = SessionLocal()
    try:
        stuck = db.query(RunLog).filter_by(status=RunStatus.RUNNING.value).all()
        for row in stuck:
            row.status = RunStatus.ERROR.value
            row.finished_at = _now()
            row.errors = row.errors or ['interrupted by server restart']
        if stuck:
            db.commit()
            print(f"[recovery] marked {len(stuck)} interrupted run(s) as errored")
    except Exception:
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# JOB 4 — CHECK REPLIES
# ---------------------------------------------------------------------------

def job_check_replies(campaign_ids: list[int] | None = None, account_ids: list[int] | None = None, dry_run=False):
    """JOB 4: invite-accept detection + reply detection per (campaign, account).

    - Accepts: leads at INVITE_SENT with no reply whose thread starts with an
      INVITATION message get invite_track[0] sent (status -> INVITE_AFTER_ACCEPT).
      Draws from the SHARED messages_sent budget, capped at round(message_limit/2).
    - Replies: any thread message authored BY THE LEAD marks received_replies,
      stores reply_message, and queues the reply digest email.
    """
    run = None
    db = SessionLocal()
    today = date.today()
    try:
        run = _Run(db, JobType.CHECK_REPLIES, 'All campaigns/accounts', dry_run)
        log = run.log
        campaigns = db.execute(select(Campaign).order_by(Campaign.id)).scalars().all()
        if campaign_ids:
            campaigns = [c for c in campaigns if c.id in campaign_ids]

        replies_found = []

        for campaign in campaigns:
            links = sorted(campaign.account_links, key=lambda l: l.order_index)
            for link in links:
                if account_ids and link.account_id not in account_ids:
                    continue
                account = link.account
                if account.status != 'active':
                    continue

                # --- Shared daily budget: one counter, half-cap consumers ---
                daily = _get_daily(db, campaign.id, account.id, today)
                messages_sent = daily.messages_sent
                message_limit = max(0, round(link.message_limit / 2))

                def limit_reached():
                    return messages_sent >= message_limit

                log(f"[{campaign.campaign_key}/{account.name}] shared message budget: {messages_sent}/{message_limit}")

                session = None
                if not dry_run:
                    try:
                        session = load_session_ref(account)
                        inbox = li.fetch_inbox(session, count=90)
                    except li.SeatRequiredError:
                        log(f"[{campaign.campaign_key}/{account.name}] no Sales Nav seat - skipping")
                        continue
                    except li.LinkedinError as e:
                        log(f"[{campaign.campaign_key}/{account.name}] inbox fetch failed: {e}")
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: {e}")
                        continue

                    msgs = inbox.get('elements', [])
                    threads_by_lead = {
                        t['participants'][0]: t for t in msgs if t.get('participants')
                    }
                else:
                    threads_by_lead = {}

                campaign_account_stats = {'accepts_messaged': 0, 'new_replies': 0}

                # --- 1) Invite accepts ---
                pending_invites = db.execute(
                    select(Lead).where(
                        Lead.campaign_id == campaign.id,
                        Lead.associate_account_id == account.id,
                        Lead.status == LeadStatus.INVITE_SENT.value,
                        Lead.received_replies.is_(False),
                    )
                ).scalars().all()

                for lead in pending_invites:
                    if dry_run:
                        break
                    thread = threads_by_lead.get(lead.sales_nav_id)
                    if not thread:
                        continue
                    thread_msgs = thread.get('messages') or []
                    if not thread_msgs or thread_msgs[0].get('type') != 'INVITATION':
                        continue
                    if limit_reached():
                        log(f"[{campaign.campaign_key}/{account.name}] shared budget reached - stopping accepts")
                        break
                    log(f"[{campaign.campaign_key}/{account.name}] invite accepted by {lead.full_name} - sending after-acceptance message")
                    body = _template_format(
                        (campaign.invite_track or [''])[0],
                        lead.first_name or lead.full_name,
                        link.calendar_url or '',
                    )
                    ok, err_kind, detail = li.send_message(session, lead.sales_nav_id, body)
                    messages_sent += 1
                    daily.messages_sent = messages_sent
                    db.commit()
                    li.polite_sleep(10, 20)
                    if ok:
                        _set_status(db, lead, LeadStatus.INVITE_AFTER_ACCEPT.value, JobType.CHECK_REPLIES.value)
                        _add_event(db, lead.id, 'outbound', 'After-acceptance message sent', JobType.CHECK_REPLIES.value)
                        campaign_account_stats['accepts_messaged'] += 1
                        db.commit()
                    else:
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: after-accept failed: {detail}")
                        if err_kind == 'validation':
                            break

                # --- 2) Reply detection ---
                candidates = db.execute(
                    select(Lead).where(
                        Lead.campaign_id == campaign.id,
                        Lead.associate_account_id == account.id,
                        Lead.received_replies.is_(False),
                    )
                ).scalars().all()

                for lead in candidates:
                    thread = threads_by_lead.get(lead.sales_nav_id)
                    if not thread:
                        continue
                    lead_replies = [
                        m for m in (thread.get('messages') or [])
                        if m.get('author') == lead.sales_nav_id and m.get('body')
                    ]
                    if not lead_replies:
                        continue
                    log(f"[{campaign.campaign_key}/{account.name}] reply from {lead.full_name}")
                    lead.received_replies = True
                    lead.reply_message = lead_replies[0].get('body', '')
                    lead.reply_received_at = _now()
                    _add_event(db, lead.id, 'reply', lead_replies[0].get('body', '')[:500], JobType.CHECK_REPLIES.value)
                    replies_found.append({
                        'name': lead.full_name or f"{lead.first_name} {lead.last_name}",
                        'message': lead.reply_message,
                        'campaign': campaign.campaign_key,
                        'account': account.name,
                    })
                    campaign_account_stats['new_replies'] += 1

                db.commit()
                run.stats[f"{campaign.campaign_key}/{account.name}"] = campaign_account_stats

        db.commit()
        if replies_found and not dry_run:
            notify.send_reply_digest(replies_found)
        notify_run_summary_and_errors(run, 'Check Replies')
        run.finish()
    except Exception as e:
        db.rollback()
        _fatal(db, JobType.CHECK_REPLIES, e, run_row=run.run if run else None)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# JOB 5 — SEND FOLLOW-UPS
# ---------------------------------------------------------------------------

# stage: (trigger status, days elapsed, track index, result status, label)
INVITE_STAGES = [
    ('INVITE_AFTER_ACCEPT', 3, 1, 'INVITE_FOLLOWUP_1', 'Invite Follow-up 1'),
    ('INVITE_FOLLOWUP_1', 5, 2, 'INVITE_FOLLOWUP_2', 'Invite Follow-up 2'),
    ('INVITE_FOLLOWUP_2', 7, 3, 'INVITE_FOLLOWUP_3', 'Invite Follow-up 3'),
]
INMAIL_STAGES = [
    ('INMAIL_SENT', 3, 0, 'INMAIL_FOLLOWUP_1', 'InMail Follow-up 1'),
    ('INMAIL_FOLLOWUP_1', 5, 1, 'INMAIL_FOLLOWUP_2', 'InMail Follow-up 2'),
    ('INMAIL_FOLLOWUP_2', 7, 2, 'INMAIL_FOLLOWUP_3', 'InMail Follow-up 3'),
]


def job_send_followups(campaign_ids: list[int] | None = None, account_ids: list[int] | None = None, dry_run=False):
    """JOB 5: staged follow-ups (+3/+5/+7 days) for both tracks, skipping any
    lead with received_replies. Draws from the SHARED messages_sent budget
    (capped at round(message_limit/2)), shared with Job 4."""
    run = None
    db = SessionLocal()
    today = date.today()
    try:
        run = _Run(db, JobType.SEND_FOLLOWUPS, 'All campaigns/accounts', dry_run)
        log = run.log
        campaigns = db.execute(select(Campaign).order_by(Campaign.id)).scalars().all()
        if campaign_ids:
            campaigns = [c for c in campaigns if c.id in campaign_ids]

        for campaign in campaigns:
            links = sorted(campaign.account_links, key=lambda l: l.order_index)
            for link in links:
                if account_ids and link.account_id not in account_ids:
                    continue
                account = link.account
                if account.status != 'active':
                    continue

                daily = _get_daily(db, campaign.id, account.id, today)
                messages_sent = daily.messages_sent
                message_limit = max(0, round(link.message_limit / 2))

                log(f"[{campaign.campaign_key}/{account.name}] shared message budget: {messages_sent}/{message_limit}")

                session = None
                if not dry_run:
                    try:
                        session = load_session_ref(account)
                        li.fetch_inbox(session, count=10)  # seat probe
                    except li.SeatRequiredError:
                        log(f"[{campaign.campaign_key}/{account.name}] no Sales Nav seat - skipping")
                        continue
                    except li.LinkedinError as e:
                        log(f"[{campaign.campaign_key}/{account.name}] session probe failed: {e}")
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: {e}")
                        continue

                stage_counts = {}
                sent_this_run = 0

                for stage_list, track_name in ((INVITE_STAGES, 'invite'), (INMAIL_STAGES, 'inmail')):
                    for trigger_status, days_after, track_index, result_status, label in stage_list:
                        cutoff = _now() - timedelta(days=days_after)
                        leads = db.execute(
                            select(Lead).where(
                                Lead.campaign_id == campaign.id,
                                Lead.associate_account_id == account.id,
                                Lead.status == trigger_status,
                                Lead.received_replies.is_(False),
                                Lead.status_changed_at <= cutoff,
                            )
                        ).scalars().all()
                        if not leads:
                            stage_counts[label] = 0
                            continue

                        track = campaign.invite_track if track_name == 'invite' else campaign.inmail_track
                        track = track or []
                        if track_index >= len(track):
                            log(f"[{campaign.campaign_key}/{account.name}] {label}: no template at index {track_index} - skipping {len(leads)} lead(s)")
                            stage_counts[label] = 0
                            continue
                        template = track[track_index]

                        stage_sent = 0
                        for lead in leads:
                            if messages_sent >= message_limit:
                                log(f"[{campaign.campaign_key}/{account.name}] shared budget reached at {label}")
                                break
                            first_name = lead.first_name or lead.full_name or ''
                            calendar_url = link.calendar_url or ''

                            if track_name == 'inmail':
                                body = _template_format(template.get('body', ''), first_name, calendar_url)
                                subject = template.get('subject') or ''
                                subject = _template_format(subject, first_name, calendar_url)
                            else:
                                body = _template_format(template, first_name, calendar_url)
                                subject = ''

                            log(f"[{campaign.campaign_key}/{account.name}] {label} -> {lead.full_name}")
                            if dry_run:
                                ok = True
                            elif track_name == 'inmail':
                                ok, err_kind, detail = li.send_inmail(session, lead.sales_nav_id, subject, body)
                            else:
                                ok, err_kind, detail = li.send_message(session, lead.sales_nav_id, body)
                            if not dry_run:
                                li.polite_sleep(15, 30)

                            if ok:
                                messages_sent += 1
                                daily.messages_sent = messages_sent
                                _set_status(db, lead, result_status, JobType.SEND_FOLLOWUPS.value)
                                _add_event(db, lead.id, 'outbound', f"{label} sent", JobType.SEND_FOLLOWUPS.value)
                                stage_sent += 1
                                sent_this_run += 1
                                db.commit()
                            else:
                                run.errors.append(
                                    f"{campaign.campaign_key}/{account.name}: {label} failed for {lead.full_name}: {detail}")
                                if err_kind == 'validation':
                                    log(f"[{campaign.campaign_key}/{account.name}] validation error - stopping this account's sends")
                                    break

                        stage_counts[label] = stage_sent

                run.stats[f"{campaign.campaign_key}/{account.name}"] = {
                    **stage_counts,
                    'messages_sent': f"{messages_sent}/{message_limit}",
                }
                db.commit()

        notify_run_summary_and_errors(run, 'Send Follow-ups')
        run.finish()
    except Exception as e:
        db.rollback()
        _fatal(db, JobType.SEND_FOLLOWUPS, e, run_row=run.run if run else None)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scheduler helpers
# ---------------------------------------------------------------------------

JOB_REGISTRY = {
    'sync_leads': job_sync_leads,
    'import_list': job_import_list,
    'send_connections': job_send_connections,
    'check_replies': job_check_replies,
    'send_followups': job_send_followups,
}


def run_job(job_key: str, dry_run=False, **kwargs):
    """Entry point used by the API + scheduler. Returns the run summary."""
    fn = JOB_REGISTRY.get(job_key)
    if fn is None:
        raise ValueError(f"Unknown job: {job_key}")
    return fn(dry_run=dry_run, **kwargs)
