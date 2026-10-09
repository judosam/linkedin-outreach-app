"""Outreach Command Center — FastAPI backend.

Serves the REST API under /api and the no-build templates/static frontend.
Auth: database users with hashed passwords and HTTP-only session cookies.
"""
import os
from datetime import datetime, date, timedelta, timezone

from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, Query
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, func as sa_func

from .config import PROJECT_ROOT, SESSION_TTL_HOURS
from .auth import (hash_password, check_password, create_session, destroy_session,
                   destroy_user_sessions, session_user_id)
from .database import init_db, get_db, SessionLocal
from . import scheduler
from .models import LeadEvent, Lead
from .jobs import _add_event, recover_stuck_runs, _set_status

app = FastAPI(title='Campaign Manager', version='1.0.0')


@app.middleware('http')
async def frontend_cache_policy(request: Request, call_next):
    # Capture the actor before logout invalidates their session. Never log bodies,
    # cookies, passwords, message contents or uploaded files.
    tracked = (request.url.path.startswith('/api/') and request.url.path != '/api/login'
               and (request.method in ('POST', 'PUT', 'PATCH', 'DELETE') or request.url.path == '/api/leads/export'))
    actor = current_user(request) if tracked else None
    response = await call_next(request)
    if tracked and actor:
        from .operations import record_activity
        route = request.scope.get('route')
        action = getattr(route, 'name', request.method.lower())
        if action != 'reassign_leads' or response.status_code >= 400:
            detail = '; '.join(f"{key.replace('_', ' ')}: {value}" for key, value in request.path_params.items()) or 'Application action'
            try:
                with SessionLocal() as audit_db:
                    record_activity(audit_db, actor, action, detail,
                                    'success' if response.status_code < 400 else f'rejected ({response.status_code})')
                    audit_db.commit()
            except Exception:
                # The action may already have started a worker or committed.
                # Never report it as failed and invite an accidental retry.
                import logging
                logging.getLogger(__name__).exception('Could not record user activity for %s', action)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    elif request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache'
    return response

init_db()
recover_stuck_runs()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


ROLES = ('admin', 'campaign_manager')


def _ensure_bootstrap_admin() -> None:
    """Seed once; preserve passwords changed in the application across restarts."""
    from .config import ADMIN_USERNAME, ADMIN_PASSWORD
    from .models import User
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == ADMIN_USERNAME))
        if admin is None:
            db.add(User(username=ADMIN_USERNAME, password_hash=hash_password(ADMIN_PASSWORD),
                        display_name='Administrator', role='admin', active=True))
        elif not admin.password_hash.startswith('pbkdf2_sha256$'):
            # Migrate old plaintext rows without changing their password.
            admin.password_hash = hash_password(admin.password_hash)
        db.commit()


_ensure_bootstrap_admin()


@app.post('/api/login')
def login(body: LoginRequest, response: Response, request: Request, db=Depends(get_db)):
    from .models import User
    from sqlalchemy import func as sa_func, select as sa_select
    user = db.scalar(select(User).where(User.username == body.username.strip()))
    if user is None and (db.scalar(sa_select(sa_func.count(User.id))) or 0) == 0:
        # Self-heal: users table empty (fresh DB or recreated by tests/tools) —
        # reseed the env admin so the instance is never locked out.
        _ensure_bootstrap_admin()
        db.expire_all()
        user = db.scalar(select(User).where(User.username == body.username.strip()))
    if user is None or not check_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail='Incorrect username or password')
    if not user.active:
        raise HTTPException(status_code=403, detail='This account has been deactivated. Contact an administrator.')
    token = create_session(user.id)
    user.last_login_at = datetime.utcnow()
    from .operations import record_activity
    record_activity(db, user, 'login', 'Signed in')
    db.commit()
    response.set_cookie(
        'occ_session', token,
        max_age=SESSION_TTL_HOURS * 3600, httponly=True, samesite='lax', secure=request.url.scheme == 'https',
    )
    return {'ok': True}


@app.post('/api/logout')
def logout(request: Request, response: Response):
    token = request.cookies.get('occ_session')
    if token:
        destroy_session(token)
    response.delete_cookie('occ_session')
    return {'ok': True}


def current_user(request: Request, db=None):
    """Resolve the logged-in user, or None."""
    from .models import User
    uid = session_user_id(request.cookies.get('occ_session'))
    if uid is None:
        return None
    if db is None:
        with SessionLocal() as own:
            return own.get(User, uid)
    return db.get(User, uid)


def require_auth(request: Request):
    if session_user_id(request.cookies.get('occ_session')) is None:
        raise HTTPException(status_code=401, detail='Not authenticated')


def require_admin(request: Request, db):
    # `db` must be the request's DB session.
    from .models import User
    user = current_user(request, db)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail='Not authenticated')
    if user.role != 'admin':
        raise HTTPException(status_code=403, detail='Administrator access required')
    return user


def require_licenses_access(request: Request, db):
    """Admin or any user specifically assigned Licences Manager access."""
    user = current_user(request, db)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail='Not authenticated')
    if user.role == 'admin' or bool(getattr(user, 'can_manage_licenses', False)):
        return user
    raise HTTPException(status_code=403, detail='Licences Manager access required')


def user_scope(request: Request, db):
    """Only admins have unrestricted scope; empty grants give no access."""
    user = current_user(request, db)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail='Not authenticated')
    if user.role == 'admin':
        return user, None, None
    return user, user.allowed_campaign_ids or [], user.allowed_account_ids or []


def _lead_in_scope(lead, user) -> bool:
    """Campaign grants control tagged leads; account grants cover only the pool."""
    if lead is None:
        return False
    if user.role == 'admin':
        return True
    if lead.campaign_id is not None:
        return lead.campaign_id in (user.allowed_campaign_ids or [])
    return lead.associate_account_id in (user.allowed_account_ids or [])


def _lead_scope_conditions(camps, accts):
    """SQL equivalent of _lead_in_scope for lists, exports and aggregates."""
    from .models import Lead
    from sqlalchemy import and_, or_
    if camps is None and accts is None:
        return None
    return or_(Lead.campaign_id.in_(camps or []),
               and_(Lead.campaign_id.is_(None), Lead.associate_account_id.in_(accts or [])))


def _require_lead_access(lead, request, db):
    """404-guard for single-lead endpoints (no existence leak for out-of-scope ids)."""
    user, _c, _a = user_scope(request, db)
    if not _lead_in_scope(lead, user):
        raise HTTPException(404, 'Lead not found')
    return user


def _run_scope_filter(stmt, campaign_ids=None, account_ids=None, *, user=None):
    """Only administrators see all execution output, including legacy runs.

    Campaign/account access is not permission to read another user's logs.
    Unattributed historical and scheduled output therefore stays admin-only.
    """
    from .models import RunLog
    if user is not None and user.role == 'admin':
        return stmt
    return stmt.where(RunLog.owner_user_id == user.id) if user is not None else stmt.where(False)


def _require_in_scope(user, *, campaign_id=None, account_id=None,
                      campaign_ids=None, account_ids=None):
    """Raise 403 when a targeted id is outside the user's access scope."""
    if user.role == 'admin':
        return
    if campaign_id is not None and campaign_id not in (user.allowed_campaign_ids or []):
        raise HTTPException(status_code=403, detail='You do not have access to this campaign')
    if account_id is not None and account_id not in (user.allowed_account_ids or []):
        raise HTTPException(status_code=403, detail='You do not have access to this account')
    if campaign_ids:
        bad = [c for c in campaign_ids if c not in (user.allowed_campaign_ids or [])]
        if bad:
            raise HTTPException(status_code=403, detail='You do not have access to one or more selected campaigns')
    if account_ids:
        bad = [a for a in account_ids if a not in (user.allowed_account_ids or [])]
        if bad:
            raise HTTPException(status_code=403, detail='You do not have access to one or more selected accounts')


@app.get('/api/me')
def me(request: Request, db=Depends(get_db)):
    from .models import User
    user = current_user(request, db)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return {'user': user.username, 'name': user.display_name or user.username,
            'role': user.role, 'must_change_password': False,
            'allowed_campaign_ids': user.allowed_campaign_ids or [],
            'allowed_account_ids': user.allowed_account_ids or [],
            'can_manage_licenses': user.role == 'admin' or bool(getattr(user, 'can_manage_licenses', False))}


# ---------------------------------------------------------------------------
# Users & access (admin management + self-service password change)
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default='', max_length=120)
    role: str = 'campaign_manager'
    allowed_campaign_ids: list[int] = Field(default_factory=list)
    allowed_account_ids: list[int] = Field(default_factory=list)
    can_manage_licenses: bool = False

    @model_validator(mode='after')
    def _check_role(self):
        if self.role not in ROLES:
            raise ValueError(f'role must be one of {ROLES}')
        return self


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: str | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    allowed_campaign_ids: list[int] | None = None
    allowed_account_ids: list[int] | None = None
    can_manage_licenses: bool | None = None

    @model_validator(mode='after')
    def _check_role(self):
        if self.role is not None and self.role not in ROLES:
            raise ValueError(f'role must be one of {ROLES}')
        return self


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@app.get('/api/users')
def list_users(request: Request, db=Depends(get_db)):
    admin = require_admin(request, db)
    from .models import User
    rows = db.execute(select(User).order_by(User.username)).scalars().all()
    return {'users': [
        {'id': u.id, 'username': u.username, 'display_name': u.display_name,
         'role': u.role, 'active': u.active, 'created_at': u.created_at.isoformat() if u.created_at else None,
         'last_login_at': u.last_login_at.isoformat() if u.last_login_at else None,
         'is_you': u.id == admin.id,
         'allowed_campaign_ids': u.allowed_campaign_ids or [],
         'allowed_account_ids': u.allowed_account_ids or [],
         'can_manage_licenses': bool(getattr(u, 'can_manage_licenses', False))}
        for u in rows
    ]}


@app.post('/api/users')
def create_user(body: UserCreate, request: Request, db=Depends(get_db)):
    require_admin(request, db)
    from .models import User
    username = body.username.strip()
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=409, detail='That username is already taken')
    user = User(username=username, password_hash=hash_password(body.password),
                display_name=body.display_name.strip(), role=body.role, active=True,
                allowed_campaign_ids=body.allowed_campaign_ids,
                allowed_account_ids=body.allowed_account_ids,
                can_manage_licenses=body.can_manage_licenses)
    db.add(user)
    db.commit()
    return {'ok': True, 'id': user.id}


@app.put('/api/users/{user_id}')
def update_user(user_id: int, body: UserUpdate, request: Request, db=Depends(get_db)):
    admin = require_admin(request, db)
    from .models import User
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail='User not found')
    demoting_or_disabling_self = (
        (body.role is not None and body.role != 'admin' and user.id == admin.id)
        or (body.active is False and user.id == admin.id))
    if demoting_or_disabling_self:
        raise HTTPException(status_code=400, detail='You cannot remove your own administrator access')
    # Never leave the instance without an active admin.
    if (body.role is not None and body.role != 'admin') or body.active is False:
        admins_left = [u for u in db.execute(select(User).where(User.role == 'admin', User.active.is_(True))).scalars().all()
                       if u.id != user_id]
        if not admins_left:
            raise HTTPException(status_code=400, detail='At least one active administrator is required')
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.role is not None:
        user.role = body.role
    if body.active is not None:
        user.active = body.active
    if body.allowed_campaign_ids is not None:
        user.allowed_campaign_ids = body.allowed_campaign_ids
    if body.allowed_account_ids is not None:
        user.allowed_account_ids = body.allowed_account_ids
    if body.can_manage_licenses is not None:
        user.can_manage_licenses = body.can_manage_licenses
    if body.password:
        user.password_hash = hash_password(body.password)
    db.commit()
    if body.active is False or body.password:
        destroy_user_sessions(user.id)  # stale sessions die after disable/reset
    return {'ok': True}


@app.delete('/api/users/{user_id}')
def delete_user(user_id: int, request: Request, db=Depends(get_db)):
    admin = require_admin(request, db)
    from .models import User
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail='You cannot delete your own account')
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail='User not found')
    admins_left = [u for u in db.execute(select(User).where(User.role == 'admin', User.active.is_(True))).scalars().all()
                   if u.id != user_id]
    if user.role == 'admin' and not admins_left:
        raise HTTPException(status_code=400, detail='At least one active administrator is required')
    from . import runner
    with runner.user_deletion_lease(user_id) as allowed:
        if not allowed:
            raise HTTPException(409, 'Stop this user\'s running jobs before deleting the user')
        db.delete(user)
        db.commit()
        destroy_user_sessions(user_id)
    return {'ok': True}


@app.post('/api/me/password')
def change_my_password(body: PasswordChange, request: Request, response: Response, db=Depends(get_db)):
    """Self-service password change — available to every logged-in user.
    Other sessions of this user are logged out; the current one is kept."""
    from .models import User
    token = request.cookies.get('occ_session')
    uid = session_user_id(token)
    if uid is None:
        raise HTTPException(status_code=401, detail='Not authenticated')
    user = db.get(User, uid)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail='Not authenticated')
    if not check_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail='Current password is incorrect')
    if body.current_password == body.new_password:
        raise HTTPException(status_code=400, detail='New password must be different from the current one')
    user.password_hash = hash_password(body.new_password)
    db.commit()
    destroy_user_sessions(uid)
    # Re-issue this browser's session so the user stays logged in.
    new_token = create_session(user.id)
    response.set_cookie(
        'occ_session', new_token,
        max_age=SESSION_TTL_HOURS * 3600, httponly=True, samesite='lax', secure=request.url.scheme == 'https',
    )
    return {'ok': True}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get('/api/dashboard/summary')
