"""Offline tests for the Sales Navigator license-admin tab.

Covers the three product rules: Anne's cookies file is the only admin seat
used, at most 6 licenses may be assigned, and both activate + remove work
end to end against a mocked multiadmin API.
"""
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import engine
from app.models import Base
from app import salesnav


@pytest.fixture
def client():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with TestClient(app) as c:
        assert c.post('/api/login', json={'username': 'test-admin',
                                          'password': 'test-password-only'}).status_code == 200
        yield c


@contextmanager
def fake_session(*_args, **_kwargs):
    yield object()


def el(email, status, pid=''):
    return {'emailAddress': email, 'aggregatedLicenseStatus': status,
            'profileIdentity': pid, 'preferredFirstName': 'Test', 'preferredLastName': 'User'}


def anne():
    return dict(el('anne@example.com', 'ACTIVATED', 'admin-profile'),
                preferredFirstName='Anne', preferredLastName='Davis', isCurrentUser=True)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_build_snapshot_counts_holders_and_remaining():
    snapshot = salesnav.build_snapshot([
        el('a@x.com', 'ACTIVATED', 'p1'),
        el('b@x.com', 'INVITED', 'p2'),
        el('c@x.com', 'DECLINED', 'p3'),
        el('d@x.com', 'UNKNOWN', ''),
    ])
    assert snapshot['used'] == 2
    assert snapshot['max_licenses'] == 6
    assert snapshot['remaining'] == 4
    assert snapshot['by_email']['a@x.com']['status'] == 'ACTIVATED'
    # A profile with no license is NOT a holder: it is kept as NONE under
    # 'others' so a removed/added account stays visible (and re-activatable).
    assert snapshot['by_email']['d@x.com']['status'] == 'NONE'
    assert [e['email'] for e in snapshot['licenses']] == ['a@x.com', 'b@x.com']
    assert [e['email'] for e in snapshot['others']] == ['c@x.com', 'd@x.com']


def test_plan_activation_blocks_over_cap():
    snapshot = salesnav.build_snapshot(
        [el(f'user{i}@x.com', 'ACTIVATED', f'p{i}') for i in range(6)])
    with pytest.raises(salesnav.SalesNavCapError):
        salesnav.plan_activation(snapshot, ['new@x.com'])


def test_plan_activation_splits_already_and_newly():
    snapshot = salesnav.build_snapshot([el('a@x.com', 'ACTIVATED', 'p1')])
    plan = salesnav.plan_activation(snapshot, ['a@x.com', 'b@x.com', 'c@x.com'])
    assert plan['already'] == ['a@x.com']
    assert plan['newly'] == ['b@x.com', 'c@x.com']
    assert plan['remaining'] == 5


# A trimmed copy of a real enterpriseProfiles response (6 profiles, all
# holding a Sales Navigator license, served with paging.count=20).
REAL_ELEMENTS = [
    el('andrew.jeremy.dreger@gmail.com', 'ACTIVATED', 'ABk-tfkI-1'),
    el('annedavis@vservesolution.com', 'ACTIVATED', 'ABk-tfkI-2'),
    el('cindy@vservesolution.com', 'INVITED', 'ABk-tfkI-3'),
    el('cynthiadavid94@gmail.com', 'ACTIVATED', 'ABk-tfkI-4'),
    el('david@vservecommerce.com', 'ACTIVATED', 'ABk-tfkI-5'),
    el('kimberly@vgrowsolutions.co', 'ACTIVATED', 'ABk-tfkI-6'),
]


def test_real_payload_is_saturated_at_the_cap():
    snapshot = salesnav.build_snapshot(REAL_ELEMENTS)
    assert snapshot['used'] == 6
    assert snapshot['remaining'] == 0
    with pytest.raises(salesnav.SalesNavCapError):
        salesnav.plan_activation(snapshot, ['someone@new.com'])
    # Removing a seat frees a slot for exactly one activation.
    freed = salesnav.plan_activation(snapshot, ['cindy@vservesolution.com'])
    assert freed['already'] == ['cindy@vservesolution.com']


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ''

    def json(self):
        return self._payload


