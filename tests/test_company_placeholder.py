"""The {company} placeholder in campaign texts (invite, InMail, follow-ups).

Offline: LinkedIn sends are mocked; no sessions, emails or chats leave here.
"""
from unittest.mock import Mock

from app import jobs
from app.database import SessionLocal
from app.models import Campaign
from tests.test_audit_fixes import audit, seed_lead  # noqa: F401


def _capture_invite(monkeypatch):
    """Point jobs.li.send_connection_invite at a spy and return it."""
    send = Mock(return_value=(True, None, 'offline'))
    monkeypatch.setattr(jobs.li, 'send_connection_invite', send)
    return send


def test_invite_note_substitutes_company(audit, monkeypatch):
    seed_lead(sales_nav_id='ACwCO1', first_name='Dee', full_name='Dee Duvall', company='Northwind Traders')
    send = _capture_invite(monkeypatch)
    with SessionLocal() as db:
        db.get(Campaign, 1).invite_text = 'Hi {first_name} from {company}!'
        db.commit()
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    assert send.call_args.args[2] == 'Hi Dee from Northwind Traders!'


def test_invite_note_missing_company_becomes_blank(audit, monkeypatch):
    """No {company} value on the lead must never leak a raw '{company}'."""
    seed_lead(sales_nav_id='ACwCO2', first_name='Lou', full_name='Lou Reed', company=None)
    send = _capture_invite(monkeypatch)
    with SessionLocal() as db:
        db.get(Campaign, 1).invite_text = 'Hi {first_name} at {company}!'
        db.commit()
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    assert send.call_args.args[2] == 'Hi Lou at !'


def test_invite_note_accepts_empty_company_without_braces(audit, monkeypatch):
    """Legacy campaign texts without any {company} keep working unchanged."""
    seed_lead(sales_nav_id='ACwCO3', first_name='Kai', full_name='Kai Wren', company='Globex')
    send = _capture_invite(monkeypatch)
    with SessionLocal() as db:
        db.get(Campaign, 1).invite_text = 'Hello {first_name}, quick chat? {calendar_url}'
        db.commit()
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    assert send.call_args.args[2] == 'Hello Kai, quick chat? '


def test_inmail_subject_and_body_substitute_company(audit, monkeypatch):
    seed_lead(sales_nav_id='ACwCO4', first_name='Ana', full_name='Ana Petrov',
              opentomsg=True, company='Stark Industries')
    inmail = Mock(return_value=(True, None, 'offline'))
    monkeypatch.setattr(jobs.li, 'send_inmail', inmail)
    with SessionLocal() as db:
        c = db.get(Campaign, 1)
        c.inmail_subject = '{company}: {first_name}?'
        c.inmail_text = 'Hi {first_name}, saw {company} is hiring.'
        db.commit()
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    subject, body = inmail.call_args.args[2], inmail.call_args.args[3]
    assert subject == 'Stark Industries: Ana?'
    assert body == 'Hi Ana, saw Stark Industries is hiring.'


def test_after_acceptance_message_substitutes_company(audit, monkeypatch):
    lead_id = seed_lead(sales_nav_id='ACwCO5', first_name='Rho', full_name='Rho Basil',
                        company='Wayne Enterprises', status='INVITE_SENT', associate_account_id=1)
    send = Mock(return_value=(True, None, 'offline'))
    monkeypatch.setattr(jobs.li, 'send_message', send)
    monkeypatch.setattr(jobs.li, 'fetch_inbox', lambda *a, **k: {'elements': [
        {'participants': ['urn:li:fs_salesProfile:ACwCO5'],
         'messages': [{'type': 'INVITATION', 'body': 'connect', 'author': 'urn:li:fs_salesProfile:ACwCO5'}]}]})
    with SessionLocal() as db:
        db.get(Campaign, 1).invite_track = ['Welcome to {company} onboarding, {first_name}!']
        db.commit()
    jobs.job_check_replies(campaign_ids=[1], account_ids=[1])
    assert send.call_args.args[2] == 'Welcome to Wayne Enterprises onboarding, Rho!'


def test_followup_substitutes_company(audit, monkeypatch):
    """InMail-track follow-up bodies and subjects get {company} too."""
    from datetime import datetime, timedelta
    seed_lead(sales_nav_id='ACwCO6', first_name='Sol', full_name='Sol Ren', company='Umbrella Corp',
              status='INMAIL_SENT', associate_account_id=1,
              status_changed_at=datetime.utcnow() - timedelta(days=5))
    inmail = Mock(return_value=(True, None, 'offline'))
    monkeypatch.setattr(jobs.li, 'send_inmail', inmail)
    with SessionLocal() as db:
        c = db.get(Campaign, 1)
        c.inmail_track = [{'subject': 'Re {first_name}', 'body': 'Following up with {company}'}]
        db.commit()
    jobs.job_send_followups(campaign_ids=[1], account_ids=[1])
    assert inmail.call_count == 1
    subject, body = inmail.call_args.args[2], inmail.call_args.args[3]
    assert subject == 'Re Sol'
    assert body == 'Following up with Umbrella Corp'


def test_unknown_placeholders_blank_out_instead_of_crashing(audit, monkeypatch):
    """A stray {token}, doubled braces or lone brace must not crash a send or
    leak raw braces to a prospect."""
    seed_lead(sales_nav_id='ACwCO7', first_name='Fay', full_name='Fay Nord', company='Acme')
    send = _capture_invite(monkeypatch)
    with SessionLocal() as db:
        db.get(Campaign, 1).invite_text = 'Hey {first_name} {{literal}} {company} {oops} }'
        db.commit()
    jobs.job_send_connections(campaign_ids=[1], account_ids=[1])
    note = send.call_args.args[2]
    assert note == 'Hey Fay  Acme  '
    assert '{' not in note and '}' not in note
