"""Sales Navigator license administration via LinkedIn's enterprise multiadmin API.

Productizes the standalone "Sales Nav activater" script as an in-app feature.

Two rules are baked in on purpose:

* The enterprise admin seat this feature uses is **Anne Davis's cookies file
  only**. No other account's session may be substituted, because only Anne's
  login holds the license-admin entitlement.
* At most ``MAX_LICENSES`` people may hold a Sales Navigator license at once.
  ``plan_activation`` refuses a request that would push the fleet past the cap
  instead of silently over-provisioning the subscription.

Everything here is network-bound (LinkedIn). The orchestration lives in
``app/main.py``; the HTTP calls are kept in small functions so the endpoints can
be exercised offline with mocks.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

from .config import PROJECT_ROOT

try:  # Imported lazily-safe so tests can import this module without the dep.
    import curl_cffi
except Exception:  # pragma: no cover - production always has curl_cffi installed
    curl_cffi = None

# --- Enterprise identifiers -------------------------------------------------
ENTERPRISE_ACCOUNT_ID = '263028290'
ACCOUNT_URN = f'urn:li:enterpriseAccount:{ENTERPRISE_ACCOUNT_ID}'
APP_INSTANCE_URN = f'urn:li:enterpriseApplicationInstance:({ACCOUNT_URN},246906505)'
APPLICATION_URN = 'urn:li:enterpriseApplication:salesNavigator'
LICENSE_TYPE_URN = f'urn:li:enterpriseLicenseType:({APPLICATION_URN},tier2)'
BASE_URL = 'https://www.linkedin.com/enterprise/multiadmin-api'

# The ONLY account whose cookies may drive this feature (enterprise admin seat).
ACTIVATER_ACCOUNT = 'Anne Davis'
ACTIVATER_EMAIL = 'annedavis@vservesolution.com'
ACTIVATER_COOKIES_FILE = 'anne_cookies.json'  # only a fallback; registry wins

# Hard cap on concurrently-assigned Sales Navigator licenses.
MAX_LICENSES = 6

DELAY_SECONDS = 1.5   # be gentle between paged / multi-step calls
PAGE_SIZE = 100
REQUEST_TIMEOUT = 30

LIST_FIELDS = (
    'account,adminType,aggregatedLicenseStatus,aggregatedLicenseStatusChangeTime,'
    'applicationProfileData,emailAddress,groups,idpManagementStatus,isCurrentUser,'
    'licenseTypes,memberBindingStatus,mediaId,preferredFirstName,preferredLastName,'
    'profileIdentity,profileVectorImage,publicFirstName,publicLastName,roleAssignments,'
    'roles,workTitle'
)
TYPEAHEAD_FACETS = (
    '(combinedQueryOption:SHOULD,aclRoles:List(urn%3Ali%3AaclRole%3A%28urn%3Ali%3AaclProductGroup'
    '%3AEnterprisePlatform%2CSalesNavigatorTeamSkuProductAdmin%29,urn%3Ali%3AaclRole%3A%28urn'
    '%3Ali%3AaclProductGroup%3AEnterprisePlatform%2CSalesNavigatorReportingAdmin%29),'
    'enterpriseGroupMatchingOperation:ANY_GROUP)'
)
LICENSE_FACETS = '(activationStatuses:List(ACTIVE,PENDING,DECLINED),combinedQueryOption:SHOULD)'

# A license is "held" (consumes one of the seats) in any of these states.
# DECLINED/UNKNOWN do NOT hold a seat, so they can be re-activated.
HOLDING_STATUSES = frozenset({'ACTIVATED', 'ACTIVE', 'INVITED', 'PENDING'})

# UI ordering for the status pill.
STATUS_ORDER = ('ACTIVATED', 'ACTIVE', 'INVITED', 'PENDING', 'DECLINED', 'NONE')


class SalesNavError(RuntimeError):
    """A multiadmin call failed for a recoverable (server) reason."""


class SalesNavAuthError(SalesNavError):
    """Anne's cookies were missing or rejected by LinkedIn."""


class SalesNavCapError(SalesNavError):
    """A request would exceed the license cap."""


class SalesNavProtectedError(SalesNavError):
    """The admin identity cannot safely be removed."""


@dataclass
class HttpResult:
    status_code: int
    text: str = ''

    @property
    def ok(self) -> bool:
        return self.status_code in (200, 201, 202, 204)


# ---------------------------------------------------------------------------
# Cookie / session handling
# ---------------------------------------------------------------------------

