"""SQLAlchemy 2.0 models for the Outreach Command Center.

This DB is the new system of record. The one-time migration script
(migrate_sheets_to_db.py) populates it from Google Sheets + campaigns.py.
"""
from datetime import datetime, date
from enum import Enum as PyEnum

from sqlalchemy import (
    String, Text, Integer, Boolean, DateTime, Date, ForeignKey, JSON,
    UniqueConstraint, Index, Float,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship,
)


class Base(DeclarativeBase):
    pass


# --- Enums (stored as plain strings for SQLite/Postgres portability) ---

class LeadStatus(str, PyEnum):
    NONE = ''
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


class AccountStatus(str, PyEnum):
    ACTIVE = 'active'
    PAUSED = 'paused'
    NEEDS_REAUTH = 'needs_reauth'


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
        # One row per Sales Nav ID + campaign; untagged leads (campaign NULL)
        # can repeat across imports, hence the nullable-safe unique index.
        Index('uq_lead_snid_campaign', 'sales_nav_id', 'campaign_id', unique=True),
        Index('ix_leads_status', 'status'),
        Index('ix_leads_campaign_status', 'campaign_id', 'status'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sales_nav_id: Mapped[str] = mapped_column(String(120), default='')
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
    received_replies: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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


class DailySendCount(Base):
    """One row per (campaign, account, day). Three independent counters:
    invite_sent_count + opentomsg_count are enforced by send_connections;
    messages_sent is the SHARED counter consumed by both check_replies
    (after-acceptance sends) and send_followups, each capped at
    round(message_limit / 2) per the spec."""
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
    job_type: Mapped[str] = mapped_column(String(40))
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
