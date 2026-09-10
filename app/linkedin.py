"""LinkedIn Sales Navigator client layer.

Thin, reusable wrappers around the EXACT endpoints and session handling the
original scripts use (via get_cookies.load_session -> curl_cffi). No LinkedIn
logic is reinvented here - each function mirrors one call from the legacy
scripts so the jobs read like the originals.
"""
import re
import random
import time
from urllib.parse import urlparse, parse_qs

import pipeline_common as pcom
from get_cookies import load_session, ACCOUNTS

DECORATION_ID = 'com.linkedin.sales.deco.desktop.searchv2.LeadSearchResult-14'
PAGE_SIZE = 25
MAX_START = 2500

MESSAGE_ACTIONS_URL = 'https://www.linkedin.com/sales-api/salesApiMessageActions?action=createMessage'
CONNECT_URL = 'https://www.linkedin.com/sales-api/salesApiConnection?action=connectV2'

PROFILE_DECORATION = (
    '(listCount,crmStatus,degree,entityUrn,teamlink,objectUrn,firstName,lastName,'
    'fullName,headline,inmailRestriction,location,pendingInvitation,'
    'profilePictureDisplayImage,savedLead,contactInfo,blockThirdPartyDataSharing,'
    'colleague,memberBadges,defaultPosition,flagshipProfileUrl)'
)


def extract_profile_id(entity_urn_or_text: str) -> str | None:
    """salesNav raw IDs embed the profile id: '(ACwXXX,...' or urn '...ACwXXX'."""
    m = re.search(r'ACw[A-Za-z0-9_-]+', entity_urn_or_text or '')
    return m.group(0) if m else None


def build_search_params(search_url: str) -> dict:
    """salesApiLeadSearch params from either a saved search or a guided search URL
    (mirrors build_search_params in salesApiLeadSearch.py)."""
    qs = parse_qs(urlparse(search_url).query)
    if 'savedSearchId' in qs:
        return {'q': 'savedSearchId', 'savedSearchId': qs['savedSearchId'][0]}
    if 'query' in qs:
        return {'q': 'guided', 'query': qs['query'][0]}
    raise ValueError(f"search_url has neither 'savedSearchId' nor 'query' param: {search_url}")


def search_leads(session, search_url: str, start: int):
    """One page of salesApiLeadSearch (25/page in the legacy scripts).
    Returns the raw 'elements' list."""
    params = {**build_search_params(search_url), 'start': start, 'count': PAGE_SIZE,
              'decorationId': DECORATION_ID}
    response = session.get('https://www.linkedin.com/sales-api/salesApiLeadSearch', params=params)
    if response.status_code in (400, 401):
        raise LinkedinError(f"LeadSearch HTTP {response.status_code}: {response.text[:150]}", status=response.status_code)
    if response.status_code != 200:
        raise LinkedinError(f"LeadSearch HTTP {response.status_code}: {response.text[:150]}", status=response.status_code)
    return response.json().get('elements', [])


def people_search_by_list(session, list_id: int, start: int):
    """One page of the List-pivot salesApiPeopleSearch endpoint
    (mirrors salesApiSavedSearch.build_url/build_query)."""
    decoration = (
        '%28entityUrn%2CobjectUrn%2CprofilePictureDisplayImage%2CfirstName%2ClastName%2CfullName%2C'
        'degree%2CblockThirdPartyDataSharing%2CcrmStatus%2CgeoRegion%2ClastUpdatedTimeInListAt%2C'
        'pendingInvitation%2CnewListEntitySinceLastViewed%2Csaved%2CleadAssociatedAccount~fs_salesCompany'
        '%28entityUrn%2Cname%29%2CoutreachActivity%2Cmemorialized%2ClistCount%2CsavedAccount~fs_salesCompany'
        '%28entityUrn%2Cname%29%2CnotificationUrnOnLeadList%2CuniquePositionCompanyCount%2C'
        'currentPositions*%28title%2CcompanyName%2Ccurrent%2CcompanyUrn%29%2CmostRecentEntityNote'
        '%28body%2ClastModifiedAt%2CnoteId%2Cseat%2Centity%2CownerInfo%2Cownership%2Cvisibility%29%29'
    )
    query = (
        f'(spotlightParam:(selectedType:ALL),doFetchSpotlights:true,doFetchHits:true,'
        f'doFetchFilters:false,pivotParam:(com.linkedin.sales.search.LeadListPivotRequest:'
        f'(list:urn%3Ali%3Afs_salesList%3A{list_id},sortCriteria:LAST_ACTIVITY,sortOrder:DESCENDING)),'
        f'list:(scope:LEAD,includeAll:false,excludeAll:false,includedValues:List((id:{list_id}))))'
    )
    url = (
        'https://www.linkedin.com/sales-api/salesApiPeopleSearch'
        f'?q=peopleSearchQuery&query={query}&start={start}&count={PAGE_SIZE}&decoration={decoration}'
    )
    response = session.get(url, timeout=30)
    if response.status_code != 200:
        raise LinkedinError(f"PeopleSearch HTTP {response.status_code}: {response.text[:150]}", status=response.status_code)
    return response.json().get('elements', [])


