"""Campaign reporting, safe reassignment and user activity history."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_
from .database import get_db
from .models import (Lead, LeadEvent, LeadStatus, Campaign, Account, CampaignAccount,
                     DailySendCount, RunLog, RunTarget, UserActivity)

router = APIRouter()


def record_activity(db, user, action, detail='', result='success'):
    db.add(UserActivity(user_id=user.id, username=user.username, action=action,
                        detail=detail, result=result))


def restore_error_stage(db, lead):
    """Restore stage and its age, retaining all contact/reply history."""
    from .jobs import _set_status
    if lead.status != LeadStatus.BLOCKED_ERROR.value:
        lead.last_error = ''
        return
    stage, stamp = lead.status_before_error, lead.stage_time_before_error
    if stage is None:
        events = db.scalars(select(LeadEvent).where(LeadEvent.lead_id == lead.id,
            LeadEvent.kind == 'status_change').order_by(LeadEvent.created_at.desc(), LeadEvent.id.desc())).all()
        for ev in events:
            if ' -> BLOCKED_ERROR' in ev.detail:
                stage = ev.detail.split(' -> BLOCKED_ERROR', 1)[0]
                stage = '' if stage == '(none)' else stage
                previous = next((e for e in events if e.id < ev.id and e.detail.partition(' -> ')[2].split(':', 1)[0] == stage), None)
                stamp = previous.created_at if previous else None
                break
        if stage is None:
            stage = lead.last_followup_stage or ({'invite': 'INVITE_SENT', 'inmail': 'INMAIL_SENT'}.get(lead.contact_channel))
            stamp = lead.last_followup_at or lead.first_contacted_at
            if stage is None and not lead.first_contacted_at:
                stage = ''
    valid = {s.value for s in LeadStatus} - {'BLOCKED_ERROR'}
    if stage not in valid:
        raise HTTPException(409, f'Cannot determine the previous stage for lead {lead.id}; history was kept unchanged.')
    _set_status(db, lead, stage, None, detail='error removed; previous stage restored')
    lead.status_changed_at = stamp
    lead.last_error = ''
    lead.status_before_error = None
    lead.stage_time_before_error = None


class ReassignBody(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=10000)
    campaign_id: int | None = None
    account_id: int | None = None


@router.post('/api/leads/reassign')
def reassign_leads(body: ReassignBody, request: Request, db=Depends(get_db)):
    from .main import user_scope, _lead_in_scope, _require_in_scope
    from .jobs import validate_import_assignment, _add_event
    from .runner import idle_lease
    user, _, _ = user_scope(request, db)
    change_campaign = 'campaign_id' in body.model_fields_set
    change_account = 'account_id' in body.model_fields_set
    if not (change_campaign or change_account):
        raise HTTPException(422, 'Choose a campaign or account to change.')
    _require_in_scope(user, campaign_id=body.campaign_id, account_id=body.account_id)
    if change_campaign and body.campaign_id is not None and not db.get(Campaign, body.campaign_id):
        raise HTTPException(404, 'Campaign not found')
    if change_account and body.account_id is not None and not db.get(Account, body.account_id):
        raise HTTPException(404, 'Account not found')
    with idle_lease() as acquired:
        if not acquired:
            raise HTTPException(409, 'Wait for running workers to finish before reassigning leads.')
        ids = set(body.ids)
        leads = db.scalars(select(Lead).where(Lead.id.in_(ids))).all()
        if len(leads) != len(ids) or any(not _lead_in_scope(l, user) for l in leads):
            raise HTTPException(403, 'Some selected leads are unavailable or outside your access.')
        planned, seen = [], set()
        for lead in leads:
            cid = body.campaign_id if change_campaign else lead.campaign_id
            aid = body.account_id if change_account else lead.associate_account_id
            _require_in_scope(user, campaign_id=cid, account_id=aid)
            if user.role != 'admin' and cid is None and aid is None:
                raise HTTPException(403, 'Choose a destination within your access.')
            try:
                validate_import_assignment(db, aid, cid, require_active=change_account and aid is not None)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
            key = (cid, lead.sales_nav_id)
            if lead.sales_nav_id:
                duplicate = db.scalar(select(Lead.id).where(Lead.campaign_id == cid,
                    Lead.sales_nav_id == lead.sales_nav_id, Lead.id != lead.id).limit(1))
                if duplicate or key in seen:
                    raise HTTPException(409, 'A Sales Nav ID already exists in the destination campaign. No leads were moved.')
                seen.add(key)
            planned.append((lead, cid, aid))
        changed = 0
        for lead, cid, aid in planned:
            if (lead.campaign_id, lead.associate_account_id) == (cid, aid):
                continue
            _add_event(db, lead.id, 'assignment',
                f'Reassigned by {user.username}: campaign {lead.campaign_id} -> {cid}; account {lead.associate_account_id} -> {aid}. Stage preserved.', None)
            lead.campaign_id, lead.associate_account_id = cid, aid
            lead.source = 'campaign_search' if cid is not None else 'list_import'
            changed += 1
        record_activity(db, user, 'reassign_leads', f'{changed} leads reassigned; stages and history preserved')
        from sqlalchemy.exc import IntegrityError
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'The destination changed while saving. No leads were moved; refresh and retry.')
        return {'ok': True, 'changed': changed}


@router.get('/api/dashboard/campaign-stats')
def campaign_stats(request: Request, db=Depends(get_db), days: int = 0, active_only: bool = False):
    from .main import user_scope
    user, camps, accts = user_scope(request, db)
    if days not in (0, 1, 7, 30):
        raise HTTPException(422, 'Choose all time, today, 7 days or 30 days.')
    today = datetime.utcnow().date()
    start = today - timedelta(days=days - 1) if days else None
    end = today + timedelta(days=1)
    campaign_map = {c.id: c for c in db.scalars(select(Campaign)) if (camps is None or c.id in camps) and (not active_only or c.status == 'active')}
    account_map = {a.id: a for a in db.scalars(select(Account)) if accts is None or a.id in accts}
    rows = {}
    def get(cid, aid):
        if cid not in campaign_map or (aid is not None and aid not in account_map):
            return None
        return rows.setdefault((cid, aid), dict(campaign_id=cid, campaign=campaign_map[cid].name,
            account_id=aid, account=account_map[aid].name if aid is not None else 'Unassigned',
            invites=0, inmails=0, messages=0, replies=0, runs=0, last_run=None))
    for link in db.scalars(select(CampaignAccount)):
        get(link.campaign_id, link.account_id)
    # The confirmed counters belong to the sending pair, even after leads move.
    q = select(DailySendCount.campaign_id, DailySendCount.account_id,
        func.sum(DailySendCount.invite_sent_count), func.sum(DailySendCount.opentomsg_count),
        func.sum(DailySendCount.messages_sent)).where(DailySendCount.date < end)
    if start:
        q = q.where(DailySendCount.date >= start)
    for cid, aid, invites, inmails, messages in db.execute(q.group_by(DailySendCount.campaign_id, DailySendCount.account_id)):
        row = get(cid, aid)
        if row is not None:
            row.update(invites=int(invites or 0), inmails=int(inmails or 0), messages=int(messages or 0))
    # Attributed replies
    rq = select(Lead.campaign_id, Lead.associate_account_id, func.count(Lead.id)).where(
        Lead.received_replies.is_(True),
        Lead.campaign_id.is_not(None)
    )
    if start:
        rq = rq.where(or_(Lead.reply_received_at >= datetime.combine(start, datetime.min.time()),
                          and_(Lead.reply_received_at.is_(None), Lead.created_at >= datetime.combine(start, datetime.min.time()))))
    if end:
        rq = rq.where(or_(Lead.reply_received_at < datetime.combine(end, datetime.min.time()),
                          and_(Lead.reply_received_at.is_(None), Lead.created_at < datetime.combine(end, datetime.min.time()))))
    for cid, aid, count in db.execute(rq.group_by(Lead.campaign_id, Lead.associate_account_id)):
        row = get(cid, aid)
        if row is not None:
            row['replies'] = int(count or 0)
        else:
            mapped_row = next((r for (c, a), r in rows.items() if c == cid and a is not None), None)
            if mapped_row:
                mapped_row['replies'] += int(count or 0)
    # Legacy runs can be attributed only when both IDs were explicitly recorded.
    targets = select(RunTarget.run_id, RunTarget.campaign_id, RunTarget.account_id).union(
        select(RunLog.id, RunLog.campaign_id, RunLog.account_id).where(
            RunLog.campaign_id.is_not(None), RunLog.account_id.is_not(None))).subquery()
    q = select(RunLog.id, RunLog.job_type, RunLog.status, RunLog.started_at, targets.c.campaign_id, targets.c.account_id).join(targets, targets.c.run_id == RunLog.id).where(
        RunLog.dry_run.is_(False), RunLog.started_at < datetime.combine(end, datetime.min.time()))
    if start:
        q = q.where(RunLog.started_at >= datetime.combine(start, datetime.min.time()))
    if user.role != 'admin':
        q = q.where(RunLog.owner_user_id == user.id)
    for rid, job, status, started, cid, aid in db.execute(q.order_by(RunLog.started_at, RunLog.id)):
        row = get(cid, aid)
        if row is not None:
            row['runs'] += 1
            row['last_run'] = dict(id=rid, job=job, status=status, started_at=started.isoformat())
    present_campaigns = {cid for cid, _ in rows}
    for cid in campaign_map.keys() - present_campaigns:
        get(cid, None)['account'] = 'No mapped account available'
    return {'rows': sorted(rows.values(), key=lambda r: (r['campaign'].lower(), r['account'].lower())),
            'days': days, 'timezone': 'UTC', 'start': str(start) if start else None,
            'end': str(today)}


@router.get('/api/user-activity')
def user_activity(request: Request, db=Depends(get_db), page: int = Query(1, ge=1),
                  action: str = '', username: str = '', days: int = Query(0, ge=0, le=365)):
    from .main import user_scope
    user, _, _ = user_scope(request, db)
    q = select(UserActivity)
    if user.role != 'admin':
        q = q.where(UserActivity.user_id == user.id)
    if action:
        q = q.where(UserActivity.action == action)
    if username.strip():
        q = q.where(UserActivity.username.ilike('%' + username.strip() + '%'))
    if days:
        q = q.where(UserActivity.created_at >= datetime.utcnow() - timedelta(days=days))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.order_by(UserActivity.id.desc()).offset((page - 1) * 50).limit(50))
    return {'total': total, 'page': page, 'items': [dict(id=a.id, username=a.username, action=a.action,
        detail=a.detail, result=a.result, run_id=a.run_id, created_at=a.created_at.isoformat()) for a in items]}
