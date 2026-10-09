"""Historical workbook merge: LinkedIn Outreach Automation.xlsx -> OCC DB.

Two modes:
  python merge_xlsx_history.py <file.xlsx> --preview   (default: report only)
  python merge_xlsx_history.py <file.xlsx> --apply     (writes, never downgrades)
  python merge_xlsx_history.py --dedupe [--apply]      (no xlsx; clean DB dupes)

Sheets (current layout):
  'Overall Leads' = full pool; 'Invite or InMail Status' holds emoji statuses.
  'Processed'     = rows with campaign/account/status/reply history.

Safety rules enforced:
- Match by Sales Nav ID first, then normalized LinkedIn URL; name matches are
  reported as conflicts, never auto-merged.
- Never downgrade an existing stage; never clear replies/comments/categories.
- Historical dates are stored on the lead (first_contacted_at / follow-ups).
- Historical sends never consume today's quota (DailySendCount untouched).
- Row fingerprint stored on Lead.import_fp -> re-importing the same file skips.
- Unknown campaigns/accounts are reported; nothing is auto-created.
"""
import argparse
import hashlib
import re
import sys
from datetime import datetime, date

import openpyxl

from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Account, Campaign, Lead, LeadEvent, ReplyComment, ImportBatch  # noqa: E402
from app.classify import suggest_category  # noqa: E402

# Legacy sheet status -> app status machine (invite track + inmail track).
STATUS_MAP = {
    'sent invite': 'INVITE_SENT',
    'sent inmail': 'INMAIL_SENT',
    'sent after acceptance follow-up': 'INVITE_AFTER_ACCEPT',
    'sent invite follow-up 1': 'INVITE_FOLLOWUP_1',
    'sent invite follow-up 2': 'INVITE_FOLLOWUP_2',
    'sent invite follow-up 3': 'INVITE_FOLLOWUP_3',
    'sent inmail follow-up 1': 'INMAIL_FOLLOWUP_1',
    'sent inmail follow-up 2': 'INMAIL_FOLLOWUP_2',
    'sent inmail follow-up 3': 'INMAIL_FOLLOWUP_3',
}
STAGE_ORDER = ['', 'INVITE_SENT', 'INMAIL_SENT', 'INVITE_AFTER_ACCEPT',
               'INVITE_FOLLOWUP_1', 'INMAIL_FOLLOWUP_1',
               'INVITE_FOLLOWUP_2', 'INMAIL_FOLLOWUP_2',
               'INVITE_FOLLOWUP_3', 'INMAIL_FOLLOWUP_3']

TRUTHY = {'true', 'yes', '1', 'y', '✅yes'}
SEND_ERRORS = re.compile(r'HTTP 4\d\d|HTTP 5\d\d|Connection request HTTP|{"value"', re.IGNORECASE)


def norm(v) -> str:
    return str(v).strip() if v is not None else ''


def clean_snid(v) -> str:
    s = norm(v)
    if 'ACw' in s:
        return s[s.index('ACw'):].split(',')[0].strip()
    return s


def is_urn(v) -> str:
    """Return the exact 'urn:li:fs_salesProfile:(...)' string when the cell
    carries the full URN (newer exports), else ''."""
    s = norm(v)
    return s if s.startswith('urn:li:fs_salesProfile:') else ''


def boolish(v) -> bool:
    return norm(v).lower().startswith('yes') or norm(v).lower() in TRUTHY


