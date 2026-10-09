"""One-time import: LinkedIn Outreach Automation.xlsx -> Outreach Command Center DB.

Sheet 'Search Data'  = full lead pool (untagged, untouched unless also in sheet 2).
Sheet 'Followup msg' = processed rows: campaign + account + status + replies.

Creates Campaigns and Accounts on the fly (defaults for link budgets), maps the
legacy emoji statuses to the app's status machine, imports reply messages with
timestamps when available, then upserts the Search Data pool. Idempotent:
re-running skips existing (sales_nav_id, campaign_id) pairs.
"""
import sys
import io
import re
import argparse
from datetime import datetime, date

import openpyxl

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.database import SessionLocal, init_db
from app.models import Account, Campaign, Lead, LeadEvent, LeadSource

# Legacy sheet status -> app status enum value
STATUS_MAP = {
    'sent invite': '',
    'sent inmail': 'INMAIL_SENT',
    'sent after acceptance follow-up': 'INVITE_AFTER_ACCEPT',
    'sent invite follow-up 1': 'INVITE_FOLLOWUP_1',
    'sent invite follow-up 2': 'INVITE_FOLLOWUP_2',
    'sent invite follow-up 3': 'INVITE_FOLLOWUP_3',
    'sent inmail follow-up 1': 'INMAIL_FOLLOWUP_1',
    'sent inmail follow-up 2': 'INMAIL_FOLLOWUP_2',
    'sent inmail follow-up 3': 'INMAIL_FOLLOWUP_3',
}

TRUTHY = {'true', 'yes', '1', 'y'}
FALSY = {'false', 'no', '0', 'n', ''}


def norm(v) -> str:
    return str(v).strip() if v is not None else ''


def boolish(v) -> bool | None:
    s = norm(v).lower()
    if s in TRUTHY:
        return True
    if s in FALSY:
        return False
    return None


