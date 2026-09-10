"""Outreach Command Center — FastAPI backend.

Serves the REST API under /api and the built React frontend from frontend/dist.
Auth: single admin password -> HTTP-only session cookie.
"""
import os
import secrets
from datetime import datetime, date, timedelta

from fastapi import FastAPI, Depends, HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import PROJECT_ROOT, SESSION_TTL_HOURS
from .auth import verify_password, create_session, validate_session, destroy_session
from .database import init_db, get_db, SessionLocal
from . import scheduler
from .models import LeadEvent
from .jobs import _add_event

app = FastAPI(title='Outreach Command Center', version='1.0.0')

init_db()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    password: str


@app.post('/api/login')
def login(body: LoginRequest, response: Response):
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail='Incorrect password')
    token = create_session()
    response.set_cookie(
        'occ_session', token,
        max_age=SESSION_TTL_HOURS * 3600, httponly=True, samesite='lax',
    )
    return {'ok': True}


@app.post('/api/logout')
def logout(request: Request, response: Response):
    token = request.cookies.get('occ_session')
    if token:
        destroy_session(token)
    response.delete_cookie('occ_session')
    return {'ok': True}


@app.get('/api/me')
def me(request: Request):
    if not validate_session(request.cookies.get('occ_session')):
        raise HTTPException(status_code=401, detail='Not authenticated')
    return {'user': 'admin', 'role': 'admin'}


def require_auth(request: Request):
    if not validate_session(request.cookies.get('occ_session')):
        raise HTTPException(status_code=401, detail='Not authenticated')


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get('/api/dashboard/summary')
def dashboard_summary(request: Request, db=Depends(get_db)):
    require_auth(request)
    from sqlalchemy import select, func
    from .models import Lead, Account, Campaign, DailySendCount, RunLog

    today = date.today()
    yesterday = today - timedelta(days=1)

    totals = {
        'leads_total': db.scalar(select(func.count(Lead.id))) or 0,
        'leads_untagged': db.scalar(select(func.count(Lead.id)).where(Lead.campaign_id.is_(None))) or 0,
        'campaigns_active': db.scalar(select(func.count(Campaign.id)).where(Campaign.status == 'active')) or 0,
        'accounts_active': db.scalar(select(func.count(Account.id)).where(Account.status == 'active')) or 0,
    }
    replies = {
        'total': db.scalar(select(func.count(Lead.id)).where(Lead.received_replies.is_(True))) or 0,
        'today': db.scalar(select(func.count(Lead.id)).where(
            Lead.received_replies.is_(True), Lead.reply_received_at >= datetime.combine(today, datetime.min.time()))) or 0,
    }

    # Today's sends vs budgets across (campaign, account)
    from .models import CampaignAccount
    rows = db.execute(
        select(DailySendCount).where(DailySendCount.date == today)
    ).scalars().all()

    limits = {}
    for link in db.execute(select(CampaignAccount)).scalars().all():
        limits[(link.campaign_id, link.account_id)] = link

    invites_today = sum(r.invite_sent_count for r in rows)
    inmails_today = sum(r.opentomsg_count for r in rows)
    messages_today = sum(r.messages_sent for r in rows)
    invite_limit = sum(l.invite_limit for l in limits.values())
    inmail_limit = sum(l.inmail_limit for l in limits.values())
    message_limit_half_sum = sum(max(0, round(l.message_limit / 2)) for l in limits.values())

    contacted_today = invites_today + inmails_today

    # Yesterday for deltas
    y_rows = db.execute(
        select(DailySendCount).where(DailySendCount.date == yesterday)
    ).scalars().all()
    y_contacted = sum(r.invite_sent_count + r.opentomsg_count for r in y_rows)

    # Simple status funnel
    funnel = dict(db.execute(
        select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    ).all())

    # Campaign reply rates
    campaign_rates = []
    for c in db.execute(select(Campaign)).scalars().all():
        total = db.scalar(select(func.count(Lead.id)).where(Lead.campaign_id == c.id)) or 0
        replied = db.scalar(select(func.count(Lead.id)).where(
            Lead.campaign_id == c.id, Lead.received_replies.is_(True))) or 0
        campaign_rates.append({
            'campaign_key': c.campaign_key,
            'id': c.id,
            'leads': total,
            'replied': replied,
            'rate': round(replied / total * 100, 1) if total else 0,
        })

    recent_runs = db.execute(
        select(RunLog).order_by(RunLog.id.desc()).limit(5)
    ).scalars().all()
    runs = [{'id': r.id, 'job': r.job_type, 'status': r.status, 'started_at': r.started_at.isoformat() if r.started_at else None,
             'duration_s': r.duration_s, 'dry_run': r.dry_run} for r in recent_runs]

    return {
        'totals': totals,
        'today': {
            'invites': invites_today, 'inmails': inmails_today,
            'invites_limit': invite_limit, 'inmails_limit': inmail_limit,
            'followups': messages_today, 'followups_limit': message_limit_half_sum,
            'contacted': contacted_today, 'contacted_yesterday': y_contacted,
        },
        'replies': replies,
        'funnel': funnel,
        'campaign_rates': campaign_rates,
        'recent_runs': runs,
        'scheduler_healthy': scheduler._scheduler is not None and scheduler._scheduler.running,
    }


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class AccountIn(BaseModel):
    name: str
    status: str = 'active'
    session_ref: str = ''