class _AnneAccount:
    """Minimal stand-in so we can reuse app.jobs.canonical_cookies_path."""

    name = ACTIVATER_ACCOUNT


def anne_cookies_path() -> Path:
    """Resolve Anne's cookies file exactly as the rest of the app resolves it.

    ``app.jobs.canonical_cookies_path`` anchors the ROOT ``get_cookies.py``
    registry entry at PROJECT_ROOT, so the app's one true Anne file is
    ``<project root>/cookies_files/anne_cookies.json``. The app-local
    ``app/get_cookies.py`` registry resolves relative to ``app/`` (a DIFFERENT,
    usually nonexistent directory), so it is only a last-resort fallback —
    reading it first would make this feature look for a file that is not there.
    """
    candidates: list[Path] = []

    # 1. The app's canonical resolver (this is where web uploads + local
    #    captures both land, and what session verification reads).
    try:
        from .jobs import canonical_cookies_path
        candidates.append(Path(canonical_cookies_path(_AnneAccount())))
    except Exception:
        pass

    # 2. Root get_cookies.py registry joined to the project root.
    try:
        import importlib
        root_reg = importlib.import_module('get_cookies')
        reg = (getattr(root_reg, 'ACCOUNTS', {}) or {}).get(ACTIVATER_ACCOUNT, {}).get('cookies_file')
        if reg:
            candidates.append(Path(PROJECT_ROOT) / reg)
    except Exception:
        pass

    # 3. App-local registry (legacy layout).
    try:
        from .get_cookies import ACCOUNTS
        cfg = ACCOUNTS.get(ACTIVATER_ACCOUNT) or {}
        if cfg.get('cookies_file'):
            candidates.append(Path(cfg['cookies_file']))
    except Exception:
        pass

    # 4. Conventional name in the app's canonical cookies directory.
    candidates.append(Path(PROJECT_ROOT) / 'cookies_files' / ACTIVATER_COOKIES_FILE)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _build_session():
    if curl_cffi is None:
        raise SalesNavError('curl_cffi is not installed on the server')
    path = anne_cookies_path()
    if not path.exists():
        raise SalesNavAuthError(
            f"Anne's cookies file was not found ({path}). Capture it with get_cookies.py "
            f"for '{ACTIVATER_ACCOUNT}' and retry."
        )
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise SalesNavAuthError(f"Anne's cookies file could not be read: {exc}") from exc
    session = curl_cffi.Session()
    session.headers.update(data.get('headers', {}))
    session.cookies.update(data.get('cookies', {}))
    # These two headers scope every enterprise call to our account + app seat.
    session.headers['x-li-app-instance-urn'] = APP_INSTANCE_URN
    session.headers['x-li-enterprise-account-urn'] = ACCOUNT_URN
    return session