def test_list_licenses_follows_server_page_size():
    # LinkedIn serves fewer rows than requested (count=2 even though we ask for
    # PAGE_SIZE=100) — pagination must use paging.total, not the requested size.
    pages = [
        {'elements': [el('a@x.com', 'ACTIVATED', 'p1'), el('b@x.com', 'ACTIVATED', 'p2')],
         'paging': {'start': 0, 'count': 2, 'total': 3}},
        {'elements': [el('c@x.com', 'ACTIVATED', 'p3')],
         'paging': {'start': 2, 'count': 1, 'total': 3}},
    ]
    calls = {'n': 0}

    class _Session:
        def get(self, _url, timeout=None):
            payload = pages[calls['n']]
            calls['n'] += 1
            return _FakeResponse(payload)

    with patch.object(salesnav, 'DELAY_SECONDS', 0):
        elements = salesnav.list_licenses(_Session())
    assert len(elements) == 3
    assert calls['n'] == 2


def test_anne_is_the_only_admin_seat():
    assert salesnav.ACTIVATER_ACCOUNT == 'Anne Davis'
    assert salesnav.MAX_LICENSES == 6
    assert salesnav.anne_cookies_path().name == 'anne_cookies.json'


def test_anne_cookies_path_is_the_apps_canonical_file():
    # Regression: the file must resolve the SAME way the rest of the app
    # resolves it (<project root>/cookies_files/anne_cookies.json), not via
    # app/get_cookies.py which anchors under app/cookies_files/ (nonexistent).
    from pathlib import Path
    from app.config import PROJECT_ROOT
    from app.jobs import canonical_cookies_path
    resolved = salesnav.anne_cookies_path()
    assert resolved == Path(canonical_cookies_path(salesnav._AnneAccount()))
    assert resolved.parent == Path(PROJECT_ROOT) / 'cookies_files'


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def test_requires_auth():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with TestClient(app) as c:
        assert c.get('/api/salesnav/licenses').status_code == 401
        assert c.post('/api/salesnav/activate', json={'emails': ['a@x.com']}).status_code == 401


def test_license_list(client):
    elements = [el('a@x.com', 'ACTIVATED', 'p1'), el('b@x.com', 'INVITED', 'p2'),
                el('c@x.com', 'DECLINED', 'p3'), el('d@x.com', 'UNKNOWN', '')]
    with patch.object(salesnav, 'open_session', fake_session), \
         patch.object(salesnav, 'list_licenses', return_value=elements):
        response = client.get('/api/salesnav/licenses')
    assert response.status_code == 200
    body = response.json()
    assert body['used'] == 2 and body['max_licenses'] == 6 and body['remaining'] == 4
    assert {row['email'] for row in body['licenses']} == {'a@x.com', 'b@x.com'}
    # Non-holders are returned separately so they stay listed after a removal.
    assert {row['email'] for row in body['others']} == {'c@x.com', 'd@x.com'}


def test_activate_within_cap(client):
    elements = [el('a@x.com', 'ACTIVATED', 'p1'), el('b@x.com', 'INVITED', 'p2')]

    def resolve(_session, emails, create_missing=True):
        return {e: 'p-' + e for e in emails}

    with patch.object(salesnav, 'open_session', fake_session), \
         patch.object(salesnav, 'list_licenses', return_value=elements), \
         patch.object(salesnav, 'resolve_profile_ids', side_effect=resolve), \
         patch.object(salesnav, 'assign_license', return_value=salesnav.HttpResult(200, '{}')), \
         patch.object(salesnav, 'activation_link', return_value='https://act/x'):
        response = client.post('/api/salesnav/activate',
                               json={'emails': ['c@x.com', 'D@X.com ', 'c@x.com']})
    assert response.status_code == 200
    body = response.json()
    # 2 pre-existing + 2 new seats, dedupe + normalization applied.
    assert body['used'] == 4 and body['remaining'] == 2
    assert sorted(row['email'] for row in body['results']) == ['c@x.com', 'd@x.com']
    assert {row['action'] for row in body['results']} == {'activated'}
    assert all(row['link'] == 'https://act/x' for row in body['results'])


def test_activate_over_cap_is_blocked(client):
    elements = [el(f'u{i}@x.com', 'ACTIVATED', f'p{i}') for i in range(6)]
    with patch.object(salesnav, 'open_session', fake_session), \
         patch.object(salesnav, 'list_licenses', return_value=elements), \
         patch.object(salesnav, 'assign_license') as assign:
        response = client.post('/api/salesnav/activate', json={'emails': ['new@x.com']})
    assert response.status_code == 409
    assert 'cap' in response.json()['detail'].lower()
    assign.assert_not_called()