def fetch_inbox(session, count=90):
    """The account's messaging inbox (same decorated endpoint as the legacy scripts).
    Returns the parsed JSON dict."""
    response = session.get(pcom.threads_url(count))
    try:
        res = response.json()
    except Exception:
        raise LinkedinError(f"Inbox returned non-JSON (HTTP {response.status_code})", status=response.status_code)
    if response.status_code != 200:
        code = res.get('code')
        if code == 'SALES_SEAT_REQUIRED':
            raise SeatRequiredError('Account does not have a Sales Navigator seat')
        raise LinkedinError(f"Inbox HTTP {response.status_code}: {str(res)[:150]}", status=response.status_code)
    return res


def get_profile_opentomsg(session, sales_nav_id: str) -> tuple[bool, str]:
    """(open_to_message, linkedin_url) via the profile API - mirrors the
    Opentomsg check in salesApiConnection.py."""
    profile_id = extract_profile_id(sales_nav_id)
    response = session.get(
        f'https://www.linkedin.com/sales-api/salesApiProfiles/(profileId:{profile_id},authType:NAME_SEARCH)',
        params={'decoration': PROFILE_DECORATION},
    )
    res = response.json()
    if response.status_code != 200:
        raise LinkedinError(f"Profile check HTTP {response.status_code}: {str(res)[:150]}", status=response.status_code)
    opentomsg = bool(res.get('memberBadges', {}).get('openLink'))
    return opentomsg, res.get('flagshipProfileUrl', '')


def send_inmail(session, recipient_snid: str, subject: str, body: str):
    """createMessage with a subject (first-touch InMail + InMail follow-ups)."""
    payload = {'createMessageRequest': {
        'subject': subject, 'body': body, 'copyToCrm': False,
        'recipients': [recipient_snid],
    }}
    return _post_message(session, payload)


def send_message(session, recipient_snid: str, body: str):
    """createMessage without a subject (connection messages + after-accept + invite follow-ups)."""
    payload = {'createMessageRequest': {
        'body': body, 'copyToCrm': False, 'recipients': [recipient_snid],
    }}
    return _post_message(session, payload)


def send_connection_invite(session, member_profile_id: str, note: str):
    """connectV2 connection request with the first-touch note."""
    response = session.post(CONNECT_URL, json={'member': member_profile_id, 'message': note})
    return _interpret(response, expect_validation=False)


def _post_message(session, payload):
    response = session.post(MESSAGE_ACTIONS_URL, json=payload)
    return _interpret(response, expect_validation=True)


def _interpret(response, expect_validation=True):
    """Normalize LinkedIn responses into (ok, error_kind, detail).

    error_kind:
      None                       -> ok
      'validation'               -> MESSAGE_VALIDATION_PLUGIN_ERROR (e.g. out of InMail credits)
      'email_required'           -> HTTP 400 "email required to connect" family
      'rate_limited'             -> HTTP 429
      'http'                     -> anything else non-200
    """
    try:
        res = response.json()
    except Exception:
        res = {}
    if expect_validation and res.get('code') == 'MESSAGE_VALIDATION_PLUGIN_ERROR':
        return False, 'validation', res.get('message', 'message validation error')
    if response.status_code == 200:
        return True, None, ''
    if response.status_code == 429:
        return False, 'rate_limited', f"HTTP 429: {response.text[:150]}"
    if response.status_code == 400:
        return False, 'email_required', f"HTTP 400: {response.text[:150]}"
    return False, 'http', f"HTTP {response.status_code}: {response.text[:150]}"


def polite_sleep(lo=10, hi=20):
    """Legacy scripts sleep 10-20s between outbound actions; keep that safety."""
    time.sleep(random.uniform(lo, hi))


class LinkedinError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class SeatRequiredError(LinkedinError):
    pass
