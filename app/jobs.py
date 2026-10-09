"""The five pipeline jobs, re-implemented on the database with the exact
Part-A behavior:

- Budget model: (campaign, account, day) holds invite_sent_count +
  opentomsg_count (enforced by send_connections) and the SHARED
  messages_sent counter consumed by check_replies (after-accept sends) and
  send_followups. Follow-ups use the full remaining effective limit;
  check_replies retains its half-limit threshold.
- Status machine: INVITE_SENT -> INVITE_AFTER_ACCEPT -> INVITE_FOLLOWUP_1..3
  (+3/+5/+7 days) and INMAIL_SENT -> INMAIL_FOLLOWUP_1..3 (+3/+5/+7).
- received_replies excludes a lead from ALL further automated sends.
- send_connections rolls unhandled leads to the NEXT account in the
  campaign's ordered list. Assigned leads stay with their chosen account;
  unhandled leads retain their assignment for the next run.
- Distinct failure handling: 400 -> mark reason, no auto-retry; 429 -> stop
  account's loop, keep lead; validation error -> stop InMail sends for run.

Every run is recorded in run_logs; every outbound action appends a LeadEvent.
"""
import importlib
import json
import os
import re
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
from .invite_limits import weekly_invite_status
from .models import AccountInviteSend


class JobStoppedError(Exception):
    """Raised when a job run is stopped by user request."""
    pass


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.utcnow()


# Placeholders allowed in campaign texts (invite note, InMail subject/body,
# follow-ups). Every value substitutes as an empty string when missing, so a
# lead without a company never leaves a raw '{company}' in the message.
_TEMPLATE_TOKEN_RE = re.compile(r'\{([^{}]*)\}')


def _template_format(text, first_name, calendar_url, company=''):
    """Substitute {first_name}, {company} and {calendar_url} in campaign texts.

    Missing values render as '' (a lead without a company never leaks a raw
    '{company}'). Unknown tokens ({oops}), escaped/doubled braces and stray
    unmatched braces are blanked out instead of crashing the send - plain dict
    lookup, no str.format attribute traversal on user-written templates.
    """
    if not text:
        return ''
    values = {
        'first_name': first_name or '',
        'company': company or '',
        'calendar_url': calendar_url or '',
    }
    formatted = _TEMPLATE_TOKEN_RE.sub(
        lambda m: values.get(m.group(1).strip(), ''), text)
    return formatted.replace('{', '').replace('}', '')


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
        # Do not hold SQLite's write lock during LinkedIn requests or pacing.
        db.commit()
    return row


def _set_status(db: OrmSession, lead: Lead, new_status: str, job_type: str, detail: str = ''):
    if lead.status != new_status:
        if new_status == LeadStatus.BLOCKED_ERROR.value:
            lead.status_before_error = lead.status or ''
            lead.stage_time_before_error = lead.status_changed_at
        old = lead.status or '(none)'
        lead.status = new_status
        lead.status_changed_at = _now()
        _add_event(db, lead.id, 'status_change', f"{old} -> {new_status}" + (f": {detail}" if detail else ''), job_type)


def _effective_limits(link: CampaignAccount, db=None, daily=None):
    """Per-(campaign, account) send budget = the lower of the campaign link's
    own limit and the account's fleet-level daily cap."""
    if db is not None and daily is not None:
        other = db.execute(select(DailySendCount).where(DailySendCount.account_id == link.account_id,
                           DailySendCount.date == daily.date, DailySendCount.campaign_id != link.campaign_id)).scalars().all()
        return (max(0, min(link.invite_limit, link.account.daily_invite_cap - sum(r.invite_sent_count for r in other))),
                max(0, min(link.inmail_limit, link.account.daily_inmail_cap - sum(r.opentomsg_count for r in other))),
                max(0, min(link.message_limit, link.account.daily_message_cap - sum(r.messages_sent for r in other))))
    return (
        max(0, min(link.invite_limit, link.account.daily_invite_cap)),
        max(0, min(link.inmail_limit, link.account.daily_inmail_cap)),
        max(0, min(link.message_limit, link.account.daily_message_cap)),
    )


def _stamp_first_contact(lead: Lead, channel: str):
    """Record the day/channel of first contact (initial invite or InMail)."""
    if not lead.first_contacted_at:
        lead.first_contacted_at = _now()
    lead.contact_channel = channel


def _stamp_followup(lead: Lead, stage: str):
    lead.last_followup_at = _now()
    lead.last_followup_stage = stage


def _stop_note(run, log):
    """Emit '🛑 Job stopped by user.' at most ONCE per run.

    Every nested loop (campaign / account / stage / lead / sleep) checks the
    stop flag while a stop unwinds; without dedupe each nesting level printed
    the line again (the duplicate stop-log bug). First site that notices
    logs it; the rest stay silent but still unwind their own loop."""
    from .runner import is_stop_requested
    if not is_stop_requested() or getattr(run, 'stop_noted', False):
        return
    run.stop_noted = True
    log('🛑 Job stopped by user.')


def complete_account_action(run, account_id: int, action_id: str) -> int | None:
    """Count one COMPLETED account-level action toward the account's total run
    count.

    Contract:
    - Call ONLY after the action's own successful db.commit() — i.e. the
      invite/InMail/follow-up actually went out (or an import page landed).
      Never on job start, never on failure: a stopped or failed action is
      not a run.
    - Idempotent: keyed by (execution token, account_id, action_id) in the
      run's counted set, so the same completion event processed twice
      increments once. The token is unique per job execution, so two runs
      doing the same lead never collide.
    - Publishes to the runner's live progress so open views update in real
      time without a refresh.
    """
    from .runner import execution_context, publish_account_runs
    account = run.db.get(Account, account_id)
    if account is None:
        return None
    token = getattr(execution_context, 'run_token', '') or f"run{run.run.id}"
    key = (token, account_id, action_id)
    counted = getattr(run, 'counted_actions', None)
    if counted is None:
        counted = run.counted_actions = set()
    if key in counted:
        return account.total_runs
    counted.add(key)
    account.total_runs = (account.total_runs or 0) + 1
    try:
        run.db.commit()
    except Exception:
        run.db.rollback()
        return account.total_runs
    try:
        publish_account_runs(account_id, account.total_runs)
    except Exception:
        pass
    return account.total_runs


class _Logger:
    def __init__(self, on_line=None):
        self.lines = []
        self.on_line = on_line

    def __call__(self, message):
        line = f"[{_now().strftime('%H:%M:%S')}] {message}"
        self.lines.append(line)
        print(message)
        if self.on_line:
            self.on_line(self.lines)


def _runner_logger(run: RunLog):
    """Collect full run output and publish a bounded live tail. The run owner
    persists the final tail when finishing or aborting its transaction."""
    # Publish independently of the worker's database transaction. Moving an
    # attached ORM row into another session fails; committing the worker's
    # session here would accidentally commit unrelated outreach changes.
    from .runner import publish_log
    log = _Logger(lambda lines: publish_log(run.id, '\n'.join(lines)[-60000:]))
    run._log_lines = log.lines
    publish_log(run.id, '')
    return log


def _finish(run, db, status, stats, errors=None):
    run.status = status.value if hasattr(status, 'value') else status
    run.finished_at = _now()
    run.duration_s = (run.finished_at - run.started_at).total_seconds()
    run.stats = stats
    run.errors = errors or []
    run.log_text = '\n'.join(getattr(run, '_log_lines', []))[-60000:]
    db.commit()
    notify.notify_lifecycle(run)


class _Run:
    """Context manager wrapping one run_log row + logger."""

    def __init__(self, db: OrmSession, job_type: JobType, target: str, dry_run: bool,
                 campaign_id=None, account_id=None):
        self.db = db
        from .runner import execution_context
        context_names = []
        if campaign_id is not None:
            campaign = db.get(Campaign, campaign_id)
            if campaign and campaign.name not in target:
                context_names.append(campaign.name)
        if account_id is not None:
            account = db.get(Account, account_id)
            if account and account.name not in target:
                context_names.append(account.name)
        if context_names:
            target = ' / '.join(context_names) + ' · ' + target
        self.run = RunLog(
            job_type=job_type.value, campaign_id=campaign_id, account_id=account_id,
            schedule_id=getattr(execution_context, 'schedule_id', None), log_text='',
            target=getattr(execution_context, 'schedule_name', None) or target, dry_run=dry_run, status=RunStatus.RUNNING.value, started_at=_now(),
        )
        db.add(self.run)
        db.commit()
        self.log = _runner_logger(self.run)
        self.run._log_lines = self.log.lines  # attach for _finish
        self.dry_run = dry_run
        self.stats = {}
        self.errors = []
        self.counted_actions = set()   # idempotency keys for run counting
        self.stop_noted = False        # 'stopped by user' logged once
        if campaign_id is not None and account_id is not None:
            self.record_target(campaign_id, account_id)
        # NOTE: no notification here — the GChat summary goes out once, on
        # completion (notify_lifecycle in _finish). A 'Started' ping was
        # removed: it was noise and duplicated the summary.

    def record_target(self, campaign_id, account_id):
        from .models import RunTarget
        pairs = getattr(self, '_target_pairs', set())
        key = (campaign_id, account_id)
        if key not in pairs:
            self.db.add(RunTarget(run_id=self.run.id, campaign_id=campaign_id, account_id=account_id))
            self.db.commit()
            self._target_pairs = pairs | {key}

    def page(self, start, elements, extracted, added):
        from .runner import publish_progress
        import math
        total = getattr(elements, 'total', None)
        page = start // li.PAGE_SIZE + 1
        values = dict(page=page, page_extracted=len(elements), extracted=extracted,
                      added=added, total=total,
                      total_pages=math.ceil(total / li.PAGE_SIZE) if total is not None else None,
                      percent=min(100, round(extracted * 100 / total)) if total else None,
                      action='Importing leads')
        self.stats.update(values)
        self.run.stats = dict(self.stats)
        self.db.commit()
        publish_progress(self.run.id, **values)
        self.log(f'Page {page}: {len(elements)} extracted · {extracted} total · {added} new leads')
        if start + li.PAGE_SIZE >= li.MAX_START and len(elements) == li.PAGE_SIZE:
            self.errors.append(f'Import reached the {li.MAX_START}-result limit; narrow the search to retrieve further results.')

    def finish(self, status: RunStatus = RunStatus.SUCCESS):
        from .runner import is_stop_requested
        if is_stop_requested():
            status = RunStatus.STOPPED
        elif status == RunStatus.SUCCESS and self.errors:
            status = RunStatus.PARTIAL
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


