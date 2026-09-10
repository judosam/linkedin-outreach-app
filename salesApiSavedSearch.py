import re
import os
import random
import time
import gspread
from get_cookies import load_session
from datetime import datetime

import pipeline_common as pcom


# Sales Navigator accounts to run this list against.
ACCOUNTS = ['Anne Davis']

DECORATION = (
    "%28entityUrn%2CobjectUrn%2CprofilePictureDisplayImage%2CfirstName%2ClastName%2CfullName%2C"
    "degree%2CblockThirdPartyDataSharing%2CcrmStatus%2CgeoRegion%2ClastUpdatedTimeInListAt%2C"
    "pendingInvitation%2CnewListEntitySinceLastViewed%2Csaved%2CleadAssociatedAccount~fs_salesCompany"
    "%28entityUrn%2Cname%29%2CoutreachActivity%2Cmemorialized%2ClistCount%2CsavedAccount~fs_salesCompany"
    "%28entityUrn%2Cname%29%2CnotificationUrnOnLeadList%2CuniquePositionCompanyCount%2C"
    "currentPositions*%28title%2CcompanyName%2Ccurrent%2CcompanyUrn%29%2CmostRecentEntityNote"
    "%28body%2ClastModifiedAt%2CnoteId%2Cseat%2Centity%2CownerInfo%2Cownership%2Cvisibility%29%29"
)
PAGE_SIZE = 25
MAX_START = 2500

# === Google Sheets ===
# Opened lazily via pipeline_common so importing this module has no side effects.
WORKSHEET_NAME = "Search Data"
ws = None


def _ensure_sheet():
    global ws
    if ws is None:
        ws = pcom.get_worksheet(WORKSHEET_NAME)

now = datetime.now()
today = now.strftime("%Y-%m-%d")

_DRY = False  # set by main(dry_run=True) - skips sheet writes


def build_query(search_id: int) -> str:
    return (
        f"(spotlightParam:(selectedType:ALL),doFetchSpotlights:true,doFetchHits:true,"
        f"doFetchFilters:false,pivotParam:(com.linkedin.sales.search.LeadListPivotRequest:"
        f"(list:urn%3Ali%3Afs_salesList%3A{search_id},sortCriteria:LAST_ACTIVITY,sortOrder:DESCENDING)),"
        f"list:(scope:LEAD,includeAll:false,excludeAll:false,includedValues:List((id:{search_id}))))"
    )


def build_url(search_id: int, start: int, count: int) -> str:
    query = build_query(search_id)
    return (
        "https://www.linkedin.com/sales-api/salesApiPeopleSearch"
        f"?q=peopleSearchQuery&query={query}"
        f"&start={start}&count={count}&decoration={DECORATION}"
    )


def extract_linkedin_id(entity_urn: str) -> str:
    match = re.search(r"ACw[A-Za-z0-9_-]+", entity_urn)
    return match.group(0) if match else ''


def fetch_leads(account, search_id):
    """Mirrors fetch_leads() from the reference salesApiLeadSearch.py, but hits the
    List-based salesApiPeopleSearch endpoint (build_query/build_url) instead of the
    saved/guided search endpoint."""
    _ensure_sheet()
    session = load_session(account)
    sheet_headers = ws.row_values(1)
    total = 0

    for start in range(0, MAX_START, PAGE_SIZE):
        url = build_url(search_id, start, PAGE_SIZE)
        response = session.get(url, timeout=30)

        if response.status_code in (400, 401):
            print(f"[{account}] HTTP {response.status_code} at start={start} - refreshing session and retrying")
            session = load_session(account, refresh=True)
            response = session.get(url, timeout=30)

        if response.status_code != 200:
            raise RuntimeError(f"salesApiPeopleSearch HTTP {response.status_code} at start={start}: {response.text[:150]}")

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
                'Campaigns': '',
                
            })

        batch_rows = [[str(row.get(col, '')) for col in sheet_headers] for row in page_rows]
        if not _DRY:
            ws.append_rows(batch_rows, value_input_option='USER_ENTERED')
        total += len(batch_rows)
        print(f"[{account}] Page start={start}: {len(elements)} lead(s) appended to {WORKSHEET_NAME}")

        if len(elements) < PAGE_SIZE:
            break

        time.sleep(random.uniform(10, 15))

    return total


def load_list_id(path='list_id.txt') -> int:
    with open(path, 'r') as f:
        raw = f.read().strip()
    if not raw.isdigit():
        raise ValueError(f"{path} does not contain a numeric list id: {raw!r}")
    return int(raw)


def main(accounts=None, list_id=None, dry_run=False):
    """Import leads from a Sales Navigator lead list (list_id.txt) into the
    Search Data sheet. Importable - the web app's 'Import from List' job runs
    this in a background thread. Returns {account: leads_found}.
    """
    global _DRY
    _DRY = bool(dry_run) or pcom.DRY_RUN

    if list_id is None:
        list_id = load_list_id()
    print(f"Using list_id={list_id}")

    totals = {}
    for account in (accounts if accounts is not None else ACCOUNTS):
        try:
            totals[account] = fetch_leads(account, list_id)
            time.sleep(random.uniform(1, 3))
        except Exception as e:
            print(f"[{account}] Fatal error: {e}")

    print("\nDone.")
    for account, total in totals.items():
        print(f"  {account}: {total} lead(s)")
    return totals


if __name__ == "__main__":
    main()