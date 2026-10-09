from app.database import SessionLocal
from app.models import Account
from app.linkedin import fetch_inbox
from app.jobs import load_session_ref

db = SessionLocal()
account = db.query(Account).filter(Account.status == 'active').first()
if account:
    session = load_session_ref(account)
    inbox = fetch_inbox(session, count=2)
    elements = inbox.get('elements', [])
    for el in elements:
        print("Participants:", el.get('participants'))
else:
    print("No active accounts")
