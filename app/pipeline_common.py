"""Shared helpers for the pipeline scripts (salesApi*.py).

Extracted so the web app (app/pipeline.py) and the scripts use ONE implementation
of: Google Sheets access, per-(campaign, account) daily counters, the Sales Nav
messaging-threads endpoint, and the dry-run switch.

Nothing here runs at import time beyond reading .env - it is safe to import.
"""
import json
import os
import sys
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Windows consoles default to cp1252 and crash on emoji in print(); the pipeline
# and web app both log emoji-rich lines, so force UTF-8 with replacement.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

# === Configuration (env-overridable, same defaults as the original scripts) ===
MASTER_SHEET_ID = os.environ.get('MASTER_SHEET_ID', '1xdZtLvQZ6cshlI75-XuLU7dSuniL-2NIqVZ8mQYHUxk')
SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', './credentials.json')

# When truthy (OCC_DRY_RUN=1), pipeline jobs run their full read/decide path but
# SKIP anything that writes to LinkedIn or mutates the sheet. Used by the web app's
# dry-run toggle; plain CLI runs default to normal (live) behavior.
DRY_RUN = os.environ.get('OCC_DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')

# === Sales Navigator messaging-threads endpoint ===
# Same decoration blob every script used; only `count` differed between callers.
_THREADS_DECORATION = (
    '%28id%2Crestrictions%2Carchived%2CunreadMessageCount%2CnextPageStartsAt%2C'
    'totalMessageCount%2Cmessages*%28id%2Ctype%2CcontentFlag%2CdeliveredAt%2C'
    'lastEditedAt%2Csubject%2Cbody%2CfooterText%2CblockCopy%2Cattachments%2C'
    'author%2CsystemMessageContent%29%2Cparticipants*~fs_salesProfile%28'
    'entityUrn%2CfirstName%2ClastName%2CfullName%2Cdegree%2C'
    'profilePictureDisplayImage%2CobjectUrn%2CinmailRestriction%29%29'
)


def threads_url(count=90):
    """Build the salesApiMessagingThreads inbox URL. `count` = thread page size
    (the reply-checker fetches 90, the connection sender fetched 10)."""
    return (
        f'https://www.linkedin.com/sales-api/salesApiMessagingThreads?'
        f'decoration={_THREADS_DECORATION}&count={count}&filter=INBOX&q=filter&messageCount=10'
    )


# === Google Sheets ===
_gspread_client = None
_sheet_cache = {}


def get_sheet():
    """Open the master spreadsheet (cached client)."""
    global _gspread_client
    import gspread
    if _gspread_client is None:
        _gspread_client = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    return _gspread_client.open_by_key(MASTER_SHEET_ID)


def get_worksheet(name):
    """Return a cached worksheet handle by tab name ('Search Data', 'Followup msg')."""
    if name not in _sheet_cache:
        _sheet_cache[name] = get_sheet().worksheet(name)
    return _sheet_cache[name]


def reset_sheet_cache():
    """Drop cached handles (call if the workbook/tab set changed mid-process)."""
    global _gspread_client
    _gspread_client = None
    _sheet_cache.clear()


# === Per-(campaign, account) daily counters ===
# Each pair gets its own JSON file under ./daily_run_counts/ so an account running
# two campaigns never shares a counter. Two value shapes live in these files:
#   - opentomsg_count / invite_sent_count  (salesApiConnection.py)
#   - messages_sent                        (both messaging scripts)
# All three may coexist for one pair - they are independent keys.

def today_str():
    """The sheet's date format: 10-Sep-2026."""
    return datetime.now().strftime('%d-%b-%Y')


def counts_file_for(campaign_id, account):
    return f'./daily_run_counts/daily_run_counts_{campaign_id}_{account}.json'


def load_daily_counts(campaign_id, account):
    """Return (counts_file, all_counts, day_counts) for today. day_counts is the
    live dict to mutate; persist it with save_daily_counts()."""
    counts_file = counts_file_for(campaign_id, account)
    if os.path.exists(counts_file):
        with open(counts_file, 'r') as f:
            all_counts = json.load(f)
    else:
        all_counts = {}
    day_counts = all_counts.get(today_str(), {})
    return counts_file, all_counts, day_counts


def save_daily_counts(counts_file, all_counts, day_counts):
    """Persist today's (mutated) day_counts back to disk."""
    all_counts[today_str()] = day_counts
    os.makedirs(os.path.dirname(counts_file) or '.', exist_ok=True)
    with open(counts_file, 'w') as f:
        json.dump(all_counts, f, indent=2)
