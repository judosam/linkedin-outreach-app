"""Calendar-week invitation budget (resets Monday 00:00 UTC), shared by every
campaign on an account."""
from collections import Counter
from datetime import datetime, timedelta
from sqlalchemy import select, func
from .models import AccountInviteSend, DailySendCount, Lead, LeadEvent, Setting


def week_start_utc(now=None):
    """Monday 00:00 UTC of the week containing `now` — the reset moment."""
    now = now or datetime.utcnow()
    monday = now.date() - timedelta(days=now.weekday())
    return datetime.combine(monday, datetime.min.time())


def weekly_invite_status(db, account, now=None):
    """Invites sent since the current week's Monday 00:00 UTC. The counter
    shows the full cap again the moment the new week starts."""
    now = now or datetime.utcnow()
    cap = min(150, max(0, account.weekly_invite_cap if account.weekly_invite_cap is not None else 100))
    used = int(db.scalar(select(func.coalesce(func.sum(AccountInviteSend.count), 0)).where(
        AccountInviteSend.account_id == account.id,
        AccountInviteSend.sent_at >= week_start_utc(now))) or 0)
    return {'used': used, 'limit': cap, 'remaining': max(0, cap - used)}


def backfill_weekly_invites(db, now=None):
    """One-time migration: retain known recent sends without double counting.

    Exact audit timestamps take precedence. Daily-only counts expire at the
    end of that day plus seven days, conservatively retaining uncertain times.
    No lead, campaign or daily counter is modified.
    """
    marker = 'weekly_invites_backfill_v1'
    if db.get(Setting, marker):
        return
    now = now or datetime.utcnow()
    start = now - timedelta(days=7)
    totals = Counter()
    events = db.execute(select(Lead.associate_account_id, LeadEvent.created_at).join(
        Lead, Lead.id == LeadEvent.lead_id).where(
        Lead.associate_account_id.is_not(None), LeadEvent.kind == 'outbound',
        LeadEvent.job_type == 'send_connections', LeadEvent.detail.ilike('%invite sent%'),
        LeadEvent.created_at >= datetime.combine(start.date(), datetime.min.time()))).all()
    for aid, sent_at in events:
        db.add(AccountInviteSend(account_id=aid, sent_at=sent_at, count=1))
        totals[(aid, sent_at.date())] += 1
    daily = db.execute(select(DailySendCount.account_id, DailySendCount.date,
        func.sum(DailySendCount.invite_sent_count)).where(DailySendCount.date >= start.date()).group_by(
        DailySendCount.account_id, DailySendCount.date)).all()
    for aid, day, count in daily:
        missing = max(0, int(count or 0) - totals[(aid, day)])
        if missing:
            sent_at = min(now, datetime.combine(day, datetime.max.time()))
            db.add(AccountInviteSend(account_id=aid, sent_at=sent_at, count=missing))
    db.add(Setting(key=marker, value_json='true'))
    db.commit()