class _AccountSession:
    """Wrapper around a LinkedIn session that guards account health.

    A missing Sales Navigator seat is persisted separately as seat_required.
    Other 401/403 responses mean the captured cookies are no longer valid:
    the account is flipped to needs_reauth, the underlying session is poisoned
    so later requests in the same run fail fast, and a LinkedinError is raised
    so the current account loop stops immediately (B10).
    """

    def __init__(self, session, account_id: int, db: 'OrmSession | None' = None):
        self._session = session
        self._account_id = account_id
        self._db = db
        self._rejected = False
        self._rejection_state = 'needs_reauth'

    def _mark_rejected(self, state='needs_reauth'):
        self._rejected = True
        self._rejection_state = state
        try:
            db = self._db or SessionLocal()
            try:
                account = db.get(Account, self._account_id)
                if account is not None and account.status != state:
                    account.status = state
                    db.commit()
                    print(f"[account] account {self._account_id} marked {state}")
            finally:
                if self._db is None:
                    db.close()
        except Exception:
            pass

    def _guard(self):
        if self._rejected:
            if self._rejection_state == 'seat_required':
                raise li.SeatRequiredError('Account does not have a Sales Navigator seat')
            raise li.LinkedinError('Session rejected (401/403) - re-authenticate this account before further requests')

    def _wrap(self, method, *args, **kwargs):
        from .runner import is_stop_requested
        if is_stop_requested():
            raise JobStoppedError('Stopped before the next LinkedIn request')
        self._guard()
        kwargs.setdefault('timeout', 30)
        response = getattr(self._session, method)(*args, **kwargs)
        if getattr(response, 'status_code', None) != 200:
            try:
                payload = response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict) and payload.get('code') == 'SALES_SEAT_REQUIRED':
                self._mark_rejected('seat_required')
                raise li.SeatRequiredError('Account does not have a Sales Navigator seat', status=response.status_code)
        if getattr(response, 'status_code', None) in (401, 403):
            self._mark_rejected()
            raise li.LinkedinError(f'HTTP {response.status_code} - session expired or forbidden', status=response.status_code)
        return response

    def get(self, *args, **kwargs):
        return self._wrap('get', *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._wrap('post', *args, **kwargs)

    def put(self, *args, **kwargs):
        return self._wrap('put', *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._wrap('delete', *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


# ---------------------------------------------------------------------------
# JOB 1 — SYNC CAMPAIGN LEADS (batch: all campaigns, all search URLs)
# ---------------------------------------------------------------------------

def _recipient(lead) -> str:
    """Message recipient exactly like the raw scripts: the sheets store the
    full 'urn:li:fs_salesProfile:(ACw…,NAME_SEARCH,…)' and the scripts pass it
    verbatim as the createMessage recipient. Bare tokens are the fallback for
    leads that never got a URN backfilled."""
    return (getattr(lead, 'sales_nav_urn', '') or '').strip() or lead.sales_nav_id


def _lead_from_element(element, campaign_id, source=LeadSource.CAMPAIGN_SEARCH, list_id=None, assigned_account_id=None):
    current_position = (element.get('currentPositions') or [{}])[0]
    # Normalize the ID to the bare ACw profile token. Raw entityUrns look like
    # 'urn:li:fs_salesProfile:(ACwXXX,NAME_SEARCH,...)'; storing the full urn
    # made the same person two rows (urn vs bare) that never matched the
    # (sales_nav_id, campaign_id) unique key. extract_profile_id pulls ACwXXX
    # out of any format and falls back to the raw value when absent.
    raw_urn = element.get('entityUrn', '')
    snid = li.extract_profile_id(raw_urn) or raw_urn
    return dict(
        sales_nav_id=snid,
        # Keep the exact urn for API parity with the sheets
        # ('urn:li:fs_salesProfile:(ACw…,NAME_SEARCH,…)').
        sales_nav_urn=raw_urn if str(raw_urn).startswith('urn:li:fs_salesProfile:') else '',
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
        campaign_id=campaign_id, associate_account_id=assigned_account_id,
    )


def _upsert_lead(db: OrmSession, data: dict) -> bool:
    """Deduplicate by Sales Nav ID and campaign, including the untagged pool.

    Refresh profile data only in this destination; preserve outreach history.
    """
    if not data.get('sales_nav_id'):
        return False
    matches = db.execute(
        select(Lead).where(Lead.sales_nav_id == data['sales_nav_id'],
                           Lead.campaign_id == data.get('campaign_id')).order_by(Lead.id)
    ).scalars().all()
    for existing in matches:
        # Historical pool duplicates may exist. Refresh only matching rows
        # in this destination without merging their outreach histories.
        if data.get('sales_nav_urn') and not (existing.sales_nav_urn or ''):
            existing.sales_nav_urn = data['sales_nav_urn']
        for field in ('full_name', 'title', 'summary', 'location', 'company',
                      'premium', 'pending_invitation', 'viewed', 'linkedin_url'):
            if data.get(field):
                setattr(existing, field, data[field])
    if matches:
        return False
    db.add(Lead(**data))
    return True


def validate_import_assignment(db, account_id, campaign_id, *, require_active=False):
    if account_id is None:
        return
    if require_active:
        account = db.get(Account, account_id)
        if not account or account.status != 'active':
            raise ValueError('Choose an active outreach account or leave it unassigned.')
    if campaign_id is not None:
        mapped = db.scalar(select(CampaignAccount.id).where(
            CampaignAccount.campaign_id == campaign_id, CampaignAccount.account_id == account_id))
        if mapped is None:
            raise ValueError('The selected account is not mapped to this campaign. Choose a mapped campaign or update its account mappings.')


def job_sync_leads(campaign_ids: list[int] | None = None, dry_run=False, account_id=None, saved_search_id=None, campaign_id=None, outreach_account_id=None):
    """JOB 1: one BATCH run over every active campaign. Campaign-level search_url
    runs with the first account's session; per-account overrides run with their
    own session. New leads are tagged with the campaign and added to the pool."""
    run = None
    db = SessionLocal()
    try:
        from .runner import is_stop_requested
        if account_id is not None or saved_search_id is not None:
            run = _Run(db, JobType.SYNC_LEADS, f'SavedSearch {saved_search_id}', dry_run, account_id=account_id, campaign_id=campaign_id)
            account = db.get(Account, account_id)
            if not account or account.status != 'active' or not str(saved_search_id).isascii() or not str(saved_search_id).isdigit():
                raise li.LinkedinError('Choose an active account and numeric Search ID')
            validate_import_assignment(db, outreach_account_id, campaign_id, require_active=True)
            if dry_run:
                run.log('DRY RUN: saved search skipped')
            else:
                session = _AccountSession(load_session_ref(account), account.id, db)
                added = 0
                extracted = 0
                url = f'https://www.linkedin.com/sales/search/people?savedSearchId={saved_search_id}'
                for start in range(0, li.MAX_START, li.PAGE_SIZE):
                    if is_stop_requested():
                        _stop_note(run, run.log)
                        break
                    elements = li.search_leads(session, url, start)
                    for element in elements:
                        added += _upsert_lead(db, _lead_from_element(element, campaign_id,
                                                   assigned_account_id=outreach_account_id))
                    db.commit()
                    complete_account_action(run, account.id, f'page:{start}')
                    extracted += len(elements)
                    run.page(start, elements, extracted, added)
                    if len(elements) < li.PAGE_SIZE:
                        break
                    if not li.polite_sleep():
                        _stop_note(run, run.log)
                        break
                run.stats['new_leads'] = added
                run.log(f'Import SavedSearch: {added} new leads; campaign tag: {campaign_id or "none"}')
            run.finish()
            return
        run = _Run(db, JobType.SYNC_LEADS, 'All active campaigns', dry_run)
        log = run.log
        campaigns = db.execute(
            select(Campaign).where(Campaign.status == 'active')
            .order_by(Campaign.id)
        ).scalars().all()
        if campaign_ids is not None:
            campaigns = [c for c in campaigns if c.id in campaign_ids]

        sessions = {}  # account_id -> curl_cffi session (reused across campaigns)

        def _session_for(account: Account):
            if account.id not in sessions:
                sessions[account.id] = load_session_ref(account)
            return sessions[account.id]

        any_error = False
        for campaign in campaigns:
            if is_stop_requested():
                _stop_note(run, log)
                break
            if campaign.status != 'active':
                continue
            found_for_campaign = 0
            searches = []  # (account, url)
            active_links = [l for l in sorted(campaign.account_links, key=lambda l: l.order_index) if l.account and l.account.status == 'active']
            if campaign.search_url and active_links:
                searches.append((active_links[0].account, campaign.search_url))
            for link in active_links:
                if link.search_url_override:
                    searches.append((link.account, link.search_url_override))

            for account, url in searches:
                if is_stop_requested():
                    _stop_note(run, log)
                    break
                log(f"[{campaign.campaign_key}] Searching via {account.name}")
                if dry_run:
                    log(f"[{campaign.campaign_key}] DRY RUN - search POST skipped, simulating 0 new leads")
                    continue
                try:
                    session = _session_for(account)
                    total_pages = 0
                    new_leads = 0
                    for start in range(0, li.MAX_START, li.PAGE_SIZE):
                        if is_stop_requested():
                            _stop_note(run, log)
                            break
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
                        complete_account_action(run, account.id, f'page:{campaign.id}:{start}')
                        if len(elements) < li.PAGE_SIZE:
                            break
                        if not li.polite_sleep(10, 15):
                            _stop_note(run, log)
                            break
                    found_for_campaign += new_leads
                    log(f"[{campaign.campaign_key}] {url[:60]}...: {new_leads} new lead(s) across {total_pages} page(s)")
                except Exception as e:
                    any_error = True
                    run.errors.append(f"[{campaign.campaign_key}] search failed: {e}")
                    log(f"[{campaign.campaign_key}] 🚫 search failed: {e}")

            run.stats[campaign.campaign_key] = {'leads_added': found_for_campaign}
            db.commit()

        run.finish(RunStatus.PARTIAL if any_error else RunStatus.SUCCESS)
    except Exception as e:
        db.rollback()
        _fatal(db, JobType.SYNC_LEADS, e, run_row=run.run if run else None)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# JOB 2 — IMPORT FROM LIST (manual one-off, untagged leads)
# ---------------------------------------------------------------------------

def job_import_list(account_id: int, list_id: str, dry_run=False, campaign_id=None, outreach_account_id=None):
    """JOB 2: separate manual tool - imports a numeric Sales Navigator List ID
    via the List-pivot people-search endpoint. Leads land untagged by default;
    when campaign_id is provided they are tagged with that campaign
    (source=list_import). Assignment can still happen later manually."""
    run = None
    db = SessionLocal()
    try:
        account = db.get(Account, account_id)
        if account is None:
            # We can't even start a proper run row with the target name
            db.add(RunLog(job_type=JobType.IMPORT_LIST.value, target=f"list {list_id}", status=RunStatus.ERROR.value, started_at=_now(), finished_at=_now(), duration_s=0, errors=[f"Account {account_id} not found"]))
            db.commit()
            return
        if account.status != 'active':
            db.add(RunLog(job_type=JobType.IMPORT_LIST.value, target=f"{account.name} · list {list_id}", status=RunStatus.ERROR.value, started_at=_now(), finished_at=_now(), duration_s=0, errors=[f"Account {account.name} is not active ({account.status})"]))
            db.commit()
            return
        run = _Run(db, JobType.IMPORT_LIST, f"{account.name} · SavedList {list_id}", dry_run, account_id=account_id, campaign_id=campaign_id)
        log = run.log
        validate_import_assignment(db, outreach_account_id, campaign_id, require_active=True)

        if dry_run:
            run.stats['leads_added'] = 0
            log(f"DRY RUN - list import skipped for {account.name}")
            run.finish()
            return

        from .runner import is_stop_requested
        session = _AccountSession(load_session_ref(account), account.id, db)
        new_total = 0
        extracted = 0
        for start in range(0, li.MAX_START, li.PAGE_SIZE):
            if is_stop_requested():
                _stop_note(run, log)
                break
            elements = li.people_search_by_list(session, int(list_id), start)
            added = 0
            for element in elements:
                data = _lead_from_element(element, campaign_id=campaign_id,
                                          source=LeadSource.LIST_IMPORT, list_id=list_id,
                                          assigned_account_id=outreach_account_id)
                if not data['sales_nav_id']:
                    continue
                # Both paths dedupe within their destination. Tagged imports refresh
                # profile fields; untagged imports leave existing rows unchanged.
                if campaign_id is not None:
                    if not _upsert_lead(db, data):
                        continue
                elif not _upsert_lead_untagged(db, data):
                    continue
                added += 1
            new_total += added
            db.commit()
            complete_account_action(run, account.id, f'page:{start}')
            extracted += len(elements)
            run.page(start, elements, extracted, new_total)
            if len(elements) < li.PAGE_SIZE:
                break
            if not li.polite_sleep(10, 15):
                _stop_note(run, log)
                break

        run.stats['leads_added'] = new_total
        log(f"Imported {new_total} new untagged lead(s) from list {list_id}")
        run.finish()
    except Exception as e:
        db.rollback()
        _fatal(db, JobType.IMPORT_LIST, e, run_row=run.run if run else None)
    finally:
        db.close()


def _upsert_lead_untagged(db: OrmSession, data: dict) -> bool:
    """Check the untagged pool only; campaign leads are separate records."""
    if not data.get('sales_nav_id'):
        return False
    existing_id = db.scalar(select(Lead.id).where(Lead.sales_nav_id == data['sales_nav_id'],
                                                 Lead.campaign_id.is_(None)).limit(1))
    if existing_id is not None:
        return False
    db.add(Lead(**data))
    return True


# ---------------------------------------------------------------------------
# JOB 3 — SEND CONNECTIONS
# ---------------------------------------------------------------------------

RATE_LIMIT_429_THRESHOLD = 5
# Max real profile fetches (OpenToMsg) per account per run. Cached leads don't
# count - only live get_profile_opentomsg calls consume the budget.
OPENTOMSG_CHECK_LIMIT = 200
"""Consecutive HTTP 429 responses required before an account is rate-limit
stopped for the rest of the run. A single 429 is treated as transient: the
lead is retained for rollover and sending continues. Only a streak of
consecutive 429s (no successful send in between) means the account is
genuinely rate-limited."""


class _RateLimitGuard:
    """Tracks consecutive HTTP 429 failures for one account within a run.
    hit() returns True only after RATE_LIMIT_429_THRESHOLD consecutive 429s;
    any successful send resets the streak."""

    def __init__(self):
        self.streak = 0

    def hit(self) -> bool:
        self.streak += 1
        return self.streak >= RATE_LIMIT_429_THRESHOLD

    def reset(self):
        self.streak = 0


CONNECT_400_STREAK_LIMIT = 3
"""Consecutive HTTP 400 first-touch rejections before an account's sends are
stopped for the run. LinkedIn answers connectV2/createMessage with an opaque
400 for lead-specific AND account-level problems; a streak means the account
or session is the problem (invitation cap reached, degraded session), so
sending stops and the leads blocked during the streak are released again
instead of the whole pool rotting in BLOCKED_ERROR."""


class _Connect400Guard:
    """Tracks consecutive HTTP 400 first-touch failures for one account within
    a run and remembers which leads were blocked so they can be released when
    the streak proves the failure was account-level. Any successful send
    resets the streak."""

    def __init__(self):
        self.streak = 0
        self.blocked_lead_ids: list[int] = []

    def hit(self, lead_id: int) -> bool:
        self.streak += 1
        self.blocked_lead_ids.append(lead_id)
        return self.streak >= CONNECT_400_STREAK_LIMIT

    def reset(self):
        self.streak = 0
        self.blocked_lead_ids = []


def _connect_400_streak_stop(db, run, log, scope, guard):
    """Circuit breaker tripped: stop this account's sends and release the
    leads that were blocked during the all-HTTP-400 streak — they were most
    likely rejected because of the account/session (invitation cap reached,
    degraded session, LinkedIn-side restriction), not because each lead is
    individually bad. A lone 400 still blocks just that lead."""
    log(f"[{scope}] {CONNECT_400_STREAK_LIMIT} consecutive connect rejections (HTTP 400) - stopping this account's sends and releasing the leads blocked during the streak")
    run.errors.append(f"{scope}: {CONNECT_400_STREAK_LIMIT} consecutive connect rejections (HTTP 400) - sending stopped for this run (check the account's invitation cap, session health or LinkedIn-side restrictions)")
    for lead_id in guard.blocked_lead_ids:
        lead = db.get(Lead, lead_id)
        if lead is not None and lead.status == LeadStatus.BLOCKED_ERROR.value:
            _set_status(db, lead, '', None, detail='error cleared - account-level rejection streak')
            lead.last_error = ''
            log(f"[{scope}] released {lead.full_name} back to the outreach queue")
    db.commit()


def job_send_connections(campaign_ids: list[int] | None = None, dry_run=False, account_ids: list[int] | None = None):
    """JOB 3: for each campaign, fill leads through the campaign's accounts IN
    ORDER; an account sends until its own budgets are exhausted, then leftovers
    roll to the next account. OpenLink -> InMail (needs inmail budget);
    otherwise invite (needs invite budget)."""
    run = None
    db = SessionLocal()
    today = _now().date()
    simulated_weekly = {}
    try:
        # Run attribution: targeted runs record (first) campaign/account ids so
        # restricted users' history can filter them; fleet runs stay NULL.
        _scope_campaigns = sorted(campaign_ids) if campaign_ids else None
        _scope_accounts = sorted(account_ids) if account_ids else None
        run = _Run(db, JobType.SEND_CONNECTIONS, 'All active campaigns', dry_run,
                   campaign_id=(_scope_campaigns[0] if _scope_campaigns and len(_scope_campaigns) == 1 else None),
                   account_id=(_scope_accounts[0] if _scope_accounts and len(_scope_accounts) == 1 else None))
        log = run.log
        campaigns = db.execute(
            select(Campaign).where(Campaign.status == 'active').order_by(Campaign.id)
        ).scalars().all()
        if campaign_ids is not None:
            campaigns = [c for c in campaigns if c.id in campaign_ids]

        from .runner import is_stop_requested
        for campaign in campaigns:
            if is_stop_requested():
                _stop_note(run, log)
                break
            links = sorted(campaign.account_links, key=lambda l: l.order_index)
            if not links:
                continue

            # Today's untouched leads for this campaign (no status, not pending).
            untouched = db.execute(
                select(Lead).where(
                    Lead.campaign_id == campaign.id,
                    Lead.status == '',
                    Lead.pending_invitation != 'True',
                    Lead.received_replies.is_(False),
                ).order_by(Lead.id)
            ).scalars().all()

            remaining = list(untouched)
            if not remaining:
                run.stats[campaign.campaign_key] = {'note': 'no untouched leads'}
                continue
            log(f"[{campaign.campaign_key}] {len(remaining)} untouched lead(s)")

            campaign_stats = {'contacted': 0, 'invites_sent': 0, 'inmails_sent': 0, 'opentomsg_checked': 0, 'leftover': 0}

            for link in links:
                if is_stop_requested():
                    _stop_note(run, log)
                    break
                if account_ids is not None and link.account_id not in account_ids:
                    continue
                if not remaining:
                    break
                account = link.account
                run.record_target(campaign.id, account.id)
                if account.status != 'active':
                    reason = {'paused': 'paused by user',
                              'needs_reauth': 'session needs refresh',
                              'seat_required': 'saved session requires Sales Navigator access'}.get(
                                  account.status, f'account status: {account.status}')
                    log(f"[{campaign.campaign_key}/{account.name}] skipped: {reason} - rolling leads to next account")
                    continue

                if not any(lead.associate_account_id in (None, account.id) for lead in remaining):
                    log(f'[{campaign.campaign_key}/{account.name}] no eligible leads for this account - skipping')
                    continue

                daily = _get_daily(db, campaign.id, account.id, today)
                invite_limit, inmail_limit, _msg_cap = _effective_limits(link, db, daily)
                invite_count = daily.invite_sent_count
                inmail_count = daily.opentomsg_count
                weekly = weekly_invite_status(db, account)
                weekly_remaining = max(0, weekly['remaining'] - simulated_weekly.get(account.id, 0))
                invite_limit = min(invite_limit, invite_count + weekly_remaining)
                log(f"[{campaign.campaign_key}/{account.name}] weekly invitations: {weekly['used']}/{weekly['limit']} (resets Monday); {weekly_remaining} remaining")

                log(f"[{campaign.campaign_key}/{account.name}] "
                    f"budget: InMail {inmail_count}/{inmail_limit}, Invite {invite_count}/{invite_limit}")

                if invite_count >= invite_limit and inmail_count >= inmail_limit:
                    log(f"[{campaign.campaign_key}/{account.name}] both budgets exhausted - rolling to next account")
                    continue

                # Seat check via inbox fetch (same probe the legacy script used)
                session = None
                if not dry_run:
                    try:
                        session = _AccountSession(load_session_ref(account), account.id, db)
                        li.fetch_inbox(session, count=10)
                    except li.SeatRequiredError:
                        log(f"[{campaign.campaign_key}/{account.name}] no Sales Nav seat - skipping account")
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: no Sales Navigator seat")
                        continue
                    except Exception as e:
                        log(f"[{campaign.campaign_key}/{account.name}] session/inbox error: {e}")
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: {e}")
                        continue

                account_contacted = 0
                account_invites = 0
                account_inmails = 0
                leftover = []
                inmail_stopped = False  # MESSAGE_VALIDATION_PLUGIN_ERROR trips this
                rate_guard = _RateLimitGuard()  # stops only after consecutive 429s
                c400 = _Connect400Guard()  # stops only after consecutive HTTP 400s
                paced_real_send = False  # a live send happened this iteration
                opentomsg_checks = 0

                for i, lead in enumerate(remaining, 1):
                    if is_stop_requested():
                        _stop_note(run, log)
                        leftover.extend(remaining[i - 1:])
                        break
                    if inmail_count >= inmail_limit and invite_count >= invite_limit:
                        leftover.extend(remaining[i - 1:])
                        break

                    # Imported/preassigned leads belong to their selected sender.
                    # Only unassigned leads may roll between campaign accounts.
                    if lead.associate_account_id is not None and lead.associate_account_id != account.id:
                        leftover.append(lead)
                        continue

                    if not li.extract_profile_id(lead.sales_nav_id):
                        detail = f"{campaign.campaign_key}/{account.name}: {lead.full_name} has no valid Sales Nav ID - outreach skipped"
                        log(detail)
                        run.errors.append(detail)
                        leftover.append(lead)
                        continue

                    open_flag = lead.opentomsg
                    # Also fetch when the lead was checked before URL capture
                    # existed (opentomsg set, linkedin_url empty) - one-time
                    # backfill so the name becomes a profile link in Leads.
                    if open_flag is None or not lead.linkedin_url:
                        if dry_run:
                            log(f"[{campaign.campaign_key}/{account.name}] DRY RUN: would fetch OpenLink for {lead.full_name}")
                            leftover.append(lead)
                            continue
                        if opentomsg_checks >= OPENTOMSG_CHECK_LIMIT:
                            log(f"[{campaign.campaign_key}/{account.name}] OpenToMsg check limit reached ({OPENTOMSG_CHECK_LIMIT} profile fetches) - remaining leads retained")
                            leftover.extend(remaining[i - 1:])
                            break
                        opentomsg_checks += 1
                        campaign_stats['opentomsg_checked'] += 1
                        try:
                            log(f"[{campaign.campaign_key}/{account.name}] OpenToMsg check {opentomsg_checks}/{OPENTOMSG_CHECK_LIMIT}: {lead.full_name} - checking profile")
                            open_flag, profile_url = li.get_profile_opentomsg(session, lead.sales_nav_id)
                            lead.opentomsg = open_flag
                            if profile_url:
                                lead.linkedin_url = lead.linkedin_url or profile_url
                            db.commit()
                            log(f"[{campaign.campaign_key}/{account.name}] OpenToMsg result: {lead.full_name} - {'open to messages' if open_flag else 'not open to messages'} (saved)")
                            if not li.polite_sleep(5, 10):
                                _stop_note(run, log)
                                leftover.extend(remaining[i - 1:])
                                break
                        except li.LinkedinError as e:
                            detail = f"{campaign.campaign_key}/{account.name}: OpenToMsg check failed for {lead.full_name}: {e}"
                            log(detail)
                            run.errors.append(detail)
                            if e.status in (401, 403) or isinstance(e, li.SeatRequiredError):
                                leftover.extend(remaining[i - 1:])
                                break
                            leftover.append(lead)
                            continue
                    else:
                        log(f"[{campaign.campaign_key}/{account.name}] OpenToMsg cached (no fetch): {lead.full_name} - {'open to messages' if open_flag else 'not open to messages'}")

                    calendar_url = link.calendar_url or ''
                    first_name = lead.first_name or lead.full_name or ''

                    if open_flag and inmail_count < inmail_limit and not inmail_stopped:
                        body = _template_format(campaign.inmail_text, first_name, calendar_url, lead.company)
                        subject = _template_format(campaign.inmail_subject, first_name, calendar_url, lead.company) or f"A quick note for {first_name}"
                        log(f"[{campaign.campaign_key}/{account.name}] InMail attempt -> {lead.full_name}")
                        if dry_run:
                            inmail_count += 1
                            log('DRY RUN: InMail skipped; lead state unchanged')
                            continue
                        else:
                            try:
                                ok, err_kind, detail = li.send_inmail(session, _recipient(lead), subject, body)
                            except li.SeatRequiredError:
                                # Seat revoked mid-run: stop this account,
                                # roll untried leads to the next account, keep
                                # the run alive (was: whole run FAILED).
                                log(f"[{campaign.campaign_key}/{account.name}] no Sales Nav seat - stopping InMails, rolling leads to next account")
                                run.errors.append(f"{campaign.campaign_key}/{account.name}: no Sales Navigator seat (InMail send)")
                                leftover.extend(remaining[i - 1:])
                                break
                            except Exception as e:
                                log(f"[{campaign.campaign_key}/{account.name}] InMail send raised for {lead.full_name}: {e} - rolling leads to next account")
                                run.errors.append(f"{campaign.campaign_key}/{account.name}: InMail send error for {lead.full_name}: {e}")
                                leftover.extend(remaining[i - 1:])
                                break
                        if ok:
                            inmail_count += 1
                            rate_guard.reset()
                            c400.reset()
                            daily.opentomsg_count = inmail_count
                            _set_status(db, lead, LeadStatus.INMAIL_SENT.value, JobType.SEND_CONNECTIONS.value)
                            lead.associate_account_id = account.id
                            _stamp_first_contact(lead, 'inmail')
                            _add_event(db, lead.id, 'outbound', f"InMail sent by {account.name}", JobType.SEND_CONNECTIONS.value)
                            campaign_stats['contacted'] += 1
                            campaign_stats['inmails_sent'] += 1
                            account_contacted += 1
                            account_inmails += 1
                            db.commit()
                            complete_account_action(run, account.id, f'inmail:{lead.id}')
                            log(f"[{campaign.campaign_key}/{account.name}] InMail sent -> {lead.full_name} (confirmed)")
                            paced_real_send = True
                        else:
                            failure = f"{campaign.campaign_key}/{account.name}: InMail failed for {lead.full_name}: {detail or err_kind or 'unknown error'}"
                            log(f"{failure} - not counted as sent")
                            run.errors.append(failure)
                            if err_kind == 'validation':
                                log(f"[{campaign.campaign_key}/{account.name}] InMail validation error: {detail} - stopping InMails for this account this run")
                                inmail_stopped = True
                                leftover.append(lead)
                            elif err_kind == 'rate_limited':
                                # Single 429 = transient: retain the lead and
                                # keep going. Only consecutive 429s stop the
                                # account for the rest of this run.
                                leftover.append(lead)
                                if rate_guard.hit():
                                    log(f"[{campaign.campaign_key}/{account.name}] rate-limited ({RATE_LIMIT_429_THRESHOLD} consecutive HTTP 429) - stopping this account")
                                    run.errors.append(f"{campaign.campaign_key}/{account.name}: HTTP 429 x{rate_guard.streak}")
                                    leftover.extend(remaining[i:])
                                    break
                                log(f"[{campaign.campaign_key}/{account.name}] HTTP 429 ({rate_guard.streak}/{RATE_LIMIT_429_THRESHOLD}) on {lead.full_name} - lead retained, continuing")
                                li.polite_sleep(10, 20)
                            else:
                                if err_kind in ('email_required', 'bad_request') and c400.hit(lead.id):
                                    _connect_400_streak_stop(db, run, log, f"{campaign.campaign_key}/{account.name}", c400)
                                    leftover.append(lead)
                                    leftover.extend(remaining[i:])
                                    break
                                lead_reason = detail or ('Email is required to connect' if err_kind == 'email_required' else 'InMail send failed')
                                _set_status(db, lead, LeadStatus.BLOCKED_ERROR.value, JobType.SEND_CONNECTIONS.value,
                                            detail=f"blocked: {lead_reason}")
                                lead.last_error = lead_reason
                                _add_event(db, lead.id, 'error', f"InMail failed: {detail} - lead blocked ({lead_reason})", JobType.SEND_CONNECTIONS.value)
                                db.commit()
                                log(f"[{campaign.campaign_key}/{account.name}] lead {lead.full_name} marked {LeadStatus.BLOCKED_ERROR.value} - skipped in future runs")
                                leftover.append(lead)
                                li.polite_sleep(10, 20)

                    elif not open_flag and invite_count < invite_limit:
                        # Recheck immediately before each invite, including cap edits during a run.
                        db.refresh(account, ['weekly_invite_cap'])
                        weekly = weekly_invite_status(db, account)
                        if weekly['remaining'] <= simulated_weekly.get(account.id, 0):
                            log(f"[{account.name}] weekly invitation limit reached - invite skipped")
                            leftover.append(lead)
                            continue
                        note = _template_format(campaign.invite_text, first_name, calendar_url, lead.company)
                        profile_id = li.extract_profile_id(lead.sales_nav_id)
                        log(f"[{campaign.campaign_key}/{account.name}] Invite attempt -> {lead.full_name}")
                        if dry_run:
                            invite_count += 1
                            simulated_weekly[account.id] = simulated_weekly.get(account.id, 0) + 1
                            log('DRY RUN: invitation skipped; lead state unchanged')
                            continue
                        else:
                            try:
                                ok, err_kind, detail = li.send_connection_invite(session, profile_id, note)
                            except li.SeatRequiredError:
                                # Seat revoked mid-run: stop this account,
                                # roll untried leads to the next account, keep
                                # the run alive (was: whole run FAILED).
                                log(f"[{campaign.campaign_key}/{account.name}] no Sales Nav seat - stopping invites, rolling leads to next account")
                                run.errors.append(f"{campaign.campaign_key}/{account.name}: no Sales Navigator seat (invite send)")
                                leftover.extend(remaining[i - 1:])
                                break
                            except Exception as e:
                                log(f"[{campaign.campaign_key}/{account.name}] Invite send raised for {lead.full_name}: {e} - rolling leads to next account")
                                run.errors.append(f"{campaign.campaign_key}/{account.name}: Invite send error for {lead.full_name}: {e}")
                                leftover.extend(remaining[i - 1:])
                                break
                        if ok:
                            invite_count += 1
                            rate_guard.reset()
                            c400.reset()
                            daily.invite_sent_count = invite_count
                            db.add(AccountInviteSend(account_id=account.id, sent_at=_now(), count=1))
                            _set_status(db, lead, LeadStatus.INVITE_SENT.value, JobType.SEND_CONNECTIONS.value)
                            lead.associate_account_id = account.id
                            _stamp_first_contact(lead, 'invite')
                            _add_event(db, lead.id, 'outbound', f"Connection invite sent by {account.name}", JobType.SEND_CONNECTIONS.value)
                            campaign_stats['contacted'] += 1
                            campaign_stats['invites_sent'] += 1
                            account_contacted += 1
                            account_invites += 1
                            db.commit()
                            complete_account_action(run, account.id, f'invite:{lead.id}')
                            log(f"[{campaign.campaign_key}/{account.name}] Invite sent -> {lead.full_name} (confirmed)")
                            paced_real_send = True
                        else:
                            failure = f"{campaign.campaign_key}/{account.name}: Invite failed for {lead.full_name}: {detail or err_kind or 'unknown error'}"
                            log(f"{failure} - not counted as sent")
                            run.errors.append(failure)
                            if err_kind == 'rate_limited':
                                # Single 429 = transient: retain the lead and
                                # keep going. Only consecutive 429s stop the
                                # account for the rest of this run.
                                leftover.append(lead)
                                if rate_guard.hit():
                                    log(f"[{campaign.campaign_key}/{account.name}] rate-limited ({RATE_LIMIT_429_THRESHOLD} consecutive HTTP 429) - stopping this account")
                                    run.errors.append(f"{campaign.campaign_key}/{account.name}: HTTP 429 x{rate_guard.streak}")
                                    leftover.extend(remaining[i:])
                                    break
                                log(f"[{campaign.campaign_key}/{account.name}] HTTP 429 ({rate_guard.streak}/{RATE_LIMIT_429_THRESHOLD}) on {lead.full_name} - lead retained, continuing")
                                li.polite_sleep(10, 20)
                            else:
                                if err_kind in ('email_required', 'bad_request') and c400.hit(lead.id):
                                    _connect_400_streak_stop(db, run, log, f"{campaign.campaign_key}/{account.name}", c400)
                                    leftover.append(lead)
                                    leftover.extend(remaining[i:])
                                    break
                                reason = detail or ('Email is required to connect' if err_kind == 'email_required' else 'Connection request failed')
                                _set_status(db, lead, LeadStatus.BLOCKED_ERROR.value, JobType.SEND_CONNECTIONS.value,
                                            detail=f"blocked: {reason}")
                                lead.last_error = reason
                                _add_event(db, lead.id, 'error', f"Invite failed: {detail} - lead blocked ({reason})", JobType.SEND_CONNECTIONS.value)
                                db.commit()
                                log(f"[{campaign.campaign_key}/{account.name}] lead {lead.full_name} marked {LeadStatus.BLOCKED_ERROR.value} - skipped in future runs")
                                li.polite_sleep(10, 20)
                    else:
                        # No budget for this lead's path on this account
                        leftover.append(lead)

                    # Pace AFTER the action is committed: a stop arriving during
                    # the sleep no longer discards a delivered invite/InMail.
                    if paced_real_send:
                        paced_real_send = False
                        if not li.polite_sleep():
                            _stop_note(run, log)
                            leftover.extend(remaining[i:])
                            break

                db.commit()
                log(f"[{campaign.campaign_key}/{account.name}] done: contacted {account_contacted}, "
                    f"final InMail {inmail_count}/{inmail_limit}, Invite {invite_count}/{invite_limit}")
                # Per-account card line (like Follow-ups): what THIS account sent.
                # Zeros are hidden by the notification formatter, so quiet accounts
                # simply don't appear in the GChat card.
                run.stats[f"{campaign.campaign_key}/{account.name}"] = {
                    'contacted': account_contacted,
                    'invites_sent': account_invites,
                    'inmails_sent': account_inmails,
                    'opentomsg_checked': opentomsg_checks,
                }
                remaining = leftover

            campaign_stats['leftover'] = len(remaining)
            if remaining:
                log(f"[{campaign.campaign_key}] {len(remaining)} lead(s) left over - retained for a future run")
            run.stats[f"{campaign.campaign_key} \u00b7 Totals"] = campaign_stats
            db.commit()

        run.finish()
    except Exception as e:
        db.rollback()
        _fatal(db, JobType.SEND_CONNECTIONS, e, run_row=run.run if run else None)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Shared: sessions + notifications plumbing
# ---------------------------------------------------------------------------

def canonical_cookies_path(account) -> str:
    """The ONE fixed cookies filename for an account.

    Every upload (and session verification) lands here no matter what the
    uploaded file was called, so an account never ends up with two competing
    cookie files. Preference: the get_cookies.py registry path (so local
    captures and web uploads share a single file) with fallback to
    ./cookies_files/<slugified account name>_cookies.json.
    Returns an absolute path string anchored at PROJECT_ROOT.
    """
    import re
    from .config import PROJECT_ROOT
    cookies_dir = os.path.join(PROJECT_ROOT, 'cookies_files')
    try:
        legacy = importlib.import_module('get_cookies')
        reg = getattr(legacy, 'ACCOUNTS', {}).get(account.name, {}).get('cookies_file')
        if reg:
            return os.path.normpath(os.path.join(PROJECT_ROOT, reg))
    except Exception:
        pass
    slug = re.sub(r'[^a-z0-9]+', '_', (account.name or 'account').lower()).strip('_') or 'account'
    return os.path.join(cookies_dir, f'{slug}_cookies.json')


def stale_cookie_candidates(account, keep: str):
    """Every file that has historically held this account's cookies
    (DB session_ref, get_cookies registry path, first-name guess) minus the
    canonical file we keep. Used to delete old, differently-named copies so
    a fixed name per account is the only one left on disk."""
    from .config import PROJECT_ROOT
    first = account.name.split()[0].lower() if account.name else ''
    cands = {
        account.session_ref,
        f"./cookies_files/{first}_cookies.json" if first else None,
    }
    try:
        legacy = importlib.import_module('get_cookies')
        cands.add(getattr(legacy, 'ACCOUNTS', {}).get(account.name, {}).get('cookies_file'))
    except Exception:
        pass
    keep_norm = os.path.normpath(keep)
    out = []
    for c in cands:
        if not c:
            continue
        if os.path.normpath(os.path.abspath(c)) == keep_norm:
            continue
        out.append(c)
    return out


def load_session_ref(account: Account, persist: bool = False):
    """Resolve an Account row to a live curl_cffi session via get_cookies.

    Order (never auto-launches a browser capture from the web app):
    1. DB session_ref that exists on disk wins.
    2. Registered get_cookies account -> its registered cookies file.
    3. Conventional ./cookies_files/<first>_cookies.json guess.
    4. Otherwise raise - capture cookies locally with get_cookies.py first.

    persist=True (used by the Verify endpoint) writes the resolved path back
    to account.session_ref so a session found via legacy/fallback lookup is
    shown as configured in the UI instead of "Session missing" after a
    successful verification.
    """
    LEGACY_ACCOUNTS = {}
    try:
        legacy_module = importlib.import_module('get_cookies')
        LEGACY_ACCOUNTS = getattr(legacy_module, 'ACCOUNTS', {})
    except Exception:
        LEGACY_ACCOUNTS = {}

    # Gather every candidate file, then prefer the NEWEST one. A stale
    # session_ref used to shadow a freshly captured conventional/legacy
    # file (e.g. get_cookies.py rewrote <first>_cookies.json while the DB
    # still pointed at an older web-upload path) - the app kept 401-ing on
    # expired cookies even though new ones sat right next to them.
    candidates = [canonical_cookies_path(account)]
    if account.session_ref:
        candidates.append(account.session_ref)
    legacy_path = LEGACY_ACCOUNTS.get(account.name, {}).get('cookies_file')
    if legacy_path:
        candidates.append(legacy_path)
    first = account.name.split()[0].lower() if account.name else ''
    if first:
        candidates.append(f"./cookies_files/{first}_cookies.json")
    existing = [c for c in dict.fromkeys(candidates) if c and os.path.exists(c)]
    if existing:
        newest = max(existing, key=lambda c: os.path.getmtime(c))
        if persist and newest != account.session_ref:
            account.session_ref = newest
        return _session_from_files({'cookies_file': newest})
    raise li.LinkedinError(
        f"No session file for {account.name!r} (session_ref={account.session_ref!r}). "
        "Capture cookies locally with get_cookies.py first."
    )


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


def verify_account_sessions(accounts: list, db=None) -> list[str]:
    """Try to load session files for each account. Returns a list of error strings
    for accounts whose session files are missing or invalid.
    Used by the pre-job check in main.py and for improved error logging in job loops."""
    errors = []
    for account in accounts:
        try:
            load_session_ref(account)
        except Exception as exc:
            errors.append(f'{account.name}: {exc}')
    return errors


def notify_run_summary_and_errors(run, label):
    """Deprecated no-op kept for compatibility.
    GChat dedupe: the ONE completion card is emitted by _finish ->
    notify.notify_lifecycle (stats + duration + errors). The separate
    'Run summary' + 'Execution warnings' cards sent here duplicated it on
    every run, so they were removed. Stopped/dry runs stay silent.
    """
    return None


def _fatal(db: OrmSession, job_type: JobType, exc: Exception, run_row: RunLog | None = None, schedule_id=None, schedule_name=None):
    """Finalize the job's own run row (preferred), else the latest stuck 'running'
    row, else a fresh '(fatal)' row — then alert immediately."""
    if isinstance(exc, JobStoppedError) and run_row is not None:
        _finish(run_row, db, RunStatus.STOPPED, run_row.stats or {}, [])
        return
    from .runner import execution_context
    dry_run = bool(run_row.dry_run) if run_row is not None else getattr(execution_context, 'dry_run', False)
    traceback.print_exc()
    try:
        row = run_row
        if row is None and getattr(execution_context, 'run_token', None):
            row = db.query(RunLog).filter_by(
                job_type=job_type.value, status=RunStatus.RUNNING.value,
                execution_id=execution_context.run_token,
            ).order_by(RunLog.id.desc()).first()
        if row is not None:
            row.status = RunStatus.ERROR.value
            row.finished_at = _now()
            row.duration_s = (row.finished_at - row.started_at).total_seconds() if row.started_at else 0
            row.errors = [str(exc)[:1000]]
            row.log_text = '\n'.join(getattr(row, '_log_lines', [])) + '\nERROR: ' + str(exc)[:1000]
        else:
            db.add(RunLog(
                job_type=job_type.value, target=schedule_name or '(fatal)', schedule_id=schedule_id, status=RunStatus.ERROR.value,
                started_at=_now(), finished_at=_now(), duration_s=0, errors=[str(exc)[:1000]], dry_run=dry_run,
            ))
        db.commit()
    except Exception:
        db.rollback()
        pass
    if dry_run:
        return
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
    today = _now().date()
    try:
        # Run attribution for history scoping (see job_send_connections).
        _scope_campaigns = sorted(campaign_ids) if campaign_ids else None
        _scope_accounts = sorted(account_ids) if account_ids else None
        run = _Run(db, JobType.CHECK_REPLIES, 'All campaigns/accounts', dry_run,
                   campaign_id=(_scope_campaigns[0] if _scope_campaigns and len(_scope_campaigns) == 1 else None),
                   account_id=(_scope_accounts[0] if _scope_accounts and len(_scope_accounts) == 1 else None))
        log = run.log
        campaigns = db.execute(select(Campaign).where(Campaign.status == 'active').order_by(Campaign.id)).scalars().all()
        if campaign_ids is not None:
            campaigns = [c for c in campaigns if c.id in campaign_ids]

        replies_found = []

        from .runner import is_stop_requested
        for campaign in campaigns:
            if is_stop_requested():
                _stop_note(run, log)
                break
            links = sorted(campaign.account_links, key=lambda l: l.order_index)
            for link in links:
                if is_stop_requested():
                    _stop_note(run, log)
                    break
                if account_ids is not None and link.account_id not in account_ids:
                    continue
                account = link.account
                run.record_target(campaign.id, account.id)
                if account.status != 'active':
                    log(f"[{campaign.campaign_key}/{account.name}] reply check skipped: account status {account.status}; inbox not checked")
                    continue

                # --- Shared daily budget: after-acceptance half-limit threshold ---
                daily = _get_daily(db, campaign.id, account.id, today)
                messages_sent = daily.messages_sent
                _invite_l, _inmail_l, msg_cap = _effective_limits(link, db, daily)
                message_limit = max(0, round(msg_cap / 2))

                def limit_reached():
                    return messages_sent >= message_limit

                log(f"[{campaign.campaign_key}/{account.name}] shared message budget: {messages_sent}/{message_limit}")

                candidates = db.execute(select(Lead).where(
                    Lead.campaign_id == campaign.id,
                    Lead.associate_account_id == account.id,
                    Lead.received_replies.is_(False),
                )).scalars().all()
                pending_invites = [lead for lead in candidates if lead.status == LeadStatus.INVITE_SENT.value]
                campaign_account_stats = {
                    'records_to_check': len(candidates), 'pending_invites': len(pending_invites),
                    'threads_fetched': 0, 'threads_matched': 0, 'accepts_found': 0,
                    'accepts_messaged': 0, 'new_replies': 0,
                }
                rate_guard = _RateLimitGuard()  # stops only after consecutive 429s
                run.stats[f"{campaign.campaign_key}/{account.name}"] = campaign_account_stats
                log(f"[{campaign.campaign_key}/{account.name}] {len(candidates)} record(s) to check, {len(pending_invites)} pending invite(s)")
                # _get_daily may INSERT today's counter. Release that SQLite
                # write lock before the remote inbox request (which can wait
                # for 30s), so logins and other UI writes remain available.
                db.commit()

                session = None
                if not dry_run:
                    try:
                        session = _AccountSession(load_session_ref(account), account.id, db)
                        inbox = li.fetch_inbox(session, count=90)
                    except li.SeatRequiredError:
                        log(f"[{campaign.campaign_key}/{account.name}] no Sales Nav seat - skipping")
                        campaign_account_stats['note'] = 'Inbox not checked: saved session requires Sales Navigator access'
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: no Sales Navigator seat")
                        continue
                    except Exception as e:
                        log(f"[{campaign.campaign_key}/{account.name}] session/inbox error: {e}")
                        campaign_account_stats['note'] = 'Inbox not checked: session/inbox error'
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: {e}")
                        continue

                    msgs = inbox.get('elements', [])
                    threads_by_lead = {
                        li.profile_identity(t['participants'][0]): t for t in msgs
                        if t.get('participants') and li.profile_identity(t['participants'][0])
                    }
                    campaign_account_stats['threads_fetched'] = len(msgs)
                else:
                    threads_by_lead = {}
                    campaign_account_stats['note'] = 'Dry run: inbox not fetched; accepts and replies not checked'
                    log(f"[{campaign.campaign_key}/{account.name}] DRY RUN: inbox not fetched; accepts and replies not checked")

                campaign_account_stats['threads_matched'] = sum(
                    li.profile_identity(lead.sales_nav_id) in threads_by_lead for lead in candidates)
                log(f"[{campaign.campaign_key}/{account.name}] {campaign_account_stats['threads_fetched']} inbox thread(s), "
                    f"{campaign_account_stats['threads_matched']}/{len(candidates)} lead(s) matched by profile ID")

                def lead_messages(lead, thread):
                    # Match the lead's author, never the account's own message
                    # or an invitation/system event. Check before sending.
                    identity = li.profile_identity(lead.sales_nav_id)
                    return [m for m in (thread.get('messages') or [])
                            if identity and li.profile_identity(m.get('author')) == identity
                            and m.get('body') and m.get('type') not in ('INVITATION', 'SYSTEM')]

                # --- 1) Invite accepts ---
                accepted_invites = []
                for lead in pending_invites:
                    thread = threads_by_lead.get(li.profile_identity(lead.sales_nav_id))
                    thread_msgs = (thread or {}).get('messages') or []
                    if thread_msgs and thread_msgs[0].get('type') == 'INVITATION':
                        accepted_invites.append(lead)
                campaign_account_stats['accepts_found'] = len(accepted_invites)
                if not dry_run:
                    log(f"[{campaign.campaign_key}/{account.name}] Found {len(accepted_invites)} invite accepts")

                for lead in accepted_invites:
                    if is_stop_requested():
                        _stop_note(run, log)
                        break
                    if dry_run:
                        break
                    thread = threads_by_lead[li.profile_identity(lead.sales_nav_id)]
                    if lead_messages(lead, thread):
                        log(f"[{campaign.campaign_key}/{account.name}] after-accept skipped for {lead.full_name}: lead already replied")
                        continue
                    if limit_reached():
                        log(f"[{campaign.campaign_key}/{account.name}] shared budget reached - stopping accepts")
                        break
                    _after_accept_tpl = (campaign.invite_track or [''])[0]
                    if not (_after_accept_tpl or '').strip():
                        # Blank after-acceptance template must not send an
                        # empty message. The lead stays INVITE_SENT so the
                        # message goes out once a template is configured.
                        campaign_account_stats['accepts_skipped_blank'] = campaign_account_stats.get('accepts_skipped_blank', 0) + 1
                        log(f"[{campaign.campaign_key}/{account.name}] after-acceptance template is blank - skipped {lead.full_name} (no message sent)")
                        continue
                    log(f"[{campaign.campaign_key}/{account.name}] invite accepted by {lead.full_name} - sending after-acceptance message")
                    body = _template_format(
                        _after_accept_tpl,
                        lead.first_name or lead.full_name,
                        link.calendar_url or '',
                        lead.company,
                    )
                    recipient = thread['participants'][0]
                    try:
                        ok, err_kind, detail = li.send_message(session, _recipient(lead), body)
                    except li.SeatRequiredError:
                        # The inbox fetch succeeded but the seat was revoked
                        # mid-run (or LinkedIn only enforces it on sends).
                        # Previously this exception killed the WHOLE run ->
                        # 'Failed' alert. Stop this account, keep the run alive,
                        # let remaining campaigns/accounts continue.
                        log(f"[{campaign.campaign_key}/{account.name}] no Sales Nav seat - skipping remaining after-acceptance sends")
                        campaign_account_stats['note'] = 'Seat lost mid-run: no further sends; replies still checked from the fetched inbox'
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: no Sales Navigator seat (after-accept send)")
                        break
                    except Exception as e:
                        failure = f"{campaign.campaign_key}/{account.name}: after-accept send raised for {lead.full_name}: {e}"
                        log(failure)
                        run.errors.append(failure)
                        continue
                    if ok:
                        messages_sent += 1
                        rate_guard.reset()
                        daily.messages_sent = messages_sent
                        _set_status(db, lead, LeadStatus.INVITE_AFTER_ACCEPT.value, JobType.CHECK_REPLIES.value)
                        _stamp_followup(lead, 'INVITE_AFTER_ACCEPT')
                        _add_event(db, lead.id, 'outbound', 'After-acceptance message sent', JobType.CHECK_REPLIES.value)
                        campaign_account_stats['accepts_messaged'] += 1
                        db.commit()
                        complete_account_action(run, account.id, f'accept:{lead.id}')
                        log(f"[{campaign.campaign_key}/{account.name}] after-acceptance message sent to {lead.full_name} (confirmed)")
                        # Pace AFTER the commit: a stop during the sleep no
                        # longer discards the delivered after-accept message.
                        if not li.polite_sleep(10, 20):
                            _stop_note(run, log)
                            break
                    else:
                        failure = f"{campaign.campaign_key}/{account.name}: after-accept failed for {lead.full_name}: {detail}"
                        # Mirror the raw scripts: every failure must be visible
                        # in the console log, not only the error digest.
                        log(f"[{campaign.campaign_key}/{account.name}] after-accept send failed ({detail}), status not updated")
                        log(failure)
                        run.errors.append(failure)
                        _add_event(db, lead.id, 'error', failure, JobType.CHECK_REPLIES.value)
                        db.commit()
                        if err_kind == 'validation':
                            break
                        if err_kind == 'rate_limited':
                            # Single 429 = transient - keep going. Only
                            # consecutive 429s stop this account's sends.
                            if rate_guard.hit():
                                log(f"[{campaign.campaign_key}/{account.name}] rate-limited ({RATE_LIMIT_429_THRESHOLD} consecutive HTTP 429) - stopping after-acceptance sends")
                                break
                            log(f"[{campaign.campaign_key}/{account.name}] HTTP 429 ({rate_guard.streak}/{RATE_LIMIT_429_THRESHOLD}) on {lead.full_name} - continuing")

                # --- 2) Reply detection ---
                for lead in candidates:
                    if is_stop_requested():
                        _stop_note(run, log)
                        break
                    thread = threads_by_lead.get(li.profile_identity(lead.sales_nav_id))
                    if not thread:
                        continue
                    lead_replies = lead_messages(lead, thread)
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
        if not is_stop_requested():
            if replies_found and not dry_run:
                notify.send_reply_digest(replies_found)
                notify.notify_new_replies(replies_found)
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
# Delay days come from OCC_INVITE_FU_DAYS / OCC_INMAIL_FU_DAYS (comma list,
# legacy order +3/+5/+7) so operators can retime follow-ups without a deploy.
def _fu_days(env_key: str, default: str) -> list[int]:
    raw = (os.environ.get(env_key, '') or '').strip() or default
    days = []
    for part in raw.split(','):
        try:
            v = int(part.strip())
        except ValueError:
            continue
        if v >= 0:
            days.append(v)
    # Pad/trim to exactly 3 stages (0 = send same day).
    while len(days) < 3:
        days.append(days[-1] if days else 0)
    return days[:3]


_INVITE_DAYS = _fu_days('OCC_INVITE_FU_DAYS', '3,5,7')
_INMAIL_DAYS = _fu_days('OCC_INMAIL_FU_DAYS', '3,5,7')


def reload_fu_days():
    """Re-read OCC_*_FU_DAYS from the settings store + env (Settings page PUT).
    Values persisted in the settings table win over env defaults."""
    global _INVITE_DAYS, _INMAIL_DAYS
    try:
        from .database import SessionLocal
        from .models import Setting
        db = SessionLocal()
        try:
            for key, target in (('OCC_INVITE_FU_DAYS', '_INVITE_DAYS'), ('OCC_INMAIL_FU_DAYS', '_INMAIL_DAYS')):
                row = db.get(Setting, key)
                if row is not None and (row.value_json or '').strip():
                    days = _fu_days(key, row.value_json.strip())
                    globals()[target] = days
                    os.environ[key] = row.value_json.strip()
        finally:
            db.close()
    except Exception:
        pass  # settings store unavailable — keep current values
    _rebuild_fu_stages()


def _rebuild_fu_stages():
    global INVITE_STAGES, INMAIL_STAGES
    INVITE_STAGES = [
        ('INVITE_AFTER_ACCEPT', _INVITE_DAYS[0], 1, 'INVITE_FOLLOWUP_1', 'Invite Follow-up 1'),
        ('INVITE_FOLLOWUP_1', _INVITE_DAYS[1], 2, 'INVITE_FOLLOWUP_2', 'Invite Follow-up 2'),
        ('INVITE_FOLLOWUP_2', _INVITE_DAYS[2], 3, 'INVITE_FOLLOWUP_3', 'Invite Follow-up 3'),
    ]
    INMAIL_STAGES = [
        ('INMAIL_SENT', _INMAIL_DAYS[0], 0, 'INMAIL_FOLLOWUP_1', 'InMail Follow-up 1'),
        ('INMAIL_FOLLOWUP_1', _INMAIL_DAYS[1], 1, 'INMAIL_FOLLOWUP_2', 'InMail Follow-up 2'),
        ('INMAIL_FOLLOWUP_2', _INMAIL_DAYS[2], 2, 'INMAIL_FOLLOWUP_3', 'InMail Follow-up 3'),
    ]


def _build_campaign_stages(c: Campaign):
    inv_days = c.invite_fu_days if (isinstance(c.invite_fu_days, list) and len(c.invite_fu_days) >= 3) else _INVITE_DAYS
    inm_days = c.inmail_fu_days if (isinstance(c.inmail_fu_days, list) and len(c.inmail_fu_days) >= 3) else _INMAIL_DAYS
    try:
        inv_days = [max(0, int(d)) for d in inv_days[:3]]
    except Exception:
        inv_days = list(_INVITE_DAYS)
    try:
        inm_days = [max(0, int(d)) for d in inm_days[:3]]
    except Exception:
        inm_days = list(_INMAIL_DAYS)
    while len(inv_days) < 3:
        inv_days.append(inv_days[-1] if inv_days else 0)
    while len(inm_days) < 3:
        inm_days.append(inm_days[-1] if inm_days else 0)

    invite_stages = [
        ('INVITE_AFTER_ACCEPT', inv_days[0], 1, 'INVITE_FOLLOWUP_1', 'Invite Follow-up 1'),
        ('INVITE_FOLLOWUP_1', inv_days[1], 2, 'INVITE_FOLLOWUP_2', 'Invite Follow-up 2'),
        ('INVITE_FOLLOWUP_2', inv_days[2], 3, 'INVITE_FOLLOWUP_3', 'Invite Follow-up 3'),
    ]
    inmail_stages = [
        ('INMAIL_SENT', inm_days[0], 0, 'INMAIL_FOLLOWUP_1', 'InMail Follow-up 1'),
        ('INMAIL_FOLLOWUP_1', inm_days[1], 1, 'INMAIL_FOLLOWUP_2', 'InMail Follow-up 2'),
        ('INMAIL_FOLLOWUP_2', inm_days[2], 2, 'INMAIL_FOLLOWUP_3', 'InMail Follow-up 3'),
    ]
    return invite_stages, inmail_stages


_rebuild_fu_stages()


def job_send_followups(campaign_ids: list[int] | None = None, account_ids: list[int] | None = None, dry_run=False):
    """JOB 5: staged follow-ups (per-campaign configurable delays) for both tracks, skipping any
    lead with received_replies. Draws from the SHARED messages_sent budget
    up to the full effective daily limit, shared with Job 4."""
    run = None
    db = SessionLocal()
    today = _now().date()
    try:
        # Run attribution for history scoping (see job_send_connections).
        _scope_campaigns = sorted(campaign_ids) if campaign_ids else None
        _scope_accounts = sorted(account_ids) if account_ids else None
        run = _Run(db, JobType.SEND_FOLLOWUPS, 'All campaigns/accounts', dry_run,
                   campaign_id=(_scope_campaigns[0] if _scope_campaigns and len(_scope_campaigns) == 1 else None),
                   account_id=(_scope_accounts[0] if _scope_accounts and len(_scope_accounts) == 1 else None))
        log = run.log
        campaigns = db.execute(select(Campaign).where(Campaign.status == 'active').order_by(Campaign.id)).scalars().all()
        if campaign_ids is not None:
            campaigns = [c for c in campaigns if c.id in campaign_ids]

        from .runner import is_stop_requested
        for campaign in campaigns:
            if is_stop_requested():
                _stop_note(run, log)
                break
            camp_invite_stages, camp_inmail_stages = _build_campaign_stages(campaign)
            links = sorted(campaign.account_links, key=lambda l: l.order_index)
            for link in links:
                if is_stop_requested():
                    _stop_note(run, log)
                    break
                if account_ids is not None and link.account_id not in account_ids:
                    continue
                account = link.account
                run.record_target(campaign.id, account.id)
                if account.status != 'active':
                    continue

                daily = _get_daily(db, campaign.id, account.id, today)
                messages_sent = daily.messages_sent
                _invite_l, _inmail_l, msg_cap = _effective_limits(link, db, daily)
                message_limit = msg_cap

                log(f"[{campaign.campaign_key}/{account.name}] shared message budget: {messages_sent}/{message_limit}")

                session = None
                if not dry_run:
                    try:
                        session = _AccountSession(load_session_ref(account), account.id, db)
                        li.fetch_inbox(session, count=10)  # seat probe
                    except li.SeatRequiredError:
                        log(f"[{campaign.campaign_key}/{account.name}] no Sales Nav seat - skipping")
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: no Sales Navigator seat")
                        continue
                    except Exception as e:
                        log(f"[{campaign.campaign_key}/{account.name}] session/inbox error: {e}")
                        run.errors.append(f"{campaign.campaign_key}/{account.name}: {e}")
                        continue

                stage_counts = {}
                sent_this_run = 0
                account_stopped = False  # validation errors halt every stage
                rate_guard = _RateLimitGuard()  # 429 stops only after consecutive hits

                for stage_list, track_name in ((camp_invite_stages, 'invite'), (camp_inmail_stages, 'inmail')):
                    if account_stopped:
                        break
                    for trigger_status, days_after, track_index, result_status, label in stage_list:
                        if is_stop_requested():
                            _stop_note(run, log)
                            account_stopped = True
                            break
                        if account_stopped:
                            break
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
                        template = track[track_index] if track_index < len(track) else None
                        # A missing OR BLANK template never sends: a stage the
                        # user left empty (e.g. only 2 follow-ups configured)
                        # must not go out as an empty message. Invite stage
                        # indexes start at 1 (0 is the after-acceptance note
                        # handled by check_replies), so blank is never a
                        # valid configured stage here.
                        _tpl_body = template.get('body', '') if isinstance(template, dict) else (template or '')
                        if template is None or not str(_tpl_body).strip():
                            log(f"[{campaign.campaign_key}/{account.name}] {label}: no template configured - skipping {len(leads)} lead(s)")
                            stage_counts[label] = 0
                            continue

                        stage_sent = 0
                        for lead in leads:
                            if is_stop_requested():
                                _stop_note(run, log)
                                account_stopped = True
                                break
                            if messages_sent >= message_limit:
                                log(f"[{campaign.campaign_key}/{account.name}] shared budget reached at {label}")
                                break
                            first_name = lead.first_name or lead.full_name or ''
                            calendar_url = link.calendar_url or ''

                            if track_name == 'inmail':
                                body = _template_format(template.get('body', ''), first_name, calendar_url, lead.company)
                                subject = template.get('subject') or ''
                                subject = _template_format(subject, first_name, calendar_url, lead.company)
                            else:
                                body = _template_format(template, first_name, calendar_url, lead.company)
                                subject = ''

                            log(f"[{campaign.campaign_key}/{account.name}] {label} -> {lead.full_name}")
                            if dry_run:
                                # Dry run: nothing is sent and no state may advance.
                                stage_counts[label] = stage_counts.get(label, 0)
                                continue

                            try:
                                if track_name == 'inmail':
                                    ok, err_kind, detail = li.send_inmail(session, _recipient(lead), subject, body)
                                else:
                                    ok, err_kind, detail = li.send_message(session, _recipient(lead), body)
                            except li.SeatRequiredError:
                                # Seat revoked mid-run (or only enforced on
                                # sends): stop this account, keep the run alive.
                                log(f"[{campaign.campaign_key}/{account.name}] no Sales Nav seat - stopping follow-ups for this account")
                                run.errors.append(f"{campaign.campaign_key}/{account.name}: no Sales Navigator seat (follow-up send)")
                                account_stopped = True
                                break
                            except Exception as e:
                                failure = f"{campaign.campaign_key}/{account.name}: {label} send raised for {lead.full_name}: {e}"
                                log(failure)
                                run.errors.append(failure)
                                continue

                            if ok:
                                messages_sent += 1
                                rate_guard.reset()
                                daily.messages_sent = messages_sent
                                _set_status(db, lead, result_status, JobType.SEND_FOLLOWUPS.value)
                                _stamp_followup(lead, result_status)
                                _add_event(db, lead.id, 'outbound', f"{label} sent", JobType.SEND_FOLLOWUPS.value)
                                stage_sent += 1
                                sent_this_run += 1
                                db.commit()
                                complete_account_action(run, account.id, f'fu:{lead.id}:{result_status}')
                            else:
                                failure = f"{campaign.campaign_key}/{account.name}: {label} failed for {lead.full_name}: {detail}"
                                log(f"[{campaign.campaign_key}/{account.name}]   -> send failed ({detail}), status not updated")
                                run.errors.append(failure)
                                if err_kind == 'rate_limited':
                                    # Single 429 = transient: the lead stays in
                                    # its trigger status and is retried next
                                    # run. Only consecutive 429s stop the
                                    # account for the rest of this run.
                                    if rate_guard.hit():
                                        log(f"[{campaign.campaign_key}/{account.name}] rate-limited ({RATE_LIMIT_429_THRESHOLD} consecutive HTTP 429) - stopping all stages for this account")
                                        account_stopped = True
                                        break
                                    log(f"[{campaign.campaign_key}/{account.name}] HTTP 429 ({rate_guard.streak}/{RATE_LIMIT_429_THRESHOLD}) on {lead.full_name} - continuing")
                                if err_kind == 'validation':
                                    log(f"[{campaign.campaign_key}/{account.name}] validation error - stopping this account's sends")
                                    account_stopped = True
                                    break
                                # Lead-specific failure (e.g. HTTP 400 Email required,
                                # HTTP 500 recipient rejected): block just this lead
                                # so the same bad recipient never retries forever.
                                if err_kind != 'rate_limited':
                                    _set_status(db, lead, LeadStatus.BLOCKED_ERROR.value, JobType.SEND_FOLLOWUPS.value,
                                                detail=f"blocked: {label} send failed")
                                    lead.last_error = (detail or 'send failed')[:255]
                                    _add_event(db, lead.id, 'error', f"{label} failed: {detail} - lead blocked", JobType.SEND_FOLLOWUPS.value)
                                    db.commit()
                                    log(f"[{campaign.campaign_key}/{account.name}] lead {lead.full_name} marked {LeadStatus.BLOCKED_ERROR.value} - skipped in future runs")
                            # Pace AFTER the action is committed: a stop during
                            # the sleep no longer discards a delivered message.
                            if not li.polite_sleep(15, 30):
                                _stop_note(run, log)
                                account_stopped = True
                                break

                        stage_counts[label] = stage_sent

                run.stats[f"{campaign.campaign_key}/{account.name}"] = {
                    **stage_counts,
                    'messages_sent': f"{messages_sent}/{message_limit}",
                }
                db.commit()

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
