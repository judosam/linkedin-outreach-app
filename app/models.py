"""SQLAlchemy 2.0 models for the Outreach Command Center.

This DB is the new system of record. The one-time migration script
(migrate_sheets_to_db.py) populates it from Google Sheets + campaigns.py.
"""
from datetime import datetime, date
from enum import Enum as PyEnum

from sqlalchemy import (
    String, Text, Integer, Boolean, DateTime, Date, ForeignKey, JSON,
    UniqueConstraint, Index, Float, text,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship,
)


class Base(DeclarativeBase):
    pass


# --- Enums (stored as plain strings for SQLite/Postgres portability) ---

class LeadStatus(str, PyEnum):
    NONE = ''
    # Terminal hold for leads whose send failed with a lead-specific error
    # (e.g. HTTP 400 "Email is required to connect"). Send jobs select only
    # untouched / stage-matched leads, so BLOCKED_ERROR leads are skipped on
    # every future run until a user retries them from the Leads page.
    BLOCKED_ERROR = 'BLOCKED_ERROR'
    INVITE_SENT = 'INVITE_SENT'
    INMAIL_SENT = 'INMAIL_SENT'
    INVITE_AFTER_ACCEPT = 'INVITE_AFTER_ACCEPT'
    INVITE_FOLLOWUP_1 = 'INVITE_FOLLOWUP_1'
    INVITE_FOLLOWUP_2 = 'INVITE_FOLLOWUP_2'
    INVITE_FOLLOWUP_3 = 'INVITE_FOLLOWUP_3'
    INMAIL_FOLLOWUP_1 = 'INMAIL_FOLLOWUP_1'
    INMAIL_FOLLOWUP_2 = 'INMAIL_FOLLOWUP_2'
    INMAIL_FOLLOWUP_3 = 'INMAIL_FOLLOWUP_3'


class LeadSource(str, PyEnum):
    CAMPAIGN_SEARCH = 'campaign_search'
    LIST_IMPORT = 'list_import'


class JobType(str, PyEnum):
    SYNC_LEADS = 'sync_leads'
    IMPORT_LIST = 'import_list'
    SEND_CONNECTIONS = 'send_connections'
    CHECK_REPLIES = 'check_replies'
    SEND_FOLLOWUPS = 'send_followups'


class RunStatus(str, PyEnum):
    RUNNING = 'running'
    SUCCESS = 'success'
    PARTIAL = 'partial'
    ERROR = 'error'
    STOPPED = 'stopped'
    SKIPPED = 'skipped'


# Reply categories: 'unclassified' is the explicit "no reliable detection" value.
class ReplyCategory(str, PyEnum):
    POSITIVE = 'positive'
    MEETING = 'meeting'
    FOLLOWUP_LATER = 'followup_later'
    REFERRAL = 'referral'
    DECLINED = 'declined'
    UNSUBSCRIBE = 'unsubscribe'
    OOO = 'ooo'
    UNCLASSIFIED = 'unclassified'


class AccountStatus(str, PyEnum):
    ACTIVE = 'active'
    PAUSED = 'paused'
    NEEDS_REAUTH = 'needs_reauth'
    SEAT_REQUIRED = 'seat_required'


# --- Tables ---

class Account(Base):
    __tablename__ = 'accounts'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    # session_ref points at the cookies file / profile dir managed by
    # get_cookies.py (never a copy of the cookie values themselves).
    session_ref: Mapped[str] = mapped_column(String(255), default='')
    status: Mapped[str] = mapped_column(String(20), default=AccountStatus.ACTIVE.value)
    last_cookie_refresh_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Fleet-level daily ceilings. A campaign link still needs its own limits;
    # the effective send budget is min(campaign link limit, account cap).
    daily_invite_cap: Mapped[int] = mapped_column(Integer, default=30)
    weekly_invite_cap: Mapped[int] = mapped_column(Integer, default=100)
    daily_inmail_cap: Mapped[int] = mapped_column(Integer, default=10)
    daily_message_cap: Mapped[int] = mapped_column(Integer, default=60)

    # Lifetime count of successfully completed account-level actions
    # (each delivered invite / InMail / follow-up / import page = 1 run).
    # Incremented ONLY after the action's own DB commit succeeds, so a
    # stopped or failed job never inflates it.
    total_runs: Mapped[int] = mapped_column(Integer, default=0)

    campaign_links: Mapped[list['CampaignAccount']] = relationship(
        back_populates='account', cascade='all, delete-orphan'
    )