@app.get('/api/accounts')
def list_accounts(request: Request, db=Depends(get_db)):
    require_auth(request)
    from sqlalchemy import select
    from .models import Account, CampaignAccount
    from datetime import timedelta

    accounts = db.execute(select(Account).order_by(Account.name)).scalars().all()
    links = db.execute(select(CampaignAccount)).scalars().all()
    campaigns_by_account = {}
    for l in links:
        campaigns_by_account.setdefault(l.account_id, []).append(l.campaign.campaign_key if l.campaign else '?')

    now = datetime.utcnow()
    data = []
    for a in accounts:
        cookie_age_h = None
        if a.last_cookie_refresh_at:
            cookie_age_h = round((now - a.last_cookie_refresh_at).total_seconds() / 3600, 1)
        # Session health: cookie file older than 7 days -> warn
        stale = cookie_age_h is not None and cookie_age_h > 168
        data.append({
            'id': a.id, 'name': a.name, 'status': a.status,
            'session_configured': bool(a.session_ref),
            'last_cookie_refresh_at': a.last_cookie_refresh_at.isoformat() if a.last_cookie_refresh_at else None,
            'cookie_age_hours': cookie_age_h,
            'session_state': ('stale' if stale else 'ok') if a.status == 'active' else a.status,
            'campaigns': sorted(campaigns_by_account.get(a.id, [])),
        })
    return data


