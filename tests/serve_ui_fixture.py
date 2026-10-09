"""Local UI fixture; no real accounts, credentials or scheduled jobs."""
import os
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temp = tempfile.TemporaryDirectory()
os.environ.update(OCC_APP_DATA_DIR=temp.name,
                  OCC_DB_URL='sqlite:///' + temp.name.replace('\\', '/') + '/ui.db',
                  OCC_DISABLE_SCHEDULER='1', OCC_ADMIN_USERNAME='test-admin',
                  OCC_ADMIN_PASSWORD='test-password-only', NOTIFY_SENDER_APP_PASSWORD='offline-test-only',
                  GCHAT_WEBHOOK_URL='')
from app.main import app
from app import notify
notify.send_gchat = lambda *args, **kwargs: False
notify.send_reply_digest = lambda *args, **kwargs: False
from app.database import SessionLocal
from app.models import Account, Campaign, CampaignAccount, Lead
from datetime import datetime
with SessionLocal() as db:
    account = Account(name='Fixture account', session_ref='')
    one = Campaign(name='Fixture SCM', campaign_key='Fixture SCM')
    two = Campaign(name='Fixture Procurement', campaign_key='Fixture Procurement')
    db.add_all([account,one,two]); db.flush()
    db.add_all([CampaignAccount(campaign_id=one.id,account_id=account.id), CampaignAccount(campaign_id=two.id,account_id=account.id)])
    db.add(Lead(sales_nav_id='ACwTEST', full_name='Fixture lead', campaign_id=one.id, received_replies=True, reply_message='Fixture reply', reply_received_at=datetime.utcnow()))
    db.commit()
import uvicorn
uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('OCC_TEST_PORT', '8765')))