def test_activate_already_licensed_is_idempotent(client):
    elements = [el('a@x.com', 'ACTIVATED', 'p1')]
    with patch.object(salesnav, 'open_session', fake_session), \
         patch.object(salesnav, 'list_licenses', return_value=elements), \
         patch.object(salesnav, 'assign_license') as assign:
        response = client.post('/api/salesnav/activate', json={'emails': ['a@x.com']})
    assert response.status_code == 200
    body = response.json()
    assert body['used'] == 1
    assert body['results'][0]['action'] == 'skipped'
    assign.assert_not_called()


def test_remove_licenses(client):
    def resolve(_session, emails, create_missing=False):
        return {e: 'p1' for e in emails if e == 'a@x.com'}

    with patch.object(salesnav, 'open_session', fake_session), \
         patch.object(salesnav, 'list_licenses', return_value=[anne(), el('a@x.com', 'ACTIVE', 'p1')]), \
         patch.object(salesnav, 'resolve_profile_ids', side_effect=resolve), \
         patch.object(salesnav, 'remove_licenses', return_value=salesnav.HttpResult(200, '')):
        response = client.post('/api/salesnav/remove', json={'emails': ['a@x.com', 'b@x.com']})
    assert response.status_code == 200
    body = response.json()
    assert body['removed'] == 1
    actions = {row['email']: row['action'] for row in body['results']}
    assert actions == {'a@x.com': 'removed', 'b@x.com': 'skipped'}


def test_add_creates_profiles_without_license(client):
    def lookup(_session, emails):
        return {'a@x.com': 'p1'} if 'a@x.com' in emails else {}

    def resolve(_session, emails, create_missing=True):
        return {e: 'p-' + e for e in emails}

    with patch.object(salesnav, 'open_session', fake_session), \
         patch.object(salesnav, 'lookup_profiles', side_effect=lookup), \
         patch.object(salesnav, 'resolve_profile_ids', side_effect=resolve):
        response = client.post('/api/salesnav/add', json={'emails': ['a@x.com', 'b@x.com']})
    assert response.status_code == 200
    body = response.json()
    assert body['created'] == 1
    actions = {row['email']: row['action'] for row in body['results']}
    assert actions == {'a@x.com': 'exists', 'b@x.com': 'created'}


def test_invalid_email_rejected(client):
    with patch.object(salesnav, 'open_session', fake_session):
        assert client.post('/api/salesnav/activate',
                           json={'emails': ['not-an-email']}).status_code == 422
        assert client.post('/api/salesnav/remove', json={'emails': []}).status_code == 422


def test_missing_anne_cookies_does_not_expire_app_login(client, tmp_path):
    with patch.object(salesnav, 'anne_cookies_path', return_value=tmp_path / 'nope.json'):
        response = client.get('/api/salesnav/licenses')
    assert response.status_code == 502
    assert client.get('/api/me').status_code == 200


@pytest.mark.parametrize('emails', [['anne@example.com'], ['a@x.com', 'ANNE@example.com']])
def test_remove_admin_rejected_before_any_mutation(client, emails):
    with patch.object(salesnav, 'open_session', fake_session), \
         patch.object(salesnav, 'list_licenses', return_value=[anne()]), \
         patch.object(salesnav, 'resolve_profile_ids') as resolve, \
         patch.object(salesnav, 'remove_licenses') as remove:
        response = client.post('/api/salesnav/remove', json={'emails': emails})
    assert response.status_code == 403
    assert 'cannot be removed' in response.json()['detail']
    resolve.assert_not_called()
    remove.assert_not_called()


def test_protected_profile_alias_cannot_bypass_guard(client):
    with patch.object(salesnav, 'open_session', fake_session), \
         patch.object(salesnav, 'list_licenses', return_value=[anne()]), \
         patch.object(salesnav, 'resolve_profile_ids', return_value={'alias@x.com':'admin-profile'}), \
         patch.object(salesnav, 'remove_licenses') as remove:
        response = client.post('/api/salesnav/remove', json={'emails':['alias@x.com']})
    assert response.status_code == 403
    remove.assert_not_called()