def parse_date(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    s = norm(v)
    if not s:
        return None
    for fmt in ('%m/%d/%Y %H:%M', '%m/%d/%Y', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def clean_snid(v: str) -> str:
    """urn:li:fs_salesProfile:(ACwXXX,...) -> ACwXXX (falls back to raw)."""
    s = norm(v)
    if 'ACw' in s:
        idx = s.index('ACw')
        tail = s[idx:]
        return tail.split(',')[0].strip()
    return s


def import_file(path: str):
    init_db()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    db = SessionLocal()
    try:
        # ---------------- Pass 1: Followup msg (campaigns, accounts, state) ----------------
        ws2 = wb['Followup msg']
        accounts: dict[str, Account] = {}
        campaigns: dict[str, Campaign] = {}
        processed: dict[tuple, dict] = {}
        replied_ids: set[str] = set()

        def get_account(name: str) -> Account:
            name = norm(name)
            if name and name not in accounts:
                a = db.execute(
                    select_db(Account).where(Account.name == name)
                ).scalar_one_or_none()
                if a is None:
                    a = Account(name=name, status='active',
                                session_ref=f'./cookies_files/{name.split()[0].lower()}_cookies.json')
                    db.add(a)
                    db.flush()
                accounts[name] = a
            return accounts.get(name)

        def get_campaign(key: str) -> Campaign:
            key = norm(key)
            if key and key not in campaigns:
                c = db.execute(
                    select_db(Campaign).where(Campaign.campaign_key == key)
                ).scalar_one_or_none()
                if c is None:
                    c = Campaign(campaign_key=key, name=key, status='active')
                    db.add(c)
                    db.flush()
                campaigns[key] = c
            return campaigns.get(key)

        rows2 = list(ws2.iter_rows(values_only=True))
        hdr2 = [norm(h) for h in rows2[0]]
        col = {h: i for i, h in enumerate(hdr2) if h}

        for raw in rows2[1:]:
            snid = clean_snid(raw[col['Sales Nav ID']])
            if not snid:
                continue
            camp_name = norm(raw[col['Campaigns']])
            camp = get_campaign(camp_name) if camp_name else None
            acct = get_account(norm(raw[col['Associate Account']]))
            # Pipeline status lives in 'Invite or InMail Status' (emoji-prefixed);
            # 'Lead Status' is free-text CRM state kept as crm_note.
            status_raw = re.sub(r'^[^a-z]*', '', norm(raw[col['Invite or InMail Status']]).lower()).strip()
            status = STATUS_MAP.get(status_raw, '')
            status_at = parse_date(raw[col['Invite or InMail Date']])
            crm_note = norm(raw[col['Lead Status']]) or None
            replied = boolish(raw[col['Received Replies']])
            reply_msg = norm(raw[col['Reply messages']]) or None
            replied_final = replied if replied is not None else bool(reply_msg)
            entry = {
                'campaign': camp, 'account': acct, 'status': status, 'status_at': status_at,
                'replied': replied_final, 'reply_msg': reply_msg, 'crm_note': crm_note,
            }
            # A lead may appear once per campaign; keep the most advanced row.
            key = (snid, camp.id if camp else None)
            prev = processed.get(key)
            if prev is None or (status and not prev['status']):
                processed[key] = entry
            if replied_final:
                replied_ids.add(snid)

        db.commit()

        # ---------------- Pass 2: Search Data (full pool) ----------------
        ws1 = wb['Search Data']
        rows1 = list(ws1.iter_rows(values_only=True))
        hdr1 = [norm(h) for h in rows1[0]]
        c1 = {h: i for i, h in enumerate(hdr1) if h}

        added = skipped = events = 0
        for raw in rows1[1:]:
            snid = clean_snid(raw[c1['Sales Nav ID']])
            if not snid:
                continue
            first = norm(raw[c1['FirstName']])
            last = norm(raw[c1['LastName']])
            full = norm(raw[c1['FullName']]) or f'{first} {last}'.strip()
            proc = processed.get((snid, None))  # pool rows are untagged

            # A processed row may exist for any campaign; attach campaign state:
            # prefer an explicit campaign match, else any processed entry.
            proc_entry = None
            camp = None
            for (s, cid), p in processed.items():
                if s == snid:
                    if proc_entry is None:
                        proc_entry = p
                    if p['campaign'] is not None:
                        camp = p['campaign']
                        proc_entry = p
                        break
            if proc_entry is None:
                proc_entry = proc

            # Replies travel with the lead regardless of campaign tagging
            is_replied = snid in replied_ids
            reply_msg_val = proc_entry['reply_msg'] if proc_entry else None
            if is_replied and not reply_msg_val:
                for (s, cid), p in processed.items():
                    if s == snid and p['reply_msg']:
                        reply_msg_val = p['reply_msg']
                        break

            existing = db.execute(
                select_db(Lead).where(Lead.sales_nav_id == snid)
            ).scalar_one_or_none()
            if existing is not None:
                skipped += 1
                continue

            opentomsg = boolish(raw[c1['Opentomsg']])
            linkedin = norm(raw[c1.get('Linkedin URL', -1)]) if 'Linkedin URL' in c1 else ''
            lead = Lead(
                sales_nav_id=snid,
                first_name=first, last_name=last, full_name=full,
                title=norm(raw[c1['Title']]),
                summary=norm(raw[c1.get('Summary', -1)]) if 'Summary' in c1 else '',
                location=norm(raw[c1.get('Location', -1)]) if 'Location' in c1 else '',
                company=norm(raw[c1['Company']]),
                premium=norm(raw[c1.get('Premium', -1)]) if 'Premium' in c1 else '',
                pending_invitation=norm(raw[c1.get('PendingInvitation', -1)]) if 'PendingInvitation' in c1 else '',
                viewed=norm(raw[c1.get('Viewed', -1)]) if 'Viewed' in c1 else '',
                opentomsg=opentomsg,
                linkedin_url=linkedin,
                source=LeadSource.CAMPAIGN_SEARCH.value if camp else LeadSource.LIST_IMPORT.value,
                campaign_id=camp.id if camp else None,
                associate_account_id=proc_entry['account'].id if proc_entry and proc_entry['account'] else None,
                status=proc_entry['status'] if proc_entry else '',
                status_changed_at=(proc_entry['status_at'] if proc_entry and proc_entry['status_at'] else None),
                received_replies=is_replied,
                reply_message=reply_msg_val,
                reply_received_at=proc_entry['status_at'] if (proc_entry and is_replied and proc_entry.get('status_at')) else None,
            )
            db.add(lead)
            db.flush()
            if proc_entry:
                if proc_entry['status']:
                    db.add(LeadEvent(lead_id=lead.id, kind='status_change',
                                     detail=f'imported as {proc_entry["status"]}', job_type='xlsx_import'))
                    events += 1
            if is_replied:
                db.add(LeadEvent(lead_id=lead.id, kind='reply',
                                 detail=(reply_msg_val or '')[:500], job_type='xlsx_import'))
                events += 1
            added += 1
            if added % 500 == 0:
                db.commit()
                print(f'  ...{added} leads imported')

        # ---------------- Pass 3: Followup-only leads (assigned in sheet 2
        # but absent from the Search Data pool) ----------------
        existing_ids = {s for (s,) in db.execute(select_db(Lead.sales_nav_id)).all()}
        fu_only_added = 0
        for (snid, _cid), p in processed.items():
            if snid in existing_ids:
                continue
            rows_for = [raw for raw in rows2[1:] if clean_snid(raw[col['Sales Nav ID']]) == snid]
            raw = rows_for[0] if rows_for else None
            first = norm(raw[col['FirstName']]) if raw else ''
            last = norm(raw[col['LastName']]) if raw else ''
            full = (norm(raw[col['FullName']]) if raw else '') or f'{first} {last}'.strip() or snid
            camp = p['campaign']
            lead = Lead(
                sales_nav_id=snid, first_name=first, last_name=last, full_name=full,
                title=norm(raw[col['Title']]) if raw else '',
                summary=norm(raw[col['Summary']]) if raw else '',
                location=norm(raw[col['Location']]) if raw else '',
                company=norm(raw[col['Company']]) if raw else '',
                premium=norm(raw[col['Premium']]) if raw else '',
                linkedin_url=norm(raw[col['Linkedin URL']]) if raw else '',
                source=LeadSource.CAMPAIGN_SEARCH.value if camp else LeadSource.LIST_IMPORT.value,
                campaign_id=camp.id if camp else None,
                associate_account_id=p['account'].id if p['account'] else None,
                status=p['status'], status_changed_at=p.get('status_at') or datetime.utcnow() if p['status'] else None,
                received_replies=p['replied'], reply_message=p['reply_msg'],
                reply_received_at=p.get('status_at') if (p['replied'] and p.get('status_at')) else None,
            )
            db.add(lead)
            db.flush()
            if p['status']:
                db.add(LeadEvent(lead_id=lead.id, kind='status_change',
                                 detail=f'imported as {p["status"]}', job_type='xlsx_import'))
            if p['replied']:
                db.add(LeadEvent(lead_id=lead.id, kind='reply',
                                 detail=(p['reply_msg'] or '')[:500], job_type='xlsx_import'))
            fu_only_added += 1
        db.commit()

        db.commit()
        print(f'DONE: {added} pool leads + {fu_only_added} followup-only leads imported, '
              f'{skipped} skipped (existing), {len(campaigns)} campaigns ensured, '
              f'{len(accounts)} accounts ensured, {events} events')
    finally:
        db.close()


# local import to avoid shadowing
from sqlalchemy import select as select_db  # noqa: E402

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx', help='Path to LinkedIn Outreach Automation.xlsx')
    args = ap.parse_args()
    import_file(args.xlsx)
