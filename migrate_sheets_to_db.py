"""One-time migration: Google Sheets + campaigns.py + get_cookies.py -> database.

Run:  python migrate_sheets_to_db.py            (from the project root)

- Accounts: from get_cookies.ACCOUNTS (session_ref = legacy cookies file path).
- Campaigns: from campaigns.CAMPAIGNS incl. ordered accounts + budgets.
- Leads:
  - "Search Data" sheet -> lead pool (campaign-tagged via the Campaigns column).
  - "Followup msg" sheet -> engagement state (status, account ownership,
    replies) merged onto those leads by Sales Nav ID + campaign.
- Daily counts from daily_run_counts/*.json.

Sheet emoji status labels are translated to the DB status enum.
"""
import json
import os
import re
from datetime import datetime

import pipeline_common as pcom
from get_cookies import ACCOUNTS as LEGACY_ACCOUNTS
from campaigns import CAMPAIGNS

from app.database import SessionLocal, init_db
from app.models import (
    Account, Campaign, CampaignAccount, Lead, LeadEvent, DailySendCount,
    LeadStatus,
)

# Sheet label -> DB status
STATUS_MAP = {
    '📩 Sent Invite': LeadStatus.INVITE_SENT.value,
    '💬 Sent InMail': LeadStatus.INMAIL_SENT.value,
    '📩 Sent After Acceptance follow-up': LeadStatus.INVITE_AFTER_ACCEPT.value,
    '📩 Sent Invite Follow-up 1': LeadStatus.INVITE_FOLLOWUP_1.value,
    '📩 Sent Invite Follow-up 2': LeadStatus.INVITE_FOLLOWUP_2.value,
    '📩 Sent Invite Follow-up 3': LeadStatus.INVITE_FOLLOWUP_3.value,
    '💬 Sent InMail Follow-up 1': LeadStatus.INMAIL_FOLLOWUP_1.value,
    '💬 Sent InMail Follow-up 2': LeadStatus.INMAIL_FOLLOWUP_2.value,
    '💬 Sent InMail Follow-up 3': LeadStatus.INMAIL_FOLLOWUP_3.value,
}


def norm(s) -> str:
    return str(s or '').strip()