def dashboard_summary(request: Request, db=Depends(get_db), days: int = 1):
    require_auth(request)
    # Restricted users: every dashboard number is scoped to their allocated
    # campaigns/accounts (only admins see the whole fleet).
    _user, _scamps, _saccts = user_scope(request, db)
    from sqlalchemy import select, func, and_
    from .models import Lead, Account, Campaign, DailySendCount, RunLog

    def _lead_count(*extra):
        stmt = select(func.count(Lead.id))
        _scope = _lead_scope_conditions(_scamps, _saccts)
        if _scope is not None:
            stmt = stmt.where(_scope)
        for cond in extra:
            stmt = stmt.where(cond)
        return db.scalar(stmt) or 0

    # Counts are UTC-based to match how the pipeline stamps rows (utcnow).
    # days=1 -> today only; 7 / 30 -> trailing window (rolling, incl. today).
    days = days if days in (1, 7, 30) else 1
    today = datetime.utcnow().date()
    window_start = today - timedelta(days=days - 1)
    yesterday = today - timedelta(days=1)

    camp_active_q = select(func.count(Campaign.id)).where(Campaign.status == 'active')
    acct_active_q = select(func.count(Account.id)).where(Account.status == 'active')
    if _scamps is not None:
        camp_active_q = camp_active_q.where(Campaign.id.in_(_scamps))
    if _saccts is not None:
        acct_active_q = acct_active_q.where(Account.id.in_(_saccts))
    totals = {
        'leads_total': _lead_count(),
        'leads_untagged': _lead_count(Lead.campaign_id.is_(None)),
        'campaigns_active': db.scalar(camp_active_q) or 0,
        'accounts_active': db.scalar(acct_active_q) or 0,
    }
    replies = {
        'total': _lead_count(Lead.received_replies.is_(True)),
        'today': _lead_count(and_(Lead.received_replies.is_(True),
                                  Lead.reply_received_at >= datetime.combine(today, datetime.min.time()))),
        'window': _lead_count(and_(Lead.received_replies.is_(True),
                                   Lead.reply_received_at >= datetime.combine(window_start, datetime.min.time()))),
    }

    # Sends vs budgets across (campaign, account) for the selected window
    from .models import CampaignAccount
    # Send counts come from the LeadEvent AUDIT TRAIL, not DailySendCount:
    # deleting a campaign cascade-deletes its DailySendCount rows (they are
    # keyed by campaign_id), which made today's real sends vanish from the
    # dashboard. Lead events survive campaign deletion — they are the durable
    # record of what was actually sent.
    from .models import LeadEvent
    ev_start = datetime.combine(window_start, datetime.min.time())

    def _scope_ev(stmt):
        # Join the audit trail to Lead so restricted users' send counts only
        # include their own campaigns/accounts.
        if _scamps is None and _saccts is None:
            return stmt
        stmt = stmt.join(Lead, Lead.id == LeadEvent.lead_id)
        _scope = _lead_scope_conditions(_scamps, _saccts)
        if _scope is not None:
            stmt = stmt.where(_scope)
        return stmt
    ev_rows = db.execute(_scope_ev(
        select(LeadEvent.job_type, func.count(LeadEvent.id))
        .where(LeadEvent.kind == 'outbound', LeadEvent.created_at >= ev_start)
    ).group_by(LeadEvent.job_type)).all()
    _by_job = {jt or '': n for jt, n in ev_rows}
    invites_today = _by_job.get('send_connections', 0)
    messages_today = _by_job.get('send_followups', 0) + _by_job.get('check_replies', 0)
    # InMails vs invites within send_connections: distinguish by event detail.
    inmails_today = db.scalar(_scope_ev(select(func.count(LeadEvent.id)).where(
        LeadEvent.kind == 'outbound', LeadEvent.created_at >= ev_start,
        LeadEvent.job_type == 'send_connections', LeadEvent.detail.ilike('%InMail%')))) or 0
    invites_today = max(0, invites_today - inmails_today)

    limits = {}
    limits_q = select(CampaignAccount).join(Campaign).join(Account).where(Campaign.status == 'active', Account.status == 'active')
    if _scamps is not None:
        limits_q = limits_q.where(Campaign.id.in_(_scamps))
    if _saccts is not None:
        limits_q = limits_q.where(Account.id.in_(_saccts))
    for link in db.execute(limits_q).scalars().all():
        limits[(link.campaign_id, link.account_id)] = link

    grouped_limits = {}
    for link in limits.values():
        grouped_limits.setdefault(link.account_id, []).append(link)
    invite_limit = sum(min(ls[0].account.daily_invite_cap, sum(l.invite_limit for l in ls)) for ls in grouped_limits.values())
    inmail_limit = sum(min(ls[0].account.daily_inmail_cap, sum(l.inmail_limit for l in ls)) for ls in grouped_limits.values())
    message_limit_sum = sum(min(max(0, ls[0].account.daily_message_cap), sum(max(0, l.message_limit) for l in ls)) for ls in grouped_limits.values())

    contacted_today = invites_today + inmails_today

    # Yesterday for deltas (only meaningful in the 1-day view)
    y_start = datetime.combine(yesterday, datetime.min.time())
    y_ev = dict(db.execute(_scope_ev(
        select(LeadEvent.job_type, func.count(LeadEvent.id))
        .where(LeadEvent.kind == 'outbound', LeadEvent.created_at >= y_start,
               LeadEvent.created_at < ev_start)
    ).group_by(LeadEvent.job_type)).all())
    y_contacted = sum(y_ev.values())
    window_contacted = sum(
        db.scalar(_scope_ev(select(func.count(LeadEvent.id)).where(
            LeadEvent.kind == 'outbound', LeadEvent.created_at >= datetime.combine(
                window_start + timedelta(days=i), datetime.min.time()),
            LeadEvent.created_at < datetime.combine(
                window_start + timedelta(days=i + 1), datetime.min.time())))) or 0
        for i in range(days))

    # New leads added inside the window (pipeline growth)
    leads_in_window = _lead_count(Lead.created_at >= datetime.combine(window_start, datetime.min.time()))

    # Simple status funnel
    funnel_q = select(Lead.status, func.count(Lead.id))
    _funnel_scope = _lead_scope_conditions(_scamps, _saccts)
    if _funnel_scope is not None:
        funnel_q = funnel_q.where(_funnel_scope)
    funnel = dict(db.execute(funnel_q.group_by(Lead.status)).all())

    # Campaign reply rates - one grouped query instead of 2 queries per campaign
    # (N+1) for large fleets. SQLite/Postgres both sum booleans as ints here.
    from sqlalchemy import case
    rate_q = select(
        Campaign.id,
        Campaign.campaign_key,
        func.count(Lead.id),
        func.sum(case((Lead.received_replies.is_(True), 1), else_=0)),
    ).outerjoin(Lead, Lead.campaign_id == Campaign.id)
    _rate_scope = _lead_scope_conditions(_scamps, _saccts)
    if _rate_scope is not None:
        rate_q = rate_q.where(_rate_scope)
    rate_rows = db.execute(rate_q.group_by(Campaign.id, Campaign.campaign_key)
                           .order_by(Campaign.id)).all()
    campaign_rates = []
    for cid, key, total, replied in rate_rows:
        total = total or 0
        replied = int(replied or 0)
        campaign_rates.append({
            'campaign_key': key,
            'id': cid,
            'leads': total,
            'replied': replied,
            'rate': round(replied / total * 100, 1) if total else 0,
        })

    recent_runs = db.execute(
        _run_scope_filter(select(RunLog).order_by(RunLog.id.desc()), _scamps, _saccts, user=_user).limit(5)
    ).scalars().all()
    runs = [{'id': r.id, 'job': r.job_type, 'status': r.status, 'started_at': r.started_at.isoformat() if r.started_at else None,
             'duration_s': r.duration_s, 'dry_run': r.dry_run} for r in recent_runs]

    conn_sent = _lead_count(Lead.status.in_(['invited', 'connected', 'fu1', 'fu2', 'fu3', 'replied']))
    conn_accepted = _lead_count(Lead.status.in_(['connected', 'fu1', 'fu2', 'fu3', 'replied']))
    acceptance_rate = round(conn_accepted / conn_sent * 100, 1) if conn_sent else 0
    inmails_sent = _lead_count(Lead.contact_channel == 'inmail')
    positive_replies = _lead_count(Lead.reply_category.in_(['positive', 'interested', 'meeting_booked']))
    meetings_booked = _lead_count(Lead.reply_category.in_(['meeting_booked', 'meeting']))
    pending_followups = _lead_count(Lead.status.in_(['connected', 'fu1', 'fu2']), Lead.received_replies.is_(False))

    acct_attn_q = select(func.count(Account.id)).where(Account.status.in_(['needs_reauth', 'seat_required']))
    if _saccts is not None:
        acct_attn_q = acct_attn_q.where(Account.id.in_(_saccts))
    accts_attention = db.scalar(acct_attn_q) or 0
    pending_reviews = _lead_count(Lead.review_status == 'needs_review')

    return {
        'totals': totals,
        'window_days': days,
        'today': {
            'invites': invites_today, 'inmails': inmails_today,
            'invites_limit': invite_limit, 'inmails_limit': inmail_limit,
            'followups': messages_today, 'followups_limit': message_limit_sum,
            'contacted': contacted_today, 'contacted_yesterday': y_contacted,
            'contacted_window': window_contacted,
            'leads_added': leads_in_window,
        },
        'replies': replies,
        'funnel': funnel,
        'campaign_rates': campaign_rates,
        'recent_runs': runs,
        'scheduler_healthy': scheduler._scheduler is not None and scheduler._scheduler.running,
        'kpis': {
            'accounts_active': totals['accounts_active'],
            'campaigns_active': totals['campaigns_active'],
            'leads_total': totals['leads_total'],
            'connections_sent': conn_sent,
            'acceptance_rate': acceptance_rate,
            'inmails_sent': inmails_sent,
            'replies_received': replies['total'],
            'positive_replies': positive_replies,
            'meetings_booked': meetings_booked,
            'pending_followups': pending_followups,
            'accounts_attention': accts_attention,
            'pending_reviews': pending_reviews,
        },
    }


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@app.get('/api/dashboard/activity')
def dashboard_activity(request: Request, db=Depends(get_db), limit: int = Query(8, ge=1, le=50)):
    require_auth(request)
    from .models import Lead, Campaign
    _auser, _acamps, _aaccts = user_scope(request, db)
    activity_q = (select(LeadEvent, Lead, Campaign.name)
                  .join(Lead, Lead.id == LeadEvent.lead_id)
                  .outerjoin(Campaign, Campaign.id == Lead.campaign_id)
                  .where(LeadEvent.kind.in_(['outbound', 'reply', 'error', 'assignment'])))
    _act_scope = _lead_scope_conditions(_acamps, _aaccts)
    if _act_scope is not None:
        activity_q = activity_q.where(_act_scope)
    rows = db.execute(activity_q.order_by(
        LeadEvent.created_at.desc(), LeadEvent.id.desc()).limit(limit)).all()

    # Older rows stored the raw job key as the detail text (e.g. the feed once
    # showed literally "send_connections"). Map known bare-job details to a
    # human description; everything else passes through untouched.
    _GENERIC = {
        'send_connections': 'Connection invite sent',
        'send_followups': 'Follow-up sent',
        'check_replies': 'Message sent',
        'sync_leads': 'Lead synced from search',
        'import_list': 'Lead imported from list',
    }

    def _desc(event: LeadEvent, lead) -> str:
        d = (event.detail or '').strip()
        acct = lead.associate_account.name if lead.associate_account else None
        if d in _GENERIC:
            # Historic generic row — enrich with the account name when we know it.
            base = _GENERIC[d]
            return f'{base} by {acct}' if acct else base
        if d:
            return d
        # Empty detail: describe from the job type.
        base = _GENERIC.get(event.job_type or '', 'Pipeline updated')
        return f'{base} by {acct}' if acct else base

    return [{'id': event.id, 'kind': event.kind, 'detail': _desc(event, lead),
             'created_at': event.created_at.isoformat(), 'lead_name': lead.full_name,
             'company': lead.company, 'account': lead.associate_account.name if lead.associate_account else None,
             'campaign': campaign, 'campaign_id': lead.campaign_id,
             'job': event.job_type} for event, lead, campaign in rows]


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    status: str = 'active'
    session_ref: str = ''
    daily_invite_cap: int = Field(default=30, ge=0)
    weekly_invite_cap: int = Field(default=100, ge=0, le=150, strict=True)
    daily_inmail_cap: int = Field(default=10, ge=0)
    daily_message_cap: int = Field(default=60, ge=0)
    # Optional list of campaign IDs to assign this account to (upsert logic)
    campaign_ids: list[int] | None = None

    @model_validator(mode='after')
    def validate_account(self):
        if not self.name.strip() or self.status not in ('active', 'paused', 'needs_reauth', 'seat_required'):
            raise ValueError('Enter an account name and valid status')
        return self


@app.get('/api/accounts')
def list_accounts(request: Request, db=Depends(get_db)):
    from .invite_limits import weekly_invite_status
    _user, _camp_scope, acct_scope = user_scope(request, db)
    from sqlalchemy import select
    from .models import Account, CampaignAccount, DailySendCount

    accounts = db.execute(select(Account).order_by(Account.name)).scalars().all()
    links = db.execute(select(CampaignAccount)).scalars().all()
    campaigns_by_account = {}
    for lnk in links:
        if _camp_scope is not None and lnk.campaign_id not in _camp_scope:
            continue
        campaigns_by_account.setdefault(lnk.account_id, []).append(lnk.campaign.campaign_key if lnk.campaign else '?')

    today = datetime.utcnow().date()
    usage = {}  # account_id -> {invites, inmails, messages} sent today
    for r in db.execute(select(DailySendCount).where(DailySendCount.date == today)).scalars().all():
        u = usage.setdefault(r.account_id, {'invites': 0, 'inmails': 0, 'messages': 0})
        u['invites'] += r.invite_sent_count
        u['inmails'] += r.opentomsg_count
        u['messages'] += r.messages_sent

    now = datetime.utcnow()
    # Live per-account run totals from the in-flight job, merged over the
    # stored values so open views update the moment an action completes.
    from . import runner as _runner
    live_runs = _runner.live_account_runs()
    data = []
    for a in accounts:
        if acct_scope is not None and a.id not in set(acct_scope):
            continue
        cookie_age_h = None
        if a.last_cookie_refresh_at:
            cookie_age_h = round((now - a.last_cookie_refresh_at).total_seconds() / 3600, 1)
        # Cookie age is informational only — it no longer flags the session
        # stale after 7 days. Session health comes from real access checks
        # (verify / last job outcome: ok / seat_required / needs_reauth).
        u = usage.get(a.id, {'invites': 0, 'inmails': 0, 'messages': 0})
        data.append({
            'id': a.id, 'name': a.name, 'status': a.status,
            'session_configured': bool(a.session_ref),
            'last_cookie_refresh_at': a.last_cookie_refresh_at.isoformat() if a.last_cookie_refresh_at else None,
            'cookie_age_hours': cookie_age_h,
            'session_state': 'ok' if a.status == 'active' else a.status,
            'campaigns': sorted(campaigns_by_account.get(a.id, [])),
            'campaign_ids': [lnk.campaign_id for lnk in a.campaign_links
                             if _camp_scope is None or lnk.campaign_id in _camp_scope],
            'daily_invite_cap': a.daily_invite_cap,
            'weekly_invite_cap': a.weekly_invite_cap,
            'weekly_invites': weekly_invite_status(db, a),
            'daily_inmail_cap': a.daily_inmail_cap,
            'daily_message_cap': a.daily_message_cap,
            'usage_today': u,
            # Lifetime successful account-level actions (live-merged).
            'total_runs': live_runs.get(str(a.id), a.total_runs or 0),
        })
    return data


def _apply_campaign_assignments(account_id: int, campaign_ids: list[int], db, campaign_scope=None) -> None:
    """Upsert CampaignAccount links for an account given a list of campaign IDs.
    Existing links not in the list are removed; new ones use default limits."""
    from .models import CampaignAccount, Campaign
    existing = {r.campaign_id: r for r in db.query(CampaignAccount).filter_by(account_id=account_id).all()}
    wanted_ids = set(campaign_ids)
    for cid, link in list(existing.items()):
        if campaign_scope is not None and cid not in campaign_scope:
            continue
        if cid not in wanted_ids:
            db.delete(link)
    for cid in wanted_ids:
        if cid not in existing:
            if not db.get(Campaign, cid):
                raise HTTPException(422, f'Campaign {cid} not found')
            max_order = db.query(CampaignAccount).filter_by(campaign_id=cid).count()
            db.add(CampaignAccount(
                campaign_id=cid, account_id=account_id,
                order_index=max_order,
                invite_limit=10, inmail_limit=10, message_limit=30,
            ))


@app.post('/api/accounts')
def create_account(body: AccountIn, request: Request, db=Depends(get_db)):
    user, camps, _ = user_scope(request, db)
    _require_in_scope(user, campaign_ids=body.campaign_ids)
    from .models import Account
    a = Account(name=body.name, status=body.status, session_ref=body.session_ref,
                daily_invite_cap=body.daily_invite_cap, weekly_invite_cap=body.weekly_invite_cap,
                daily_inmail_cap=body.daily_inmail_cap,
                daily_message_cap=body.daily_message_cap)
    db.add(a)
    db.flush()
    if body.campaign_ids is not None:
        _apply_campaign_assignments(a.id, body.campaign_ids, db, camps)
    if user.role != 'admin':
        user.allowed_account_ids = [*(user.allowed_account_ids or []), a.id]
    db.commit()
    db.refresh(a)
    return {'id': a.id}


@app.put('/api/accounts/{account_id}')
def update_account(account_id: int, body: AccountIn, request: Request, db=Depends(get_db)):
    user, camps, _ = user_scope(request, db)
    _require_in_scope(user, account_id=account_id, campaign_ids=body.campaign_ids)
    from .models import Account
    a = db.get(Account, account_id)
    if not a:
        raise HTTPException(404, 'Account not found')
    next_status = body.status if 'status' in body.model_fields_set else a.status
    if a.status in ('needs_reauth', 'seat_required') and next_status != a.status:
        raise HTTPException(422, 'Verify this account successfully before changing its status')
    a.name = body.name
    a.status = next_status
    if body.session_ref:
        a.session_ref = body.session_ref
    for field in ('daily_invite_cap', 'weekly_invite_cap', 'daily_inmail_cap', 'daily_message_cap'):
        if field in body.model_fields_set:
            setattr(a, field, getattr(body, field))
    if body.campaign_ids is not None:
        _apply_campaign_assignments(account_id, body.campaign_ids, db, camps)
    db.commit()
    return {'ok': True}