@app.post('/api/accounts')
def create_account(body: AccountIn, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Account
    a = Account(name=body.name, status=body.status, session_ref=body.session_ref)
    db.add(a)
    db.commit()
    db.refresh(a)
    return {'id': a.id}


@app.put('/api/accounts/{account_id}')
def update_account(account_id: int, body: AccountIn, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Account
    a = db.get(Account, account_id)
    if not a:
        raise HTTPException(404, 'Account not found')
    a.name = body.name
    a.status = body.status
    if body.session_ref:
        a.session_ref = body.session_ref
    db.commit()
    return {'ok': True}


@app.post('/api/accounts/{account_id}/refresh-cookies')
def refresh_cookies(account_id: int, request: Request):
    """Runs the SeleniumBase cookie capture for one account (blocking; takes ~1min)."""
    require_auth(request)
    from .models import Account
    from get_cookies import ACCOUNTS as LEGACY, fetch_cookies
    db = SessionLocal()
    try:
        a = db.get(Account, account_id)
        if not a:
            raise HTTPException(404, 'Account not found')
        if a.name not in LEGACY:
            raise HTTPException(400, f"'{a.name}' has no browser profile configured in get_cookies.py")
        fetch_cookies(a.name)
        a.last_cookie_refresh_at = datetime.utcnow()
        db.commit()
        return {'ok': True}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Campaigns (CRUD incl. nested accounts + message templates)
# ---------------------------------------------------------------------------

class CampaignAccountIn(BaseModel):
    account_id: int
    order_index: int = 0
    invite_limit: int = 10
    inmail_limit: int = 10
    message_limit: int = 30
    calendar_url: str | None = None
    search_url_override: str | None = None


class CampaignIn(BaseModel):
    name: str
    campaign_key: str | None = None   # None = keep existing (immutable after create)
    search_url: str = ''
    status: str = 'active'
    invite_text: str = ''
    invite_track: list[str] = Field(default_factory=list)
    inmail_subject: str = ''
    inmail_text: str = ''
    inmail_track: list[dict] = Field(default_factory=list)
    accounts: list[CampaignAccountIn] = Field(default_factory=list)


@app.get('/api/campaigns')
def list_campaigns(request: Request, db=Depends(get_db)):
    require_auth(request)
    from sqlalchemy import select, func
    from .models import Campaign, Lead
    campaigns = db.execute(select(Campaign).order_by(Campaign.id)).scalars().all()
    out = []
    for c in campaigns:
        total = db.scalar(select(func.count(Lead.id)).where(Lead.campaign_id == c.id)) or 0
        replied = db.scalar(select(func.count(Lead.id)).where(
            Lead.campaign_id == c.id, Lead.received_replies.is_(True))) or 0
        contacted = db.scalar(select(func.count(Lead.id)).where(
            Lead.campaign_id == c.id, Lead.status != '')) or 0
        out.append({
            'id': c.id, 'campaign_key': c.campaign_key, 'name': c.name,
            'status': c.status, 'search_url': c.search_url,
            'accounts': [
                {'account_id': l.account_id, 'account_name': l.account.name,
                 'order_index': l.order_index, 'invite_limit': l.invite_limit,
                 'inmail_limit': l.inmail_limit, 'message_limit': l.message_limit,
                 'calendar_url': l.calendar_url, 'search_url_override': l.search_url_override}
                for l in sorted(c.account_links, key=lambda x: x.order_index)
            ],
            'leads': total, 'contacted': contacted, 'replied': replied,
            'reply_rate': round(replied / total * 100, 1) if total else 0,
        })
    return out


@app.get('/api/campaigns/{campaign_id}')
def get_campaign(campaign_id: int, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Campaign
    c = db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(404, 'Campaign not found')
    return {
        'id': c.id, 'campaign_key': c.campaign_key, 'name': c.name,
        'status': c.status, 'search_url': c.search_url,
        'invite_text': c.invite_text,
        'invite_track': c.invite_track or [],
        'inmail_subject': c.inmail_subject,
        'inmail_text': c.inmail_text,
        'inmail_track': c.inmail_track or [],
        'accounts': [
            {'account_id': l.account_id, 'account_name': l.account.name,
             'order_index': l.order_index, 'invite_limit': l.invite_limit,
             'inmail_limit': l.inmail_limit, 'message_limit': l.message_limit,
             'calendar_url': l.calendar_url, 'search_url_override': l.search_url_override}
            for l in sorted(c.account_links, key=lambda x: x.order_index)
        ],
    }


@app.post('/api/campaigns')
def create_campaign(body: CampaignIn, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Campaign, CampaignAccount
    key = body.campaign_key or body.name
    if db.execute(select_stmt(key)).scalar():
        raise HTTPException(409, f"Campaign key '{key}' already exists")
    c = Campaign(
        campaign_key=key, name=body.name, search_url=body.search_url,
        status=body.status, invite_text=body.invite_text,
        invite_track=body.invite_track, inmail_subject=body.inmail_subject,
        inmail_text=body.inmail_text, inmail_track=body.inmail_track,
    )
    db.add(c)
    db.flush()
    for link in body.accounts:
        db.add(CampaignAccount(
            campaign_id=c.id, account_id=link.account_id, order_index=link.order_index,
            invite_limit=link.invite_limit, inmail_limit=link.inmail_limit,
            message_limit=link.message_limit, calendar_url=link.calendar_url,
            search_url_override=link.search_url_override,
        ))
    db.commit()
    return {'id': c.id}


def select_stmt(key):
    from sqlalchemy import select
    from .models import Campaign
    return select(func.count(Campaign.id)).where(Campaign.campaign_key == key)


@app.put('/api/campaigns/{campaign_id}')
def update_campaign(campaign_id: int, body: CampaignIn, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Campaign, CampaignAccount
    c = db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(404, 'Campaign not found')
    if body.campaign_key and body.campaign_key != c.campaign_key:
        raise HTTPException(400, 'campaign_key is immutable - it is the tag on every lead row')
    c.name = body.name
    c.search_url = body.search_url
    c.status = body.status
    c.invite_text = body.invite_text
    c.invite_track = body.invite_track
    c.inmail_subject = body.inmail_subject
    c.inmail_text = body.inmail_text
    c.inmail_track = body.inmail_track
    # Replace account links wholesale (order_index drives the load balancer)
    db.query(CampaignAccount).filter_by(campaign_id=c.id).delete()
    for link in body.accounts:
        db.add(CampaignAccount(
            campaign_id=c.id, account_id=link.account_id, order_index=link.order_index,
            invite_limit=link.invite_limit, inmail_limit=link.inmail_limit,
            message_limit=link.message_limit, calendar_url=link.calendar_url,
            search_url_override=link.search_url_override,
        ))
    db.commit()
    return {'ok': True}


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

@app.get('/api/leads')
def list_leads(request: Request, db=Depends(get_db),
               campaign_id: int | None = None, account_id: int | None = None,
               status: str | None = None, source: str | None = None,
               q: str | None = None, replied: bool | None = None,
               page: int = 1, page_size: int = 50):
    require_auth(request)
    from sqlalchemy import select, func, or_
    from .models import Lead

    stmt = select(Lead)
    if campaign_id:
        stmt = stmt.where(Lead.campaign_id == campaign_id)
    if account_id:
        stmt = stmt.where(Lead.associate_account_id == account_id)
    if status is not None and status != '':
        if status == '__untouched__':
            stmt = stmt.where(Lead.status == '')
        else:
            stmt = stmt.where(Lead.status == status)
    if source:
        stmt = stmt.where(Lead.source == source)
    if replied is not None:
        stmt = stmt.where(Lead.received_replies.is_(replied))
    if q:
        like = f'%{q}%'
        stmt = stmt.where(or_(
            Lead.full_name.ilike(like), Lead.company.ilike(like),
            Lead.title.ilike(like), Lead.sales_nav_id.ilike(like),
        ))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(Lead.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()

    def serialize(l: Lead):
        return {
            'id': l.id,
            'sales_nav_id': l.sales_nav_id,
            'full_name': l.full_name or f"{l.first_name} {l.last_name}".strip(),
            'title': l.title, 'company': l.company, 'location': l.location,
            'opentomsg': l.opentomsg, 'linkedin_url': l.linkedin_url,
            'source': l.source, 'list_id': l.list_id,
            'campaign': l.campaign.campaign_key if l.campaign else None,
            'associate_account': l.associate_account.name if l.associate_account else None,
            'status': l.status, 'status_changed_at': l.status_changed_at.isoformat() if l.status_changed_at else None,
            'received_replies': l.received_replies,
            'reply_message': (l.reply_message or '')[:200],
            'created_at': l.created_at.isoformat() if l.created_at else None,
        }

    return {'total': total, 'page': page, 'page_size': page_size, 'items': [serialize(l) for l in rows]}


@app.get('/api/leads/{lead_id}/timeline')
def lead_timeline(lead_id: int, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Lead, LeadEvent
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, 'Lead not found')
    events = db.execute(
        select(LeadEvent).where(LeadEvent.lead_id == lead_id).order_by(LeadEvent.id)
    ).scalars().all()
    return {
        'lead': {
            'id': lead.id, 'full_name': lead.full_name, 'company': lead.company,
            'title': lead.title, 'status': lead.status,
            'received_replies': lead.received_replies, 'reply_message': lead.reply_message,
        },
        'events': [
            {'kind': e.kind, 'detail': e.detail, 'job': e.job_type,
             'at': e.created_at.isoformat() if e.created_at else None}
            for e in events
        ],
    }


class AssignBody(BaseModel):
    campaign_id: int | None = None  # null = unassign back to list-import pool


@app.put('/api/leads/{lead_id}/assign')
def assign_lead(lead_id: int, body: AssignBody, request: Request, db=Depends(get_db)):
    """Manual campaign assignment for untagged list-import leads."""
    require_auth(request)
    from .models import Lead, Campaign
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, 'Lead not found')
    if body.campaign_id is None:
        lead.campaign_id = None
        lead.source = 'list_import'
    else:
        campaign = db.get(Campaign, body.campaign_id)
        if not campaign:
            raise HTTPException(404, 'Campaign not found')
        lead.campaign_id = campaign.id
        lead.source = 'campaign_search'
        lead.list_id = None
        _add_event(db, lead.id, 'assignment', f"Manually assigned to {campaign.campaign_key}", None)
    db.commit()
    return {'ok': True}


# ---------------------------------------------------------------------------
# Threads & Replies
# ---------------------------------------------------------------------------

@app.get('/api/threads')
def threads(request: Request, db=Depends(get_db),
            channel: str = 'all', q: str | None = None,
            page: int = 1, page_size: int = 25):
    """Reply inbox backed by leads.received_replies / reply_message."""
    require_auth(request)
    from sqlalchemy import select, func, or_
    from .models import Lead

    stmt = select(Lead).where(Lead.received_replies.is_(True))
    if q:
        like = f'%{q}%'
        stmt = stmt.where(or_(Lead.full_name.ilike(like), Lead.reply_message.ilike(like)))
    if channel == 'booked':
        stmt = stmt.where(Lead.reply_message.ilike('%book%| %calendly%|%calendar%'))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(Lead.reply_received_at.desc().nullslast(), Lead.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()

    items = [{
        'id': l.id,
        'full_name': l.full_name or f"{l.first_name} {l.last_name}".strip(),
        'title': l.title, 'company': l.company,
        'campaign': l.campaign.campaign_key if l.campaign else None,
        'account': l.associate_account.name if l.associate_account else None,
        'reply_message': l.reply_message,
        'reply_received_at': l.reply_received_at.isoformat() if l.reply_received_at else None,
        'status': l.status,
    } for l in rows]
    return {'total': total, 'page': page, 'page_size': page_size, 'items': items}


# ---------------------------------------------------------------------------
# Jobs & runs
# ---------------------------------------------------------------------------

@app.get('/api/jobs')
def list_jobs(request: Request):
    require_auth(request)
    from . import runner
    from .jobs import JOB_REGISTRY
    schedule = scheduler.load_schedule()
    from sqlalchemy import select
    from .models import RunLog
    db = SessionLocal()
    try:
        last_runs = {}
        for r in db.execute(select(RunLog).order_by(RunLog.id.desc()).limit(200)).scalars().all():
            if r.job_type not in last_runs:
                last_runs[r.job_type] = {
                    'id': r.id, 'status': r.status, 'started_at': r.started_at.isoformat() if r.started_at else None,
                    'duration_s': r.duration_s, 'dry_run': r.dry_run,
                }
        from .models import JobType
        jobs = []
        descriptions = {
            'sync_leads': 'Batch-pulls new prospects for every active campaign from its search URL(s) into the lead pool.',
            'import_list': 'Manual one-off: import a Sales Navigator list by numeric ID. Leads arrive untagged.',
            'send_connections': 'Assigns untouched leads to accounts by budget order, then sends InMails or connection invites.',
            'check_replies': 'Detects invite accepts (sends the after-accept message) and new replies; flags leads and emails the digest.',
            'send_followups': 'Runs the +3/+5/+7-day follow-up sequences for both invite and InMail tracks.',
        }
        for key in JobType:
            jobs.append({
                'key': key.value,
                'schedule': schedule.get(key.value) or [],
                'last_run': last_runs.get(key.value),
                'running_now': runner.is_running() and runner.live_status().get('job') == key.value,
                'description': descriptions.get(key.value, ''),
            })
        return {'jobs': jobs, 'live': runner.live_status(), 'scheduler_running': scheduler._scheduler is not None and scheduler._scheduler.running}
    finally:
        db.close()


class JobStart(BaseModel):
    dry_run: bool = False
    campaign_ids: list[int] | None = None
    account_ids: list[int] | None = None
    account_id: int | None = None     # import_list
    list_id: str | None = None        # import_list


@app.post('/api/jobs/{job_key}/run')
def run_job(job_key: str, body: JobStart, request: Request):
    require_auth(request)
    from . import runner
    kwargs = {}
    if body.campaign_ids:
        kwargs['campaign_ids'] = body.campaign_ids
    if body.account_ids:
        kwargs['account_ids'] = body.account_ids
    if job_key == 'import_list':
        if not body.account_id or not body.list_id:
            raise HTTPException(422, 'import_list requires account_id and list_id')
        kwargs['account_id'] = body.account_id
        kwargs['list_id'] = body.list_id
    ok, message, _ = runner.start_job(job_key, dry_run=body.dry_run, **kwargs)
    if not ok:
        raise HTTPException(409, message)
    return {'ok': True, 'message': message}


@app.get('/api/runs')
def list_runs(request: Request, job: str | None = None, status: str | None = None,
              limit: int = 50):
    require_auth(request)
    from sqlalchemy import select
    from .models import RunLog
    db = SessionLocal()
    try:
        stmt = select(RunLog).order_by(RunLog.id.desc()).limit(min(limit, 200))
        if job:
            stmt = stmt.where(RunLog.job_type == job)
        if status:
            stmt = stmt.where(RunLog.status == status)
        rows = db.execute(stmt).scalars().all()
        return [{
            'id': r.id, 'job': r.job_type, 'target': r.target, 'dry_run': r.dry_run,
            'status': r.status, 'started_at': r.started_at.isoformat() if r.started_at else None,
            'finished_at': r.finished_at.isoformat() if r.finished_at else None,
            'duration_s': r.duration_s, 'stats': r.stats, 'errors': r.errors,
        } for r in rows]
    finally:
        db.close()


@app.get('/api/runs/{run_id}/log')
def run_log(run_id: int, request: Request):
    require_auth(request)
    from .models import RunLog
    db = SessionLocal()
    try:
        r = db.get(RunLog, run_id)
        if not r:
            raise HTTPException(404, 'Run not found')
        return {'id': r.id, 'status': r.status, 'log_text': r.log_text or '', 'stats': r.stats, 'errors': r.errors}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class NotificationSettingsIn(BaseModel):
    gchat_webhook_url: str = ''
    email_recipients: list[str] = Field(default_factory=list)
    alert_critical: bool = True
    alert_run_summary: bool = True
    alert_send_errors: bool = True
    alert_reply_digest: bool = True


@app.get('/api/settings/notifications')
def get_notification_settings(request: Request):
    require_auth(request)
    from .notify import get_settings
    s = get_settings()
    return {
        'gchat_webhook_url': ('•' * 8 + s.gchat_webhook_url[-12:]) if s.gchat_webhook_url else '',
        'webhook_configured': bool(s.gchat_webhook_url),
        'email_recipients': s.email_recipients or [],
        'alert_critical': s.alert_critical,
        'alert_run_summary': s.alert_run_summary,
        'alert_send_errors': s.alert_send_errors,
        'alert_reply_digest': s.alert_reply_digest,
    }


@app.put('/api/settings/notifications')
def put_notification_settings(body: NotificationSettingsIn, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import NotificationSettings
    s = db.get(NotificationSettings, 1)
    if s is None:
        s = NotificationSettings(id=1)
        db.add(s)
    # Masked value ('••••••••...tail') means "unchanged" - only overwrite on a real URL
    if body.gchat_webhook_url and not body.gchat_webhook_url.startswith('•'):
        s.gchat_webhook_url = body.gchat_webhook_url.strip()
    s.email_recipients = [r.strip() for r in body.email_recipients if r.strip()]
    s.alert_critical = body.alert_critical
    s.alert_run_summary = body.alert_run_summary
    s.alert_send_errors = body.alert_send_errors
    s.alert_reply_digest = body.alert_reply_digest
    db.commit()
    return {'ok': True}


@app.post('/api/settings/test-webhook')
def test_webhook(request: Request):
    require_auth(request)
    from .notify import send_gchat
    ok = send_gchat("🧪 *Test message* from Outreach Command Center — webhook wired up correctly ✅")
    return {'ok': ok}


@app.get('/api/settings/schedule')
def get_schedule(request: Request):
    require_auth(request)
    return scheduler.load_schedule()


class ScheduleIn(BaseModel):
    schedule: dict[str, list[str]]


@app.put('/api/settings/schedule')
def put_schedule(body: ScheduleIn, request: Request):
    require_auth(request)
    scheduler.save_schedule(body.schedule)
    # Re-register cron jobs
    if scheduler._scheduler:
        scheduler._scheduler.remove_all_jobs()
        schedule = scheduler.load_schedule()
        for job_key, times in schedule.items():
            if not times or job_key == 'import_list':
                continue
            for t in times:
                try:
                    hour, minute = str(t).split(':')[:2]
                    scheduler._scheduler.add_job(
                        scheduler._run_scheduled, CronTriggerProxy(hour=int(hour), minute=int(minute)),
                        args=[job_key], id=f"{job_key}@{t}", replace_existing=True, misfire_grace_time=900)
                except Exception:
                    pass
    return {'ok': True}


def CronTriggerProxy(**kw):
    from apscheduler.triggers.cron import CronTrigger
    return CronTrigger(**kw)


@app.get('/api/health')
def health():
    return {'ok': True, 'time': datetime.utcnow().isoformat(timespec='seconds')}


# ---------------------------------------------------------------------------
# Static frontend (built React app) - registered LAST so /api/* wins
# ---------------------------------------------------------------------------

FRONTEND_DIST = PROJECT_ROOT / 'frontend' / 'dist'
if FRONTEND_DIST.exists():
    app.mount('/assets', StaticFiles(directory=FRONTEND_DIST / 'assets'), name='assets')

    @app.get('/{full_path:path}', include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith('api/') or full_path == 'api':
            return JSONResponse({'detail': 'Not found'}, status_code=404)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / 'index.html')


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

if os.environ.get('OCC_DISABLE_SCHEDULER', '').strip().lower() not in ('1', 'true', 'yes'):
    try:
        scheduler.init_scheduler()
    except Exception as e:
        print(f"⚠️ Scheduler failed to start: {e}")
