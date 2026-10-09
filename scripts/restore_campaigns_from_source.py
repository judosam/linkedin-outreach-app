"""Restore campaign content + account links from campaigns.py into the DB.

The DB is the system of record, but campaigns.py remains the legacy source of
truth for the original 6 campaigns. If the DB rows were blanked (empty
templates / missing account links), this script re-imports them verbatim.

Safe to run repeatedly: it only touches the 6 legacy campaign_keys, only
updates fields that are actually blank, and skips link rows that already match
the source (same account + order).

Run:  python scripts/restore_campaigns_from_source.py   (from the project root)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from campaigns import CAMPAIGNS  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Account, Campaign, CampaignAccount  # noqa: E402


def main():
    init_db()
    db = SessionLocal()
    restored_templates = 0
    restored_links = 0
    created_campaigns = 0
    try:
        accounts_by_name = {a.name: a for a in db.query(Account).all()}

        for key, cfg in CAMPAIGNS.items():
            c = db.query(Campaign).filter_by(campaign_key=key).first()
            if c is None:
                print(f"+ {key}: not in DB - creating")
                c = Campaign(campaign_key=key, name=key, status='active')
                db.add(c)
                db.flush()
                created_campaigns += 1

            # --- Templates: fill only what is blank (never overwrite UI edits)
            changed = []
            if not (c.invite_text or '').strip() and cfg.get('invite'):
                c.invite_text = cfg['invite']; changed.append('invite_text')
            if not list(c.invite_track or []) and cfg.get('invite_track'):
                c.invite_track = list(cfg['invite_track']); changed.append('invite_track')
            if not (c.inmail_subject or '').strip() and cfg.get('inmail_subject'):
                c.inmail_subject = cfg['inmail_subject']; changed.append('inmail_subject')
            if not (c.inmail_text or '').strip() and cfg.get('inmail'):
                c.inmail_text = cfg['inmail']; changed.append('inmail_text')
            if not list(c.inmail_track or []) and cfg.get('inmail_track'):
                c.inmail_track = list(cfg['inmail_track']); changed.append('inmail_track')
            if changed:
                restored_templates += 1
                print(f"~ {key}: restored {', '.join(changed)}")

            # --- Account links: rebuild if missing/mismatched vs source
            want = []
            for i, acc in enumerate(cfg.get('accounts', [])):
                account = accounts_by_name.get(acc['account'])
                if account is None:
                    print(f"  ! {key}: account '{acc['account']}' not found in DB - skipped")
                    continue
                want.append((account.id, i, acc))

            existing = sorted(
                db.query(CampaignAccount).filter_by(campaign_id=c.id).all(),
                key=lambda l: l.order_index)
            existing_pairs = [(l.account_id, l.order_index) for l in existing]
            want_pairs = [(a_id, i) for a_id, i, _ in want]

            if existing_pairs != want_pairs:
                for l in existing:
                    db.delete(l)
                db.flush()
                for a_id, i, acc in want:
                    db.add(CampaignAccount(
                        campaign_id=c.id, account_id=a_id, order_index=i,
                        invite_limit=acc.get('invite_limit', 10),
                        inmail_limit=acc.get('inmail_limit', 10),
                        message_limit=acc.get('message_limit', 30),
                        calendar_url=acc.get('calendar_url'),
                        search_url_override=acc.get('search_url'),
                    ))
                restored_links += 1
                print(f"~ {key}: account links rebuilt -> "
                      f"{[accounts_by_name_reverse(accounts_by_name, a) for a, _ in want_pairs]}")
            else:
                print(f"= {key}: account links already correct")

        db.commit()
        print(f"\nDone. {created_campaigns} campaign(s) created, "
              f"{restored_templates} campaign(s) had templates restored, "
              f"{restored_links} campaign(s) had account links rebuilt.")
        print("The 2 UI-created campaigns (Sales Outsourcing, CXO Podcast) were left untouched -")
        print("edit them in the dashboard (they have no accounts yet, so jobs skip them).")
    finally:
        db.close()


def accounts_by_name_reverse(accounts_by_name, account_id):
    for name, a in accounts_by_name.items():
        if a.id == account_id:
            return name
    return f"account#{account_id}"


if __name__ == '__main__':
    main()