@contextmanager
def open_session() -> Iterator[object]:
    """Yield a curl_cffi session built from Anne's cookies (always closed)."""
    session = _build_session()
    try:
        yield session
    finally:
        close = getattr(session, 'close', None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _raise_for_auth(status_code: int, body: str) -> None:
    if status_code in (401, 403):
        raise SalesNavAuthError(
            f"Anne's cookies were rejected by LinkedIn (HTTP {status_code}). "
            'Re-capture her cookies and retry.'
        )
    raise SalesNavError(f'Sales Navigator API error: HTTP {status_code} {body[:200]}')


# ---------------------------------------------------------------------------
# Multiadmin API calls
# ---------------------------------------------------------------------------

def list_licenses(session) -> list[dict]:
    """Fetch every enterprise profile page-by-page and return the raw elements.

    LinkedIn caps the served page size (a request for 100 still returns
    ``paging.count`` entries, e.g. 20), so pagination is driven by the response
    ``paging`` block rather than by our requested ``PAGE_SIZE``. Stopping on
    ``len(page) < PAGE_SIZE`` would silently truncate a fleet larger than the
    server-side page size.
    """
    app_instance = quote(APP_INSTANCE_URN, safe='')
    elements: list[dict] = []
    start = 0
    while True:
        url = (
            f'{BASE_URL}/enterpriseProfiles?start={start}&count={PAGE_SIZE}&q=searchQuery'
            f'&query=%27%27&rolesFacets=List()&fields={LIST_FIELDS}'
            f'&applicationInstance={app_instance}'
            f'&employeeTypeaheadFacets={TYPEAHEAD_FACETS}'
            f'&licenseAssignmentsFacets={LICENSE_FACETS}'
        )
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            _raise_for_auth(response.status_code, response.text)
        data = response.json() or {}
        page = data.get('elements', []) or []
        elements.extend(page)
        paging = data.get('paging') or {}
        total = paging.get('total')
        count = paging.get('count') or len(page)
        start += count
        if not page or count <= 0:
            break
        if total is not None:
            if start >= total:
                break
        elif len(page) < (paging.get('count') or PAGE_SIZE):
            break
        time.sleep(DELAY_SECONDS)
    return elements


def lookup_profiles(session, emails: list[str]) -> dict[str, str]:
    """Return {email: profileIdentity} for emails that already have a profile."""
    found: dict[str, str] = {}
    if not emails:
        return found
    emails_param = 'List(' + ','.join(quote(e, safe='') for e in emails) + ')'
    response = session.get(f'{BASE_URL}/enterpriseProfiles?emails={emails_param}&q=emails',
                           timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        _raise_for_auth(response.status_code, response.text)
    wanted = {e.lower(): e for e in emails}
    for element in (response.json() or {}).get('elements', []) or []:
        email = (element.get('emailAddress') or '').lower()
        profile_id = element.get('profileIdentity')
        if email in wanted and profile_id:
            found[wanted[email]] = profile_id
    return found


def resolve_profile_ids(session, emails: list[str], create_missing: bool = True) -> dict[str, str]:
    """Resolve profile IDs, optionally creating enterprise profiles for new emails."""
    id_map = lookup_profiles(session, emails)
    missing = [e for e in emails if e not in id_map]
    if not missing or not create_missing:
        return id_map
    response = session.post(f'{BASE_URL}/enterpriseProfiles',
                            params={'action': 'createByEmails'},
                            json={'account': ACCOUNT_URN, 'emails': missing},
                            timeout=REQUEST_TIMEOUT)
    if response.status_code not in (200, 201):
        _raise_for_auth(response.status_code, response.text)
    id_map.update((response.json() or {}).get('value', {}) or {})
    return id_map


def assign_license(session, profile_ids: list[str]) -> HttpResult:
    payload = {
        'applicationInstance': APP_INSTANCE_URN,
        'profiles': profile_ids,
        'licenseTypes': [LICENSE_TYPE_URN],
        'licenseAssignmentAction': {
            'com.linkedin.enterprise.bulk.BulkLicenseOverrideActionContext': {}
        },
        'application': APPLICATION_URN,
    }
    response = session.post(f'{BASE_URL}/bulkAssignLicenseTasks', json=payload,
                            timeout=REQUEST_TIMEOUT)
    return HttpResult(response.status_code, response.text)


def remove_licenses(session, profile_ids: list[str]) -> HttpResult:
    # Protect at the network boundary as well as the endpoint. Resolve from
    # LinkedIn, never from a client-supplied name or protection flag.
    snapshot = build_snapshot(list_licenses(session))
    assert_removable(snapshot, profile_ids=profile_ids)
    payload = {'applicationInstance': APP_INSTANCE_URN, 'profiles': profile_ids}
    response = session.post(f'{BASE_URL}/bulkRemoveProfiles', json=payload,
                            timeout=REQUEST_TIMEOUT)
    return HttpResult(response.status_code, response.text)


def _find_url(obj) -> str | None:
    if isinstance(obj, str):
        return obj if obj.startswith('http') else None
    if isinstance(obj, dict):
        for value in obj.values():
            found = _find_url(value)
            if found:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = _find_url(value)
            if found:
                return found
    return None


def activation_link(session, profile_id: str) -> str:
    """Fetch (best-effort) the activation URL for an emailed invite."""
    if not profile_id:
        return ''
    try:
        response = session.post(
            f'{BASE_URL}/enterpriseProfiles',
            params={'action': 'getActivationLink'},
            data=json.dumps({'application': 'salesNavigator', 'profile': profile_id}),
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            return ''
        return _find_url(response.json()) or ''
    except Exception:
        return ''


# ---------------------------------------------------------------------------
# Pure helpers (no network — easily unit-tested)
# ---------------------------------------------------------------------------

def normalize_email(value: str) -> str:
    return (value or '').strip().lower()


def _element_name(element: dict) -> str:
    first = element.get('preferredFirstName') or element.get('publicFirstName') or ''
    last = element.get('preferredLastName') or element.get('publicLastName') or ''
    return f'{first} {last}'.strip()


def is_protected_profile(element: dict) -> bool:
    names = [_element_name(element),
             f"{element.get('publicFirstName') or ''} {element.get('publicLastName') or ''}"]
    return (normalize_email(element.get('emailAddress')) == ACTIVATER_EMAIL or
            element.get('isCurrentUser') is True or
            any(' '.join(name.split()).casefold() == ACTIVATER_ACCOUNT.casefold()
                for name in names))


def assert_removable(snapshot: dict, emails=(), profile_ids=()) -> None:
    entries = snapshot.get('licenses', []) + snapshot.get('others', [])
    protected = [entry for entry in entries if entry.get('protected')]
    if not protected or any(not entry.get('profile_id') for entry in protected):
        raise SalesNavProtectedError(
            'Cannot verify the protected admin account. Refresh the roster before removing access.')
    protected_emails = {entry['email'] for entry in protected}
    protected_ids = {entry['profile_id'] for entry in protected}
    if protected_emails.intersection(map(normalize_email, emails)) or protected_ids.intersection(profile_ids):
        raise SalesNavProtectedError("Anne Davis is the licence administrator. Her access cannot be removed.")


def build_snapshot(elements: list[dict]) -> dict:
    """Turn raw enterprise profiles into a license summary + per-email lookup.

    Every enterprise profile is returned, split into:
      * ``licenses`` - profiles holding a seat (ACTIVATED/ACTIVE/INVITED/PENDING)
      * ``others``   - profiles WITHOUT a seat (newly added, removed, DECLINED)

    A profile with no license status is reported as ``NONE`` rather than
    dropped, so an account added in the app stays visible after its license is
    removed and can be re-activated.
    """
    entries: list[dict] = []
    by_email: dict[str, dict] = {}
    by_identity: dict[str, dict] = {}
    for element in elements:
        email = normalize_email(element.get('emailAddress'))
        profile_id = element.get('profileIdentity') or ''
        if not email and not profile_id:
            continue
        raw = (element.get('aggregatedLicenseStatus') or '').strip().upper()
        status = 'NONE' if raw in ('', 'UNKNOWN') else raw
        entry = {
            'email': email,
            'status': status,
            'profile_id': profile_id,
            'name': _element_name(element),
            'member_binding_status': element.get('memberBindingStatus') or '',
            'protected': is_protected_profile(element),
        }
        identity = profile_id or email
        if identity in by_identity:
            existing = by_identity[identity]
            existing['protected'] |= entry['protected']
            if entry['status'] in HOLDING_STATUSES:
                existing['status'] = entry['status']
            if email:
                by_email[email] = existing
            continue
        by_identity[identity] = entry
        entries.append(entry)
        if email:
            by_email[email] = entry
    holders = [entry for entry in entries if entry['status'] in HOLDING_STATUSES]
    others = [entry for entry in entries if entry['status'] not in HOLDING_STATUSES]
    used = len(holders)
    return {
        'max_licenses': MAX_LICENSES,
        'used': used,
        'remaining': max(0, MAX_LICENSES - used),
        'licenses': sorted(holders, key=lambda e: (STATUS_ORDER.index(e['status'])
                                                   if e['status'] in STATUS_ORDER else 99,
                                                   e['email'])),
        'others': sorted(others, key=lambda e: e['email']),
        'by_email': by_email,
    }


def plan_activation(snapshot: dict, emails: list[str]) -> dict:
    """Split requested emails into already-held / newly-requested and enforce the cap.

    Raises ``SalesNavCapError`` when the request would exceed ``MAX_LICENSES``.
    """
    by_email = snapshot.get('by_email', {})
    already: list[str] = []
    newly: list[str] = []
    for email in emails:
        if (by_email.get(email, {}).get('status') in HOLDING_STATUSES):
            already.append(email)
        else:
            newly.append(email)
    remaining = MAX_LICENSES - snapshot.get('used', 0)
    if len(newly) > remaining:
        held = ', '.join(f"{e['email']} ({e['status']})" for e in snapshot.get('licenses', [])
                         if e['status'] in HOLDING_STATUSES) or 'none'
        raise SalesNavCapError(
            f'License cap is {MAX_LICENSES}; {snapshot.get("used", 0)} are already in use '
            f'and only {max(0, remaining)} slot(s) remain, but {len(newly)} new license(s) '
            f'were requested. Remove a license first. Currently held by: {held}.'
        )
    return {'already': already, 'newly': newly, 'remaining': max(0, remaining)}