@app.post('/api/accounts/{account_id}/upload-cookies')
async def upload_account_cookies(account_id: int, request: Request, file: UploadFile, db=Depends(get_db)):
    """Accept a .json cookies file upload and save it to cookies_files/ on the server.
    Sets account.session_ref to the saved path and updates last_cookie_refresh_at."""
    require_auth(request)
    import json as _json
    import re as _re
    from pathlib import Path as _Path
    from .config import PROJECT_ROOT
    from .models import Account
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, 'Account not found')
    if not file.filename or not file.filename.lower().endswith('.json'):
        raise HTTPException(422, 'Only .json cookie files are supported')
    raw = await file.read()
    if len(raw) > 512 * 1024:
        raise HTTPException(422, 'Cookie file too large (limit 500 KB)')
    try:
        data = _json.loads(raw)
    except Exception:
        raise HTTPException(422, 'File is not valid JSON')
    if not isinstance(data, dict) or 'cookies' not in data:
        raise HTTPException(422, "Cookie file must be a JSON object with a 'cookies' key")
    # Fixed name per account: whatever the uploaded file was called, it is
    # saved as this account's ONE canonical cookies file (prefer the
    # get_cookies.py registry path so local captures and web uploads
    # share the same file).
    from .jobs import canonical_cookies_path, stale_cookie_candidates
    dest = _Path(canonical_cookies_path(account))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    # Best-effort cleanup of this account's older, differently-named cookie
    # files so exactly one file per account remains on disk.
    allowed = (_Path(PROJECT_ROOT) / 'cookies_files').resolve()
    for old in stale_cookie_candidates(account, keep=str(dest)):
        try:
            p = _Path(old)
            if p.exists() and p.resolve().parent == allowed:
                p.unlink()
        except OSError:
            pass
    account.session_ref = str(dest)
    account.last_cookie_refresh_at = datetime.utcnow()
    # Live-check the NEW cookies right away (same semantics as the Verify
    # endpoint) so the UI reflects reality without a second manual click:
    #   ok      -> active (a needs_reauth/seat_required flag is cleared)
    #   seat    -> seat_required (new cookies cannot fix a missing seat)
    #   401/403 -> needs_reauth (cookies really are rejected)
    #   other   -> transient; upload stays saved, status untouched
    # A needs_reauth account with valid cookies that LinkedIn rejects only
    # with a transient error MUST NOT flip to needs_reauth based on nothing
    # more than a bad network moment - that is what re-flagged accounts
    # right after a good upload.
    session_ok = None
    session = None
    from .jobs import load_session_ref
    from .linkedin import fetch_inbox, LinkedinError, SeatRequiredError
    try:
        session = load_session_ref(account, persist=True)
        fetch_inbox(session, count=1)
        session_ok = True
        if account.status in ('needs_reauth', 'seat_required'):
            account.status = 'active'
    except SeatRequiredError:
        session_ok = False
        if account.status != 'paused':
            account.status = 'seat_required'
    except LinkedinError as exc:
        if getattr(exc, 'status', None) in (401, 403) and account.status != 'paused':
            session_ok = False
            account.status = 'needs_reauth'
        # Transient (timeout/5xx/parse) LinkedinError: cookies are saved but
        # not proven good yet; leave the previous status alone.
    except Exception:
        # Connection errors/timeouts do not prove the cookies are invalid.
        pass
    finally:
        close = getattr(session, 'close', None)
        if callable(close):
            try: close()
            except Exception: pass
    db.commit()
    return {'ok': True, 'session_ref': str(dest), 'saved_as': dest.name, 'session_ok': session_ok, 'status': account.status}


@app.delete('/api/accounts/{account_id}')
def delete_account(account_id: int, request: Request, db=Depends(get_db)):
    """Remove a LinkedIn account and its campaign links + cookie file.
    Leads keep their history: their associate_account_id is set to NULL by the
    FK (ondelete=SET NULL), so nothing is lost — the rows just become unowned.
    Deletion is blocked while a job is running to avoid pulling a seat out from
    under an active run."""
    user, _, _ = user_scope(request, db)
    _require_in_scope(user, account_id=account_id)
    from .models import Account, RunLog
    a = db.get(Account, account_id)
    if not a:
        raise HTTPException(404, 'Account not found')
    _require_in_scope(user, campaign_ids=[link.campaign_id for link in a.campaign_links])
    running = db.scalar(select(RunLog).where(RunLog.status == 'running', RunLog.account_id == account_id))
    if running:
        raise HTTPException(409, 'A job is currently running for this account. Stop it (or wait for it to finish) before removing the account.')
    cookie_path = a.session_ref or None
    db.delete(a)  # campaign_links cascade; leads.associate_account_id -> NULL
    db.commit()
    # Best-effort cleanup of the uploaded cookies file (defensive: only delete
    # files that live inside cookies_files/).
    if cookie_path:
        try:
            from pathlib import Path as _Path
            from .config import PROJECT_ROOT
            p = _Path(cookie_path)
            allowed = (_Path(PROJECT_ROOT) / 'cookies_files').resolve()
            if p.exists() and p.resolve().parent == allowed:
                p.unlink()
        except OSError:
            pass
    return {'ok': True}