class Campaign(Base):
    __tablename__ = 'campaigns'

    id: Mapped[int] = mapped_column(primary_key=True)
    # campaign_key is the literal string tagged onto lead rows ("SCM Podcast").
    # NEVER rename without a data migration (see spec Part A).
    campaign_key: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    search_url: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='active')  # active | paused

    invite_text: Mapped[str] = mapped_column(Text, default='')
    # Ordered array: [0]=after-acceptance, [1..3]=Follow-up 1..3
    invite_track: Mapped[list] = mapped_column(JSON, default=list)
    inmail_subject: Mapped[str] = mapped_column(Text, default='')
    inmail_text: Mapped[str] = mapped_column(Text, default='')
    # Ordered array of {subject, body}: [0..2]=InMail Follow-up 1..3
    inmail_track: Mapped[list] = mapped_column(JSON, default=list)

    # Per-campaign follow-up timing (days to wait before FU 1, 2, 3)
    invite_fu_days: Mapped[list] = mapped_column(JSON, default=lambda: [3, 5, 7])
    inmail_fu_days: Mapped[list] = mapped_column(JSON, default=lambda: [3, 5, 7])

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account_links: Mapped[list['CampaignAccount']] = relationship(
        back_populates='campaign', cascade='all, delete-orphan',
        order_by='CampaignAccount.order_index',
    )


