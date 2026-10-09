from email_notifier import send_reply_notification
import re
import pandas as pd
import numpy as np
import os
from rich import print as pprint
from rich.console import Console
from get_cookies import load_session
from gchat_notifier import notify_critical, notify_final_status, notify_run_summary, notify_send_errors
from campaigns import CAMPAIGNS, get_account_config, effective_campaigns
from datetime import datetime, timedelta
import gspread
from gspread.utils import rowcol_to_a1
import time
import json
import random

import pipeline_common as pcom

now = datetime.now()
dt = now.strftime("%b-%d")

console = Console()

_DRY = False  # set by main(dry_run=True) - skips LinkedIn POSTs & sheet writes

# Decrypt and print the result

pprint(":spider_web: [bold green] The web is a jungle, and I'm the data hunter.[/bold green] :crossed_swords:\n")

if os.name == 'nt':
    script_name = os.path.splitext(os.path.basename(__file__))[0]
    os.system(f'title {script_name}')

def get_sales_nav_id(text):
    match = re.search(r'\(([^,]+),', text)
    match = match.group(1) if match else None
    return match

today = datetime.now().date()
today_str = today.strftime('%d-%b-%Y')  # matches the sheet's date format

# === Google Sheets ===
# Opened lazily via pipeline_common so importing this module has no side effects.
ws = None


def _ensure_sheet():
    global ws
    if ws is None:
        ws = pcom.get_worksheet('Followup msg')


# === Get existing sheet data ===
existing_data = None
headers_row = None
data = None


def _load_sheet_data():
    """Refresh the module-level DataFrame from the Followup msg sheet. Called at
    the start of main() instead of at import time."""
    global existing_data, headers_row, data
    _ensure_sheet()
    existing_data = ws.get_all_values()
    headers_row = existing_data[0]
    data = pd.DataFrame(existing_data[1:], columns=headers_row)
    # Keep track of the ORIGINAL sheet row number for each record before filtering
    # +2 because row 1 is the header and gspread is 1-indexed
    data['sheet_row'] = data.index + 2

    print(f"Loaded {len(data)} records from the Google Sheet")
    print(f"Today's date is: {today}")

# Reply detection should write to 'Received Replies' (NOT 'Invite or InMail Status',
# which belongs to the follow-up-sending script). Set REPLY_TEXT_COLUMN_NAME to
# whatever header you use in the sheet to store the reply body - if it doesn't
# exist, the script will still flip 'Received Replies' but skip writing the text.
REPLY_STATUS_COLUMN_NAME = 'Received Replies'
REPLY_TEXT_COLUMN_NAME = 'Reply messages'  # <-- confirm/change this to match your sheet

REP_STATUS_COL = None  # bound in _bind_columns() after _load_sheet_data()
REP_MSG_COL = None
STATUS_COL = None
DATE_COL = None


def _bind_columns():
    global REP_STATUS_COL, REP_MSG_COL, STATUS_COL, DATE_COL
    REP_STATUS_COL = headers_row.index(REPLY_STATUS_COLUMN_NAME) + 1
    REP_MSG_COL = headers_row.index(REPLY_TEXT_COLUMN_NAME) + 1 if REPLY_TEXT_COLUMN_NAME in headers_row else None
    if REP_MSG_COL is None:
        print(f"Note: column '{REPLY_TEXT_COLUMN_NAME}' not found in the sheet - reply text won't be written, only the 'Received Replies' flag.")
    STATUS_COL = headers_row.index('Invite or InMail Status') + 1
    DATE_COL = headers_row.index('Invite or InMail Date') + 1

# === Status labels for the invite-accept -> after-acceptance-message flow ===
STATUS_INVITE_SENT = '📩 Sent Invite'
STATUS_INVITE_AFTER_ACCEPT = '📩 Sent After Acceptance follow-up'

# Accumulated across ALL campaigns/accounts, flushed to the sheet once at the end
pending_updates = []
replies_found = []