def test_removal_fails_closed_when_admin_identity_missing(client):
    with patch.object(salesnav, 'open_session', fake_session), \
         patch.object(salesnav, 'list_licenses', return_value=[]), \
         patch.object(salesnav, 'remove_licenses') as remove:
        response = client.post('/api/salesnav/remove', json={'emails':['a@x.com']})
    assert response.status_code == 403
    remove.assert_not_called()


def test_network_boundary_also_protects_admin():
    from unittest.mock import Mock
    session = Mock()
    with patch.object(salesnav, 'list_licenses', return_value=[anne()]):
        with pytest.raises(salesnav.SalesNavProtectedError):
            salesnav.remove_licenses(session, ['admin-profile'])
    session.post.assert_not_called()


@pytest.mark.parametrize('overrides', [dict(isCurrentUser=False),
    dict(preferredFirstName='Different', preferredLastName='Name'),
    dict(isCurrentUser=False, preferredFirstName='Different', preferredLastName='Name',
         publicFirstName='Anne', publicLastName='Davis')])
def test_admin_identified_from_provider_identity_and_names(overrides):
    row=anne();row.update(overrides)
    assert salesnav.build_snapshot([row])['licenses'][0]['protected']


def test_snapshot_deduplicates_profile_and_counts_seats_without_email():
    data=salesnav.build_snapshot([anne(),anne(),el('', 'ACTIVE', 'no-email')])
    assert data['used']==2


@pytest.mark.parametrize('code', [401,403,429,500])
def test_profile_lookup_failure_never_creates_profiles(code):
    from unittest.mock import Mock
    session=Mock();session.get.return_value.status_code=code;session.get.return_value.text='failure'
    with pytest.raises(salesnav.SalesNavError):
        salesnav.resolve_profile_ids(session,['new@example.com'])
    session.post.assert_not_called()


@pytest.mark.parametrize('email', ['a@@b.com','a b@x.com','a@.com','a@x.com.'])
def test_malformed_emails_blocked(client,email):
    with patch.object(salesnav,'open_session') as session:
        assert client.post('/api/salesnav/add',json={'emails':[email]}).status_code==422
    session.assert_not_called()


def test_campaign_manager_cannot_manage_enterprise_licences(client):
    from app.database import SessionLocal
    from app.models import User
    from app.auth import create_session, hash_password
    with SessionLocal() as db:
        user=User(username='restricted-manager',password_hash=hash_password('test'),role='campaign_manager',active=True)
        db.add(user);db.commit();token=create_session(user.id)
    client.cookies.set('occ_session',token)
    with patch.object(salesnav,'open_session') as session:
        assert client.get('/api/salesnav/licenses').status_code==403
        for action in ['add','activate','remove','link']:
            assert client.post('/api/salesnav/'+action,json={'emails':['a@x.com']}).status_code==403
    session.assert_not_called()


def test_campaign_manager_with_can_manage_licenses_can_access(client):
    from app.database import SessionLocal
    from app.models import User
    from app.auth import create_session, hash_password
    with SessionLocal() as db:
        user=User(username='licensed-manager',password_hash=hash_password('test'),role='campaign_manager',can_manage_licenses=True,active=True)
        db.add(user);db.commit();token=create_session(user.id)
    client.cookies.set('occ_session',token)
    with patch.object(salesnav,'open_session'), patch.object(salesnav,'list_licenses',return_value=[]):
        res = client.get('/api/salesnav/licenses')
        assert res.status_code == 200


def test_admin_email_protected_when_names_are_missing():
    assert salesnav.build_snapshot([el(salesnav.ACTIVATER_EMAIL, 'ACTIVE', 'admin')])['licenses'][0]['protected']


def test_pagination_without_total_uses_provider_page_size():
    from unittest.mock import Mock
    session=Mock()
    session.get.side_effect=[
        _FakeResponse({'elements':[el('a@x.com','ACTIVE','1')], 'paging':{'count':1}}),
        _FakeResponse({'elements':[el('b@x.com','ACTIVE','2')], 'paging':{'count':1}}),
        _FakeResponse({'elements':[], 'paging':{'count':1}}),
    ]
    with patch.object(salesnav,'DELAY_SECONDS',0):
        assert len(salesnav.list_licenses(session))==2
    assert session.get.call_count==3


def test_invite_link_timeout_does_not_report_assignment_as_failed():
    from unittest.mock import Mock
    session=Mock();session.post.side_effect=TimeoutError('provider timeout')
    assert salesnav.activation_link(session, 'assigned-profile') == ''
