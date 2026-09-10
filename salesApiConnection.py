import re
import pandas as pd
import os
from rich import print as pprint
from rich.console import Console
from get_cookies import load_session
from gchat_notifier import notify_critical, notify_final_status, notify_run_summary, notify_send_errors
from campaigns import CAMPAIGNS, get_account_config, effective_campaigns
from datetime import datetime
import random
import time

import pipeline_common as pcom

now = datetime.now()
dt = now.strftime("%b-%d")

console = Console()

_DRY = False  # set by main(dry_run=True) - skips LinkedIn POSTs

pprint(":spider_web: [bold green] The web is a jungle, and I'm the data hunter.[/bold green] :crossed_swords:\n")

if os.name == 'nt':
    script_name = os.path.splitext(os.path.basename(__file__))[0]
    os.system(f'title {script_name}')

today = datetime.now().strftime("%d-%b-%Y")

def get_sales_nav_id(text):
    match = re.search(r'\(([^,]+),', text)
    match = match.group(1) if match else None
    return match

# === Google Sheets ===
# Worksheets are opened lazily via pipeline_common so this module can also be
# imported by the web app without touching the network at import time.
ws = None
ws2 = None
ws2_headers = None


def _ensure_sheets():
    """Bind the module-level worksheet handles on first use."""
    global ws, ws2, ws2_headers
    if ws is None:
        ws = pcom.get_worksheet('Search Data')
        ws2 = pcom.get_worksheet('Followup msg')
        ws2_headers = ws2.row_values(1)


def extract_spreadsheet_data():
    _ensure_sheets()
    existing_data = ws.get_all_values()
    headers_row = existing_data[0]
    data = pd.DataFrame(existing_data[1:], columns=headers_row)
    # Keep track of the ORIGINAL sheet row number for each record before filtering
    # +2 because row 1 is the header and gspread is 1-indexed
    data['sheet_row'] = data.index + 2

    data = data[(data['PendingInvitation'] == 'FALSE') & (data['Invite or InMail Status'] == '')]
    invite_sent_col = headers_row.index('Invite or InMail Status') + 1  
    opentomsg_col = headers_row.index('Opentomsg') + 1 if 'Opentomsg' in headers_row else None
    linkedIn_url_col = headers_row.index('Linkedin URL') + 1 if 'Linkedin URL' in headers_row else None
    return data, invite_sent_col, opentomsg_col, linkedIn_url_col

# data, invite_sent_col, opentomsg_col = extract_spreadsheet_data(ws)

# Search Data only tags a lead with its 'Campaigns' value - it never says which
# physical account handles it. That's decided here, per campaign, by filling
# leads through campaign['accounts'] IN ORDER: account 1 sends until it hits its
# OWN invite_limit/inmail_limit for the day, then whatever's left rolls to
# account 2, and so on. The moment a lead is actually contacted, its row moves
# to the Followup msg sheet carrying BOTH 'Campaigns' and 'Associate Account' -
# that sheet is the only record of which login owns which lead (no local file).

def append_to_followup_sheet(record, campaign_id, account, status_label):
    """Append a new row to Followup msg, built by NAME from ws2's own header order."""
    _ensure_sheets()
    match = re.search(r"ACw[A-Za-z0-9_-]+", record.get('Sales Nav ID') or '')
    overrides = {
        'Linkedin URL': record.get('Linkedin URL', ''),
        'Associate Account': account,
        'Campaigns': campaign_id,
        'Invite or InMail Status': status_label,
        'Received Replies': '🚫No',
        'Invite or InMail Date': today,
    }
    row = [overrides.get(col, record.get(col, '')) for col in ws2_headers]

    # append_row's table-detection can misjudge where data ends if any earlier
    # column of an existing row is blank, and overwrite that row instead of
    # appending below it. Compute the target row explicitly instead.
    next_row = len(ws2.get_all_values()) + 1
    ws2.update(values=[row], range_name=f'A{next_row}', value_input_option='USER_ENTERED')

# Daily counters now live in pipeline_common (one shared implementation for the
# scripts and the web app). Thin wrappers keep the historical call sites working.
def load_daily_counts(campaign_id, account):
    """Each (campaign, account) pair gets its own budget file, so an account
    running two campaigns never shares a counter between them."""
    return pcom.load_daily_counts(campaign_id, account)