def parse_date(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    s = norm(v)
    if not s:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%m/%d/%Y %H:%M', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def norm_url(u: str) -> str:
    s = norm(u).lower()
    return s.split('?')[0].rstrip('/')


def map_status(raw: str):
    """'📩 Sent Invite Follow-up 1' -> 'INVITE_FOLLOWUP_1'. Send errors -> None.
    Longest key wins: 'sent invite follow-up 1' must not match the shorter
    'sent invite' prefix (that bug flattened every historical follow-up row
    to a bare INVITE_SENT/INMAIL_SENT)."""
    s = norm(raw).lower()
    if not s or SEND_ERRORS.search(norm(raw)):
        return None
    s = re.sub(r'^[^a-z]+', '', s).strip()
    for key in sorted(STATUS_MAP, key=len, reverse=True):
        if s.startswith(key):
            return STATUS_MAP[key]
    return None


def channel_of(stage: str) -> str:
    return 'inmail' if stage.startswith('INMAIL') else 'invite'


def row_fp(*parts) -> str:
    return hashlib.sha256('|'.join(norm(p) for p in parts).encode()).hexdigest()[:16]


def set_urn(lead, raw_snid_cell) -> bool:
    """Store the exact sheet URN ('urn:li:fs_salesProfile:(ACw…,NAME_SEARCH,…)')
    on the lead. Returns True when the value was added/updated."""
    urn = is_urn(raw_snid_cell)
    if urn and (lead.sales_nav_urn or '') != urn:
        lead.sales_nav_urn = urn
        return True
    return False


def read_workbook(path: str):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = {}
    # Pool sheet: 'Overall Leads' in older exports, 'Leads' in newer ones.
    pool_name = next((n for n in ('Overall Leads', 'Leads') if n in wb.sheetnames), None)
    if not pool_name or 'Processed' not in wb.sheetnames:
        raise SystemExit(f"Expected a pool sheet ('Overall Leads'/'Leads') + 'Processed'. Sheets: {wb.sheetnames}")
    for name in (pool_name, 'Processed'):
        ws = wb[name]
        rows = list(ws.iter_rows(values_only=True))
        hdr = [norm(h) for h in rows[0]]
        col = {h: i for i, h in enumerate(hdr) if h}
        sheets[name] = (rows[1:], col)
    return sheets


def norm_url(u: str) -> str:
    s = norm(u).lower()
    return s.split('?')[0].rstrip('/')


# ---------------------------------------------------------------------------
# Dedupe: DB self-cleaning (no workbook needed)
# ---------------------------------------------------------------------------

def _normalize_snid(v) -> str:
    """Bare ACw profile token out of any id format ('urn:li:fs_salesProfile:
    (ACwXXX,NAME_SEARCH,zz)' -> 'ACwXXX')."""
    s = clean_snid(v)
    m = re.search(r'ACw[A-Za-z0-9_-]+', s)
    return m.group(0) if m else s


def _is_real_url(u: str) -> bool:
    s = norm(u).lower()
    return bool(s) and s not in ('0', '-', '--', 'n/a', 'na', 'none', 'null') \
        and ('linkedin.com' in s or s.startswith('/in/') or s.startswith('http'))


def run_dedupe(apply: bool = False):
    """Find and merge duplicate leads already in the DB. Duplicate = same
    normalized Sales Nav ID (urn vs bare formats collapse), or same normalized
    LinkedIn URL. The 'kept' row is the most engaged one (replied > stage
    depth > earlier created); the twin's engagement data is merged in, then
    the twin is deleted. Also normalizes urn snids and strips junk URLs.
    Returns a list of report lines."""
    from sqlalchemy import select, or_
    db = SessionLocal()
    report = {'urn_normalized': 0, 'junk_urls': 0, 'merged_groups': 0,
              'deleted': 0, 'replies_rescued': 0, 'comments_rescued': 0,
              'events_rescued': 0, 'kept_snapshots': []}
    try:
        leads = db.execute(select(Lead)).scalars().all()

        # --- Pass A: normalize urn-format snids in place --------------------
        by_snid: dict[str, list] = {}
        for lead in leads:
            nsnid = _normalize_snid(lead.sales_nav_id)
            if nsnid != lead.sales_nav_id:
                lead.sales_nav_id = nsnid
                report['urn_normalized'] += 1
            by_snid.setdefault(nsnid, []).append(lead)

        # --- Pass B: junk URL cleanup (keeps gap-fill from re-caching) ------
        for lead in leads:
            if lead.linkedin_url and not _is_real_url(lead.linkedin_url):
                lead.linkedin_url = ''
                report['junk_urls'] += 1

        db.flush()

        # --- Pass C: group twins -------------------------------------------
        groups: list[list] = []
        seen_ids: set[int] = set()
        for lead in leads:
            if lead.id in seen_ids:
                continue
            twins = list({t.id: t for t in by_snid.get(lead.sales_nav_id, [])}.values()) \
                if lead.sales_nav_id else [lead]
            if len(twins) == 1 and _is_real_url(lead.linkedin_url):
                lurl = norm_url(lead.linkedin_url)
                twins += [t for t in leads
                          if t.id != lead.id and t.id not in seen_ids
                          and t.sales_nav_id != lead.sales_nav_id
                          and _is_real_url(t.linkedin_url)
                          and norm_url(t.linkedin_url) == lurl]
            if len(twins) > 1:
                seen_ids.update(t.id for t in twins)
                groups.append(twins)

        STAGE_DEPTH = {s: i for i, s in enumerate(STAGE_ORDER)}

        def keep_rank(t):
            # replied leads always win; then deepest stage; then oldest row.
            return (1 if t.received_replies else 0,
                    STAGE_DEPTH.get(t.status or '', 0),
                    -t.id)

        for twins in groups:
            twins.sort(key=keep_rank, reverse=True)
            keep, extras = twins[0], twins[1:]
            changed = []
            for extra in extras:
                wanted_campaign = wanted_source = None
                # Engagement first: a reply on a twin must survive the merge.
                if extra.received_replies and not keep.received_replies:
                    keep.received_replies = True
                    keep.reply_message = extra.reply_message or keep.reply_message
                    keep.reply_received_at = extra.reply_received_at or datetime.utcnow()
                    keep.reply_category = extra.reply_category or keep.reply_category
                    keep.reply_category_source = extra.reply_category_source or keep.reply_category_source
                    keep.reply_category_at = datetime.utcnow()
                    keep.review_status = keep.review_status or 'needs_review'
                    report['replies_rescued'] += 1
                    changed.append('reply-rescued')
                if extra.last_followup_at and (not keep.last_followup_at or extra.last_followup_at > keep.last_followup_at):
                    keep.last_followup_at = extra.last_followup_at
                    keep.last_followup_stage = extra.last_followup_stage or keep.last_followup_stage
                    changed.append('followup-latest')
                depth_extra, depth_keep = STAGE_DEPTH.get(extra.status or '', 0), STAGE_DEPTH.get(keep.status or '', 0)
                if depth_extra > depth_keep:
                    keep.status = extra.status
                    keep.status_changed_at = extra.status_changed_at or keep.status_changed_at
                    changed.append(f'stage->{extra.status}')
                for attr in ('first_name', 'last_name', 'title', 'company', 'location',
                             'summary', 'linkedin_url', 'opentomsg', 'premium',
                             'first_contacted_at', 'contact_channel', 'associate_account_id'):
                    ev, kv = getattr(extra, attr), getattr(keep, attr)
                    if ev in (None, '') or (attr == 'linkedin_url' and not _is_real_url(ev)):
                        continue
                    if attr == 'opentomsg':
                        if keep.opentomsg is None:
                            keep.opentomsg = ev
                            changed.append('opentomsg')
                    elif kv in (None, ''):
                        setattr(keep, attr, ev)
                        changed.append(attr)
                if not keep.campaign_id and extra.campaign_id:
                    wanted_campaign, wanted_source = extra.campaign_id, extra.source
                # Never lose history: move events + comments onto the keeper.
                for ev_row in db.execute(select(LeadEvent).where(LeadEvent.lead_id == extra.id)).scalars():
                    ev_row.lead_id = keep.id
                    report['events_rescued'] += 1
                for c_row in db.execute(select(ReplyComment).where(ReplyComment.lead_id == extra.id)).scalars():
                    c_row.lead_id = keep.id
                    report['comments_rescued'] += 1
                db.delete(extra)
                report['deleted'] += 1
                if wanted_campaign is not None:
                    # The twin must be gone BEFORE the keeper takes its
                    # campaign: both rows share the same sales_nav_id, and the
                    # (sales_nav_id, campaign_id) unique index would trip while
                    # the twin still exists (updates flush before deletes).
                    db.flush()
                    keep.campaign_id = wanted_campaign
                    keep.source = wanted_source or 'campaign_search'
                    changed.append('campaign-kept')
            if changed:
                report['merged_groups'] += 1
                if len(report['kept_snapshots']) < 15:
                    report['kept_snapshots'].append(
                        f"kept #{keep.id} {keep.full_name} [{', '.join(changed[:4])}]"
                        f" <- removed {', '.join('#' + str(x.id) for x in extras)}")

        if apply:
            db.commit()
        else:
            db.rollback()

        lines = ['DEDUPE ' + ('APPLIED.' if apply else 'PREVIEW ONLY — nothing written. Re-run with --apply to write.'),
                 f"urn-format snids normalized: {report['urn_normalized']}",
                 f"junk urls cleared: {report['junk_urls']}",
                 f"duplicate groups merged: {report['merged_groups']}",
                 f"twin rows deleted: {report['deleted']}",
                 f"replies rescued from twins: {report['replies_rescued']}",
                 f"events moved to keepers: {report['events_rescued']}",
                 f"comments moved to keepers: {report['comments_rescued']}"]
        lines += ['  ' + s for s in report['kept_snapshots']]
        return lines
    finally:
        db.close()


def run_retag(path: str, apply: bool = False, create_missing: bool = False):
    """Attach campaign tags from the workbook's pool sheet ('Campaigns'
    column) to DB leads that arrived 'untagged'. The original merge treated
    unknown campaigns as report-only, so thousands of leads sat untagged even
    though the workbook knew their campaign. Modes:
    - campaigns that already exist in the app: leads are tagged directly
    - unknown campaigns: reported, or created with --create-campaigns
      (exact campaign_key from the sheet, e.g. 'GCC-Cynthia', 'GCC').
    Never re-tags a lead that already has a campaign. Returns report lines."""
    from sqlalchemy import select
    pool_name, pool_rows, pool_col = _pool_sheet(path)
    db = SessionLocal()
    report = {'tagged': 0, 'already_tagged': 0, 'no_campaign_in_sheet': 0,
              'created_campaigns': [], 'unknown_campaigns': set(),
              'per_campaign': {}}
    try:
        def camp_key(raw):
            return norm(raw)

        campaigns = {c.campaign_key: c for c in db.execute(select(Campaign)).scalars()}

        # snid -> campaign name from the sheet (last non-empty wins).
        camp_by_snid: dict[str, str] = {}
        for raw in pool_rows:
            snid = _normalize_snid(raw[pool_col['Sales Nav ID']]) if 'Sales Nav ID' in pool_col else ''
            if not snid:
                continue
            c = camp_key(raw[pool_col['Campaigns']]) if 'Campaigns' in pool_col else ''
            if c:
                camp_by_snid[snid] = c

        untagged = db.execute(select(Lead).where(Lead.campaign_id.is_(None))).scalars().all()
        for lead in untagged:
            c = camp_by_snid.get(lead.sales_nav_id, '')
            if not c:
                report['no_campaign_in_sheet'] += 1
                continue
            camp = campaigns.get(c)
            if camp is None and create_missing:
                camp = Campaign(name=c, campaign_key=c)
                db.add(camp)
                db.flush()
                campaigns[c] = camp
                report['created_campaigns'].append(c)
            if camp is None:
                report['unknown_campaigns'].add(c)
                continue
            lead.campaign_id = camp.id
            if lead.source == 'list_import':
                lead.source = 'campaign_search'
            report['tagged'] += 1
            report['per_campaign'][c] = report['per_campaign'].get(c, 0) + 1

        if apply:
            db.add(ImportBatch(
                source=path, mode='retag', stats={
                    'tagged': report['tagged'],
                    'created_campaigns': report['created_campaigns'],
                    'unknown_campaigns': sorted(report['unknown_campaigns']),
                    'per_campaign': report['per_campaign'],
                }))
            db.commit()
        else:
            db.rollback()

        lines = [f'RETAG {"APPLIED." if apply else "PREVIEW ONLY — nothing written. Re-run with --apply."}',
                 f"leads tagged: {report['tagged']}",
                 f"untagged leads with no campaign in the sheet: {report['no_campaign_in_sheet']}"]
        if report['created_campaigns']:
            lines.append('campaigns created: ' + ', '.join(sorted(report['created_campaigns'])))
        if report['unknown_campaigns']:
            lines.append('unknown campaigns (not created; pass --create-campaigns): '
                         + ', '.join(sorted(report['unknown_campaigns'])))
        for c in sorted(report['per_campaign']):
            lines.append(f'  {c}: {report["per_campaign"][c]}')
        return lines
    finally:
        db.close()


def run_replace(path: str, apply: bool = False, limit: int = 0):
    """REPLACE mode: the workbook is the source of truth.

    Normal merge/retag modes are deliberately conservative (gap-fill only,
    never overwrite). This mode does the opposite — for every lead found in
    the workbook, DB values are OVERWRITTEN with the sheet values:
      - profile fields (title, summary, location, company, premium, etc.)
      - linkedin_url (junk sheet values like '0' are ignored)
      - opentomsg / pending_invitation / viewed flags
      - stage: set to the sheet's status, even if that DOWNGRADES the DB
      - replies: replaced by the sheet's reply text/flag
      - campaign + associate account: set to EXACTLY what the sheet says
        (including clearing a DB campaign the sheet doesn't list)
    Leads not present in the workbook are left untouched; DB-only leads are
    never deleted. Rows in the sheet with an empty Campaigns cell clear the
    DB campaign (source of truth = the sheet). Unknown campaigns/accounts
    are auto-created so the sheet's names always end up usable. Returns
    report lines."""
    from sqlalchemy import select
    sheets = read_workbook(path)
    pool_name = next(n for n in sheets if n != 'Processed')
    pool_rows, pool_col = sheets[pool_name]
    proc_rows, proc_col = sheets['Processed']
    if limit:
        pool_rows = pool_rows[:limit]
        proc_rows = proc_rows[:limit]

    report = {'updated': 0, 'unchanged': 0, 'new_leads': 0, 'replaced_replies': 0,
              'campaigns_created': [], 'accounts_created': [],
              'campaign_cleared': 0, 'field_changes': 0, 'stage_upgrades': 0,
              'stage_downgrades': 0, 'samples': []}

    # Processed-sheet index (same ranking as the normal merge: most advanced
    # row wins) — supplies status/reply truth. Campaign/account truth is
    # collected separately from ALL rows per snid: the most-advanced row often
    # has an empty Campaigns cell while sibling rows carry it, and a 'replace'
    # must not wipe tags the sheet genuinely knows.
    proc_by_snid: dict[str, dict] = {}
    camp_by_snid: dict[str, str] = {}
    acct_by_snid: dict[str, str] = {}
    for i, raw in enumerate(proc_rows, start=2):
        snid = clean_snid(raw[proc_col['Sales Nav ID']]) if 'Sales Nav ID' in proc_col else ''
        if not snid:
            continue
        stage_raw = norm(raw[proc_col['Invite or InMail Status']]) if 'Invite or InMail Status' in proc_col else ''
        stage = map_status(stage_raw)
        entry = {'campaign_key': norm(raw[proc_col['Campaigns']]) if 'Campaigns' in proc_col else '',
                 'account_name': norm(raw[proc_col['Associate Account']]) if 'Associate Account' in proc_col else '',
                 'stage': stage,
                 'stage_at': parse_date(raw[proc_col['Invite or InMail Date']]) if 'Invite or InMail Date' in proc_col else None,
                 'replied': boolish(raw[proc_col['Received Replies']]) if 'Received Replies' in proc_col else False,
                 'reply_msg': norm(raw[proc_col['Reply messages']]) if 'Reply messages' in proc_col else ''}
        prev = proc_by_snid.get(snid)
        if prev is None or (entry['stage'] and STAGE_ORDER.index(entry['stage'] or '') > STAGE_ORDER.index(prev['stage'] or '')):
            proc_by_snid[snid] = entry
        if entry['campaign_key']:
            camp_by_snid[snid] = entry['campaign_key']
        if entry['account_name']:
            acct_by_snid[snid] = entry['account_name']

    db = SessionLocal()
    try:
        campaigns = {c.campaign_key: c for c in db.execute(select(Campaign)).scalars()}
        accounts = {a.name: a for a in db.execute(select(Account)).scalars()}
        # One snid->lead map up front: a per-row point query over 9k rows made
        # replace runs take minutes; this makes them take seconds.
        lead_by_snid: dict[str, Lead] = {
            l.sales_nav_id: l for l in db.execute(select(Lead)).scalars()}

        def ensure_campaign(key: str):
            if not key:
                return None
            if key not in campaigns:
                c = Campaign(name=key, campaign_key=key)
                db.add(c)
                db.flush()
                campaigns[key] = c
                report['campaigns_created'].append(key)
            return campaigns[key]

        def ensure_account(name: str):
            if not name:
                return None
            if name not in accounts:
                a = Account(name=name)
                db.add(a)
                db.flush()
                accounts[name] = a
                report['accounts_created'].append(name)
            return accounts[name]

        def set_field(lead, attr, new, changed, real_check=False):
            old = getattr(lead, attr)
            if real_check and new and not _is_real_url(new):
                return  # junk sheet value: leave whatever the DB has
            if (old or '') != (new or ''):
                setattr(lead, attr, new or '')
                changed.append(attr)

        # ---- Replace every lead present in the pool sheet -----------------
        for i, raw in enumerate(pool_rows, start=2):
            snid = clean_snid(raw[pool_col['Sales Nav ID']]) if 'Sales Nav ID' in pool_col else ''
            if not snid:
                continue
            first = norm(raw[pool_col['FirstName']]) if 'FirstName' in pool_col else ''
            last = norm(raw[pool_col['LastName']]) if 'LastName' in pool_col else ''
            full = norm(raw[pool_col['FullName']]) if 'FullName' in pool_col else ''
            full = full or f'{first} {last}'.strip() or snid
            proc = proc_by_snid.get(snid) or {}
            lead = lead_by_snid.get(snid)

            created = lead is None
            if created:
                lead = Lead(sales_nav_id=snid, first_name=first, last_name=last,
                            full_name=full, source='list_import')
                db.add(lead)
                db.flush()
                lead_by_snid[snid] = lead
                report['new_leads'] += 1

            changed = []
            set_field(lead, 'full_name', full, changed)
            set_field(lead, 'first_name', first, changed)
            set_field(lead, 'last_name', last, changed)
            set_urn(lead, raw[pool_col['Sales Nav ID']] if 'Sales Nav ID' in pool_col else '') \
                and changed.append('sales_nav_urn')
            for col, attr in (('Title', 'title'), ('Summary', 'summary'), ('Location', 'location'),
                              ('Company', 'company'), ('Premium', 'premium'),
                              ('PendingInvitation', 'pending_invitation'), ('Viewed', 'viewed')):
                if col in pool_col:
                    set_field(lead, attr, norm(raw[pool_col[col]]), changed)
            if 'Opentomsg' in pool_col:
                ot = norm(raw[pool_col['Opentomsg']]).lower() in ('true', '1', 'yes')
                if lead.opentomsg != ot:
                    lead.opentomsg = ot
                    changed.append('opentomsg')
            if 'Linkedin URL' in pool_col:
                set_field(lead, 'linkedin_url', norm(raw[pool_col['Linkedin URL']]), changed, real_check=True)
            if not (lead.linkedin_url or '').strip() and proc.get('linkedin_url'):
                set_field(lead, 'linkedin_url', proc['linkedin_url'], changed, real_check=True)

            # Stage truth: apply the sheet's status even if it downgrades.
            stage = proc.get('stage')
            if stage:
                if lead.status != stage:
                    cur, new = STAGE_ORDER.index(lead.status or ''), STAGE_ORDER.index(stage)
                    report['stage_upgrades' if new > cur else 'stage_downgrades'] += 1
                    lead.status = stage
                    changed.append(f'stage->{stage}')
                if proc.get('stage_at'):
                    if lead.first_contacted_at != proc['stage_at']:
                        lead.first_contacted_at = proc['stage_at']
                        changed.append('first_contacted_at')
                    lead.contact_channel = channel_of(stage)
                    if lead.status_changed_at != proc['stage_at']:
                        lead.status_changed_at = proc['stage_at']
                        changed.append('status_changed_at')

            # Reply truth: replace DB reply with the sheet's reply.
            sheet_reply = proc.get('reply_msg', '')
            sheet_replied = bool(proc.get('replied') or sheet_reply.strip())
            if sheet_replied:
                if (lead.reply_message or '') != sheet_reply:
                    lead.received_replies = True
                    lead.reply_message = sheet_reply or None
                    lead.reply_received_at = proc.get('stage_at') or lead.reply_received_at
                    cat, csrc = suggest_category(sheet_reply)
                    lead.reply_category, lead.reply_category_source = cat, csrc
                    lead.reply_category_at = datetime.utcnow()
                    lead.review_status = lead.review_status or 'needs_review'
                    changed.append('reply-replaced')
                    report['replaced_replies'] += 1
            elif 'Received Replies' in proc_col and proc.get('replied') is False and lead.received_replies:
                # Sheet says not replied and has no message: clear DB reply.
                lead.received_replies = False
                lead.reply_message = None
                changed.append('reply-cleared')

            # Campaign/account truth: what the sheet says anywhere for this
            # snid (Processed sheet rows, then the pool row's own cells;
            # empty only when NO sheet source mentions one -> clear).
            sheet_camp = camp_by_snid.get(snid, '')
            if not sheet_camp and 'Campaigns' in pool_col:
                sheet_camp = norm(raw[pool_col['Campaigns']])
            sheet_acct = acct_by_snid.get(snid, '')
            if not sheet_acct and 'Associate Account' in pool_col:
                sheet_acct = norm(raw[pool_col['Associate Account']])
            camp = ensure_campaign(sheet_camp)
            if (lead.campaign_id or None) != (camp.id if camp else None):
                if camp is None and lead.campaign_id is not None:
                    report['campaign_cleared'] += 1
                lead.campaign_id = camp.id if camp else None
                lead.source = 'campaign_search' if camp else 'list_import'
                changed.append('campaign')
            acct = ensure_account(sheet_acct)
            if (lead.associate_account_id or None) != (acct.id if acct else None):
                lead.associate_account_id = acct.id if acct else None
                changed.append('account')

            if changed:
                report['updated'] += 1
                report['field_changes'] += len(changed)
                if len(report['samples']) < 15:
                    report['samples'].append(
                        f"{'new' if created else 'upd'} #{lead.id} {full}: {', '.join(changed[:5])}")
            else:
                report['unchanged'] += 1

        if apply:
            db.add(ImportBatch(
                source=path, mode='replace', stats={
                    'updated': report['updated'], 'new_leads': report['new_leads'],
                    'unchanged': report['unchanged'], 'replaced_replies': report['replaced_replies'],
                    'campaign_cleared': report['campaign_cleared'],
                    'campaigns_created': report['campaigns_created'],
                    'accounts_created': report['accounts_created'],
                    'field_changes': report['field_changes'],
                }))
            db.commit()
        else:
            db.rollback()

        lines = [f'REPLACE {"APPLIED." if apply else "PREVIEW ONLY — nothing written. Re-run with --apply."}',
                 f"leads updated (fields overwritten from the sheet): {report['updated']}",
                 f"leads unchanged (sheet matches DB): {report['unchanged']}",
                 f"leads added (in sheet, not in DB): {report['new_leads']}",
                 f"replies replaced from the sheet: {report['replaced_replies']}",
                 f"stage changes: {report['stage_upgrades']} upgraded / {report['stage_downgrades']} DOWNGRADED to the sheet's value",
                 f"campaign tags cleared (sheet row has no campaign): {report['campaign_cleared']}",
                 f"campaigns created: {', '.join(sorted(set(report['campaigns_created']))) or '—'}",
                 f"accounts created: {', '.join(sorted(set(report['accounts_created']))) or '—'}"]
        lines += ['  ' + s for s in report['samples']]
        return lines
    finally:
        db.close()


def _pool_sheet(path: str):
    """(pool_sheet_name, data_rows, col_index_map) for the pool sheet."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    pool_name = next((n for n in ('Overall Leads', 'Leads') if n in wb.sheetnames), None)
    if not pool_name:
        raise SystemExit(f"Expected a pool sheet ('Overall Leads'/'Leads'). Sheets: {wb.sheetnames}")
    rows = list(wb[pool_name].iter_rows(values_only=True))
    hdr = [norm(h) for h in rows[0]]
    wb.close()
    return pool_name, rows[1:], {h: i for i, h in enumerate(hdr) if h}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx', nargs='?', help='Workbook path (omit with --dedupe)')
    ap.add_argument('--apply', action='store_true', help='Write changes (default preview)')
    ap.add_argument('--limit', type=int, default=0, help='Process at most N rows (testing)')
    ap.add_argument('--dedupe', action='store_true',
                    help='No workbook: find/merge duplicate leads already in the DB')
    ap.add_argument('--retag', action='store_true',
                    help='Attach sheet campaign names to untagged DB leads')
    ap.add_argument('--replace', action='store_true',
                    help='Workbook is the source of truth: overwrite DB fields, '
                         'stages, replies, campaign/account tags from the sheet')
    ap.add_argument('--create-campaigns', action='store_true',
                    help='With --retag: create campaigns that are missing in the app')
    args = ap.parse_args()
    init_db()
    if args.dedupe:
        print('\n'.join(run_dedupe(apply=args.apply)))
        return
    if args.retag:
        if not args.xlsx:
            ap.error('--retag needs an .xlsx path')
        print('\n'.join(run_retag(args.xlsx, apply=args.apply,
                                  create_missing=args.create_campaigns)))
        return
    if args.replace:
        if not args.xlsx:
            ap.error('--replace needs an .xlsx path')
        print('\n'.join(run_replace(args.xlsx, apply=args.apply, limit=args.limit)))
        return
    if not args.xlsx:
        ap.error('provide an .xlsx path, or use --dedupe / --retag / --replace')
    lines = run_merge(args.xlsx, apply=args.apply, limit=args.limit)
    print('\n'.join(lines))


def run_merge(path: str, apply: bool = False, limit: int = 0):
    """Preview or apply the historical merge. Returns a list of report lines."""
    init_db()
    sheets = read_workbook(path)
    pool_name = next(n for n in sheets if n != 'Processed')
    pool_rows, pool_col = sheets[pool_name]
    proc_rows, proc_col = sheets['Processed']
    if limit:
        pool_rows = pool_rows[:limit]
        proc_rows = proc_rows[:limit]

    report = {
        'new_leads': 0, 'enriched': 0, 'duplicates': 0,
        'conflicts': [], 'invalid': [], 'unknown_campaigns': set(),
        'unknown_accounts': set(), 'replied_imported': 0, 'review_flagged': 0,
        'replies_by_msg': 0, 'urls_backfilled': 0,
    }

    # ---- Pass 1: Processed sheet (campaign/account/status/replies) ----------
    proc_by_snid: dict[str, dict] = {}
    for i, raw in enumerate(proc_rows, start=2):
        snid = clean_snid(raw[proc_col['Sales Nav ID']]) if 'Sales Nav ID' in proc_col else ''
        if not snid:
            continue
        stage_raw = norm(raw[proc_col['Invite or InMail Status']]) if 'Invite or InMail Status' in proc_col else ''
        stage = map_status(stage_raw)
        entry = {
            'row': i,
            'linkedin_url': norm(raw[proc_col['Linkedin URL']]) if 'Linkedin URL' in proc_col else '',
            'campaign_key': norm(raw[proc_col['Campaigns']]) if 'Campaigns' in proc_col else '',
            'account_name': norm(raw[proc_col['Associate Account']]) if 'Associate Account' in proc_col else '',
            'stage': stage,
            'stage_raw': stage_raw,
            'stage_at': parse_date(raw[proc_col['Invite or InMail Date']]) if 'Invite or InMail Date' in proc_col else None,
            'replied': boolish(raw[proc_col['Received Replies']]) if 'Received Replies' in proc_col else False,
            'reply_msg': norm(raw[proc_col['Reply messages']]) if 'Reply messages' in proc_col else '',
            'crm_note': norm(raw[proc_col['Lead Status']]) if 'Lead Status' in proc_col else '',
            'fp': row_fp(snid, raw[proc_col['Campaigns']] if 'Campaigns' in proc_col else '',
                         raw[proc_col['Invite or InMail Status']] if 'Invite or InMail Status' in proc_col else '',
                         raw[proc_col['Invite or InMail Date']] if 'Invite or InMail Date' in proc_col else ''),
        }
        # Keep the most advanced row per lead.
        prev = proc_by_snid.get(snid)
        if prev is None or (entry['stage'] and STAGE_ORDER.index(entry['stage'] or '') > STAGE_ORDER.index(prev['stage'] or '')):
            proc_by_snid[snid] = entry

    db = SessionLocal()
    try:
        campaigns = {c.campaign_key: c for c in db.execute(__import__('sqlalchemy').select(Campaign)).scalars()}
        accounts = {a.name: a for a in db.execute(__import__('sqlalchemy').select(Account)).scalars()}

        # ---- Pass 2: Overall Leads pool -> upsert --------------------------
        for i, raw in enumerate(pool_rows, start=2):
            snid = clean_snid(raw[pool_col['Sales Nav ID']]) if 'Sales Nav ID' in pool_col else ''
            if not snid:
                continue
            if 'FullName' not in pool_col and 'FirstName' not in pool_col:
                report['invalid'].append(f'row {i}: no name columns')
                continue
            first = norm(raw[pool_col['FirstName']]) if 'FirstName' in pool_col else ''
            last = norm(raw[pool_col['LastName']]) if 'LastName' in pool_col else ''
            full = norm(raw[pool_col['FullName']]) if 'FullName' in pool_col else ''
            full = full or f'{first} {last}'.strip() or snid
            fp = row_fp(snid, full, norm(raw[pool_col['Updated Date']]) if 'Updated Date' in pool_col else '')
            proc = proc_by_snid.get(snid)
            lead = db.execute(__import__('sqlalchemy').select(Lead).where(Lead.sales_nav_id == snid)).scalar_one_or_none()

            if lead is None:
                campaign = accounts_use = None
                campaign_id = None
                account_id = None
                if proc:
                    ck = proc['campaign_key']
                    if ck:
                        if ck in campaigns:
                            campaign_id = campaigns[ck].id
                        else:
                            report['unknown_campaigns'].add(ck)
                    an = proc['account_name']
                    if an:
                        if an in accounts:
                            account_id = accounts[an].id
                        else:
                            report['unknown_accounts'].add(an)
                stage = proc['stage'] if proc else None
                reply_msg = proc['reply_msg'] if proc else ''
                # Exports often omit the yes flag but include the message text.
                replied = bool(proc and (proc['replied'] or reply_msg.strip()))
                if replied and not proc['replied']:
                    report['replies_by_msg'] += 1
                cat, csrc = suggest_category(reply_msg) if replied else ('', '')
                lead = Lead(
                    sales_nav_id=snid, first_name=first, last_name=last, full_name=full,
                    sales_nav_urn=is_urn(raw[pool_col['Sales Nav ID']]) if 'Sales Nav ID' in pool_col else '',
                    title=norm(raw[pool_col['Title']]) if 'Title' in pool_col else '',
                    summary=norm(raw[pool_col['Summary']]) if 'Summary' in pool_col else '',
                    location=norm(raw[pool_col['Location']]) if 'Location' in pool_col else '',
                    company=norm(raw[pool_col['Company']]) if 'Company' in pool_col else '',
                    premium=norm(raw[pool_col['Premium']]) if 'Premium' in pool_col else '',
                    pending_invitation=norm(raw[pool_col['PendingInvitation']]) if 'PendingInvitation' in pool_col else '',
                    viewed=norm(raw[pool_col['Viewed']]) if 'Viewed' in pool_col else '',
                    opentomsg=(norm(raw[pool_col['Opentomsg']]).lower() in ('true', '1', 'yes')) if 'Opentomsg' in pool_col else None,
                    linkedin_url=norm(raw[pool_col['Linkedin URL']]) if 'Linkedin URL' in pool_col else '',
                    source='campaign_search' if campaign_id else 'list_import',
                    campaign_id=campaign_id, associate_account_id=account_id,
                    status=stage or '', status_changed_at=proc['stage_at'] if proc and stage else None,
                    first_contacted_at=proc['stage_at'] if proc and stage and proc['stage_at'] else None,
                    contact_channel=channel_of(stage) if stage else '',
                    received_replies=replied,
                    reply_message=reply_msg or None,
                    reply_received_at=proc['stage_at'] if replied and proc and proc['stage_at'] else None,
                    reply_category=cat, reply_category_source=csrc if replied else '',
                    reply_category_at=datetime.utcnow() if replied else None,
                    review_status='needs_review' if replied else '',
                    import_fp=fp,
                )
                db.add(lead)
                db.flush()
                if stage:
                    db.add(LeadEvent(lead_id=lead.id, kind='status_change',
                                     detail=f'imported as {stage} (workbook history)', job_type='xlsx_merge'))
                if replied:
                    db.add(LeadEvent(lead_id=lead.id, kind='reply',
                                     detail=(reply_msg or '')[:500], job_type='xlsx_merge'))
                    report['replied_imported'] += 1
                if proc and proc['crm_note']:
                    db.add(ReplyComment(lead_id=lead.id, author='xlsx-import',
                                        body=f"CRM note (Processed row {proc['row']}): {proc['crm_note']}"))
                report['new_leads'] += 1
                continue

            # ---- Existing lead: enrich, never downgrade --------------------
            if lead.import_fp == fp:
                changed = []
                # Fingerprint duplicates still get gap-fills for data the export
                # carries but the DB lacks (replies-by-message, LinkedIn URLs).
                if set_urn(lead, raw[pool_col['Sales Nav ID']] if 'Sales Nav ID' in pool_col else ''):
                    changed.append('urn-backfill')
                if proc:
                    if proc['reply_msg'].strip() and not lead.received_replies:
                        lead.received_replies = True
                        lead.reply_message = proc['reply_msg']
                        lead.reply_received_at = proc['stage_at'] or datetime.utcnow()
                        cat, csrc = suggest_category(proc['reply_msg'])
                        lead.reply_category, lead.reply_category_source = cat, csrc
                        lead.reply_category_at = datetime.utcnow()
                        lead.review_status = 'needs_review'
                        db.add(LeadEvent(lead_id=lead.id, kind='reply',
                                         detail=proc['reply_msg'][:500], job_type='xlsx_merge'))
                        report['replied_imported'] += 1
                        report['replies_by_msg'] += 1
                        changed.append('reply-imported')
                    if proc['linkedin_url'] and not (lead.linkedin_url or '').strip():
                        lead.linkedin_url = proc['linkedin_url']
                        changed.append('url-backfill')
                        report['urls_backfilled'] += 1
                    pool_url = norm(raw[pool_col['Linkedin URL']]) if 'Linkedin URL' in pool_col else ''
                    if pool_url and not (lead.linkedin_url or '').strip():
                        lead.linkedin_url = pool_url
                        changed.append('url-backfill')
                        report['urls_backfilled'] += 1
                if changed:
                    report['enriched'] += 1
                else:
                    report['duplicates'] += 1
                continue
            changed = []
            if proc:
                stage = proc['stage']
                cur_idx = STAGE_ORDER.index(lead.status or '')
                if stage and STAGE_ORDER.index(stage) > cur_idx and lead.received_replies is False:
                    lead.status = stage
                    lead.status_changed_at = proc['stage_at'] or lead.status_changed_at
                    if not lead.first_contacted_at:
                        lead.first_contacted_at = proc['stage_at']
                        lead.contact_channel = channel_of(stage)
                    changed.append(f'stage->{stage}')
                if proc['replied'] or proc['reply_msg'].strip():
                    if not lead.received_replies:
                        lead.received_replies = True
                        lead.reply_message = proc['reply_msg'] or lead.reply_message
                        lead.reply_received_at = proc['stage_at'] or datetime.utcnow()
                        cat, csrc = suggest_category(proc['reply_msg'])
                        lead.reply_category = cat
                        lead.reply_category_source = csrc
                        lead.reply_category_at = datetime.utcnow()
                        lead.review_status = 'needs_review'
                        db.add(LeadEvent(lead_id=lead.id, kind='reply',
                                         detail=(proc['reply_msg'] or '')[:500], job_type='xlsx_merge'))
                        report['replied_imported'] += 1
                        if not proc['replied']:
                            report['replies_by_msg'] += 1
                        changed.append('reply-imported')
                    else:
                        # Reply already known: never overwrite text/category/comments.
                        report['review_flagged'] += 1
                        if proc['reply_msg'] and proc['reply_msg'] != (lead.reply_message or ''):
                            report['conflicts'].append(
                                f'row {i} ({full}): reply text differs from stored reply — kept stored version')
                if proc['account_name']:
                    if proc['account_name'] in accounts:
                        if not lead.associate_account_id:
                            lead.associate_account_id = accounts[proc['account_name']].id
                            changed.append(f"account->{proc['account_name']}")
                    else:
                        report['unknown_accounts'].add(proc['account_name'])
                if proc['campaign_key']:
                    if proc['campaign_key'] in campaigns:
                        if not lead.campaign_id:
                            lead.campaign_id = campaigns[proc['campaign_key']].id
                            lead.source = 'campaign_search'
                            changed.append(f"campaign->{proc['campaign_key']}")
                    else:
                        report['unknown_campaigns'].add(proc['campaign_key'])
                if proc['crm_note'] and not lead.import_fp:
                    db.add(ReplyComment(lead_id=lead.id, author='xlsx-import',
                                        body=f"CRM note (Processed row {proc['row']}): {proc['crm_note']}"))
                    changed.append('crm-note-added')
            set_urn(lead, raw[pool_col['Sales Nav ID']] if 'Sales Nav ID' in pool_col else '') \
                and changed.append('urn-backfill')
            if not lead.first_contacted_at and lead.status and lead.status_changed_at:
                lead.first_contacted_at = lead.status_changed_at
                lead.contact_channel = channel_of(lead.status)
                changed.append('contact-date-backfilled')
            # LinkedIn URL gap-fill (pool or Processed sheet), never overwrite.
            pool_url = norm(raw[pool_col['Linkedin URL']]) if 'Linkedin URL' in pool_col else ''
            if not (lead.linkedin_url or '').strip() and (pool_url or (proc and proc['linkedin_url'])):
                lead.linkedin_url = pool_url or proc['linkedin_url']
                changed.append('url-backfill')
                report['urls_backfilled'] += 1
            if changed:
                lead.import_fp = fp
                report['enriched'] += 1
            else:
                report['duplicates'] += 1

        # ---- Pass 3: Processed-only leads (not in the pool sheet) ----------
        # Some exports process leads that never made it back into the pool;
        # they'd be invisible to Pass 2. Create them (with reply/stage history)
        # or gap-fill the ones already in the DB.
        pool_seen = {clean_snid(r[pool_col['Sales Nav ID']]) for r in pool_rows
                     if r[pool_col['Sales Nav ID']] is not None and clean_snid(r[pool_col['Sales Nav ID']])}
        for i, raw in enumerate(proc_rows, start=2):
            snid = clean_snid(raw[proc_col['Sales Nav ID']]) if 'Sales Nav ID' in proc_col else ''
            if not snid or snid in pool_seen:
                continue
            proc = proc_by_snid.get(snid)
            if not proc:
                continue
            first = norm(raw[proc_col['FirstName']]) if 'FirstName' in proc_col else ''
            last = norm(raw[proc_col['LastName']]) if 'LastName' in proc_col else ''
            full = norm(raw[proc_col['FullName']]) if 'FullName' in proc_col else ''
            full = full or f'{first} {last}'.strip() or snid
            lead = db.execute(__import__('sqlalchemy').select(Lead).where(Lead.sales_nav_id == snid)).scalar_one_or_none()
            if lead is None:
                campaign_id = None
                account_id = None
                ck, an = proc['campaign_key'], proc['account_name']
                if ck:
                    if ck in campaigns: campaign_id = campaigns[ck].id
                    else: report['unknown_campaigns'].add(ck)
                if an:
                    if an in accounts: account_id = accounts[an].id
                    else: report['unknown_accounts'].add(an)
                stage = proc['stage']
                reply_msg = proc['reply_msg']
                replied = bool(proc['replied'] or reply_msg.strip())
                if replied and not proc['replied']:
                    report['replies_by_msg'] += 1
                cat, csrc = suggest_category(reply_msg) if replied else ('', '')
                lead = Lead(
                    sales_nav_id=snid, first_name=first, last_name=last, full_name=full,
                    sales_nav_urn=is_urn(raw[proc_col['Sales Nav ID']]) if 'Sales Nav ID' in proc_col else '',
                    title=norm(raw[proc_col['Title']]) if 'Title' in proc_col else '',
                    summary=norm(raw[proc_col['Summary']]) if 'Summary' in proc_col else '',
                    location=norm(raw[proc_col['Location']]) if 'Location' in proc_col else '',
                    company=norm(raw[proc_col['Company']]) if 'Company' in proc_col else '',
                    premium=norm(raw[proc_col['Premium']]) if 'Premium' in proc_col else '',
                    linkedin_url=proc['linkedin_url'],
                    source='campaign_search' if campaign_id else 'list_import',
                    campaign_id=campaign_id, associate_account_id=account_id,
                    status=stage or '', status_changed_at=proc['stage_at'] if stage else None,
                    first_contacted_at=proc['stage_at'] if stage and proc['stage_at'] else None,
                    contact_channel=channel_of(stage) if stage else '',
                    received_replies=replied,
                    reply_message=reply_msg or None,
                    reply_received_at=proc['stage_at'] if replied and proc['stage_at'] else None,
                    reply_category=cat, reply_category_source=csrc if replied else '',
                    reply_category_at=datetime.utcnow() if replied else None,
                    review_status='needs_review' if replied else '',
                    import_fp=row_fp(snid, full, 'processed-only'),
                )
                db.add(lead)
                db.flush()
                if stage:
                    db.add(LeadEvent(lead_id=lead.id, kind='status_change',
                                     detail=f'imported as {stage} (workbook history, Processed sheet)', job_type='xlsx_merge'))
                if replied:
                    db.add(LeadEvent(lead_id=lead.id, kind='reply',
                                     detail=(reply_msg or '')[:500], job_type='xlsx_merge'))
                    report['replied_imported'] += 1
                if proc['crm_note']:
                    db.add(ReplyComment(lead_id=lead.id, author='xlsx-import',
                                        body=f"CRM note (Processed row {proc['row']}): {proc['crm_note']}"))
                report['new_leads'] += 1
            else:
                changed = []
                if proc['reply_msg'].strip() and not lead.received_replies:
                    lead.received_replies = True
                    lead.reply_message = proc['reply_msg']
                    lead.reply_received_at = proc['stage_at'] or datetime.utcnow()
                    cat, csrc = suggest_category(proc['reply_msg'])
                    lead.reply_category, lead.reply_category_source = cat, csrc
                    lead.reply_category_at = datetime.utcnow()
                    lead.review_status = 'needs_review'
                    db.add(LeadEvent(lead_id=lead.id, kind='reply',
                                     detail=proc['reply_msg'][:500], job_type='xlsx_merge'))
                    report['replied_imported'] += 1
                    if not proc['replied']:
                        report['replies_by_msg'] += 1
                    changed.append('reply-imported')
                if not (lead.linkedin_url or '').strip() and proc['linkedin_url']:
                    lead.linkedin_url = proc['linkedin_url']
                    changed.append('url-backfill')
                    report['urls_backfilled'] += 1
                if proc['campaign_key'] in campaigns and not lead.campaign_id:
                    lead.campaign_id = campaigns[proc['campaign_key']].id
                    lead.source = 'campaign_search'
                    changed.append(f"campaign->{proc['campaign_key']}")
                elif proc['campaign_key'] and proc['campaign_key'] not in campaigns:
                    report['unknown_campaigns'].add(proc['campaign_key'])
                if proc['account_name'] in accounts and not lead.associate_account_id:
                    lead.associate_account_id = accounts[proc['account_name']].id
                    changed.append(f"account->{proc['account_name']}")
                elif proc['account_name'] and proc['account_name'] not in accounts:
                    report['unknown_accounts'].add(proc['account_name'])
                if changed:
                    report['enriched'] += 1
                else:
                    report['duplicates'] += 1

        # Audit record on apply; preview rolls everything back.
        if apply:
            db.add(ImportBatch(
                source=path, mode='apply', stats={
                    'new_leads': report['new_leads'], 'enriched': report['enriched'],
                    'duplicates': report['duplicates'],
                    'unknown_campaigns': sorted(report['unknown_campaigns']),
                    'unknown_accounts': sorted(report['unknown_accounts']),
                    'conflicts': report['conflicts'][:100], 'invalid': report['invalid'][:100],
                }))
            db.commit()
        else:
            db.rollback()

        lines = []
        lines.append('APPLIED.' if apply else 'PREVIEW ONLY — nothing written. Press “Apply merge” to write.')
        lines.append(f"new leads: {report['new_leads']}")
        lines.append(f"enriched existing: {report['enriched']}")
        lines.append(f"duplicates skipped: {report['duplicates']}")
        lines.append(f"replies imported: {report['replied_imported']}")
        if report['replies_by_msg']:
            lines.append(f"  (of which detected by message text, not the yes flag: {report['replies_by_msg']})")
        lines.append(f"linkedin urls backfilled: {report['urls_backfilled']}")
        lines.append(f"reply-text conflicts (kept stored): {len(report['conflicts'])}")
        lines.append(f"review-flagged (reply already known): {report['review_flagged']}")
        if report['unknown_campaigns']:
            lines.append('unknown campaigns (not created): ' + ', '.join(sorted(report['unknown_campaigns'])))
        if report['unknown_accounts']:
            lines.append('unknown accounts (not created): ' + ', '.join(sorted(report['unknown_accounts'])))
        for c in report['conflicts'][:20]:
            lines.append('CONFLICT: ' + c)
        for c in report['invalid'][:20]:
            lines.append('INVALID: ' + c)
        return lines
    finally:
        db.close()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
