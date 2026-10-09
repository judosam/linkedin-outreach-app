"""Isolated licence UI fixture. All provider actions are mocked; no real seats."""
import os
import sys
import tempfile
from pathlib import Path
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temp = tempfile.TemporaryDirectory()
os.environ.update(OCC_APP_DATA_DIR=temp.name,
                  OCC_DB_URL='sqlite:///' + temp.name.replace('\\', '/') + '/demo.db',
                  OCC_DISABLE_SCHEDULER='1', OCC_ADMIN_USERNAME='test-admin',
                  OCC_ADMIN_PASSWORD='test-password-only',
                  NOTIFY_SENDER_APP_PASSWORD='offline-test-only', GCHAT_WEBHOOK_URL='')
from app.main import app
from app import salesnav, notify
from app.database import SessionLocal
from app.models import Account, Campaign, CampaignAccount, DailySendCount, Lead
from datetime import datetime

with SessionLocal() as db:
    db.add_all([Account(id=1,name='Anne Davis'),Account(id=2,name='Ranganathan A')])
    db.add_all([Campaign(id=1,name='GCC',campaign_key='gcc'),Campaign(id=2,name='SCM Podcast',campaign_key='scm')])
    db.flush()
    db.add_all([CampaignAccount(campaign_id=1,account_id=2),CampaignAccount(campaign_id=2,account_id=1)])
    db.add(DailySendCount(campaign_id=1,account_id=2,date=datetime.utcnow().date(),invite_sent_count=12,opentomsg_count=4,messages_sent=18))
    db.add(Lead(full_name='Demo prospect',sales_nav_id='ACwDEMO',campaign_id=1))
    db.commit()

notify.send_gchat = lambda *a, **k: False
notify.send_reply_digest = lambda *a, **k: False

@contextmanager
def fake_session():
    yield object()

def row(name, email, status, pid, **extra):
    first, last = name.split(' ', 1)
    return dict(emailAddress=email, preferredFirstName=first, preferredLastName=last,
                aggregatedLicenseStatus=status, profileIdentity=pid, **extra)

elements = [row('Anne Davis', 'annedavis@vservesolution.com', 'ACTIVATED', 'admin', isCurrentUser=True),
            row('Cindy Smith', 'cindy@example.com', 'INVITED', 'cindy'),
            row('Ranganathan A', 'ranganathan@example.com', 'ACTIVATED', 'ranganathan'),
            row('Andrew Dreger', 'andrew@example.com', 'NONE', 'andrew')]
salesnav.open_session = fake_session
salesnav.list_licenses = lambda session: elements
salesnav.resolve_profile_ids = lambda session, emails, create_missing=True: {e:'p-'+e for e in emails}
salesnav.lookup_profiles = lambda session, emails: {e:'p-'+e for e in emails}
salesnav.assign_license = lambda *a: salesnav.HttpResult(202, '')
salesnav.remove_licenses = lambda *a: salesnav.HttpResult(500, 'Simulated removal failure')
salesnav.activation_link = lambda *a: 'https://www.linkedin.com/mock-invite'

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8775)