class CampaignAccount(Base):
    """Ordered join: which physical accounts run a campaign, in priority order,
    each with its own daily budgets and optional per-account search override."""
    __tablename__ = 'campaign_accounts'
    __table_args__ = (
        UniqueConstraint('campaign_id', 'account_id', name='uq_campaign_account'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id', ondelete='CASCADE'))
    account_id: Mapped[int] = mapped_column(ForeignKey('accounts.id', ondelete='CASCADE'))
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    invite_limit: Mapped[int] = mapped_column(Integer, default=10)
    inmail_limit: Mapped[int] = mapped_column(Integer, default=10)
    message_limit: Mapped[int] = mapped_column(Integer, default=30)
    calendar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_url_override: Mapped[str | None] = mapped_column(Text, nullable=True)

    campaign: Mapped['Campaign'] = relationship(back_populates='account_links')
    account: Mapped['Account'] = relationship(back_populates='campaign_links')


class Lead(Base):
    __tablename__ = 'leads'
    __table_args__ = (
        # Missing IDs are allowed for CSV leads; only identified leads share
        # this uniqueness constraint. Import paths also deduplicate by URL.
        Index('uq_lead_snid_campaign_present', 'sales_nav_id', 'campaign_id', unique=True,
              sqlite_where=text("sales_nav_id <> ''"),
              postgresql_where=text("sales_nav_id <> ''")),
        Index('ix_leads_status', 'status'),
        Index('ix_leads_campaign_status', 'campaign_id', 'status'),
        # Sort/filter columns used by the pipeline table — without these every
        # sort click was a full table scan + filesort on large datasets.
        Index('ix_leads_last_followup', 'last_followup_at'),
        Index('ix_leads_first_contacted', 'first_contacted_at'),
        Index('ix_leads_created_at', 'created_at'),
        Index('ix_leads_company', 'company'),
        Index('ix_leads_full_name', 'full_name'),
        Index('ix_leads_associate_account', 'associate_account_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sales_nav_id: Mapped[str] = mapped_column(String(120), default='')
    # Exact Sales Navigator identity as exported by the sheets / inbox URNs
    # ('urn:li:fs_salesProfile:(ACw…,NAME_SEARCH,K1mY)'). Matching stays on the
    # bare token in sales_nav_id; this preserves the original URN byte-for-byte.
    sales_nav_urn: Mapped[str] = mapped_column(String(255), default='')
    first_name: Mapped[str] = mapped_column(String(120), default='')
    last_name: Mapped[str] = mapped_column(String(120), default='')
    full_name: Mapped[str] = mapped_column(String(240), default='')
    title: Mapped[str] = mapped_column(String(255), default='')
    summary: Mapped[str] = mapped_column(Text, default='')
    location: Mapped[str] = mapped_column(String(255), default='')
    company: Mapped[str] = mapped_column(String(255), default='')
    premium: Mapped[str] = mapped_column(String(20), default='')
    pending_invitation: Mapped[str] = mapped_column(String(20), default='')
    viewed: Mapped[str] = mapped_column(String(20), default='')

    # Open-profile (OpenLink) flag; NULL = not yet fetched/cached.
    opentomsg: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    linkedin_url: Mapped[str] = mapped_column(Text, default='')

    source: Mapped[str] = mapped_column(String(30), default=LeadSource.CAMPAIGN_SEARCH.value)
    list_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey('campaigns.id', ondelete='SET NULL'), nullable=True)
    associate_account_id: Mapped[int | None] = mapped_column(
        ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True)

    status: Mapped[str] = mapped_column(String(40), default='')
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_before_error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    stage_time_before_error: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Human-readable reason for the most recent lead-level send failure
    # ('Email is required to connect', 'HTTP 500: …'). Shown on the lead row
    # and cleared when the lead is retried.
    last_error: Mapped[str] = mapped_column(String(255), default='')
    # First-touch timestamps: which day the lead was actually contacted and
    # via which channel (invite vs InMail), plus the last follow-up sent.
    first_contacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    contact_channel: Mapped[str] = mapped_column(String(20), default='')  # invite | inmail
    last_followup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_followup_stage: Mapped[str] = mapped_column(String(40), default='')
    received_replies: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Reply triage (additive): category suggestion vs manual pick are tracked
    # separately so a manual decision is never overwritten by automation.
    reply_category: Mapped[str] = mapped_column(String(30), default='')
    reply_category_source: Mapped[str] = mapped_column(String(10), default='')  # auto | manual
    reply_category_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default='')  # '' | needs_review | reviewed
    reply_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Fingerprint of the last imported history row (workbook merge idempotency).
    import_fp: Mapped[str] = mapped_column(String(64), default='')

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    campaign: Mapped['Campaign | None'] = relationship()
    associate_account: Mapped['Account | None'] = relationship()
    events: Mapped[list['LeadEvent']] = relationship(
        back_populates='lead', cascade='all, delete-orphan',
        order_by='LeadEvent.created_at',
    )


class LeadEvent(Base):
    """Audit trail: every outbound action / state change on a lead."""
    __tablename__ = 'lead_events'
    __table_args__ = (
        Index('ix_lead_events_lead', 'lead_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id', ondelete='CASCADE'))
    kind: Mapped[str] = mapped_column(String(40))    # e.g. status_change, reply, error
    detail: Mapped[str] = mapped_column(Text, default='')
    job_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lead: Mapped['Lead'] = relationship(back_populates='events')


class AccountInviteSend(Base):
    """Account-level receipts survive deletion of leads and campaigns."""
    __tablename__ = 'account_invite_sends'
    __table_args__ = (Index('ix_account_invite_window', 'account_id', 'sent_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey('accounts.id', ondelete='CASCADE'))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    count: Mapped[int] = mapped_column(Integer, default=1)


class DailySendCount(Base):
    """One row per (campaign, account, day). Three independent counters:
    invite_sent_count + opentomsg_count are enforced by send_connections;
    messages_sent is the SHARED counter consumed by both check_replies
    (after-acceptance sends) and send_followups. Follow-ups can use the full
    remaining effective limit; after-acceptance sends keep the half-limit threshold."""
    __tablename__ = 'daily_send_counts'
    __table_args__ = (
        UniqueConstraint('campaign_id', 'account_id', 'date', name='uq_daily_counts'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id', ondelete='CASCADE'))
    account_id: Mapped[int] = mapped_column(ForeignKey('accounts.id', ondelete='CASCADE'))
    date: Mapped[date] = mapped_column(Date)
    invite_sent_count: Mapped[int] = mapped_column(Integer, default=0)
    opentomsg_count: Mapped[int] = mapped_column(Integer, default=0)
    messages_sent: Mapped[int] = mapped_column(Integer, default=0)


class RunLog(Base):
    __tablename__ = 'run_logs'

    id: Mapped[int] = mapped_column(primary_key=True)
    # Immutable execution attribution; NULL legacy/scheduler runs are admin-only.
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    job_type: Mapped[str] = mapped_column(String(40))
    schedule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey('campaigns.id', ondelete='SET NULL'), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True)
    target: Mapped[str] = mapped_column(String(255), default='')  # human label
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.RUNNING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    log_text: Mapped[str | None] = mapped_column(Text, nullable=True)


from sqlalchemy import event as _sa_event


@_sa_event.listens_for(RunLog, 'before_insert')
def _attribute_execution(_mapper, _connection, row):
    from .runner import execution_context
    token = getattr(execution_context, 'run_token', None)
    if token:
        row.execution_id = token
        row.owner_user_id = getattr(execution_context, 'owner_user_id', None)


@_sa_event.listens_for(RunLog, 'after_insert')
def _track_execution_run(_mapper, _connection, row):
    from .runner import execution_context
    if getattr(execution_context, 'run_token', None):
        execution_context.run_ids = [*getattr(execution_context, 'run_ids', []), row.id]


class Schedule(Base):
    __tablename__ = 'schedules'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    run_time: Mapped[str] = mapped_column(String(5))
    days_of_week: Mapped[list] = mapped_column(JSON, default=list)
    job_keys: Mapped[list] = mapped_column(JSON, default=list)
    scopes: Mapped[dict] = mapped_column(JSON, default=dict)
    timezone: Mapped[str] = mapped_column(String(80), default='Asia/Kolkata')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    jitter_minutes: Mapped[int] = mapped_column(Integer, default=0)
    window_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReplyComment(Base):
    """Internal note attached to a replied lead. Lives separately from the
    LinkedIn reply text; reply synchronization never touches these rows."""
    __tablename__ = 'reply_comments'
    __table_args__ = (
        Index('ix_reply_comments_lead', 'lead_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id', ondelete='CASCADE'))
    author: Mapped[str] = mapped_column(String(120), default='Admin')
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeletionAudit(Base):
    """Audit trail for bulk lead deletions (the leads' own events vanish with
    them, so the operation itself is recorded here)."""
    __tablename__ = 'deletion_audit'

    id: Mapped[int] = mapped_column(primary_key=True)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ImportBatch(Base):
    """One historical workbook merge. stats keeps the full report; fingerprints
    of applied rows live on Lead.import_fp so re-imports skip duplicates."""
    __tablename__ = 'import_batches'

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(255), default='')
    mode: Mapped[str] = mapped_column(String(20), default='apply')  # preview | apply
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    """Web-app login account. `role` is 'admin' (user management + all ops)
    or 'campaign_manager' (all ops, no user management). Passwords are stored
    as PBKDF2 hashes from app.auth (never plaintext, never exported)."""
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default='')
    role: Mapped[str] = mapped_column(String(30), default='campaign_manager')
    # Explicit grants for non-admins: empty lists grant no access.
    # Administrators bypass these lists.
    allowed_campaign_ids: Mapped[list] = mapped_column(JSON, default=list)
    allowed_account_ids: Mapped[list] = mapped_column(JSON, default=list)
    can_manage_licenses: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Setting(Base):
    """Generic key/value settings store (schedules, UI prefs, feature flags)."""
    __tablename__ = 'settings'

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default='{}')
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationSettings(Base):
    __tablename__ = 'notification_settings'

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    gchat_webhook_url: Mapped[str] = mapped_column(Text, default='')
    # JSON list of email addresses
    email_recipients: Mapped[list] = mapped_column(JSON, default=list)
    alert_critical: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_run_summary: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_send_errors: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_reply_digest: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserActivity(Base):
    __tablename__ = 'user_activity'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(120), default='System')
    action: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str] = mapped_column(Text, default='')
    result: Mapped[str] = mapped_column(String(40), default='success')
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class RunTarget(Base):
    """Pairs actually visited by a worker; independent of mutable lead ownership."""
    __tablename__ = 'run_targets'
    __table_args__ = (UniqueConstraint('run_id', 'campaign_id', 'account_id', name='uq_run_target'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('run_logs.id', ondelete='CASCADE'), index=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)


@_sa_event.listens_for(RunLog, 'after_insert')
@_sa_event.listens_for(RunLog, 'after_update')
def _audit_worker_state(_mapper, connection, row):
    from sqlalchemy import inspect, select
    if not inspect(row).attrs.status.history.has_changes():
        return
    username = connection.scalar(select(User.username).where(User.id == row.owner_user_id)) if row.owner_user_id else 'System / scheduler'
    connection.execute(UserActivity.__table__.insert().values(
        user_id=row.owner_user_id, username=username or 'Deleted user', action=row.job_type,
        detail=('Dry run: ' if row.dry_run else '') + (row.target or 'Worker run'),
        result=row.status, run_id=row.id, created_at=datetime.utcnow()))