def process_campaign_account(campaign_id, campaign, account, message_limit):
    # A lead only belongs here if THIS account was the one that actually
    # contacted it within THIS campaign - the Followup msg sheet's 'Campaigns' +
    # 'Associate Account' columns are the only record of that (no local file).
    account_data = data[(data['Campaigns'] == campaign_id) & (data['Associate Account'] == account)]
    if account_data.empty:
        return

    data_dict = account_data[(account_data['Received Replies'] == '🚫No')]
    data_dict = data_dict.to_dict(orient='records')

    invite_dict = account_data[(account_data['Received Replies'] == '🚫No') & (account_data['Invite or InMail Status'] == STATUS_INVITE_SENT)]
    invite_dict = invite_dict.to_dict(orient='records')
    print(f"[{campaign_id}/{account}] {len(data_dict)} record(s) to check, {len(invite_dict)} pending invite(s)")

    if not data_dict and not invite_dict:
        return

    session = load_session(account)

    # === Daily send-count persistence (shared with
    # salesApiMessagingThreadsSendMessages.py - both scripts draw from the same
    # per-campaign-per-account daily budget, so an account running two campaigns
    # never shares a counter between them) ===
    COUNTS_FILE = f'./daily_run_counts/daily_run_counts_{campaign_id}_{account}.json'
    if os.path.exists(COUNTS_FILE):
        with open(COUNTS_FILE, 'r') as f:
            all_counts = json.load(f)
    else:
        all_counts = {}

    day_counts = all_counts.get(today_str, {})
    messages_sent = day_counts.get('messages_sent', 0)

    def save_counts():
        day_counts['messages_sent'] = messages_sent
        all_counts[today_str] = day_counts
        with open(COUNTS_FILE, 'w') as f:
            json.dump(all_counts, f, indent=2)

    print(f"[{campaign_id}/{account}] Messages sent today so far: {messages_sent}/{message_limit}")

    messages_sent_live = 0
    def limit_reached():
        if messages_sent >= message_limit:
            print(f"[{campaign_id}/{account}] Reached the {message_limit}-message daily send limit - stopping.")
            return True
        return False

    url = pcom.threads_url(90)

    try:
        response = session.get(url)
        res = response.json()
        if response.status_code != 200:
            print(f"[{campaign_id}/{account}] Error fetching messaging threads: {response.status_code} - {res}")
            if res.get('code') == 'SALES_SEAT_REQUIRED':
                print(f"[{campaign_id}/{account}] Account does not have a Sales Navigator seat - skipping.")
                notify_send_errors(f'{campaign_id}/{account}', {"Sales Navigator required": f"Account {account} does not have a Sales Navigator seat - skipping."})
                return
            # session = load_session(account, refresh=True)
            # response = session.get(url)
            # res = response.json()
    except Exception as e:
        print(f"[{campaign_id}/{account}] Error fetching messaging threads: {e}")
        session = load_session(account, refresh=True)
        response = session.get(url)
        res = response.json()

    time.sleep(random.uniform(10, 20))
    # threads_file = f'linkedin_salesApiMessagingThreads_{account}.json'
    # with open(threads_file, 'w') as f:
    #     json.dump(res, f, indent=4)

    # with open(threads_file, 'r') as f:
    #     res = json.load(f)

    msgs = res.get('elements', [])

    # Build a lookup: lead's Sales Nav ID (always participants[0] in this feed) -> their thread.
    # participants[1] is consistently this account's own profile across every thread in this feed.
    threads_by_lead = {t['participants'][0]: t for t in msgs if t.get('participants')}

    # === Invite accepted -> send the "after acceptance" message ===
    send_errors = []
    accepted_ids = [m['participants'][0] for m in msgs if m.get('messages') and m['messages'][0].get('type') == 'INVITATION']
    invite_accept_ids = [record for record in invite_dict if record['Sales Nav ID'] in accepted_ids]
    print(f"[{campaign_id}/{account}] Found {len(invite_accept_ids)} invite accepts")

    for invite_accept_id in invite_accept_ids:
        if limit_reached():
            break
        print(f"[{campaign_id}/{account}] Invite accepted by {invite_accept_id['FirstName']} {invite_accept_id['LastName']}")
        if _DRY:
            print(f"[{campaign_id}/{account}]   -> DRY RUN: after-accept POST skipped")
            time.sleep(random.uniform(0.3, 0.8))
            continue
        url = 'https://www.linkedin.com/sales-api/salesApiMessageActions?action=createMessage'
        response = session.post(url, json={
            'createMessageRequest': {
                'body': campaign['invite_track'][0].format(first_name=invite_accept_id['FirstName'], calendar_url=get_account_config(campaign, account).get('calendar_url', '')),
                'copyToCrm': False,
                'recipients': [invite_accept_id['Sales Nav ID']],
            },
        })
        messages_sent += 1
        messages_sent_live += 1
        save_counts()
        if response.status_code == 200:
            pending_updates.append({'range': rowcol_to_a1(invite_accept_id['sheet_row'], STATUS_COL), 'values': [[STATUS_INVITE_AFTER_ACCEPT]]})
            # pending_updates.append({'range': rowcol_to_a1(invite_accept_id['sheet_row'], DATE_COL), 'values': [[today_str]]})
        else:
            print(f"[{campaign_id}/{account}]   -> send failed ({response.status_code}), status not updated")
            send_errors.append(f"After-acceptance send HTTP {response.status_code}: {response.text[:150]}")
        time.sleep(random.uniform(10, 20))

    # === Reply detection ===
    for row_data in data_dict:
        sales_nav_id = row_data['Sales Nav ID']

        thread = threads_by_lead.get(sales_nav_id)
        if not thread:
            continue  # no thread for this lead in the fetched inbox page

        # A reply is a message in their thread actually authored by the lead.
        # NOTE: message 'type' (e.g. INMAIL_REPLY) does NOT tell you who sent it -
        # you have to check 'author' against the lead's own Sales Nav ID.
        replies = [m for m in thread.get('messages', []) if m.get('author') == sales_nav_id]
        if not replies:
            continue

        print(f"[{campaign_id}/{account}] Found a reply for Sales Nav ID: {row_data.get('FullName', '')}")
        lead_name = row_data.get('FullName', '')
        replies_found.append({'sales_nav_id': sales_nav_id, 'name': lead_name, 'message': replies[0]['body'].replace('\n', '<br>'), 'account': account, 'campaign': campaign_id})
        sheet_row = row_data['sheet_row']
        pending_updates.append({'range': rowcol_to_a1(sheet_row, REP_STATUS_COL), 'values': [['✅Yes']]})
        if REP_MSG_COL and not _DRY:
            pending_updates.append({'range': rowcol_to_a1(sheet_row, REP_MSG_COL), 'values': [[replies[0]['body']]]})

    print(f"[{campaign_id}/{account}] Messages sent today (cumulative, all scripts): {messages_sent}/{message_limit}")
    # print(f"[{campaign_id}/{account}] Live messages sent today: {messages_sent_live}")
    return {'🤝 Invite accepts messaged': len(invite_accept_ids), '💌 New replies found': len([r for r in replies_found if r['account'] == account and r['campaign'] == campaign_id]), '📨 Messages sent today': f'{messages_sent_live}/{message_limit}'}, send_errors

