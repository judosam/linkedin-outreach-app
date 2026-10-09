import re
import pandas as pd
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

_DRY = False  # set by main(dry_run=True) - simulates sends without POSTing

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
today_str = today.strftime('%d-%b-%Y')  # matches the sheet's "Invite or InMail Date" format

# === Google Sheets ===
# Opened lazily via pipeline_common so importing this module has no side effects.
ws = None


def _ensure_sheet():
    global ws
    if ws is None:
        ws = pcom.get_worksheet('Followup msg')


# === Get existing sheet data (module-level snapshot) ===
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

# === Column indices used for writing the status/date back to the sheet ===
STATUS_COL = None  # bound in _bind_columns() after _load_sheet_data()
DATE_COL = None


def _bind_columns():
    global STATUS_COL, DATE_COL
    STATUS_COL = headers_row.index('Invite or InMail Status') + 1
    DATE_COL = headers_row.index('Invite or InMail Date') + 1

# === Status labels - each stage now writes a DISTINCT label so the next stage's
# filter can actually trigger (previously invite_f1 both triggered on AND wrote back
# the same label, which meant it could never progress to invite_f2/invite_f3). ===
STATUS = {
    'accepted': '📩 Sent After Acceptance follow-up',  # set by salesApiMessagingThreadsCheckingReplies.py
    'invite_f1': '📩 Sent Invite Follow-up 1',
    'invite_f2': '📩 Sent Invite Follow-up 2',
    'invite_f3': '📩 Sent Invite Follow-up 3',
    'inmail_sent': '💬 Sent InMail',  # set by salesApiConnection.py
    'inmail_f1': '💬 Sent InMail Follow-up 1',
    'inmail_f2': '💬 Sent InMail Follow-up 2',
    'inmail_f3': '💬 Sent InMail Follow-up 3',
}

# Each stage: (trigger status key, days to wait, campaign track index, result status key, label)
INVITE_STAGES = [
    ('accepted', 3, 1, 'invite_f1', 'Invite 1st Follow-up'),
    ('invite_f1', 5, 2, 'invite_f2', 'Invite 2nd Follow-up'),
    ('invite_f2', 7, 3, 'invite_f3', 'Invite 3rd Follow-up'),
]
INMAIL_STAGES = [
    ('inmail_sent', 3, 0, 'inmail_f1', 'InMail 1st Follow-up'),
    ('inmail_f1', 5, 1, 'inmail_f2', 'InMail 2nd Follow-up'),
    ('inmail_f2', 7, 2, 'inmail_f3', 'InMail 3rd Follow-up'),
]

def queue_status_update(record, new_status):
    """Write the status (and date) back to the sheet immediately, live, for this row."""
    if _DRY:
        return
    row = record['sheet_row']
    updates = [
        {'range': rowcol_to_a1(row, STATUS_COL), 'values': [[new_status]]},
        # {'range': rowcol_to_a1(row, DATE_COL), 'values': [[today_str]]},
    ]
    ws.batch_update(updates)
    print(f"[live update] row {row} -> {new_status}")

def flush_status_updates():
    pass  # no-op now, kept so the call at the bottom of the script doesn't need removing