@app.post('/api/accounts/{account_id}/verify-session')
def verify_account_session(account_id: int, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Account
    from .jobs import load_session_ref
    from .linkedin import fetch_inbox, LinkedinError, SeatRequiredError
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, 'Account not found')
    try:
        session = load_session_ref(account, persist=True)
        # A fallback-resolved session (legacy/filename guess) is now persisted,
        # so the UI shows it as configured immediately after verification.
        db.commit()
    except Exception as exc:
        db.rollback()
        # A paused account stays paused; verifying must never silently resume it.
        if account.status != 'paused':
            account.status = 'needs_reauth'
        db.commit()
        raise HTTPException(422, str(exc))
    try:
        fetch_inbox(session, count=1)
    except SeatRequiredError as exc:
        if account.status != 'paused':
            account.status = 'seat_required'
        db.commit()
        raise HTTPException(422, str(exc))
    except LinkedinError as exc:
        if exc.status in (401, 403) and account.status != 'paused':
            account.status = 'needs_reauth'
            db.commit()
        raise HTTPException(422, str(exc))
    except Exception as exc:
        # A timeout or server error does not prove that credentials are invalid.
        raise HTTPException(422, str(exc))
    finally:
        close = getattr(session, 'close', None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
    account.last_cookie_refresh_at = datetime.utcnow()
    if account.status in ('needs_reauth', 'seat_required'):
        account.status = 'active'
    db.commit()
    return {'ok': True, 'status': account.status}


@app.post('/api/accounts/verify-all')
def verify_all_accounts_session(request: Request, db=Depends(get_db)):
    require_auth(request)
    _user, _camp_scope, acct_scope = user_scope(request, db)
    from sqlalchemy import select
    from .models import Account
    from .jobs import load_session_ref
    from .linkedin import fetch_inbox, LinkedinError, SeatRequiredError

    accounts = db.execute(select(Account).order_by(Account.name)).scalars().all()
    verified_count = 0
    failed_count = 0
    skipped_count = 0
    results = []

    for account in accounts:
        if acct_scope is not None and account.id not in set(acct_scope):
            continue
        if not account.session_ref:
            skipped_count += 1
            results.append({'id': account.id, 'name': account.name, 'status': 'skipped', 'reason': 'No session configured'})
            continue

        session = None
        try:
            session = load_session_ref(account, persist=True)
            db.commit()
            fetch_inbox(session, count=1)
            account.last_cookie_refresh_at = datetime.utcnow()
            if account.status in ('needs_reauth', 'seat_required'):
                account.status = 'active'
            db.commit()
            verified_count += 1
            results.append({'id': account.id, 'name': account.name, 'status': account.status, 'ok': True})
        except SeatRequiredError as exc:
            if account.status != 'paused':
                account.status = 'seat_required'
            db.commit()
            failed_count += 1
            results.append({'id': account.id, 'name': account.name, 'status': account.status, 'ok': False, 'error': str(exc)})
        except LinkedinError as exc:
            if exc.status in (401, 403) and account.status != 'paused':
                account.status = 'needs_reauth'
            db.commit()
            failed_count += 1
            results.append({'id': account.id, 'name': account.name, 'status': account.status, 'ok': False, 'error': str(exc)})
        except Exception as exc:
            db.rollback()
            failed_count += 1
            results.append({'id': account.id, 'name': account.name, 'status': account.status, 'ok': False, 'error': str(exc)})
        finally:
            if session is not None:
                close = getattr(session, 'close', None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass

    return {
        'ok': True,
        'verified_count': verified_count,
        'failed_count': failed_count,
        'skipped_count': skipped_count,
        'total': len(results),
        'results': results,
    }


# ---------------------------------------------------------------------------
# Sales Navigator licenses (enterprise multiadmin — Anne's admin seat only)
# ---------------------------------------------------------------------------

class SalesNavEmails(BaseModel):
    emails: list[str] = Field(default_factory=list, max_length=200)


def _salesnav_emails(raw: list[str]) -> list[str]:
    """Normalize + validate the posted email list, de-duped and order-preserving."""
    from . import salesnav
    seen: set[str] = set()
    emails: list[str] = []
    for value in raw:
        email = salesnav.normalize_email(value)
        if not email:
            continue
        local, _, domain = email.partition('@')
        if (not local or '.' not in domain or email.count('@') != 1
                or any(c.isspace() for c in email) or domain.startswith('.') or domain.endswith('.')):
            raise HTTPException(422, f'Not a valid email address: {value!r}')
        if email not in seen:
            seen.add(email)
            emails.append(email)
    if not emails:
        raise HTTPException(422, 'Enter at least one email address')
    return emails


@app.get('/api/salesnav/licenses')
def salesnav_licenses(request: Request, db=Depends(get_db)):
    """List every Sales Navigator license in the enterprise account."""
    require_licenses_access(request, db)
    from . import salesnav
    try:
        with salesnav.open_session() as session:
            snapshot = salesnav.build_snapshot(salesnav.list_licenses(session))
    except salesnav.SalesNavProtectedError as exc:
        raise HTTPException(403, str(exc))
    except salesnav.SalesNavAuthError as exc:
        raise HTTPException(502, str(exc))
    except salesnav.SalesNavError as exc:
        raise HTTPException(502, str(exc))
    return snapshot


@app.post('/api/salesnav/activate')
def salesnav_activate(body: SalesNavEmails, request: Request, db=Depends(get_db)):
    """Assign a Sales Navigator license, refusing to exceed the license cap."""
    require_licenses_access(request, db)
    from . import salesnav
    emails = _salesnav_emails(body.emails)
    try:
        with salesnav.open_session() as session:
            snapshot = salesnav.build_snapshot(salesnav.list_licenses(session))
            plan = salesnav.plan_activation(snapshot, emails)
            newly = plan['newly']
            id_map = salesnav.resolve_profile_ids(session, newly, create_missing=True) if newly else {}
            ids = [id_map[e] for e in newly if id_map.get(e)]
            if ids:
                assigned = salesnav.assign_license(session, ids)
                if not assigned.ok:
                    raise HTTPException(
                        502, f'License assignment failed (HTTP {assigned.status_code}) {assigned.text[:200]}')
            results = []
            for email in emails:
                existing = snapshot['by_email'].get(email) or {}
                if email in plan['already']:
                    status = existing.get('status', '')
                    profile_id = existing.get('profile_id', '')
                    entry = {'email': email, 'action': 'skipped', 'status': status,
                             'profile_id': profile_id, 'link': '',
                             'detail': f'Already {status or "licensed"}'}
                    if status == 'INVITED' and profile_id:
                        entry['link'] = salesnav.activation_link(session, profile_id)
                        entry['detail'] = 'Already invited — activation link refreshed'
                    results.append(entry)
                elif id_map.get(email):
                    link = salesnav.activation_link(session, id_map[email]) if ids else ''
                    results.append({'email': email, 'action': 'activated', 'status': 'INVITED',
                                    'profile_id': id_map[email], 'link': link,
                                    'detail': 'Assignment accepted; LinkedIn may still be processing it'})
                else:
                    results.append({'email': email, 'action': 'failed', 'status': '',
                                    'profile_id': '', 'link': '',
                                    'detail': 'No profile ID returned by LinkedIn'})
    except salesnav.SalesNavProtectedError as exc:
        raise HTTPException(403, str(exc))
    except salesnav.SalesNavAuthError as exc:
        raise HTTPException(502, str(exc))
    except salesnav.SalesNavCapError as exc:
        raise HTTPException(409, str(exc))
    except salesnav.SalesNavError as exc:
        raise HTTPException(502, str(exc))
    used = snapshot['used'] + len(ids)
    return {'ok': True, 'max_licenses': salesnav.MAX_LICENSES, 'used': used,
            'remaining': max(0, salesnav.MAX_LICENSES - used), 'results': results}


@app.post('/api/salesnav/remove')
def salesnav_remove(body: SalesNavEmails, request: Request, db=Depends(get_db)):
    """Remove the Sales Navigator license from the given emails' profiles."""
    require_licenses_access(request, db)
    from . import salesnav
    emails = _salesnav_emails(body.emails)
    try:
        with salesnav.open_session() as session:
            snapshot = salesnav.build_snapshot(salesnav.list_licenses(session))
            salesnav.assert_removable(snapshot, emails=emails)
            id_map = salesnav.resolve_profile_ids(session, emails, create_missing=False)
            salesnav.assert_removable(snapshot, profile_ids=id_map.values())
            profile_ids = [id_map[e] for e in emails if id_map.get(e)]
            removed = salesnav.remove_licenses(session, profile_ids) if profile_ids else None
            results = []
            for email in emails:
                profile_id = id_map.get(email, '')
                if not profile_id:
                    results.append({'email': email, 'profile_id': '', 'action': 'skipped',
                                    'detail': 'No enterprise profile for this email'})
                elif removed is not None and removed.ok:
                    results.append({'email': email, 'profile_id': profile_id, 'action': 'removed',
                                    'detail': 'Removal accepted; refresh to confirm the final status'})
                else:
                    code = removed.status_code if removed else '—'
                    results.append({'email': email, 'profile_id': profile_id, 'action': 'failed',
                                    'detail': f'Removal failed (HTTP {code})'})
    except salesnav.SalesNavProtectedError as exc:
        raise HTTPException(403, str(exc))
    except salesnav.SalesNavAuthError as exc:
        raise HTTPException(502, str(exc))
    except salesnav.SalesNavError as exc:
        raise HTTPException(502, str(exc))
    return {'ok': True, 'removed': sum(1 for r in results if r['action'] == 'removed'),
            'results': results}


@app.post('/api/salesnav/link')
def salesnav_link(body: SalesNavEmails, request: Request, db=Depends(get_db)):
    """Fetch activation links without changing any license assignment."""
    require_licenses_access(request, db)
    from . import salesnav
    emails = _salesnav_emails(body.emails)
    try:
        with salesnav.open_session() as session:
            snapshot = salesnav.build_snapshot(salesnav.list_licenses(session))
            extra = salesnav.lookup_profiles(session, emails)
            results = []
            for email in emails:
                existing = snapshot['by_email'].get(email) or {}
                profile_id = existing.get('profile_id') or extra.get(email, '')
                link = salesnav.activation_link(session, profile_id) if profile_id else ''
                results.append({'email': email, 'status': existing.get('status', 'UNKNOWN'),
                                'profile_id': profile_id, 'link': link,
                                'action': 'link' if link else 'failed',
                                'detail': '' if link else 'Could not fetch an activation link'})
    except salesnav.SalesNavProtectedError as exc:
        raise HTTPException(403, str(exc))
    except salesnav.SalesNavAuthError as exc:
        raise HTTPException(502, str(exc))
    except salesnav.SalesNavError as exc:
        raise HTTPException(502, str(exc))
    return {'ok': True, 'results': results}


@app.post('/api/salesnav/add')
def salesnav_add(body: SalesNavEmails, request: Request, db=Depends(get_db)):
    """Create enterprise profiles for emails WITHOUT assigning a license.

    Enterprise profiles are the roster entries a license is later attached to;
    creating one does not consume a seat, so this is not subject to the cap.
    """
    require_licenses_access(request, db)
    from . import salesnav
    emails = _salesnav_emails(body.emails)
    try:
        with salesnav.open_session() as session:
            existing = salesnav.lookup_profiles(session, emails)
            missing = [e for e in emails if e not in existing]
            created = salesnav.resolve_profile_ids(session, missing, create_missing=True) if missing else {}
            results = []
            for email in emails:
                was_existing = email in existing
                profile_id = existing.get(email) or created.get(email, '')
                if was_existing:
                    action, detail = 'exists', 'Enterprise profile already existed'
                elif profile_id:
                    action, detail = 'created', 'Enterprise profile created'
                else:
                    action, detail = 'failed', 'No profile ID returned by LinkedIn'
                results.append({'email': email, 'profile_id': profile_id,
                                'action': action, 'detail': detail})
    except salesnav.SalesNavProtectedError as exc:
        raise HTTPException(403, str(exc))
    except salesnav.SalesNavAuthError as exc:
        raise HTTPException(502, str(exc))
    except salesnav.SalesNavError as exc:
        raise HTTPException(502, str(exc))
    return {'ok': True, 'created': sum(1 for r in results if r['action'] == 'created'),
            'results': results}


# ---------------------------------------------------------------------------
# Campaigns (CRUD incl. nested accounts + message templates)
# ---------------------------------------------------------------------------

class CampaignAccountIn(BaseModel):
    account_id: int
    order_index: int = 0
    invite_limit: int = Field(default=10, ge=0)
    inmail_limit: int = Field(default=10, ge=0)
    message_limit: int = Field(default=30, ge=0)
    calendar_url: str | None = None
    search_url_override: str | None = None


class CampaignIn(BaseModel):
    name: str
    campaign_key: str | None = None   # None = keep existing (immutable after create)
    status: str = 'active'
    search_url: str = ''
    invite_text: str = ''
    invite_track: list[str] = Field(default_factory=list)
    inmail_subject: str = ''
    inmail_text: str = ''
    inmail_track: list[dict] = Field(default_factory=list)
    invite_fu_days: list[int] = Field(default_factory=lambda: [3, 5, 7])
    inmail_fu_days: list[int] = Field(default_factory=lambda: [3, 5, 7])
    accounts: list[CampaignAccountIn] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_campaign(self):
        from string import Formatter
        if not self.name.strip():
            raise ValueError('Campaign name is required')
        if self.status not in ('active', 'paused'):
            raise ValueError('Campaign status must be active or paused')
        if len({a.account_id for a in self.accounts}) != len(self.accounts):
            raise ValueError('An account can only be assigned once')
        texts = [self.invite_text, self.inmail_subject, self.inmail_text, *self.invite_track]
        for stage in self.inmail_track:
            if any(not isinstance(v, str) for v in stage.values()):
                raise ValueError('Message subjects and bodies must be text')
            texts.extend([stage.get('subject', ''), stage.get('body', '')])
        for text in texts:
            for _, field, spec, conversion in Formatter().parse(text):
                if field is not None and (field not in ('first_name', 'company', 'calendar_url') or spec or conversion):
                    raise ValueError('Use only {first_name}, {company} and {calendar_url} placeholders')
        from .linkedin import build_search_params
        for url in [self.search_url, *(a.search_url_override for a in self.accounts)]:
            if url:
                build_search_params(url)
        return self


@app.get('/api/campaigns')
def list_campaigns(request: Request, db=Depends(get_db)):
    _user, camp_scope, _acct_scope = user_scope(request, db)
    from sqlalchemy import select, func, case
    from .models import Campaign, Lead
    campaigns = db.execute(select(Campaign).order_by(Campaign.id)).scalars().all()
    if camp_scope is not None:
        campaigns = [c for c in campaigns if c.id in set(camp_scope)]
    # Per-campaign lead stats in one grouped query (was 3 queries per campaign).
    stats = {
        row[0]: row
        for row in db.execute(
            select(
                Lead.campaign_id,
                func.count(Lead.id),
                func.sum(case((Lead.status != '', 1), else_=0)),
                func.sum(case((Lead.received_replies.is_(True), 1), else_=0)),
            ).group_by(Lead.campaign_id)
        ).all()
    }
    out = []
    for c in campaigns:
        _cid, total, contacted, replied = stats.get(c.id, (c.id, 0, 0, 0))
        total, contacted, replied = int(total or 0), int(contacted or 0), int(replied or 0)
        out.append({
            'id': c.id, 'campaign_key': c.campaign_key, 'name': c.name,
            'status': c.status,
            'invite_fu_days': c.invite_fu_days if c.invite_fu_days is not None else [3, 5, 7],
            'inmail_fu_days': c.inmail_fu_days if c.inmail_fu_days is not None else [3, 5, 7],
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
    _user, _camp_scope, _acct_scope = user_scope(request, db)
    from .models import Campaign
    c = db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(404, 'Campaign not found')
    _require_in_scope(_user, campaign_id=campaign_id)
    return {
        'id': c.id, 'campaign_key': c.campaign_key, 'name': c.name,
        'status': c.status,
        'search_url': c.search_url,
        'invite_text': c.invite_text,
        'invite_track': c.invite_track or [],
        'inmail_subject': c.inmail_subject,
        'inmail_text': c.inmail_text,
        'inmail_track': c.inmail_track or [],
        'invite_fu_days': c.invite_fu_days if c.invite_fu_days is not None else [3, 5, 7],
        'inmail_fu_days': c.inmail_fu_days if c.inmail_fu_days is not None else [3, 5, 7],
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
    user, _, _ = user_scope(request, db)
    _require_in_scope(user, account_ids=[link.account_id for link in body.accounts])
    validate_campaign_accounts(body.accounts, db)
    from .models import Campaign, CampaignAccount
    key = body.campaign_key or body.name
    if db.execute(select_stmt(key)).scalar():
        raise HTTPException(409, f"Campaign key '{key}' already exists")
    c = Campaign(
        campaign_key=key, name=body.name,
        status=body.status, search_url=body.search_url, invite_text=body.invite_text,
        invite_track=body.invite_track, inmail_subject=body.inmail_subject,
        inmail_text=body.inmail_text, inmail_track=body.inmail_track,
        invite_fu_days=body.invite_fu_days, inmail_fu_days=body.inmail_fu_days,
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
    # Auto-grant the creator access: a restricted user who can create a
    # campaign would otherwise never see it (every view filters by their
    # allowed_campaign_ids). Admins already see everything.
    creator = current_user(request, db)
    if creator is not None and creator.role != 'admin':
        ids = list(creator.allowed_campaign_ids or [])
        if c.id not in ids:
            ids.append(c.id)
            creator.allowed_campaign_ids = ids
    db.commit()
    return {'id': c.id}


class CampaignCopyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    campaign_key: str | None = Field(default=None, min_length=1, max_length=120)


@app.post('/api/campaigns/{campaign_id}/copy')
def copy_campaign(campaign_id: int, body: CampaignCopyIn, request: Request, db=Depends(get_db)):
    """Clone saved configuration only, with an independent key and paused state."""
    from copy import deepcopy
    from sqlalchemy.exc import IntegrityError
    from .models import Campaign, CampaignAccount
    user, _, _ = user_scope(request, db)
    _require_in_scope(user, campaign_id=campaign_id)
    source = db.get(Campaign, campaign_id)
    if source is None:
        raise HTTPException(404, 'Campaign not found')
    _require_in_scope(user, account_ids=[link.account_id for link in source.account_links])
    name = body.name.strip()
    key = (body.campaign_key if body.campaign_key is not None else name).strip()
    if not name or not key:
        raise HTTPException(422, 'Enter a campaign name and a unique campaign key')
    if db.scalar(select_stmt(key)):
        raise HTTPException(409, 'That campaign key already exists. Choose a different key for the copy.')
    duplicate = Campaign(name=name, campaign_key=key, status='paused',
                         search_url=source.search_url, invite_text=source.invite_text,
                         invite_track=deepcopy(source.invite_track or []),
                         inmail_subject=source.inmail_subject, inmail_text=source.inmail_text,
                         inmail_track=deepcopy(source.inmail_track or []),
                         invite_fu_days=deepcopy(source.invite_fu_days or [3, 5, 7]),
                         inmail_fu_days=deepcopy(source.inmail_fu_days or [3, 5, 7]))
    try:
        db.add(duplicate)
        db.flush()
        for link in source.account_links:
            db.add(CampaignAccount(campaign_id=duplicate.id, account_id=link.account_id,
                                   order_index=link.order_index, invite_limit=link.invite_limit,
                                   inmail_limit=link.inmail_limit, message_limit=link.message_limit,
                                   calendar_url=link.calendar_url, search_url_override=link.search_url_override))
        if user.role != 'admin':
            user.allowed_campaign_ids = [*(user.allowed_campaign_ids or []), duplicate.id]
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Could not copy the campaign. Refresh and choose a unique key.')
    return {'id': duplicate.id, 'name': duplicate.name, 'status': duplicate.status}


def select_stmt(key):
    from sqlalchemy import select, func
    from .models import Campaign
    return select(func.count(Campaign.id)).where(Campaign.campaign_key == key)


def validate_campaign_accounts(accounts, db):
    from .models import Account
    ids = {link.account_id for link in accounts}
    if ids and db.query(Account).filter(Account.id.in_(ids)).count() != len(ids):
        raise HTTPException(422, 'A mapped account no longer exists. Refresh the campaign and choose an available account.')


@app.put('/api/campaigns/{campaign_id}/pause')
def pause_campaign(campaign_id: int, request: Request, body: dict, db=Depends(get_db)):
    """Toggle a campaign's paused state without resending templates/accounts.
    Paused campaigns are skipped by every worker loop (status == 'active'
    filter in send_connections / send_followups / check_replies)."""
    user, _, _ = user_scope(request, db)
    _require_in_scope(user, campaign_id=campaign_id)
    from .models import Campaign
    c = db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(404, 'Campaign not found')
    status = (body or {}).get('status')
    if status not in ('active', 'paused'):
        raise HTTPException(422, "status must be 'active' or 'paused'")
    c.status = status
    db.commit()
    return {'ok': True, 'status': c.status}


@app.delete('/api/campaigns/{campaign_id}')
def delete_campaign(campaign_id: int, request: Request, db=Depends(get_db)):
    """Delete a campaign and its associated leads. Refuses while a run targeting
    this campaign is active."""
    user, _camp_scope, _acct_scope = user_scope(request, db)
    _require_in_scope(user, campaign_id=campaign_id)
    from .models import Campaign, RunLog, Lead
    c = db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(404, 'Campaign not found')
    running = db.scalar(select(RunLog).where(RunLog.status == 'running', RunLog.campaign_id == campaign_id))
    if running:
        raise HTTPException(409, 'A job is currently running for this campaign. Stop it (or wait) before deleting.')
    leads_to_delete = db.scalars(select(Lead).where(Lead.campaign_id == campaign_id)).all()
    lead_count = len(leads_to_delete)
    for lead in leads_to_delete:
        db.delete(lead)
    db.delete(c)  # campaign_account links cascade
    db.commit()
    return {'ok': True, 'leads_deleted': int(lead_count)}


@app.put('/api/campaigns/{campaign_id}')
def update_campaign(campaign_id: int, body: CampaignIn, request: Request, db=Depends(get_db)):
    user, _, _ = user_scope(request, db)
    _require_in_scope(user, campaign_id=campaign_id, account_ids=[link.account_id for link in body.accounts])
    validate_campaign_accounts(body.accounts, db)
    from .models import Campaign, CampaignAccount
    c = db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(404, 'Campaign not found')
    if body.campaign_key and body.campaign_key != c.campaign_key:
        raise HTTPException(400, 'campaign_key is immutable - it is the tag on every lead row')
    c.name = body.name
    c.status = body.status
    if 'search_url' in body.model_fields_set:
        c.search_url = body.search_url
    c.invite_text = body.invite_text
    c.invite_track = body.invite_track
    c.inmail_subject = body.inmail_subject
    c.inmail_text = body.inmail_text
    c.inmail_track = body.inmail_track
    c.invite_fu_days = body.invite_fu_days
    c.inmail_fu_days = body.inmail_fu_days
    # Replace account links wholesale (order_index drives the load balancer)
    if not body.accounts:
        raise HTTPException(
            400,
            'Refusing to remove all accounts from a campaign - every job loops '
            'over campaign accounts, so an empty list silently disables the '
            'campaign. Pause the campaign instead, or keep at least one account.',
        )
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

def _lead_filters(stmt, *, campaign_id=None, account_id=None, status=None, source=None,
                  q=None, replied=None, category=None, review=None, contact_from=None,
                  contact_to=None, created_from=None, created_to=None,
                  followup_from=None, followup_to=None,
                  campaign_ids: str | None = None, account_ids: str | None = None,
                  company: str | None = None, opentomsg: str | None = None,
                  error: str | None = None, statuses: str | None = None):
    """Shared filter builder so the table, exports and select-all counts agree."""
    from sqlalchemy import select, or_
    from .models import Lead
    from datetime import datetime as _dt

    def _id_list(raw):
        return [int(x) for x in (raw or '').split(',') if x.strip().isdigit()]

    def _day(raw, end=False):
        if not raw:
            return None
        try:
            # ISO with timezone (frontend sends local-time ISO) → convert to UTC naive
            if raw.endswith('Z') or ('+' in raw[10:]) or ('-' in raw[10:] and 'T' in raw):
                d = _dt.fromisoformat(raw.replace('Z', '+00:00'))
                if d.tzinfo is not None:
                    d = d.astimezone(timezone.utc).replace(tzinfo=None)
                return d
        except (ValueError, TypeError):
            pass
        try:
            d = _dt.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            return None
        return _dt.combine(d, _dt.max.time() if end else _dt.min.time())

    if campaign_id:
        stmt = stmt.where(Lead.campaign_id == campaign_id)
    cids = _id_list(campaign_ids)
    if cids:
        stmt = stmt.where(Lead.campaign_id.in_(cids))
    if account_id:
        stmt = stmt.where(Lead.associate_account_id == account_id)
    aids = _id_list(account_ids)
    if aids:
        stmt = stmt.where(Lead.associate_account_id.in_(aids))
    if statuses:
        s_list = [x.strip() for x in statuses.split(',') if x.strip()]
        if s_list:
            conds = []
            for s in s_list:
                if s == '__untouched__':
                    conds.append(Lead.status == '')
                else:
                    conds.append(Lead.status == s)
            stmt = stmt.where(or_(*conds))
    elif status is not None and status != '':
        if status == '__untouched__':
            stmt = stmt.where(Lead.status == '')
        else:
            stmt = stmt.where(Lead.status == status)
    if error == 'only':
        stmt = stmt.where(Lead.status == 'BLOCKED_ERROR')
    elif error == 'none':
        stmt = stmt.where(Lead.status != 'BLOCKED_ERROR')
    if source:
        stmt = stmt.where(Lead.source == source)
    if replied is not None:
        stmt = stmt.where(Lead.received_replies.is_(replied))
    if category:
        stmt = stmt.where(Lead.reply_category == category)
    if review == 'needs_review':
        stmt = stmt.where(Lead.review_status == 'needs_review')
    elif review == 'reviewed':
        stmt = stmt.where(Lead.review_status == 'reviewed')
    if company:
        stmt = stmt.where(Lead.company.ilike(f'%{company}%'))
    # OpenToMsg tri-state: yes (open), no (checked, not open), unchecked (null).
    if opentomsg == 'yes':
        stmt = stmt.where(Lead.opentomsg.is_(True))
    elif opentomsg == 'no':
        stmt = stmt.where(Lead.opentomsg.is_(False))
    elif opentomsg == 'unchecked':
        stmt = stmt.where(Lead.opentomsg.is_(None))
    cf, ct = _day(contact_from), _day(contact_to, end=True)
    if cf:
        stmt = stmt.where(Lead.first_contacted_at >= cf)
    if ct:
        stmt = stmt.where(Lead.first_contacted_at <= ct)
    crf, crt = _day(created_from), _day(created_to, end=True)
    if crf:
        stmt = stmt.where(Lead.created_at >= crf)
    if crt:
        stmt = stmt.where(Lead.created_at <= crt)
    ff, ft = _day(followup_from), _day(followup_to, end=True)
    if ff:
        stmt = stmt.where(Lead.last_followup_at >= ff)
    if ft:
        stmt = stmt.where(Lead.last_followup_at <= ft)
    if q:
        like = f'%{q}%'
        stmt = stmt.where(or_(
            Lead.full_name.ilike(like), Lead.company.ilike(like),
            Lead.title.ilike(like), Lead.sales_nav_id.ilike(like),
        ))
    return stmt


def lead_sorts():
    """Allow-listed sort keys, resolved lazily (models import at call time).
    'newest' = latest ACTIVITY: the most recent of (follow-up sent, status
    change, first contact, date added) — so the pipeline always opens with
    whichever lead was touched/added most recently."""
    from sqlalchemy import func
    from .models import Lead
    activity = func.coalesce(Lead.last_followup_at, Lead.status_changed_at,
                             Lead.first_contacted_at, Lead.created_at)
    return {
        'newest': (activity.desc(), Lead.id.desc()),
        'activity': (activity.desc(), Lead.id.desc()),
        'oldest': (Lead.created_at.asc(), Lead.id.asc()),
        'created': (Lead.created_at.asc(), Lead.id.asc()),
        'created_desc': (Lead.created_at.desc(), Lead.id.desc()),
        'lead_name': (Lead.full_name.asc(), Lead.id.asc()),
        'lead_name_desc': (Lead.full_name.desc(), Lead.id.desc()),
        'company': (Lead.company.asc(), Lead.id.asc()),
        'company_desc': (Lead.company.desc(), Lead.id.desc()),
        'location': (Lead.location.asc(), Lead.id.asc()),
        'location_desc': (Lead.location.desc(), Lead.id.desc()),
        'campaign': (Lead.campaign_id.asc().nullslast(), Lead.id.asc()),
        'campaign_desc': (Lead.campaign_id.desc().nullsfirst(), Lead.id.desc()),
        'account': (Lead.associate_account_id.asc().nullslast(), Lead.id.asc()),
        'account_desc': (Lead.associate_account_id.desc().nullsfirst(), Lead.id.desc()),
        'stage': (Lead.status.asc(), Lead.id.asc()),
        'stage_desc': (Lead.status.desc(), Lead.id.desc()),
        'contact': (Lead.first_contacted_at.asc().nullsfirst(), Lead.id.asc()),
        'contact_desc': (Lead.first_contacted_at.desc().nullslast(), Lead.id.desc()),
        'followup': (Lead.last_followup_at.asc().nullsfirst(), Lead.id.asc()),
        'followup_desc': (Lead.last_followup_at.desc().nullslast(), Lead.id.desc()),
    }


@app.get('/api/leads')
def list_leads(request: Request, db=Depends(get_db),
               campaign_id: str | None = None, account_id: int | None = None,
               status: str | None = None, source: str | None = None,
               q: str | None = None, replied: bool | None = None,
               category: str | None = None, review: str | None = None,
               company: str | None = None,
               campaign_ids: str | None = None, account_ids: str | None = None,
               contact_from: str | None = None, contact_to: str | None = None,
               created_from: str | None = None, created_to: str | None = None,
               followup_from: str | None = None, followup_to: str | None = None,
               opentomsg: str | None = None,
               error: str | None = None,
               statuses: str | None = None,
               sort: str = 'newest',
               page: int = 1, page_size: int = 50, ids_only: bool = False):
    require_auth(request)
    from sqlalchemy import select, func
    from sqlalchemy.orm import selectinload
    from .models import Lead, ReplyComment
    # Sentinel: campaign_id='__none__' filters the unassigned pool (no campaign).
    campaign_none = campaign_id == '__none__'
    if campaign_none:
        campaign_id = None
    elif campaign_id and campaign_id.isdigit():
        campaign_id = int(campaign_id)
    else:
        campaign_id = None
    # Server-side cap: a huge page_size would serialize the whole table.
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    # Access scope: restricted users only see their campaigns/accounts.
    _tuser, _camps, _accts = user_scope(request, db)

    stmt = _lead_filters(
        select(Lead).options(selectinload(Lead.campaign), selectinload(Lead.associate_account)),
        campaign_id=None if campaign_none else campaign_id, account_id=account_id,
        status=status, source=source, q=q, replied=replied,
        category=category, review=review, company=company,
        campaign_ids=campaign_ids, account_ids=account_ids,
        contact_from=contact_from, contact_to=contact_to,
        created_from=created_from, created_to=created_to,
        followup_from=followup_from, followup_to=followup_to,
        opentomsg=opentomsg, error=error, statuses=statuses,
    )
    # Tagged leads require campaign access, even when an allowed account owns them.
    # Account access applies only to leads with no campaign.
    _lead_scope = _lead_scope_conditions(_camps, _accts)
    if _lead_scope is not None:
        stmt = stmt.where(_lead_scope)
    if campaign_none:
        stmt = stmt.where(Lead.campaign_id.is_(None))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if ids_only:
        # A single database snapshot, rather than pagination while imports change.
        ids = list(db.scalars(select(stmt.subquery().c.id)).all())
        return {'ids': ids, 'total': len(ids)}
    order = lead_sorts().get(sort, lead_sorts()['newest'])
    rows = db.execute(
        stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()

    comment_counts = {}
    if rows:
        c_rows = db.execute(
            select(ReplyComment.lead_id, func.count(ReplyComment.id))
            .where(ReplyComment.lead_id.in_([l.id for l in rows]))
            .group_by(ReplyComment.lead_id)
        ).all()
        comment_counts = {lid: n for lid, n in c_rows}

    def serialize(l: Lead):
        return {
            'id': l.id,
            'sales_nav_id': l.sales_nav_id,
            'full_name': l.full_name or f"{l.first_name} {l.last_name}".strip(),
            'title': l.title, 'company': l.company, 'location': l.location,
            'opentomsg': l.opentomsg, 'linkedin_url': l.linkedin_url,
            'source': l.source, 'list_id': l.list_id,
            'campaign': l.campaign.campaign_key if l.campaign else None,
            # Live values so a campaign rename shows on every lead row
            # immediately (campaign_key is immutable by design).
            'campaign_id': l.campaign_id,
            'campaign_name': l.campaign.name if l.campaign else None,
            'associate_account': l.associate_account.name if l.associate_account else None,
            'status': l.status, 'status_changed_at': l.status_changed_at.isoformat() if l.status_changed_at else None,
            'last_error': l.last_error or '',
            'received_replies': l.received_replies,
            'reply_message': (l.reply_message or '')[:200],
            'reply_category': l.reply_category or ('unclassified' if l.received_replies else ''),
            'reply_category_source': l.reply_category_source or '',
            'review_status': l.review_status or '',
            'created_at': l.created_at.isoformat() if l.created_at else None,
            'first_contacted_at': l.first_contacted_at.isoformat() if l.first_contacted_at else None,
            'contact_channel': l.contact_channel or '',
            'last_followup_at': l.last_followup_at.isoformat() if l.last_followup_at else None,
            'last_followup_stage': l.last_followup_stage or '',
            'comment_count': comment_counts.get(l.id, 0),
        }

    return {'total': total, 'page': page, 'page_size': page_size, 'items': [serialize(l) for l in rows]}


@app.get('/api/leads/{lead_id}/timeline')
def lead_timeline(lead_id: int, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Lead, LeadEvent
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, 'Lead not found')
    _require_lead_access(lead, request, db)
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


class BulkDeleteBody(BaseModel):
    ids: list[int]
    campaign_id: int | None = None  # alternative: delete whole current filter via campaign


@app.post('/api/leads/bulk-delete')
def bulk_delete_leads(body: BulkDeleteBody, request: Request, db=Depends(get_db)):
    return bulk_delete_v2(DeleteBody(ids=body.ids), request, db)


@app.get('/api/leads/export')
def export_leads(request: Request, db=Depends(get_db),
                campaign_id: str | None = None, account_id: int | None = None,
                status: str | None = None, source: str | None = None,
                q: str | None = None, replied: bool | None = None,
                category: str | None = None, review: str | None = None,
                company: str | None = None,
                campaign_ids: str | None = None, account_ids: str | None = None,
                contact_from: str | None = None, contact_to: str | None = None,
                created_from: str | None = None, created_to: str | None = None,
                followup_from: str | None = None, followup_to: str | None = None,
                opentomsg: str | None = None,
                error: str | None = None,
                statuses: str | None = None,
                sort: str = 'newest'):
    """CSV download honoring the same filters as the leads table (max 10k rows)."""
    import csv as _csv
    import io
    from urllib.parse import quote
    from sqlalchemy import select, or_
    from .models import Lead
    require_auth(request)
    # Exports honor the same campaign/account scope as the table.
    _tuser, _camps, _accts = user_scope(request, db)

    stmt = _lead_filters(
        select(Lead), campaign_id=None if campaign_id == '__none__' else (int(campaign_id) if campaign_id and campaign_id.isdigit() else None), account_id=account_id,
        status=status, source=source, q=q, replied=replied,
        category=category, review=review, company=company,
        campaign_ids=campaign_ids, account_ids=account_ids,
        contact_from=contact_from, contact_to=contact_to,
        created_from=created_from, created_to=created_to,
        followup_from=followup_from, followup_to=followup_to,
        opentomsg=opentomsg, error=error, statuses=statuses,
    )
    _csv_scope = _lead_scope_conditions(_camps, _accts)
    if _csv_scope is not None:
        stmt = stmt.where(_csv_scope)
    if campaign_id == '__none__':
        stmt = stmt.where(Lead.campaign_id.is_(None))
    order = lead_sorts().get(sort, lead_sorts()['newest'])
    rows = db.execute(stmt.order_by(*order).limit(10000)).scalars().all()

    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(['id', 'sales_nav_id', 'sales_nav_urn', 'full_name', 'title', 'company', 'location',
                'campaign', 'owner_account', 'status', 'opentomsg', 'source',
                'received_replies', 'reply_category', 'reply_message',
                'first_contacted_at', 'contact_channel', 'last_followup_at',
                'last_followup_stage', 'created_at', 'linkedin_url', 'last_error'])
    for l in rows:
        w.writerow([
            l.id, l.sales_nav_id, l.sales_nav_urn or '', l.full_name, l.title, l.company, l.location,
            l.campaign.campaign_key if l.campaign else '',
            l.associate_account.name if l.associate_account else '',
            l.status, '' if l.opentomsg is None else ('yes' if l.opentomsg else 'no'),
            l.source, 'yes' if l.received_replies else 'no',
            l.reply_category or '',
            (l.reply_message or '').replace('\n', ' ')[:300],
            l.first_contacted_at.isoformat() if l.first_contacted_at else '',
            l.contact_channel or '',
            l.last_followup_at.isoformat() if l.last_followup_at else '',
            l.last_followup_stage or '',
            l.created_at.isoformat() if l.created_at else '',
            l.linkedin_url or '',
            l.last_error or '',
        ])
    content = buf.getvalue()
    return Response(
        content=content,
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f"attachment; filename=leads_export_{date.today().isoformat()}.csv"},
    )


@app.get('/api/leads/import-template')
def download_leads_import_template(request: Request):
    """CSV template for the manual lead import, with two sample rows.

    Required column: full_name (or first_name + last_name).
    Optional columns (all may be left empty): title, company, location,
    sales_nav_id, sales_nav_urn, linkedin_url, opentomsg.
    sales_nav_id accepts both Sales Nav tokens (ACw…) and the flagship member
    tokens (ACo…) that CSV people-exports carry; sales_nav_urn holds the
    decorated 'urn:li:fs_salesProfile:(…)' value used verbatim as the message
    recipient, exactly like the legacy sheets pipeline. The template test
    round-trips this file through /api/leads/import-csv so it cannot drift
    from the parser."""
    require_auth(request)
    import csv as _csv
    import io

    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(['full_name', 'sales_nav_id', 'linkedin_url', 'sales_nav_urn',
                'first_name', 'last_name', 'title', 'company', 'location', 'opentomsg'])
    # Sample people must never carry a real person's outreach identity.
    w.writerow(['Jane Sample', '', '', '',
                'Jane', 'Sample', 'Talent Partner', 'Acme Corp', 'Bengaluru, India', 'unknown'])
    w.writerow(['John Sample', '', '', '',
                'John', 'Sample', 'VP Engineering', 'Globex', 'London, UK', 'unknown'])
    return Response(
        content=buf.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=leads_import_template.csv'},
    )


# ---------------------------------------------------------------------------
# Reply triage: categories, review status, internal comments
# ---------------------------------------------------------------------------

class CategoryBody(BaseModel):
    category: str


class ReviewBody(BaseModel):
    review_status: str  # '' | needs_review | reviewed


@app.put('/api/leads/{lead_id}/category')
def set_reply_category(lead_id: int, body: CategoryBody, request: Request, db=Depends(get_db)):
    """Manual category selection. Manual picks are sticky: auto-classification
    never overwrites source='manual' rows (enforced in backfill + sync paths)."""
    require_auth(request)
    from .models import Lead
    from .classify import CATEGORY_LABELS
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, 'Lead not found')
    _require_lead_access(lead, request, db)
    if body.category not in CATEGORY_LABELS:
        raise HTTPException(422, 'Unknown category')
    lead.reply_category = body.category
    lead.reply_category_source = 'manual'
    lead.reply_category_at = datetime.utcnow()
    db.commit()
    return {'ok': True, 'category': body.category, 'source': 'manual'}


@app.post('/api/leads/{lead_id}/review')
def set_review_status(lead_id: int, body: ReviewBody, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Lead
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, 'Lead not found')
    _require_lead_access(lead, request, db)
    if body.review_status not in ('', 'needs_review', 'reviewed'):
        raise HTTPException(422, 'review_status must be empty, needs_review or reviewed')
    lead.review_status = body.review_status
    lead.reply_reviewed_at = datetime.utcnow() if body.review_status == 'reviewed' else None
    db.commit()
    return {'ok': True}


@app.get('/api/leads/{lead_id}/comments')
def list_comments(lead_id: int, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Lead, ReplyComment
    from sqlalchemy import select
    if not db.get(Lead, lead_id):
        raise HTTPException(404, 'Lead not found')
    _require_lead_access(db.get(Lead, lead_id), request, db)
    rows = db.execute(
        select(ReplyComment).where(ReplyComment.lead_id == lead_id)
        .order_by(ReplyComment.id.desc())
    ).scalars().all()
    return [{'id': c.id, 'author': c.author, 'body': c.body,
             'created_at': c.created_at.isoformat() if c.created_at else None,
             'updated_at': c.updated_at.isoformat() if c.updated_at else None} for c in rows]


class CommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    author: str = Field(default='Admin', max_length=120)


@app.post('/api/leads/{lead_id}/comments')
def add_comment(lead_id: int, body: CommentBody, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import Lead, ReplyComment
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, 'Lead not found')
    _require_lead_access(lead, request, db)
    if not body.body.strip():
        raise HTTPException(422, 'Comment cannot be empty')
    author = current_user(request, db)
    c = ReplyComment(lead_id=lead_id, author=author.display_name or author.username, body=body.body.strip())
    db.add(c)
    db.commit()
    db.refresh(c)
    return {'id': c.id, 'author': c.author, 'body': c.body,
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'updated_at': None}


class CommentEditBody(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@app.put('/api/comments/{comment_id}')
def edit_comment(comment_id: int, body: CommentEditBody, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import ReplyComment
    c = db.get(ReplyComment, comment_id)
    if not c:
        raise HTTPException(404, 'Comment not found')
    from .models import Lead
    _require_lead_access(db.get(Lead, c.lead_id), request, db)
    if not body.body.strip():
        raise HTTPException(422, 'Comment cannot be empty')
    c.body = body.body.strip()
    c.updated_at = datetime.utcnow()
    db.commit()
    return {'ok': True}


@app.delete('/api/comments/{comment_id}')
def delete_comment(comment_id: int, request: Request, db=Depends(get_db)):
    require_auth(request)
    from .models import ReplyComment
    c = db.get(ReplyComment, comment_id)
    if not c:
        raise HTTPException(404, 'Comment not found')
    from .models import Lead
    _require_lead_access(db.get(Lead, c.lead_id), request, db)
    db.delete(c)
    db.commit()
    return {'ok': True}


# ---------------------------------------------------------------------------
# Leads: bulk selection counts, delete preview + transactional delete
# ---------------------------------------------------------------------------

class CountBody(BaseModel):
    ids: list[int]


@app.post('/api/leads/count')
def count_existing_leads(body: CountBody, request: Request, db=Depends(get_db)):
    """Authoritative count for a frozen selection (how many still exist)."""
    require_auth(request)
    from .models import Lead
    from sqlalchemy import select, func
    if not body.ids:
        return {'existing': 0}
    ids = list(dict.fromkeys(body.ids))[:50000]
    user, _, _ = user_scope(request, db)
    n = sum(_lead_in_scope(l, user) for l in db.scalars(select(Lead).where(Lead.id.in_(ids))))
    return {'existing': n, 'submitted': len(body.ids)}


class DeletePreviewBody(BaseModel):
    ids: list[int]


@app.post('/api/leads/delete-preview')
def delete_preview(body: DeletePreviewBody, request: Request, db=Depends(get_db)):
    """Exact preview before a bulk delete: what exists, what vanished,
    per-campaign spread, and what associated data goes with it."""
    require_auth(request)
    from .models import Lead, ReplyComment, LeadEvent
    from sqlalchemy import select, func
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise HTTPException(422, 'ids required')
    user, _, _ = user_scope(request, db)
    rows = [(l.id, l.campaign_id) for l in db.scalars(select(Lead).where(Lead.id.in_(ids))) if _lead_in_scope(l, user)]
    existing_ids = [r[0] for r in rows]
    campaigns = {}
    for _lid, cid in rows:
        campaigns[cid] = campaigns.get(cid, 0) + 1
    campaign_names = {}
    if rows:
        from .models import Campaign
        for cid, key, name in db.execute(select(Campaign.id, Campaign.campaign_key, Campaign.name).where(Campaign.id.in_([c for c in campaigns if c]))).all():
            campaign_names[cid] = name or key
    n_comments = db.scalar(select(func.count(ReplyComment.id)).where(ReplyComment.lead_id.in_(existing_ids))) or 0 if existing_ids else 0
    n_events = db.scalar(select(func.count(LeadEvent.id)).where(LeadEvent.lead_id.in_(existing_ids))) or 0 if existing_ids else 0
    return {
        'submitted': len(ids),
        'existing': len(existing_ids),
        'missing': len(ids) - len(existing_ids),
        'campaigns': [{'campaign': campaign_names.get(cid) or 'Untagged', 'count': n} for cid, n in sorted(campaigns.items(), key=lambda x: -x[1])],
        'comments_to_remove': n_comments,
        'events_to_remove': n_events,
        'logs_kept': True,
    }


class DeleteBody(BaseModel):
    ids: list[int]


@app.post('/api/leads/bulk-delete-v2')
def bulk_delete_v2(body: DeleteBody, request: Request, db=Depends(get_db)):
    from . import runner
    require_auth(request)
    with runner.idle_lease() as acquired:
        if not acquired:
            raise HTTPException(409, 'A worker is running — deletion is blocked until it finishes.')
        return _delete_selected_leads(body, request, db)


def _delete_selected_leads(body, request, db):
    """Transactional bulk delete with a running-job guard and audit record."""
    require_auth(request)
    from . import runner
    from sqlalchemy import select as _sel
    from .models import Lead, DeletionAudit
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise HTTPException(422, 'ids required')
    # Scope: restricted users may only delete their own leads (silently skip
    # out-of-scope ids instead of leaking which exist).
    _duser, _dcamps, _daccts = user_scope(request, db)
    if _dcamps is not None or _daccts is not None:
        found = db.execute(_sel(Lead).where(Lead.id.in_(ids))).scalars().all()
        ids = [l.id for l in found if _lead_in_scope(l, _duser)]
        if not ids:
            raise HTTPException(403, 'No accessible leads in selection')
    deleted = db.query(Lead).filter(Lead.id.in_(ids)).delete(synchronize_session=False)
    db.add(DeletionAudit(deleted_count=deleted, skipped_count=len(ids) - deleted,
                         details={'submitted': len(ids), 'source': 'web_bulk_delete'}))
    db.commit()
    return {'ok': True, 'deleted': deleted, 'skipped': len(ids) - deleted}


@app.get('/api/leads/import-csv', include_in_schema=False)
def import_leads_csv_get_guard():
    raise HTTPException(405, 'Use POST')


@app.post('/api/leads/import-csv')
def import_leads_csv(request: Request, file: 'UploadFile', db=Depends(get_db),
                     campaign_id: int | None = None):
    """Bulk-import leads from CSV. Required header: full_name (or first_name+last_name).
    Optional: title, company, location, sales_nav_id, linkedin_url, opentomsg.
    Leads arrive untouched/untagged unless campaign_id is passed."""
    from .models import Lead, Campaign
    user, _campaign_scope, _account_scope = user_scope(request, db)
    # CSV creates unassigned leads. Match the same scope rules used when
    # listing leads, including the untagged/unassigned operations pool.
    if not _lead_in_scope(Lead(campaign_id=campaign_id, associate_account_id=None), user):
        raise HTTPException(403, 'You do not have access to import unassigned leads into this campaign or pool')
    import csv as _csv
    import io

    if campaign_id and db.get(Campaign, campaign_id) is None:
        raise HTTPException(404, 'Campaign not found')

    raw = file.file.read()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('latin-1', errors='replace')
    reader = _csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(422, 'CSV file has no header row')
    fields = {f.strip().lower(): f for f in reader.fieldnames}
    if 'full_name' not in fields and 'first_name' not in fields:
        raise HTTPException(422, "CSV must include a 'full_name' (or 'first_name') column")

    def cell(row, name):
        col = fields.get(name)
        return (row.get(col) or '').strip() if col else ''

    from .linkedin import extract_profile_id

    def norm_snid(v: str) -> str:
        """Bare profile token out of any id format, matching how jobs store ids
        (urn:li:fs_salesProfile:(ACwX,NAME_SEARCH,z) -> ACwX; the extract also
        accepts the ACo flagship tokens that CSV exports carry)."""
        return extract_profile_id(v) or v.strip()

    def norm_url(u: str) -> str:
        return u.strip().lower().split('?')[0].rstrip('/')

    added = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(reader, start=2):
        full = cell(row, 'full_name') or f"{cell(row, 'first_name')} {cell(row, 'last_name')}".strip()
        if not full:
            skipped += 1
            errors.append(f'row {i}: missing name')
            continue
        open_value = cell(row, 'opentomsg').lower()
        open_values = {'true': True, 'yes': True, '1': True,
                       'false': False, 'no': False, '0': False,
                       '': None, 'unknown': None, 'unchecked': None, 'null': None}
        if open_value not in open_values:
            skipped += 1
            errors.append(f'row {i}: opentomsg must be true, false or unknown')
            continue
        open_flag = open_values[open_value]
        snid = norm_snid(cell(row, 'sales_nav_id'))
        # The exact decorated URN ('urn:li:fs_salesProfile:(ACo…,NAME_SEARCH,…)')
        # is stored verbatim for API parity with the xlsx exports. It may arrive
        # in the sales_nav_id cell itself (legacy sheets format) or in the
        # dedicated sales_nav_urn column (CSV exports) — take whichever is set.
        raw_snid_cell = cell(row, 'sales_nav_id')
        urn = raw_snid_cell if str(raw_snid_cell).startswith('urn:li:fs_salesProfile:') else cell(row, 'sales_nav_urn')
        if urn and not urn.startswith('urn:li:fs_salesProfile:'):
            urn = ''
        url = cell(row, 'linkedin_url')
        # Identity is Sales Nav ID + destination campaign (None is the pool).
        # Another campaign must never suppress or be changed by this import.
        dup = None
        if snid:
            dup = db.execute(
                select(Lead).where(Lead.sales_nav_id == snid, Lead.campaign_id == campaign_id).order_by(Lead.id).limit(1)
            ).scalar_one_or_none()
        if dup is None and url:
            # URL fallback stays within this destination and never overrides
            # two distinct Sales Nav IDs.
            candidates = db.execute(
                select(Lead).where(Lead.linkedin_url != '', Lead.campaign_id == campaign_id).order_by(Lead.id)
            ).scalars().all()
            for cand in candidates:
                if (not snid or not cand.sales_nav_id) and norm_url(cand.linkedin_url or '') == norm_url(url):
                    dup = cand
                    break
        if dup:
            if not _lead_in_scope(dup, user):
                skipped += 1
                continue
            # Gap-fill known fields on duplicates: never overwrite a
            # non-empty stored value, only fill what's missing.
            if url and not dup.linkedin_url:
                dup.linkedin_url = url
            if snid and not dup.sales_nav_id:
                dup.sales_nav_id = snid
            if urn and not (dup.sales_nav_urn or ''):
                dup.sales_nav_urn = urn
            if dup.opentomsg is None and open_flag is not None:
                dup.opentomsg = open_flag
            for attr in ('title', 'company', 'location'):
                v = cell(row, attr)
                if v and not getattr(dup, attr):
                    setattr(dup, attr, v)
            skipped += 1
            continue
        db.add(Lead(
            sales_nav_id=snid, sales_nav_urn=urn, full_name=full,
            first_name=cell(row, 'first_name'), last_name=cell(row, 'last_name'),
            title=cell(row, 'title'), company=cell(row, 'company'),
            location=cell(row, 'location'), linkedin_url=url, opentomsg=open_flag,
            source='list_import', campaign_id=campaign_id,
        ))
        added += 1
    db.commit()
    return {'ok': True, 'added': added, 'skipped': skipped, 'errors': errors[:20]}


@app.put('/api/leads/{lead_id}/assign')
def assign_lead(lead_id: int, body: AssignBody, request: Request, db=Depends(get_db)):
    """Manual campaign assignment for untagged list-import leads."""
    require_auth(request)
    from .models import Lead, Campaign
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, 'Lead not found')
    user = _require_lead_access(lead, request, db)
    _require_in_scope(user, campaign_id=body.campaign_id)
    if lead.sales_nav_id:
        duplicate = db.scalar(select(Lead.id).where(
            Lead.sales_nav_id == lead.sales_nav_id,
            Lead.campaign_id == body.campaign_id, Lead.id != lead.id).limit(1))
        if duplicate is not None:
            destination = 'selected campaign' if body.campaign_id is not None else 'untagged pool'
            raise HTTPException(409, f'This Sales Nav ID already exists in the {destination}. Existing leads and history were kept unchanged.')
    if body.campaign_id is None:
        lead.campaign_id = None
        lead.source = 'list_import'
    else:
        campaign = db.get(Campaign, body.campaign_id)
        if not campaign:
            raise HTTPException(404, 'Campaign not found')
        if lead.associate_account_id is not None:
            from .jobs import validate_import_assignment
            try:
                validate_import_assignment(db, lead.associate_account_id, campaign.id)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        lead.campaign_id = campaign.id
        lead.source = 'campaign_search'
        lead.list_id = None
        _add_event(db, lead.id, 'assignment', f"Manually assigned to {campaign.campaign_key}", None)
    db.commit()
    return {'ok': True}


class ResetErrorBody(BaseModel):
    ids: list[int]


@app.post('/api/leads/reset-errors')
def reset_lead_errors(body: ResetErrorBody, request: Request, db=Depends(get_db)):
    """Clear send errors and restore the stage and age from before the failure."""
    require_auth(request)
    from . import runner
    from .models import Lead
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise HTTPException(422, 'ids required')
    with runner.idle_lease() as acquired:
        if not acquired:
            raise HTTPException(409, 'A worker is running - retry is blocked until it finishes.')
        user, _camps, _accts = user_scope(request, db)
        found = db.execute(select(Lead).where(Lead.id.in_(ids))).scalars().all()
        if _camps is not None or _accts is not None:
            found = [l for l in found if _lead_in_scope(l, user)]
            if not found:
                raise HTTPException(403, 'No accessible leads in selection')
        changed = 0
        for lead in found:
            if lead.status == 'BLOCKED_ERROR' or lead.last_error:
                from .operations import restore_error_stage
                restore_error_stage(db, lead)
                changed += 1
        db.commit()
        return {'ok': True, 'reset': changed, 'skipped': len(found) - changed}


# ---------------------------------------------------------------------------
# Threads & Replies
# ---------------------------------------------------------------------------

@app.get('/api/threads')
def threads(request: Request, db=Depends(get_db),
            channel: str = 'all', q: str | None = None,
            campaign_ids: str | None = None, account_ids: str | None = None,
            category: str | None = None, review: str | None = None,
            comments: str | None = None,
            replied_from: str | None = None, replied_to: str | None = None,
            sort: str = 'newest', page: int = 1, page_size: int = 25):
    """Reply inbox backed by leads.received_replies / reply_message.

    Filters combine server-side (campaigns × accounts × category × review ×
    comments × date range × search). Sorting is allow-listed; anything unknown
    falls back to newest.
    """
    require_auth(request)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    from sqlalchemy import select, func, or_
    from .models import Lead, ReplyComment

    stmt = select(Lead).where(Lead.received_replies.is_(True))
    # Access scope: restricted users see ONLY replies on their own leads.
    _tuser, _camps, _accts = user_scope(request, db)
    _thread_scope = _lead_scope_conditions(_camps, _accts)
    if _thread_scope is not None:
        stmt = stmt.where(_thread_scope)
    if q:
        like = f'%{q}%'
        stmt = stmt.where(or_(Lead.full_name.ilike(like), Lead.reply_message.ilike(like), Lead.company.ilike(like)))
    if channel == 'booked':
        stmt = stmt.where(or_(
            Lead.reply_message.ilike('%book%'),
            Lead.reply_message.ilike('%calendly%'),
            Lead.reply_message.ilike('%calendar%'),
        ))

    def id_list(raw: str | None):
        if not raw:
            return []
        return [int(x) for x in raw.split(',') if x.strip().isdigit()]

    cids = id_list(campaign_ids)
    if cids:
        stmt = stmt.where(Lead.campaign_id.in_(cids))
    aids = id_list(account_ids)
    if aids:
        stmt = stmt.where(Lead.associate_account_id.in_(aids))
    if category:
        stmt = stmt.where(Lead.reply_category == category)
    if review == 'needs_review':
        stmt = stmt.where(Lead.review_status == 'needs_review')
    elif review == 'reviewed':
        stmt = stmt.where(Lead.review_status == 'reviewed')
    elif review == 'unreviewed':
        stmt = stmt.where(Lead.review_status != 'reviewed')
    if comments == 'with':
        stmt = stmt.where(Lead.id.in_(select(ReplyComment.lead_id)))
    elif comments == 'without':
        stmt = stmt.where(Lead.id.not_in(select(ReplyComment.lead_id)))

    def parse_day(raw: str | None, end: bool = False):
        if not raw:
            return None
        try:
            d = datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            return None
        return datetime.combine(d, datetime.max.time() if end else datetime.min.time())

    r_from = parse_day(replied_from)
    r_to = parse_day(replied_to, end=True)
    if r_from:
        stmt = stmt.where(Lead.reply_received_at >= r_from)
    if r_to:
        stmt = stmt.where(Lead.reply_received_at <= r_to)

    SORTS = {
        'newest': (Lead.reply_received_at.desc().nullslast(), Lead.id.desc()),
        'oldest': (Lead.reply_received_at.asc().nullsfirst(), Lead.id.asc()),
        'lead_name': (Lead.full_name.asc(), Lead.id.asc()),
        'lead_name_desc': (Lead.full_name.desc(), Lead.id.desc()),
        'campaign': (Lead.campaign_id.asc().nullslast(), Lead.id.asc()),
        'campaign_desc': (Lead.campaign_id.desc().nullsfirst(), Lead.id.desc()),
        'account': (Lead.associate_account_id.asc().nullslast(), Lead.id.asc()),
        'account_desc': (Lead.associate_account_id.desc().nullsfirst(), Lead.id.desc()),
        'reviewed': (Lead.reply_reviewed_at.desc().nullslast(), Lead.id.desc()),
    }
    order = SORTS.get(sort, SORTS['newest'])

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()

    # One grouped comment count for the page (no N+1).
    comment_counts = {}
    if rows:
        c_rows = db.execute(
            select(ReplyComment.lead_id, func.count(ReplyComment.id))
            .where(ReplyComment.lead_id.in_([l.id for l in rows]))
            .group_by(ReplyComment.lead_id)
        ).all()
        comment_counts = {lid: n for lid, n in c_rows}

    items = [{
        'id': l.id,
        'full_name': l.full_name or f"{l.first_name} {l.last_name}".strip(),
        'title': l.title, 'company': l.company,
        'campaign': l.campaign.campaign_key if l.campaign else None,
        'campaign_id': l.campaign_id,
        # Live name so a campaign rename shows in the reply inbox immediately.
        'campaign_name': l.campaign.name if l.campaign else None,
        'account': l.associate_account.name if l.associate_account else None,
        'account_id': l.associate_account_id,
        'reply_message': l.reply_message,
        'reply_received_at': l.reply_received_at.isoformat() if l.reply_received_at else None,
        'status': l.status,
        'reply_category': l.reply_category or 'unclassified',
        'reply_category_source': l.reply_category_source or ('auto' if l.reply_category else ''),
        'review_status': l.review_status or '',
        'reply_reviewed_at': l.reply_reviewed_at.isoformat() if l.reply_reviewed_at else None,
        'linkedin_url': l.linkedin_url or '',
        'comment_count': comment_counts.get(l.id, 0),
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
    from . import schedule_store
    schedule = schedule_store.listing()
    from sqlalchemy import select
    from .models import RunLog
    db = SessionLocal()
    try:
        _juser, _jcamps, _jaccts = user_scope(request, db)
        visible_live = runner.live_statuses(_juser.id, _juser.role == 'admin')
        last_runs = {}
        for r in db.execute(_run_scope_filter(
                select(RunLog), _jcamps, _jaccts, user=_juser).order_by(RunLog.id.desc()).limit(200)).scalars().all():
            if r.job_type not in last_runs:
                last_runs[r.job_type] = {
                    'id': r.id, 'status': r.status, 'started_at': r.started_at.isoformat() if r.started_at else None,
                    'duration_s': r.duration_s, 'dry_run': r.dry_run,
                }
        from .models import JobType
        jobs = []
        descriptions = {
            'sync_leads': 'Manual only: select an account and enter a numeric saved search ID. Leads arrive untagged for assignment.',
            'import_list': 'Manual one-off: import a Sales Navigator list by numeric ID. Leads arrive untagged.',
            'send_connections': 'Assigns untouched leads to accounts by budget order, then sends InMails or connection invites.',
            'check_replies': 'Detects invite accepts (sends the after-accept message) and new replies; flags leads and emails the digest.',
            'send_followups': 'Runs the +3/+5/+7-day follow-up sequences for both invite and InMail tracks.',
        }
        for key in JobType:
            jobs.append({
                'key': key.value,
                'schedule': [f"{s['name']}: {', '.join(s['days_of_week']) or 'Every day'} {s['run_time']} {s['timezone']}" for s in schedule if key.value in s['job_keys'] and s['active']],
                'last_run': last_runs.get(key.value),
                'running_now': any(live.get('job') == key.value for live in visible_live),
                'description': descriptions.get(key.value, ''),
            })
        # Nav badge counts (sidebar) - cheap aggregates
        from sqlalchemy import func
        from .models import Lead, Campaign, Account
        acct_q = select(func.count(Account.id)).where(Account.status == 'active')
        camp_q = select(func.count(Campaign.id)).where(Campaign.status == 'active')
        unread_q = select(func.count(Lead.id)).where(
            Lead.received_replies.is_(True),
            Lead.reply_received_at >= datetime.utcnow() - timedelta(days=7),
        )
        if _jaccts is not None:
            acct_q = acct_q.where(Account.id.in_(_jaccts))
        if _jcamps is not None:
            camp_q = camp_q.where(Campaign.id.in_(_jcamps))
        _unread_scope = _lead_scope_conditions(_jcamps, _jaccts)
        if _unread_scope is not None:
            unread_q = unread_q.where(_unread_scope)
        accounts_active = db.scalar(acct_q) or 0
        campaigns_active = db.scalar(camp_q) or 0
        unread = db.scalar(unread_q) or 0
        return {
            'jobs': jobs,
            'live': {**runner.live_status(_juser.id, _juser.role == 'admin'),
                     'account_runs': runner.live_account_runs(_juser.id, _juser.role == 'admin')},
            'running': visible_live,
            'scheduler_running': scheduler._scheduler is not None and scheduler._scheduler.running,
            'nav': {
                'accounts_active': accounts_active,
                'campaigns_active': campaigns_active,
                'unread_replies': unread,
                'scheduler_healthy': scheduler._scheduler is not None and scheduler._scheduler.running,
            },
        }
    finally:
        db.close()


class JobStart(BaseModel):
    dry_run: bool = False
    outreach_account_id: int | None = None  # optional sender, independent of the import account
    campaign_ids: list[int] | None = None
    account_ids: list[int] | None = None
    account_id: int | None = None     # import_list + sync_leads (targeted)
    list_id: str | None = None        # import_list
    saved_search_id: str | None = None  # sync_leads
    campaign_id: int | None = None    # sync_leads (optional tagging)


def _prepare_job(job_key: str, body: JobStart, request: Request):
    require_auth(request)
    from . import runner
    from .jobs import JOB_REGISTRY
    if job_key not in JOB_REGISTRY:
        raise HTTPException(404, 'Unknown job')
    # Access scope: a restricted user can only run within their campaigns/accounts.
    from .database import SessionLocal as _SL
    with _SL() as _db:
        _ruser, _rcamps, _raccts = user_scope(request, _db)
    _require_in_scope(_ruser, campaign_id=body.campaign_id,
                      campaign_ids=body.campaign_ids, account_ids=body.account_ids)
    if body.account_id is not None:
        _require_in_scope(_ruser, account_id=body.account_id)
    if body.outreach_account_id is not None:
        _require_in_scope(_ruser, account_id=body.outreach_account_id)
    if job_key not in ('sync_leads', 'import_list'):
        body = body.model_copy(update={'campaign_ids': body.campaign_ids if body.campaign_ids is not None else _rcamps})
    kwargs = {}
    if job_key == 'sync_leads':
        if not body.account_id or not body.saved_search_id or not body.saved_search_id.isascii() or not body.saved_search_id.isdigit():
            raise HTTPException(422, 'Sync requires an account and numeric Search ID')
        if body.campaign_ids or body.list_id or body.account_ids:
            raise HTTPException(422, 'Manual sync accepts one account, a Search ID and an optional campaign tag')
        from .models import Account, Campaign
        with SessionLocal() as db:
            account = db.get(Account, body.account_id)
            if not account or account.status != 'active':
                raise HTTPException(422, 'Choose an active account')
            if body.campaign_id is not None and not db.get(Campaign, body.campaign_id):
                raise HTTPException(422, 'Selected campaign not found')
        kwargs = {'account_id': body.account_id, 'saved_search_id': body.saved_search_id}
        if body.campaign_id is not None:
            kwargs['campaign_id'] = body.campaign_id
    elif job_key == 'import_list':
        if not body.account_id or not body.list_id or not body.list_id.isascii() or not body.list_id.isdigit():
            raise HTTPException(422, 'Import requires an account and numeric List ID')
        if body.campaign_ids or body.saved_search_id or body.account_ids:
            raise HTTPException(422, 'List import accepts one account, a List ID and an optional campaign tag')
        from .models import Account, Campaign
        with SessionLocal() as db:
            account = db.get(Account, body.account_id)
            if not account or account.status != 'active':
                raise HTTPException(422, 'Choose an active account')
            if body.campaign_id is not None and not db.get(Campaign, body.campaign_id):
                raise HTTPException(422, 'Selected campaign not found')
        kwargs = {'account_id': body.account_id, 'list_id': body.list_id}
        if body.campaign_id is not None:
            kwargs['campaign_id'] = body.campaign_id
    else:
        if body.account_id or body.list_id or body.saved_search_id or body.campaign_id or body.outreach_account_id is not None:
            raise HTTPException(422, 'Use campaign configuration for batch jobs; list import is separate')
        from .schedule_store import validate_scope
        with SessionLocal() as db:
            try:
                validate_scope({'campaign_ids': body.campaign_ids, 'account_ids': body.account_ids}, db)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
            if body.account_ids is None:
                # 'All mapped' is the intersection of campaign mappings and
                # user grants, not every account the user can access.
                from .models import Account, Campaign, CampaignAccount
                mapped = select(CampaignAccount.account_id).join(Campaign).join(Account).where(
                    Campaign.status == 'active', Account.status == 'active')
                if body.campaign_ids is not None:
                    mapped = mapped.where(CampaignAccount.campaign_id.in_(body.campaign_ids))
                if _raccts is not None:
                    mapped = mapped.where(CampaignAccount.account_id.in_(_raccts))
                account_ids = sorted(set(db.scalars(mapped)))
                if not account_ids:
                    raise HTTPException(422, 'No active mapped accounts are available within your access for the selected campaigns.')
                body = body.model_copy(update={'account_ids': account_ids})
            if body.account_ids:
                from .models import Account
                inactive = db.query(Account).filter(Account.id.in_(body.account_ids), Account.status != 'active').all()
                if inactive:
                    names = ', '.join(a.name for a in inactive)
                    raise HTTPException(422, f'Cannot run inactive account(s): {names}')
        if body.campaign_ids is not None:
            kwargs['campaign_ids'] = body.campaign_ids
        if body.account_ids is not None:
            kwargs['account_ids'] = body.account_ids
    if job_key in ('sync_leads', 'import_list'):
        from .jobs import validate_import_assignment
        with SessionLocal() as db:
            try:
                validate_import_assignment(db, body.outreach_account_id, body.campaign_id, require_active=True)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        kwargs['outreach_account_id'] = body.outreach_account_id

    # --- Session pre-check: verify session files are loadable for accounts ---
    # that would actually be used by this job run. Warns on partial failure,
    # blocks on total failure so the user knows before the job starts.
    session_warnings = []
    if not body.dry_run:
        if job_key not in ('sync_leads', 'import_list'):
            from .models import Account, CampaignAccount
            from .jobs import load_session_ref
            with SessionLocal() as db:
                # Determine which accounts would run
                if body.account_ids:
                    candidate_ids = set(body.account_ids)
                elif body.campaign_ids:
                    links = db.query(CampaignAccount).filter(
                        CampaignAccount.campaign_id.in_(body.campaign_ids)
                    ).all()
                    candidate_ids = {l.account_id for l in links}
                else:
                    # All active accounts
                    candidate_ids = {a.id for a in db.query(Account).filter_by(status='active').all()}
                active_accounts = db.query(Account).filter(
                    Account.id.in_(candidate_ids), Account.status == 'active'
                ).all()
                failed_sessions = []
                ok_count = 0
                for acc in active_accounts:
                    try:
                        load_session_ref(acc)
                        ok_count += 1
                    except Exception as exc:
                        failed_sessions.append(f'{acc.name}: {exc}')
                if failed_sessions:
                    if ok_count == 0:
                        raise HTTPException(
                            422,
                            'No valid session files found for any account. '
                            'Upload cookies files first, then verify sessions.\n' +
                            '\n'.join(failed_sessions)
                        )
                    session_warnings = [f'Session not found for {e}' for e in failed_sessions]
        elif job_key in ('sync_leads', 'import_list') and body.account_id:
            from .models import Account
            from .jobs import load_session_ref
            with SessionLocal() as db:
                acc = db.get(Account, body.account_id)
                if acc:
                    try:
                        load_session_ref(acc)
                    except Exception as exc:
                        raise HTTPException(422, f'Session error for {acc.name}: {exc}. Upload a cookies file first.')

    return kwargs, session_warnings


@app.post('/api/jobs/{job_key}/run')
def run_job(job_key: str, body: JobStart, request: Request):
    from . import runner
    kwargs, session_warnings = _prepare_job(job_key, body, request)
    ok, message, execution_id = runner.start_job(job_key, dry_run=body.dry_run,
                                                       owner_user_id=current_user(request).id, **kwargs)
    if not ok:
        raise HTTPException(409, message)
    return {'ok': True, 'message': message, 'warnings': session_warnings, 'execution_id': execution_id}


class BatchStart(BaseModel):
    connections: bool = True
    followups: bool = False
    campaign_ids: list[int]
    dry_run: bool = False


@app.post('/api/jobs/batch')
def run_batch(body: BatchStart, request: Request):
    from . import runner
    if not body.campaign_ids or not (body.connections or body.followups):
        raise HTTPException(422, 'Select campaigns and at least one worker')
    steps, warnings = [], []
    for key, enabled in [('send_connections', body.connections), ('send_followups', body.followups)]:
        if enabled:
            scope, notices = _prepare_job(key, JobStart(campaign_ids=body.campaign_ids, dry_run=body.dry_run), request)
            steps.append((key, scope))
            warnings.extend(notices)
    ok, message, execution_id = runner.start_sequence(steps, dry_run=body.dry_run,
                                                            owner_user_id=current_user(request).id)
    if not ok:
        raise HTTPException(409, message)
    return {'ok': True, 'message': message, 'warnings': list(dict.fromkeys(warnings)), 'execution_id': execution_id}


class StopRequest(BaseModel):
    run_id: int | None = None
    execution_id: str | None = None


@app.post('/api/jobs/stop')
def stop_job(request: Request, body: StopRequest | None = None):
    require_auth(request)
    from . import runner
    with SessionLocal() as db:
        user, _, _ = user_scope(request, db)
        ok, message = runner.stop_job(body.run_id if body else None,
                                      execution_id=body.execution_id if body else None,
                                      owner_user_id=user.id, admin=user.role == 'admin')
    if not ok:
        raise HTTPException(400, message)
    return {'ok': True, 'message': message}


@app.get('/api/runs')
def list_runs(request: Request, job: str | None = None, status: str | None = None,
              dry_run: bool | None = None, since_days: int | None = None,
              limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
              paginated: bool = False):
    require_auth(request)
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from .models import RunLog
    db = SessionLocal()
    try:
        stmt = select(RunLog).order_by(RunLog.id.desc())
        if job:
            stmt = stmt.where(RunLog.job_type == job)
        if status:
            stmt = stmt.where(RunLog.status == status)
        if dry_run is not None:
            stmt = stmt.where(RunLog.dry_run.is_(dry_run))
        if since_days and since_days > 0:
            stmt = stmt.where(RunLog.started_at >= datetime.now(timezone.utc) - timedelta(days=since_days))
        # Execution ownership is independent of campaign access.
        _ruser, _rcamps, _raccts = user_scope(request, db)
        stmt = _run_scope_filter(stmt, _rcamps, _raccts, user=_ruser)
        from sqlalchemy import func
        total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) if paginated else None
        stmt = stmt.offset(offset).limit(limit)
        rows = db.execute(stmt).scalars().all()
        from .runner import status_for
        items = [{
            'id': r.id, 'job': r.job_type, 'target': r.target, 'dry_run': r.dry_run, 'schedule_id': r.schedule_id,
            'status': status_for(r.id, r.status), 'started_at': r.started_at.isoformat() if r.started_at else None,
            'finished_at': r.finished_at.isoformat() if r.finished_at else None,
            'duration_s': r.duration_s, 'stats': r.stats, 'errors': r.errors,
        } for r in rows]
        return {'items': items, 'total': total} if paginated else items
    finally:
        db.close()


@app.get('/api/runs/{run_id}/log')
def run_log(run_id: int, request: Request):
    require_auth(request)
    from sqlalchemy import select
    from .models import RunLog
    db = SessionLocal()
    try:
        r = db.get(RunLog, run_id)
        if not r:
            raise HTTPException(404, 'Run not found')
        # Enforce ownership even for users with unrestricted campaign access.
        _luser, _lcamps, _laccts = user_scope(request, db)
        if db.execute(_run_scope_filter(
                select(RunLog).where(RunLog.id == run_id), _lcamps, _laccts, user=_luser)
        ).scalars().first() is None:
            raise HTTPException(404, 'Run not found')
        from .runner import log_tail, status_for
        tail = log_tail(r.id) if r.status == 'running' else None
        batch_runs = []
        if r.execution_id:
            batch_rows = db.execute(
                _run_scope_filter(select(RunLog).where(RunLog.execution_id == r.execution_id).order_by(RunLog.id), _lcamps, _laccts, user=_luser)
            ).scalars().all()
            if len(batch_rows) > 1:
                batch_runs = [{
                    'id': b.id, 'job': b.job_type, 'status': status_for(b.id, b.status),
                    'duration_s': b.duration_s, 'stats': b.stats, 'errors': b.errors,
                    'dry_run': b.dry_run, 'target': b.target
                } for b in batch_rows]
        return {'id': r.id, 'status': status_for(r.id, r.status), 'log_text': tail if tail is not None else r.log_text or '',
                'stats': r.stats, 'errors': r.errors, 'job': r.job_type, 'target': r.target,
                'dry_run': r.dry_run, 'duration_s': r.duration_s,
                'started_at': r.started_at.isoformat() if r.started_at else None,
                'finished_at': r.finished_at.isoformat() if r.finished_at else None,
                'execution_id': r.execution_id, 'batch_runs': batch_runs}
    finally:
        db.close()


def _live_log_snapshot(after=0, previous_run_id=None, request=None, execution_id=None):
    """One selected execution plus the caller's visible active-run list."""
    from . import runner
    from .models import RunLog
    with SessionLocal() as db:
        user, _, _ = user_scope(request, db)
        admin = user.role == 'admin'
        active_runs = runner.live_statuses(user.id, admin)
        live = runner.live_status(user.id, admin, execution_id)
        visible = _run_scope_filter(select(RunLog), user=user)
        row = None
        if live.get('run_id'):
            row = db.execute(visible.where(RunLog.id == live['run_id'])).scalar_one_or_none()
        if row is None and execution_id:
            row = db.execute(visible.where(RunLog.execution_id == execution_id)
                             .order_by(RunLog.id.desc()).limit(1)).scalar_one_or_none()
            if row is None and not live.get('running'):
                raise HTTPException(404, 'Run not found')
        if row is None and not live.get('running') and not execution_id:
            row = db.execute(visible.order_by(RunLog.id.desc()).limit(1)).scalar_one_or_none()
        common = {'running': active_runs, 'running_count': len(active_runs),
                  'execution_id': live.get('execution_id') or (row.execution_id if row else None)}
        if row is None:
            return {**common, 'active': bool(live.get('running')), 'run_id': None,
                    'status': live.get('status', 'idle'), 'job': live.get('job'),
                    'target': live.get('target', ''), 'started_at': live.get('started_at'),
                    'lines': [], 'seq': 0, 'total_lines': 0, 'log_text': '', 'reset': True}
        tail = runner.log_tail(row.id) if row.status == 'running' else None
        text = tail if tail is not None else row.log_text or ''
        lines = text.splitlines()
        reset = previous_run_id != row.id or after > len(lines)
        start = 0 if reset else max(0, after)
        return {**common, 'execution_id': row.execution_id, 'active': row.status == 'running', 'run_id': row.id,
                'job': row.job_type, 'target': row.target, 'dry_run': row.dry_run,
                'started_at': row.started_at.isoformat() if row.started_at else None,
                'status': runner.status_for(row.id, row.status),
                'progress': live.get('progress', {}) if live.get('run_id') == row.id else row.stats or {},
                'errors': row.errors or ([live['error']] if live.get('run_id') == row.id and live.get('error') else []),
                'batch_status': live.get('status') if live.get('run_id') == row.id and len(live.get('batch_jobs', [])) > 1 else None,
                'batch_jobs': live.get('batch_jobs', []) if live.get('run_id') == row.id else [],
                'duration_s': row.duration_s, 'seq': len(lines), 'total_lines': len(lines),
                'lines': lines[start:][-200:], 'log_text': text, 'reset': reset,
                'finished': row.status != 'running'}


@app.get('/api/runs/live')
def live_run_log(request: Request, after: int = Query(0, ge=0), run_id: int | None = None, execution_id: str | None = None):
    require_auth(request)
    return _live_log_snapshot(after, run_id, request, execution_id)


@app.get('/api/runs/live/stream')
def live_run_stream(request: Request, after: int = Query(0, ge=0), run_id: int | None = None, execution_id: str | None = None):
    require_auth(request)
    _live_log_snapshot(after, run_id, request, execution_id)  # authorize before starting the response
    import asyncio
    import json as _json
    from starlette.concurrency import run_in_threadpool
    from fastapi.responses import StreamingResponse

    async def gen():
        seq, previous_id, idle_ticks = after, run_id, 0
        while idle_ticks < 30:
            if await request.is_disconnected():
                break
            try:
                payload = await run_in_threadpool(_live_log_snapshot, seq, previous_id, request, execution_id)
            except HTTPException:
                break  # revoked/expired access must stop an existing stream too
            seq, previous_id = payload['seq'], payload['run_id']
            idle_ticks = 0 if payload['active'] else idle_ticks + 1
            yield f"data: {_json.dumps(payload)}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(gen(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})



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
    if not body.gchat_webhook_url.startswith('•'):
        s.gchat_webhook_url = body.gchat_webhook_url.strip()
    s.email_recipients = [r.strip() for r in body.email_recipients if r.strip()]
    s.alert_critical = body.alert_critical
    s.alert_run_summary = body.alert_run_summary
    s.alert_send_errors = body.alert_send_errors
    s.alert_reply_digest = body.alert_reply_digest
    db.commit()
    return {'ok': True}


class FuDelaysIn(BaseModel):
    invite: list[int] = Field(default_factory=lambda: [3, 5, 7])
    inmail: list[int] = Field(default_factory=lambda: [3, 5, 7])


def _norm_fu(vals: list[int]) -> list[int]:
    out = [max(0, min(60, int(v))) for v in (list(vals) + [0, 0, 0])[:3]]
    while len(out) < 3:
        out.append(out[-1] if out else 0)
    return out


@app.get('/api/settings/fu-delays')
def get_fu_delays(request: Request):
    require_auth(request)
    from . import jobs as jobs_mod
    return {
        'invite': [s[1] for s in jobs_mod.INVITE_STAGES],
        'inmail': [s[1] for s in jobs_mod.INMAIL_STAGES],
    }


@app.put('/api/settings/fu-delays')
def put_fu_delays(body: FuDelaysIn, request: Request):
    """Persist per-stage follow-up delays. jobs.py re-reads these before each
    run, so changes apply to the next Send follow-ups run without a deploy."""
    require_auth(request)
    import os as _os
    from .models import Setting
    from .database import SessionLocal
    db = SessionLocal()
    try:
        invite = _norm_fu(body.invite)
        inmail = _norm_fu(body.inmail)
        for key, days in (('OCC_INVITE_FU_DAYS', invite), ('OCC_INMAIL_FU_DAYS', inmail)):
            row = db.get(Setting, key)
            if row is None:
                row = Setting(key=key)
                db.add(row)
            row.value_json = ','.join(str(d) for d in days)
            db.commit()
            _os.environ[key] = row.value_json
        from . import jobs as jobs_mod
        jobs_mod.reload_fu_days()
        return {'ok': True, 'invite': invite, 'inmail': inmail}
    finally:
        db.close()


@app.post('/api/settings/test-webhook')
def test_webhook(request: Request):
    require_auth(request)
    from .notify import send_gchat
    from notification_format import message
    ok = send_gchat(message('Connection test', 'info', 'Google Chat notification delivery test'))
    return {'ok': ok}


@app.get('/api/settings/schedule')
def get_schedule(request: Request):
    """Legacy endpoint — retired. Use /api/schedules for schedule management."""
    require_auth(request)
    return JSONResponse(
        status_code=200,
        content={
            'deprecated': True,
            'message': 'Scheduling has moved to /api/schedules. This endpoint will be removed in a future release.',
        }
    )


class ScheduleIn(BaseModel):
    schedule: list[dict]


def CronTriggerProxy(**kw):
    from apscheduler.triggers.cron import CronTrigger
    return CronTrigger(**kw)


@app.put('/api/settings/schedule')
def put_schedule(body: ScheduleIn, request: Request):
    require_auth(request)
    raise HTTPException(410, 'Scheduling has moved to /api/schedules. This route is retired.')


@app.get('/api/schedules')
def list_schedule_rows(request: Request):
    require_auth(request)
    from .schedule_store import listing
    with SessionLocal() as db:
        user, camps, accts = user_scope(request, db)
    return [s for s in listing() if _schedule_in_scope(s, camps, accts)]


def _schedule_in_scope(data, camps, accts):
    for key in data.get('job_keys', []):
        scope = data.get('scopes', {}).get(key, {})
        for field, allowed in [('campaign_ids', camps), ('account_ids', accts)]:
            selected = scope.get(field)
            if allowed is not None and (selected is None or not set(selected).issubset(allowed)):
                return False
    return True


def _scoped_schedule(body, request, schedule_id=None):
    """Persist restricted default scopes; never let 'all' escape a user's scope."""
    from .models import Schedule
    with SessionLocal() as db:
        user, camps, accts = user_scope(request, db)
        old = db.get(Schedule, schedule_id) if schedule_id is not None else None
        if schedule_id is not None and (old is None or not _schedule_in_scope(
                {'job_keys': old.job_keys, 'scopes': old.scopes}, camps, accts)):
            raise HTTPException(404, 'Schedule not found')
        if body is None:
            return None
        if camps is None and accts is None:
            return body
        result = dict(body)
        scopes = dict(body.get('scopes', old.scopes if old else {}))
        for key in body.get('job_keys', old.job_keys if old else []):
            scope = dict(scopes.get(key, {}))
            _require_in_scope(user, campaign_ids=scope.get('campaign_ids'), account_ids=scope.get('account_ids'))
            if scope.get('campaign_ids') is None and camps is not None:
                scope['campaign_ids'] = camps
            if scope.get('account_ids') is None and accts is not None:
                scope['account_ids'] = accts
            scopes[key] = scope
        result['scopes'] = scopes
        return result


@app.post('/api/schedules')
def create_schedule_row(body: dict, request: Request):
    require_auth(request)
    from .schedule_store import save, migrate
    migrate()
    try:
        return save(_scoped_schedule(body, request))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.put('/api/schedules/{schedule_id}')
def update_schedule_row(schedule_id: int, body: dict, request: Request):
    require_auth(request)
    from .schedule_store import save
    try:
        return save(_scoped_schedule(body, request, schedule_id), schedule_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.delete('/api/schedules/{schedule_id}')
def delete_schedule_row(schedule_id: int, request: Request):
    require_auth(request)
    from .schedule_store import delete
    _scoped_schedule(None, request, schedule_id)
    try:
        delete(schedule_id)
        return {'ok': True}
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@app.get('/api/schedules/tick')
@app.post('/api/schedules/tick')
def tick_schedules(request: Request, wait: bool = True):
    """Periodic tick called by Cloud Scheduler or internal timer.
    Checks for any active schedules that are due or overdue, triggers them, and refreshes the in-memory engine.
    """
    from .schedule_store import tick
    executed = tick(wait_completion=wait)
    return {'ok': True, 'executed': executed, 'timestamp': datetime.utcnow().isoformat() + 'Z'}


@app.post('/api/schedules/{schedule_id}/run')
def run_schedule_now(schedule_id: int, request: Request):
    require_auth(request)
    from .schedule_store import run_now
    try:
        ok, msg = run_now(schedule_id)
        if not ok:
            raise HTTPException(400, msg)
        return {'ok': True, 'message': msg}
    except LookupError as exc:
        raise HTTPException(404, str(exc))



@app.get('/api/dashboard/trends')
def dashboard_trends(request: Request, db=Depends(get_db), days: int = 7):
    """Send-volume trend + last-24h run health (sparklines & system cards).
    days: 7 or 30 (daily buckets)."""
    require_auth(request)
    from sqlalchemy import select, func, and_ as sa_and, case as sa_case
    from .models import Lead, LeadEvent, RunLog

    days = days if days in (7, 30) else 7
    today = date.today()
    _tuser, _tcamps, _taccts = user_scope(request, db)
    # Audit-trail buckets (survive campaign deletion, unlike DailySendCount).
    start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    day_expr = func.date(LeadEvent.created_at)
    from sqlalchemy import and_ as sa_and
    ev_q = select(
            day_expr,
            # invites: connections sends that are NOT InMails
            func.sum(sa_case((sa_and(LeadEvent.job_type == 'send_connections',
                                      LeadEvent.detail.notilike('%InMail%')), 1), else_=0)),
            # inmails: connections sends that ARE InMails
            func.sum(sa_case((sa_and(LeadEvent.job_type == 'send_connections',
                                      LeadEvent.detail.ilike('%InMail%')), 1), else_=0)),
            # messages: follow-ups + after-acceptance sends
            func.sum(sa_case((LeadEvent.job_type.in_(['send_followups', 'check_replies']), 1), else_=0)),
        )
    if _tcamps is not None or _taccts is not None:
        ev_q = ev_q.join(Lead, Lead.id == LeadEvent.lead_id)
        _trend_scope = _lead_scope_conditions(_tcamps, _taccts)
        if _trend_scope is not None:
            ev_q = ev_q.where(_trend_scope)
    ev_q = ev_q.where(LeadEvent.kind == 'outbound', LeadEvent.created_at >= start,
                      LeadEvent.job_type.in_(['send_connections', 'send_followups', 'check_replies']))
    ev_rows = db.execute(ev_q.group_by(day_expr)).all()
    ev_by_day = {str(d): {'inv': int(i or 0), 'im': int(m or 0), 'msg': int(g or 0)} for d, i, m, g in ev_rows}
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        b = ev_by_day.get(d.isoformat(), {'inv': 0, 'im': 0, 'msg': 0})
        out.append({
            'date': d.isoformat(),
            'invites': b['inv'],
            'inmails': b['im'],
            'messages': b['msg'],
        })

    since = datetime.utcnow() - timedelta(hours=24)
    runs = db.execute(_run_scope_filter(
        select(RunLog).where(RunLog.started_at >= since), _tcamps, _taccts, user=_tuser)).scalars().all()
    total = len(runs)
    ok = sum(1 for r in runs if r.status == 'success')
    durations = [r.duration_s for r in runs if r.duration_s is not None]
    return {
        'days': out,
        'runs_24h': {
            'total': total,
            'success': ok,
            'success_rate': round(ok / total * 100, 1) if total else None,
            'avg_duration_s': round(sum(durations) / len(durations), 1) if durations else None,
        },
    }


@app.get('/api/search')
def global_search(request: Request, q: str = '', db=Depends(get_db)):
    """Command-bar search across campaigns, leads and accounts."""
    require_auth(request)
    from sqlalchemy import select, or_
    from .models import Lead, Campaign, Account

    q = (q or '').strip()
    if len(q) < 2:
        return {'campaigns': [], 'leads': [], 'accounts': []}
    like = f'%{q}%'
    campaigns = db.execute(
        select(Campaign).where(or_(Campaign.name.ilike(like), Campaign.campaign_key.ilike(like)))
        .limit(5)
    ).scalars().all()
    leads = db.execute(
        select(Lead).where(or_(Lead.full_name.ilike(like), Lead.company.ilike(like)))
        .order_by(Lead.id.desc()).limit(6)
    ).scalars().all()
    accounts = db.execute(
        select(Account).where(Account.name.ilike(like)).limit(5)
    ).scalars().all()
    return {
        'campaigns': [
            {'id': c.id, 'name': c.name, 'campaign_key': c.campaign_key, 'status': c.status}
            for c in campaigns
        ],
        'leads': [
            {'id': l.id, 'full_name': l.full_name or f"{l.first_name} {l.last_name}".strip(),
             'company': l.company}
            for l in leads
        ],
        'accounts': [
            {'id': a.id, 'name': a.name, 'status': a.status} for a in accounts
        ],
    }


@app.get('/api/health')
def health():
    return {'ok': True, 'time': datetime.utcnow().isoformat(timespec='seconds')}


# ---------------------------------------------------------------------------
# Static frontend (templates/ + static/, biometric-app style) - registered
# LAST so /api/* wins.
# ---------------------------------------------------------------------------

from .operations import router as operations_router
app.include_router(operations_router)

STATIC_DIR = PROJECT_ROOT / 'static'
TEMPLATES_DIR = PROJECT_ROOT / 'templates'
if TEMPLATES_DIR.exists():
    if STATIC_DIR.exists():
        app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')

    import re

    def _render_template(name: str) -> HTMLResponse:
        """Serve a template, stamping every referenced /static asset with its
        mtime+size so a deployed fix can never keep using a stale bundle because
        a manual ?v= number was left unchanged. Nested paths (static/dist/…) are
        versioned too."""
        def version_asset(match):
            asset = STATIC_DIR / match.group(1)
            if not asset.is_file():
                return match.group(0)
            stat = asset.stat()
            return f'/static/{match.group(1)}?v={stat.st_mtime_ns}-{stat.st_size}'

        html = re.sub(r'/static/([\w./-]+)(?:\?v=[\w.-]+)?', version_asset,
                      (TEMPLATES_DIR / name).read_text(encoding='utf-8'))
        return HTMLResponse(html, headers={'Cache-Control': 'no-store'})

    @app.get('/legacy', include_in_schema=False)
    def legacy_spa():
        """Classic no-build interface, kept reachable while views migrate."""
        return _render_template('legacy.html')

    @app.get('/legacy/', include_in_schema=False)
    def legacy_spa_slash():
        return _render_template('legacy.html')

    @app.get('/{full_path:path}', include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith('api/') or full_path == 'api':
            return JSONResponse({'detail': 'Not found'}, status_code=404)
        # Only the explicit /static mount may serve files. Never expose project
        # files (including .env, databases, or cookie captures) through the SPA.
        if full_path and ('.' in full_path or full_path.startswith(('app_data/', 'cookies_files/'))):
            return JSONResponse({'detail': 'Not found'}, status_code=404)
        return _render_template('index.html')


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

if os.environ.get('OCC_DISABLE_SCHEDULER', '').strip().lower() not in ('1', 'true', 'yes'):
    try:
        scheduler.init_scheduler()
    except Exception as e:
        print(f"⚠️ Scheduler failed to start: {e}")