def main(campaigns=None, dry_run=False):
    """Check every campaign/account for invite accepts and lead replies, send the
    after-acceptance message, flag replies in the sheet, and email the reply report.
    Importable - the web app runs this in a background thread.
    Returns: {'<campaign> / <account>': stats_dict}.
    """
    global _DRY
    _DRY = bool(dry_run) or pcom.DRY_RUN

    # Refresh sheet snapshot + bind column indices for this run
    pending_updates.clear()
    replies_found.clear()
    _load_sheet_data()
    _bind_columns()

    all_stats = {}
    targets = campaigns if campaigns is not None else effective_campaigns()
    for campaign_id, campaign in targets.items():
        for acc_cfg in campaign['accounts']:
            account = acc_cfg['account']
            key = f"{campaign_id} / {account}"
            try:
                result = process_campaign_account(campaign_id, campaign, account, acc_cfg['message_limit'])
                if result:
                    stats, send_errors = result
                    all_stats[key] = stats
                    time.sleep(random.uniform(1, 3))  # slight delay to avoid G-Chat rate limits
                    if not _DRY:
                        notify_send_errors(key, send_errors)
            except Exception as e:
                # raise
                console.print(f"🚫 [bold red][{key}] Fatal error:[/bold red] {e}")
                if not _DRY:
                    notify_critical(key, e)

    if _DRY:
        print(f"DRY RUN: skipped {len(pending_updates)} sheet update(s)")
    elif pending_updates:
        ws.batch_update(pending_updates)
        print(f"Wrote {len(pending_updates)} cell update(s) to the sheet")
    else:
        print("No sheet updates to write")

    if replies_found and not _DRY:
        send_reply_notification(replies_found)
    elif not replies_found:
        print("No new replies found")
        time.sleep(random.uniform(1, 3))  # slight delay to avoid G-Chat rate limits

    if not _DRY:
        notify_run_summary(all_stats)
    return all_stats


if __name__ == "__main__":
    main()