def parse_sheet_date(s: str):
    s = norm(s)
    if not s:
        return None
    for fmt in ('%d-%b-%Y', '%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def seed_accounts(db) -> int:
    n = 0
    for name, cfg in LEGACY_ACCOUNTS.items():
        if db.query(Account).filter_by(name=name).first():
            continue
        cookies_file = cfg.get('cookies_file', '')
        db.add(Account(
            name=name,
            session_ref=cookies_file,
            status='active',
            last_cookie_refresh_at=datetime.fromtimestamp(
                os.path.getmtime(cookies_file)) if os.path.exists(cookies_file) else None,
        ))
        n += 1
    db.commit()
    return n


def seed_campaigns(db) -> int:
    n = 0
    account_rows = {a.name: a for a in db.query(Account).all()}
    for key, camp in CAMPAIGNS.items():
        if db.query(Campaign).filter_by(campaign_key=key).first():
            continue
        row = Campaign(
            campaign_key=key,
            name=key,
            search_url=camp.get('search_url', '') or '',
            status='active',
            invite_text=camp.get('invite', ''),
            invite_track=list(camp.get('invite_track', [])),
            inmail_subject=camp.get('inmail_subject', ''),
            inmail_text=camp.get('inmail', ''),
            inmail_track=list(camp.get('inmail_track', [])),
        )
        db.add(row)
        db.flush()
        for i, acc in enumerate(camp.get('accounts', [])):
            account = account_rows.get(acc['account'])
            if account is None:
                print(f"  ⚠️ Campaign '{key}' references unknown account '{acc['account']}' - creating it")
                account = Account(name=acc['account'], session_ref='')
                db.add(account)
                db.flush()
                account_rows[acc['account']] = account
            db.add(CampaignAccount(
                campaign_id=row.id, account_id=account.id, order_index=i,
                invite_limit=acc.get('invite_limit', 10),
                inmail_limit=acc.get('inmail_limit', 10),
                message_limit=acc.get('message_limit', 30),
                calendar_url=acc.get('calendar_url'),
                search_url_override=acc.get('search_url'),
            ))
        n += 1
    db.commit()
    return n


def _opentomsg_from(value: str):
    return {'TRUE': True, 'FALSE': False}.get(value.upper())  # 'Unknown'/'' -> None


def migrate_leads(db):
    """Search Data = lead pool; Followup msg = engagement-state overlay."""
    if not os.path.exists(pcom.SERVICE_ACCOUNT_FILE):
        print('⚠️ Skipping lead migration: Google service account file not found at '
              f"{pcom.SERVICE_ACCOUNT_FILE} - place credentials.json and re-run to import leads")
        return 0, 0, 0, {'created': 0, 'updated': 0, 'unmatched_campaign': 0}
    campaign_rows = {c.campaign_key: c for c in db.query(Campaign).all()}
    account_rows = {a.name: a for a in db.query(Account).all()}

    created = refreshed = skipped = 0

    # ---- Pass 1: Search Data ----
    search_values = pcom.get_worksheet('Search Data').get_all_values()
    if search_values:
        headers = search_values[0]
        col = {h: i for i, h in enumerate(headers)}

        def cell(row, name):
            i = col.get(name)
            return norm(row[i]) if i is not None and i < len(row) else ''

        for row in search_values[1:]:
            snid = cell(row, 'Sales Nav ID')
            if not snid:
                continue
            campaign = campaign_rows.get(cell(row, 'Campaigns'))
            if campaign is None:
                skipped += 1
                continue

            lead = db.query(Lead).filter_by(
                sales_nav_id=snid, campaign_id=campaign.id).first()
            if lead is None:
                db.add(Lead(
                    sales_nav_id=snid,
                    first_name=cell(row, 'FirstName'),
                    last_name=cell(row, 'LastName'),
                    full_name=cell(row, 'FullName') or f"{cell(row, 'FirstName')} {cell(row, 'LastName')}".strip(),
                    title=cell(row, 'Title'),
                    summary=cell(row, 'Summary'),
                    location=cell(row, 'Location'),
                    company=cell(row, 'Company'),
                    premium=cell(row, 'Premium'),
                    pending_invitation=cell(row, 'PendingInvitation'),
                    viewed=cell(row, 'Viewed'),
                    opentomsg=_opentomsg_from(cell(row, 'Opentomsg')),
                    linkedin_url=cell(row, 'Linkedin URL'),
                    source='campaign_search',
                    campaign_id=campaign.id,
                    status='',
                ))
                created += 1
            else:
                if cell(row, 'Linkedin URL') and not lead.linkedin_url:
                    lead.linkedin_url = cell(row, 'Linkedin URL')
                ot = _opentomsg_from(cell(row, 'Opentomsg'))
                if ot is not None and lead.opentomsg is None:
                    lead.opentomsg = ot
                refreshed += 1
        db.commit()

    # ---- Pass 2: Followup msg (engagement overlay) ----
    follow_stats = {'created': 0, 'updated': 0, 'unmatched_campaign': 0}
    follow_values = pcom.get_worksheet('Followup msg').get_all_values()
    if follow_values:
        fheaders = follow_values[0]
        fcol = {h: i for i, h in enumerate(fheaders)}

        def fcell(row, name):
            i = fcol.get(name)
            return norm(row[i]) if i is not None and i < len(row) else ''

        label_to_status = {norm(k).lower(): v for k, v in STATUS_MAP.items()}

        for row in follow_values[1:]:
            snid = fcell(row, 'Sales Nav ID')
            if not snid:
                continue
            campaign = campaign_rows.get(fcell(row, 'Campaigns'))
            associate = account_rows.get(fcell(row, 'Associate Account'))

            raw_status = fcell(row, 'Invite or InMail Status').lower()
            db_status = label_to_status.get(raw_status)
            replied = fcell(row, 'Received Replies').startswith('✅')

            lead = db.query(Lead).filter_by(
                sales_nav_id=snid, campaign_id=campaign.id).first() if campaign else None

            if lead is None:
                # Row only on Followup msg: create the lead so no history is lost.
                lead = Lead(
                    sales_nav_id=snid,
                    first_name=fcell(row, 'FirstName'),
                    last_name=fcell(row, 'LastName'),
                    full_name=fcell(row, 'FullName') or f"{fcell(row, 'FirstName')} {fcell(row, 'LastName')}".strip(),
                    title=fcell(row, 'Title'),
                    company=fcell(row, 'Company'),
                    source='campaign_search',
                    campaign_id=campaign.id if campaign else None,
                    status=db_status or '',
                    associate_account_id=associate.id if associate else None,
                    received_replies=replied,
                    reply_message=fcell(row, 'Reply messages') or None,
                )
                db.add(lead)
                db.flush()
                if db_status:
                    db.add(LeadEvent(
                        lead_id=lead.id, kind='status_change',
                        detail=f'migrated: {db_status}', job_type='migration'))
                follow_stats['created'] += 1
            else:
                # Engagement state lives on Followup msg - it wins.
                if db_status and db_status != lead.status:
                    lead.status = db_status
                    lead.status_changed_at = None  # date column often blank; follow-ups stay conservative
                    db.add(LeadEvent(
                        lead_id=lead.id, kind='status_change',
                        detail=f'migrated: {db_status}', job_type='migration'))
                if associate and not lead.associate_account_id:
                    lead.associate_account_id = associate.id
                if replied and not lead.received_replies:
                    lead.received_replies = True
                    lead.reply_message = fcell(row, 'Reply messages') or None
                follow_stats['updated'] += 1
        db.commit()

    return created, refreshed, skipped, follow_stats


def migrate_daily_counts(db) -> int:
    """daily_run_counts/daily_run_counts_<campaign>_<account>.json -> DB rows."""
    counts_dir = './daily_run_counts'
    if not os.path.isdir(counts_dir):
        return 0
    campaign_rows = {c.campaign_key: c for c in db.query(Campaign).all()}
    account_rows = {a.name: a for a in db.query(Account).all()}
    n = 0
    for fname in os.listdir(counts_dir):
        m = re.match(r'daily_run_counts_(.+?)_(.+)\.json$', fname)
        if not m:
            continue
        campaign = campaign_rows.get(m.group(1))
        account = account_rows.get(m.group(2))
        if not campaign or not account:
            continue
        with open(os.path.join(counts_dir, fname), 'r', encoding='utf-8') as f:
            data = json.load(f)
        for day_str, counts in data.items():
            day = parse_sheet_date(day_str)
            if day is None:
                continue
            row = db.query(DailySendCount).filter_by(
                campaign_id=campaign.id, account_id=account.id, date=day).first()
            if row is None:
                row = DailySendCount(campaign_id=campaign.id, account_id=account.id, date=day)
                db.add(row)
                n += 1
            row.invite_sent_count = int(counts.get('invite_sent_count', 0) or 0)
            row.opentomsg_count = int(counts.get('opentomsg_count', 0) or 0)
            row.messages_sent = int(counts.get('messages_sent', 0) or 0)
    db.commit()
    return n


def main():
    print('=== Outreach Command Center - migration ===')
    init_db()
    db = SessionLocal()
    try:
        print('1) Accounts...', end=' ')
        n = seed_accounts(db)
        print(f'{n} created')

        print('2) Campaigns...', end=' ')
        n = seed_campaigns(db)
        print(f'{n} created')

        print('3) Leads (Search Data + Followup msg)...', end=' ')
        created, refreshed, skipped, follow_stats = migrate_leads(db)
        print(f'{created} created, {refreshed} refreshed, {skipped} skipped (unknown campaign)')
        print(f"   Followup overlay: {follow_stats['created']} created, {follow_stats['updated']} updated")

        print('4) Daily send counts...', end=' ')
        n = migrate_daily_counts(db)
        print(f'{n} day-row(s) created')

        print('Done. The Google Sheets remain untouched; the DB is now the system of record.')
    finally:
        db.close()


if __name__ == '__main__':
    main()
