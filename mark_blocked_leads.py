"""Mark leads whose sends failed with 'Email is required to connect'.

Reads Sales Nav URNs (urn:li:fs_salesProfile:(ACw…,NAME_SEARCH,xxx)) from a
text file, matches them against leads by the bare Sales Nav token inside the
URN, and sets status=BLOCKED_ERROR + last_error so the send workers skip them.

Standalone like merge_xlsx_history.py — never imported by the app.

Usage:
  python mark_blocked_leads.py blocked_ids.txt            # preview
  python mark_blocked_leads.py blocked_ids.txt --apply    # write
"""
import argparse
import re
import sys
from datetime import datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Lead

REASON = 'Email is required to connect'
# Bare Sales Nav token: the ACw… id inside the URN (or a bare id pasted directly).
TOKEN_RE = re.compile(r'\(([^,()]+),')


def tokens_from_file(path: str) -> list[str]:
    out, seen = [], set()
    for raw in open(path, encoding='utf-8-sig'):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        m = TOKEN_RE.search(line)
        token = (m.group(1) if m else line).strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('ids_file', help='text file with one Sales Nav URN (or bare token) per line')
    ap.add_argument('--apply', action='store_true', help='write changes (default: preview only)')
    ap.add_argument('--include-active', action='store_true',
                    help='also block leads that already have a stage (INVITE_SENT etc.). '
                         'Default protects anyone already contacted.')
    args = ap.parse_args()

    tokens = tokens_from_file(args.ids_file)
    print(f'{len(tokens)} unique Sales Nav ID(s) loaded from {args.ids_file}')

    db = SessionLocal()
    try:
        leads = db.execute(select(Lead).where(Lead.sales_nav_id.in_(tokens))).scalars().all()
        found = {l.sales_nav_id: l for l in leads}
        print(f'matched {len(found)} lead(s) in the database')

        missing = [t for t in tokens if t not in found]
        if missing:
            print(f'{len(missing)} ID(s) not in the database (first 5): {missing[:5]}')

        now = datetime.utcnow()
        changed = skipped = 0
        for token, lead in found.items():
            if lead.status == 'BLOCKED_ERROR' and lead.last_error == REASON:
                skipped += 1
                continue
            if lead.status and lead.status != 'BLOCKED_ERROR' and not args.include_active:
                print(f'  protect {lead.full_name or token}: status={lead.status} (use --include-active to override)')
                skipped += 1
                continue
            if lead.received_replies:
                print(f'  protect {lead.full_name or token}: has a reply — never blocked')
                skipped += 1
                continue
            if not args.apply:
                print(f'  would block {lead.full_name or token} (campaign_id={lead.campaign_id}, status={lead.status or "untouched"})')
                changed += 1
                continue
            from app.models import LeadEvent
            old = lead.status or '(none)'
            lead.status = 'BLOCKED_ERROR'
            lead.last_error = REASON
            lead.status_changed_at = now
            db.add(LeadEvent(lead_id=lead.id, kind='status_change',
                             detail=f'{old} -> BLOCKED_ERROR: manual import of failed-send list ({REASON})',
                             job_type=None))
            changed += 1

        if args.apply:
            db.commit()
            print(f'APPLIED: {changed} lead(s) marked BLOCKED_ERROR, {skipped} skipped')
        else:
            db.rollback()
            print(f'PREVIEW: {changed} lead(s) would be marked, {skipped} skipped. Re-run with --apply to write.')
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    sys.exit(main())