def save_daily_counts(counts_file, all_counts, day_counts, opentomsg_count, invite_sent_count):
    day_counts['opentomsg_count'] = opentomsg_count
    day_counts['invite_sent_count'] = invite_sent_count
    pcom.save_daily_counts(counts_file, all_counts, day_counts)

def process_campaign(campaign_id, campaign, data, invite_sent_col, opentomsg_col, linkedIn_url_col):
    campaign_leads = data[data['Campaigns'] == campaign_id].to_dict(orient='records')
    print(f"[{campaign_id}] {len(campaign_leads)} record(s) tagged with this campaign")
    if not campaign_leads:
        return

    remaining = campaign_leads
    send_errors = []
    account_summaries = []

    for acc_cfg in campaign['accounts']:
        if not remaining:
            break

        account = acc_cfg['account']
        invite_limit = acc_cfg['invite_limit']
        inmail_limit = acc_cfg['inmail_limit']
        calendar_url = acc_cfg.get('calendar_url', '')

        counts_file, all_counts, day_counts = load_daily_counts(campaign_id, account)
        opentomsg_count = day_counts.get('opentomsg_count', 0)
        invite_sent_count = day_counts.get('invite_sent_count', 0)
        print(f"[{campaign_id}/{account}] Today's counts so far - InMail: {opentomsg_count}/{inmail_limit}, Invite: {invite_sent_count}/{invite_limit}")

        if opentomsg_count >= inmail_limit and invite_sent_count >= invite_limit:
            print(f"[{campaign_id}/{account}] Already at today's limit - rolling all {len(remaining)} lead(s) to the next account")
            account_summaries.append(f"{account}: 💬{opentomsg_count}/{inmail_limit} 📩{invite_sent_count}/{invite_limit} (skipped)")
            continue  # remaining stays as-is, tried against the next account in the list

        session = load_session(account)
        leftover = []
        url = 'https://www.linkedin.com/sales-api/salesApiMessagingThreads?decoration=%28id%2Crestrictions%2Carchived%2CunreadMessageCount%2CnextPageStartsAt%2CtotalMessageCount%2Cmessages*%28id%2Ctype%2CcontentFlag%2CdeliveredAt%2ClastEditedAt%2Csubject%2Cbody%2CfooterText%2CblockCopy%2Cattachments%2Cauthor%2CsystemMessageContent%29%2Cparticipants*~fs_salesProfile%28entityUrn%2CfirstName%2ClastName%2CfullName%2Cdegree%2CprofilePictureDisplayImage%2CobjectUrn%2CinmailRestriction%29%29&count=10&filter=INBOX&q=filter&messageCount=10'
        response = session.get(url)
        res = response.json()
        if response.status_code != 200:
            print(f"[{campaign_id}/{account}] Error fetching messaging threads: {response.status_code} - {res}")
            if res.get('code') == 'SALES_SEAT_REQUIRED':
                print(f"[{campaign_id}/{account}] Account does not have a Sales Navigator seat - skipping.")
                # notify_send_errors(f'{campaign_id}/{account}', {"Sales Navigator required": f"Account {account} does not have a Sales Navigator seat - skipping."})
                continue
        time.sleep(random.uniform(2, 5))
        opentomsg_checks = 0
        for i, record in enumerate(remaining, 1):
            if opentomsg_count >= inmail_limit and invite_sent_count >= invite_limit:
                leftover.extend(remaining[i:])
                break

            cached_opentomsg = record.get('Opentomsg', 'Unknown') if opentomsg_col else 'Unknown'
            needs_fetch = (not opentomsg_col) or cached_opentomsg in ('', 'Unknown')

            if needs_fetch and opentomsg_checks >= 200:
                leftover.append(record)
                break

            print(f"[{campaign_id}/{account}] Processing lead {i}/{len(remaining)}: {record['FullName']} - Opentomsg: {cached_opentomsg} {'(fetching)' if needs_fetch else '(cached)'}")

            if needs_fetch:
                opentomsg_checks += 1
                print(f"[{campaign_id}/{account}] Checking Opentomsg status for {record['FullName']}")
                params = {
                    'decoration': '(listCount,crmStatus,degree,entityUrn,teamlink,objectUrn,firstName,lastName,fullName,headline,inmailRestriction,location,pendingInvitation,profilePictureDisplayImage,savedLead,contactInfo,blockThirdPartyDataSharing,colleague,memberBadges,defaultPosition,flagshipProfileUrl)',
                }
                try:
                    response = session.get(
                        f'https://www.linkedin.com/sales-api/salesApiProfiles/(profileId:{get_sales_nav_id(record["Sales Nav ID"])},authType:NAME_SEARCH)',
                        params=params,
                    )
                    # if response.status_code != 200:
                    #     raise RuntimeError(f"Opentomsg check HTTP {response.status_code}: {response.text[:150]}")
                    res = response.json()
                    opentomsg = bool(res.get('memberBadges', {}).get('openLink'))
                    linkedin_url = res.get('flagshipProfileUrl', '')
                except Exception as e:
                    print(f"[{campaign_id}/{account}]   -> Opentomsg check failed for {record['FullName']}: {e} — skipping this lead for now")
                    # send_errors.append(f"[{campaign_id}] Opentomsg check failed for {record.get('FullName')}: {e}")
                    leftover.append(record)
                    time.sleep(random.uniform(5, 10))
                    continue

                if not _DRY:
                    ws.update_cell(record['sheet_row'], opentomsg_col, 'TRUE' if opentomsg else 'FALSE')
                    ws.update_cell(record['sheet_row'], linkedIn_url_col, linkedin_url)
            else:
                opentomsg = str(cached_opentomsg).strip().upper() == 'TRUE'

            # print(f"[{campaign_id}/{account}] {record['FullName']} ({record['Sales Nav ID']}) Opentomsg: {opentomsg}")
            name = record.get('FullName')
            first_name = record.get('FirstName')

            handled = False

            if opentomsg and opentomsg_count < inmail_limit:
                print(f"[{campaign_id}/{account}] Sending InMail to {name}")
                # xxx
                json_data = {
                    'createMessageRequest': {
                        'subject': (campaign.get('inmail_subject') or f"A quick note for {first_name}").format(first_name=first_name, calendar_url=calendar_url),
                        'body': campaign['inmail'].format(first_name=first_name, calendar_url=calendar_url),
                        'copyToCrm': False,
                        'recipients': [record["Sales Nav ID"]],
                    },
                }
                if _DRY:
                    print(f"[{campaign_id}/{account}]   -> DRY RUN: InMail POST skipped for {name}")
                    handled = True
                    time.sleep(random.uniform(0.3, 0.8))
                    continue
                url = 'https://www.linkedin.com/sales-api/salesApiMessageActions?action=createMessage'
                response = session.post(url, json=json_data)
                res = response.json()
                if res.get('code') == 'MESSAGE_VALIDATION_PLUGIN_ERROR':
                    print(f"[{campaign_id} / {account}] -> InMail send failed: {res.get('message')} - leaving status blank for retry")
                    # send_errors.append(f"[{campaign_id}] Sorry, you’ve used up all your InMail credits")
                    # ws.update_cell(record['sheet_row'], invite_sent_col, f"InMail send validation error: {res.get('message')}")
                    leftover.append(record)
                    time.sleep(random.uniform(10, 20))
                    break

                if response.status_code == 200:
                    print(f"[{campaign_id}/{account}] Message sent to {name}")
                    ws.update_cell(record['sheet_row'], invite_sent_col, '💬 Sent InMail')
                    append_to_followup_sheet(record, campaign_id, account, '💬 Sent InMail')
                elif response.status_code == 400:
                    print(f"[{campaign_id}/{account}]   -> Connection request failed ({response.status_code}) - leaving status blank for retry")
                    # send_errors.append(f"[{campaign_id}] Email is required to connect")
                    ws.update_cell(record['sheet_row'], invite_sent_col, f"Email is required to connect")
                    leftover.append(record)
                    time.sleep(random.uniform(10, 20))
                elif response.status_code == 429:
                    print(f"[{campaign_id}/{account}]   -> Connection request failed ({response.status_code}) - leaving status blank for retry")
                    send_errors.append(f"[{campaign_id}] Connection request HTTP {response.status_code}: {response.text[:150]}")
                    # ws.update_cell(record['sheet_row'], invite_sent_col, f"Connection request HTTP {response.status_code}: {response.text[:150]}")
                    leftover.append(record)
                    time.sleep(random.uniform(10, 20))
                    break

                opentomsg_count += 1
                save_daily_counts(counts_file, all_counts, day_counts, opentomsg_count, invite_sent_count)
                handled = True
                time.sleep(random.uniform(10, 20))
            elif not opentomsg and invite_sent_count < invite_limit:
                url = 'https://www.linkedin.com/sales-api/salesApiConnection?action=connectV2'
                payload = {
                    'member': get_sales_nav_id(record['Sales Nav ID']),
                    'message': campaign['invite'].format(first_name=record["FirstName"], calendar_url=calendar_url)
                }
                if _DRY:
                    print(f"[{campaign_id}/{account}]   -> DRY RUN: invite POST skipped for {name}")
                    handled = True
                    time.sleep(random.uniform(0.3, 0.8))
                    continue
                response = session.post(url, json=payload)
                if response.status_code == 200:
                    print(f"[{campaign_id}/{account}] Connection request sent to {name}")
                    ws.update_cell(record['sheet_row'], invite_sent_col, '📩 Sent Invite')
                    append_to_followup_sheet(record, campaign_id, account, '📩 Sent Invite')
                elif response.status_code == 400:
                    print(f"[{campaign_id}/{account}]   -> Connection request failed ({response.status_code}) - leaving status blank for retry")
                    # send_errors.append(f"[{campaign_id}] Email is required to connect")
                    ws.update_cell(record['sheet_row'], invite_sent_col, f"Email is required to connect")
                    leftover.append(record)
                    time.sleep(random.uniform(10, 20))
                elif response.status_code == 429:
                    print(f"[{campaign_id}/{account}]   -> Connection request failed ({response.status_code}) - leaving status blank for retry")
                    send_errors.append(f"[{campaign_id}] Connection request HTTP {response.status_code}: {response.text[:150]}")
                    # ws.update_cell(record['sheet_row'], invite_sent_col, f"Connection request HTTP {response.status_code}: {response.text[:150]}")
                    leftover.append(record)
                    time.sleep(random.uniform(10, 20))
                    break
                # elif response.status_code == 400:
                #     break

                invite_sent_count += 1
                save_daily_counts(counts_file, all_counts, day_counts, opentomsg_count, invite_sent_count)
                handled = True
                time.sleep(random.uniform(10, 20))

            if not handled:
                leftover.append(record)

        print(f"[{campaign_id}/{account}] Today's final counts - InMail: {opentomsg_count}/{inmail_limit}, Invite: {invite_sent_count}/{invite_limit}")
        account_summaries.append(f"{account}: 💬{opentomsg_count}/{inmail_limit} 📩{invite_sent_count}/{invite_limit}")
        remaining = leftover

    if remaining:
        print(f"[{campaign_id}] {len(remaining)} lead(s) left unassigned - every account on this campaign hit its daily limit")

    return {'👤 Accounts': ' | '.join(account_summaries), '⏳ Left over today': len(remaining)}, send_errors

