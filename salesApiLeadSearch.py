from urllib.parse import urlparse, parse_qs
import os
from rich import print as pprint
from rich.console import Console
from get_cookies import load_session
from campaigns import CAMPAIGNS, effective_campaigns
from gchat_notifier import notify_critical, notify_final_status, notify_run_summary, notify_send_errors
from datetime import datetime
import random
import time
import gspread

import pipeline_common as pcom

now = datetime.now()
dt = now.strftime("%b-%d")

console = Console()

_DRY = False  # set by main(dry_run=True) - skips sheet writes

# Decrypt and print the result

pprint(":spider_web: [bold green] The web is a jungle, and I'm the data hunter.[/bold green] :crossed_swords:\n")

if os.name == 'nt':
    script_name = os.path.splitext(os.path.basename(__file__))[0]
    os.system(f'title {script_name}')

DECORATION_ID = 'com.linkedin.sales.deco.desktop.searchv2.LeadSearchResult-14'
PAGE_SIZE = 25
MAX_START = 2500  # matches the original spider's range(0, 2500, 25) page ceiling

# === Google Sheets ===
# Opened lazily via pipeline_common so importing this module has no side effects.
ws = None


def _ensure_sheet():
    global ws
    if ws is None:
        ws = pcom.get_worksheet('Search Data')
today = now.strftime("%Y-%m-%d")

def build_search_params(search_url):
    """Turn a campaign's search_url (the plain linkedin.com/sales/search/people URL
    you'd paste from the browser) into the query params the salesApiLeadSearch
    endpoint expects. Handles both a saved search (savedSearchId=...) and a live
    filtered search (query=...) - whichever the URL actually has.
    NOTE: this mirrors the pattern LinkedIn's own frontend uses for these two search
    types, but hasn't been verified against a live response - if the API comes back
    empty/malformed, the params dict is the first thing to check."""
    qs = parse_qs(urlparse(search_url).query)
    if 'savedSearchId' in qs:
        return {'q': 'savedSearchId', 'savedSearchId': qs['savedSearchId'][0]}
    if 'query' in qs:
        return {'q': 'guided', 'query': qs['query'][0]}
    raise ValueError(f"search_url has neither 'savedSearchId' nor 'query' param: {search_url}")

def fetch_leads(campaign_id, account, search_url):
    _ensure_sheet()
    session = load_session(account)
    base_params = build_search_params(search_url)
    sheet_headers = ws.row_values(1)
    total = 0
    for start in range(0, MAX_START, PAGE_SIZE):
        params = {**base_params, 'start': start, 'count': PAGE_SIZE, 'decorationId': DECORATION_ID}
        response = session.get('https://www.linkedin.com/sales-api/salesApiLeadSearch', params=params)
        if response.status_code in (400, 401):
            print(f"[{campaign_id}] HTTP {response.status_code} at start={start} - refreshing {account}'s session and retrying")
            session = load_session(account, refresh=True)
            response = session.get('https://www.linkedin.com/sales-api/salesApiLeadSearch', params=params)
        if response.status_code != 200:
            raise RuntimeError(f"salesApiLeadSearch HTTP {response.status_code} at start={start}: {response.text[:150]}")
        elements = response.json().get('elements', [])
        if not elements:
            break

        page_rows = []
        for element in elements:
            current_position = (element.get('currentPositions') or [{}])[0]
            page_rows.append({
                'Sales Nav ID': element.get('entityUrn', ''),
                'FirstName': element.get('firstName', ''),
                'LastName': element.get('lastName', ''),
                'FullName': element.get('fullName', ''),
                'Title': current_position.get('title', ''),
                'Summary': element.get('summary', ''),
                'Location': element.get('geoRegion', ''),
                'Company': current_position.get('companyName', ''),
                'Premium': element.get('premium', ''),
                'PendingInvitation': element.get('pendingInvitation', ''),
                'Viewed': element.get('viewed', ''),
                'Opentomsg': 'Unknown',
                'Linkedin URL': '',
                'Updated Date': today,
                'Campaigns': campaign_id,
            })

        batch_rows = [[str(row.get(col, '')) for col in sheet_headers] for row in page_rows]
        if not _DRY:
            ws.append_rows(batch_rows, value_input_option='USER_ENTERED')
        total += len(batch_rows)
        print(f"[{campaign_id}] Page start={start}: {len(elements)} lead(s) appended to Search Data")
        time.sleep(random.uniform(10, 15))
    return total

def process_campaign(campaign_id, campaign):
    send_errors = []
    total = 0
    if campaign.get('search_url'):
        search_account = campaign['accounts'][0]['account']
        total += fetch_leads(campaign_id, search_account, campaign['search_url'])
    for acc_cfg in campaign['accounts']:
        acc_search_url = acc_cfg.get('search_url')
        if acc_search_url:
            total += fetch_leads(campaign_id, acc_cfg['account'], acc_search_url)
    print(f"[{campaign_id}] {total} lead(s) found and appended across all pages")

    return {'🔍 Leads found & added': total}, send_errors

all_campaign_stats = {}


def main(campaigns=None, dry_run=False):
    """Run lead search for all (or selected) campaigns and append results to the
    Search Data sheet. Importable - the web app runs this in a background thread.
    Returns: {campaign_id: stats_dict}.
    """
    global _DRY
    _DRY = bool(dry_run) or pcom.DRY_RUN

    all_campaign_stats = {}
    targets = campaigns if campaigns is not None else effective_campaigns()
    for campaign_id, campaign in targets.items():
        try:
            result = process_campaign(campaign_id, campaign)
            if result:
                stats, send_errors = result
                all_campaign_stats[campaign_id] = stats
                time.sleep(random.uniform(1, 3))  # slight delay to avoid G-Chat rate limits
                # notify_send_errors(campaign_id, send_errors)
        except Exception as e:
            # raise
            console.print(f"🚫 [bold red][{campaign_id}] Fatal error:[/bold red] {e}")
            # notify_critical(campaign_id, e)

    time.sleep(random.uniform(1, 3))  # slight delay to avoid G-Chat rate limits
    # notify_run_summary(all_campaign_stats)
    return all_campaign_stats


if __name__ == "__main__":
    main()