def process_campaign_account(campaign_id, campaign, account, message_limit):
    # Only leads THIS account actually contacted within THIS campaign - filtered
    # straight off the Followup msg sheet's own 'Campaigns' + 'Associate Account'
    # columns, so a physical account running multiple campaigns keeps each
    # campaign's leads, budget, and follow-up sequence fully separate.
    account_data = data[(data['Campaigns'] == campaign_id) & (data['Associate Account'] == account)]
    if account_data.empty:
        return
    message_limit = max(0, int(message_limit))
    session = None  # lazily created on first actual send need

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

    def limit_reached():
        return messages_sent >= message_limit

    send_errors = []
    stage_counts = {}

    def run_stage(track_key, trigger_key, days_after, track_index, result_key, label):
        nonlocal messages_sent, session
        filtered = account_data[
            (account_data['Received Replies'] == '🚫No') &
            (account_data['Invite or InMail Status'] == STATUS[trigger_key]) &
            (pd.to_datetime(account_data['Invite or InMail Date'], format='%d-%b-%Y').dt.date + pd.Timedelta(days=days_after) <= today)
        ]
        records = [r for r in filtered.to_dict(orient='records') if r['Sales Nav ID']]
        print(f"[{campaign_id}/{account}] {label}: {len(records)} eligible record(s)")
        if not records:
            return 0

        track = campaign.get(track_key, [])
        if track_index >= len(track):
            print(f"[{campaign_id}/{account}] {label}: no campaign content at this stage - skipping {len(records)} record(s)")
            return 0

        if session is None:
            session = load_session(account)
        url = pcom.threads_url(10)
        response = session.get(url)
        res = response.json()
        if response.status_code != 200:
            print(f"[{campaign_id}/{account}] Error fetching messaging threads: {response.status_code} - {res}")
            if res.get('code') == 'SALES_SEAT_REQUIRED':
                print(f"[{campaign_id}/{account}] Account does not have a Sales Navigator seat - skipping.")
                # notify_send_errors(f'{campaign_id}/{account}', {"Sales Navigator required": f"Account {account} does not have a Sales Navigator seat - skipping."})
                return
        template = track[track_index]
        calendar_url = get_account_config(campaign, account).get('calendar_url', '')
        sent = 0
        for record in records:
            if limit_reached():
                print(f"[{campaign_id}/{account}] Reached the {message_limit}-message daily send limit - stopping.")
                break
            print(f"[{campaign_id}/{account}] {label} sent to {record['FirstName']} {record['LastName']}")
            if _DRY:
                print(f"[{campaign_id}/{account}]   -> DRY RUN: message POST skipped")
                messages_sent += 1
                save_counts()
                queue_status_update(record, STATUS[result_key])
                sent += 1
                time.sleep(random.uniform(0.3, 0.8))
                continue
            url = 'https://www.linkedin.com/sales-api/salesApiMessageActions?action=createMessage'
            if isinstance(template, dict):
                subject = template.get('subject')
                body = template['body'].format(first_name=record['FirstName'], calendar_url=calendar_url)
            else:
                subject = None
                body = template.format(first_name=record['FirstName'], calendar_url=calendar_url)
            create_message_request = {'body': body, 'copyToCrm': False, 'recipients': [record['Sales Nav ID']]}
            if subject:
                create_message_request['subject'] = subject
            response = session.post(url, json={'createMessageRequest': create_message_request})
            res = response.json()
            if res.get('code') == 'MESSAGE_VALIDATION_PLUGIN_ERROR':
                print(f"[{campaign_id} / {account}] -> InMail send failed: {res.get('message')} - leaving status blank for retry")
                # send_errors.append(f"[{campaign_id}] Sorry, you’ve used up all your InMail credits")
                # ws.update_cell(record['sheet_row'], invite_sent_col, f"InMail send validation error: {res.get('message')}")
                time.sleep(random.uniform(10, 20))
                break
            messages_sent += 1
            save_counts()
            if response.status_code == 200:
                queue_status_update(record, STATUS[result_key])
                sent += 1
            else:
                print(f"[{campaign_id}/{account}]   -> send failed ({response.status_code}), status not updated")
                send_errors.append(f"{label} HTTP {response.status_code}: {response.text[:150]}")
            time.sleep(random.uniform(15, 30))
        return sent

    for trigger_key, days_after, track_index, result_key, label in INVITE_STAGES:
        stage_counts[label] = run_stage('invite_track', trigger_key, days_after, track_index, result_key, label)

    for trigger_key, days_after, track_index, result_key, label in INMAIL_STAGES:
        stage_counts[label] = run_stage('inmail_track', trigger_key, days_after, track_index, result_key, label)

    print(f"[{campaign_id}/{account}] Messages sent today (cumulative, all scripts): {messages_sent}/{message_limit}")
    return {
        '🔁 Invite follow-ups (1st/2nd/3rd)': f"{stage_counts['Invite 1st Follow-up']}/{stage_counts['Invite 2nd Follow-up']}/{stage_counts['Invite 3rd Follow-up']}",
        '🔁 InMail follow-ups (1st/2nd/3rd)': f"{stage_counts['InMail 1st Follow-up']}/{stage_counts['InMail 2nd Follow-up']}/{stage_counts['InMail 3rd Follow-up']}",
        '📨 Messages sent today': f'{messages_sent}/{message_limit}',
    }, send_errors

def main(campaigns=None, dry_run=False):
    """Run the dated follow-up sequences (invite + InMail stages) for all (or
    selected) campaigns. Importable - the web app runs this in a background thread.
    Returns: {'<campaign> / <account>': stats_dict}.
    """
    global _DRY
    _DRY = bool(dry_run) or pcom.DRY_RUN

    # Refresh sheet snapshot + bind column indices for this run
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
                console.print(f"🚫 [bold red][{key}] Fatal error:[/bold red] {e}")
                if not _DRY:
                    notify_critical(key, e)

    # === Write every queued status/date change back to the sheet in one call ===
    flush_status_updates()
    time.sleep(random.uniform(1, 3))  # slight delay to avoid G-Chat rate limits
    if not _DRY:
        notify_run_summary(all_stats)
    return all_stats


if __name__ == "__main__":
    main()