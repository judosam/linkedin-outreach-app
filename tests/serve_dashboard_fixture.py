"""Isolated dashboard demo; never uses production accounts or sends outreach."""
import os
import tempfile
import sys
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temp = tempfile.TemporaryDirectory()
os.environ.update(OCC_APP_DATA_DIR=temp.name, OCC_DB_URL='sqlite:///' + temp.name.replace('\\','/') + '/demo.db',
                  OCC_DISABLE_SCHEDULER='1', OCC_ADMIN_USERNAME='test-admin', OCC_ADMIN_PASSWORD='test-password-only',
                  NOTIFY_SENDER_APP_PASSWORD='offline-test-only', GCHAT_WEBHOOK_URL='')
from app.main import app
from app.database import SessionLocal
from app.models import Account, Campaign, CampaignAccount, DailySendCount, RunLog, UserActivity, Lead, LeadEvent
from app import notify
notify.send_gchat = lambda *a, **k: False
notify.send_reply_digest = lambda *a, **k: False
with SessionLocal() as db:
    db.add_all([Account(id=1,name='Ranganathan A'), Account(id=2,name='Cindy Smith')])
    db.add_all([Campaign(id=1,name='GCC',campaign_key='gcc'), Campaign(id=2,name='SCM Podcast',campaign_key='scm'),
                Campaign(id=3,name='Paused campaign',campaign_key='paused',status='paused'),
                Campaign(id=4,name='Procurement',campaign_key='procurement')])
    db.flush()
    for cid,aid,invites,inmails,messages in [(1,1,8,3,9),(1,2,4,2,6),(2,1,5,1,4),(3,2,99,99,99)]:
        db.add(CampaignAccount(campaign_id=cid,account_id=aid))
        db.add(DailySendCount(campaign_id=cid,account_id=aid,date=datetime.utcnow().date(),invite_sent_count=invites,opentomsg_count=inmails,messages_sent=messages))
    db.add(DailySendCount(campaign_id=1,account_id=1,date=datetime.utcnow().date()-timedelta(days=6),invite_sent_count=7))
    for job in ['send_connections','send_followups','check_replies']:
        db.add(RunLog(job_type=job,status='success',owner_user_id=1,campaign_id=1,account_id=1,
                      target='GCC / Ranganathan A',log_text='Fixture console output: completed successfully.',stats={'confirmed':8}))
    leads_data = [
        ('Edward Keefe', 'M/C Partners', 'InMail Follow-up 2 sent', 'outbound'),
        ('Jeffrey Dunn', 'Generous Brands', 'InMail Follow-up 2 sent', 'outbound'),
        ('Noreen Allen', 'YOOBIC', 'InMail Follow-up 2 sent', 'outbound'),
        ('Paul Cunningham', 'Circuitry.ai', 'InMail Follow-up 2 sent', 'outbound'),
        ('Sarah Jenkins', 'Apex Cloud', 'Thanks for the invite! Let’s chat.', 'reply'),
    ]
    for idx, (name, comp, detail, kind) in enumerate(leads_data, start=1):
        ld = Lead(id=idx, full_name=name, company=comp, sales_nav_id=f'ACw{idx}', campaign_id=1, associate_account_id=1)
        db.add(ld)
        db.flush()
        db.add(LeadEvent(lead_id=ld.id, kind=kind, detail=detail, job_type='send_followups',
                         created_at=datetime.utcnow() - timedelta(minutes=idx*14)))
    db.add(UserActivity(user_id=1,username='test-admin',action='reassign_leads',detail='4 leads moved to GCC; stages preserved',result='success'))
    db.commit()
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=8774)