def main(campaigns=None, dry_run=False):
    """Run the invite/InMail sender across campaigns. Importable (no side effects
    until called) so the web app can run it in a background thread.

    Args:
        campaigns: optional subset {campaign_id: campaign_dict} - defaults to all.
        dry_run: skip all LinkedIn POSTs and sheet writes; everything else runs.
    Returns: {campaign_id: stats_dict} accumulated across the run.
    """
    global _DRY
    _DRY = bool(dry_run) or pcom.DRY_RUN

    all_campaign_stats = {}
    targets = campaigns if campaigns is not None else effective_campaigns()
    for campaign_id, campaign in targets.items():
        data, invite_sent_col, opentomsg_col, linkedIn_url_col = extract_spreadsheet_data()
        try:
            result = process_campaign(campaign_id, campaign, data, invite_sent_col, opentomsg_col, linkedIn_url_col)
            if result:
                stats, send_errors = result
                all_campaign_stats[campaign_id] = stats
                time.sleep(random.uniform(1, 3))  # slight delay to avoid G-Chat rate limits
                if not _DRY:
                    notify_send_errors(campaign_id, send_errors)
        except Exception as e:
            # raise
            console.print(f"🚫 [bold red][{campaign_id}] Fatal error:[/bold red] {e}")
            if not _DRY:
                notify_critical(campaign_id, e)
    time.sleep(random.uniform(1, 3))  # slight delay to avoid G-Chat rate limits
    if not _DRY:
        notify_run_summary(all_campaign_stats)
    return all_campaign_stats


if __name__ == "__main__":
    main()