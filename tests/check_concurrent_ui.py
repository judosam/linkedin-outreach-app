"""Browser verification with two isolated users and simulated local workers.
Run: python tests/check_concurrent_ui.py
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = 'http://127.0.0.1:8779'


def serve():
    data = tempfile.TemporaryDirectory()
    os.environ.update(OCC_APP_DATA_DIR=data.name, OCC_DB_URL='sqlite:///'+data.name.replace('\\','/')+'/ui.db',
                      OCC_DISABLE_SCHEDULER='1', OCC_ADMIN_USERNAME='test-admin', OCC_ADMIN_PASSWORD='test-password-only',
                      NOTIFY_SENDER_APP_PASSWORD='offline-test-only', GCHAT_WEBHOOK_URL='')
    from app.main import app
    from app import jobs, runner, notify
    from app.database import SessionLocal
    from app.auth import hash_password
    from app.models import Account, Campaign, CampaignAccount, User
    notify.send_gchat = lambda *a, **kw: False
    notify.send_reply_digest = lambda *a, **kw: False
    with SessionLocal() as db:
        for aid, name in [(1,'Operator One'),(2,'Operator Two')]:
            db.add(Account(id=aid,name=name,status='active'))
            db.add(Campaign(id=aid,name=f'Campaign {aid}',campaign_key=f'fixture{aid}'))
            db.add(User(username=f'manager{aid}',password_hash=hash_password('offline-password'),role='campaign_manager',
                        allowed_campaign_ids=[aid],allowed_account_ids=[aid],active=True))
        db.flush()
        db.add_all([CampaignAccount(campaign_id=i,account_id=i) for i in (1,2)])
        db.commit()
    def simulated_worker(key,dry_run=False,**scope):
        aid=scope['account_ids'][0]
        with SessionLocal() as db:
            run=jobs._Run(db,jobs.JobType(key),f'Operator {aid}',dry_run,account_id=aid)
            run.log(f'Private output for operator {aid}')
            runner.sleep_or_stop(100)
            run.finish()
    jobs.run_job=simulated_worker
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8779,log_level='warning')


def check():
    import urllib.request
    from playwright.sync_api import sync_playwright, expect
    process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve'],cwd=ROOT,
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE+'/',timeout=1)
                break
            except Exception:
                if process.poll() is not None: raise RuntimeError('Fixture server failed')
                time.sleep(.2)
        else: raise RuntimeError('Fixture server did not start')
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            errors=[]
            def logged_in(username,password):
                context=browser.new_context(viewport={'width':1440,'height':1000})
                page=context.new_page()
                page.on('pageerror',lambda e:errors.append(str(e)))
                assert page.request.post(BASE+'/api/login',data={'username':username,'password':password}).ok
                page.goto(BASE+'/#/workers')
                expect(page.locator('[data-run="check_replies"]')).to_be_visible()
                return page
            one=logged_in('manager1','offline-password')
            two=logged_in('manager2','offline-password')
            admin=logged_in('test-admin','test-password-only')
            for page in (one,two):
                page.locator('[data-run="check_replies"]').click()
                page.locator('#wDry').check()
                page.locator('#wGo').click()
                expect(page).to_have_url(BASE+'/#/dashboard')
                expect(page.locator('#floatingOutput')).to_contain_text('Private output',timeout=10000)
            stream=one.evaluate('''async () => {
                const response=await fetch('/api/runs/live/stream');
                const reader=response.body.getReader();
                const first=await reader.read(); await reader.cancel();
                return new TextDecoder().decode(first.value);
            }''')
            assert 'operator 1' in stream and 'operator 2' not in stream
            expect(one.locator('#floatingOutput')).to_contain_text('operator 1')
            expect(two.locator('#floatingOutput')).to_contain_text('operator 2')
            assert 'operator 2' not in one.locator('#floatingOutput').inner_text()
            admin.locator('#floatingBall').click()
            expect(admin.locator('#consoleRunSelect option')).to_have_count(2,timeout=10000)
            expect(admin.locator('#floatingCount')).to_have_text('2')
            runs=admin.request.get(BASE+'/api/jobs').json()['running']
            for run in runs:
                admin.locator('#consoleRunSelect').select_option(run['execution_id'])
                aid=run['account_ids'][0]
                expect(admin.locator('#floatingOutput')).to_contain_text(f'operator {aid}',timeout=10000)
            admin.reload()
            expect(admin.locator('main .engine-chip')).to_contain_text('Running:')
            expect(admin.locator('[data-run="check_replies"]')).to_be_enabled()
            admin.locator('[data-run="send_connections"]').click()
            expect(admin.locator('#wGo')).to_be_enabled()
            admin.locator('#modalHost [data-close2]').click()
            admin.locator('#floatingBall').click()
            if not admin.locator('#floatingPanel').is_visible():admin.locator('#floatingBall').click()
            admin.screenshot(path=str(ROOT/'tests/concurrent-console-desktop.png'))
            admin.set_viewport_size({'width':390,'height':844})
            assert admin.evaluate('document.documentElement.scrollWidth <= innerWidth')
            admin.screenshot(path=str(ROOT/'tests/concurrent-console-mobile.png'))
            one.on('dialog',lambda dialog:dialog.accept())
            one.locator('#floatingStop').click()
            expect(one.locator('#floatingStatus')).to_have_text('Stopped',timeout=10000)
            assert two.request.get(BASE+'/api/runs/live').json()['active'] is True
            assert two.request.get(BASE+'/api/runs').json()[0]['status']=='running'
            # Reuse the admin browser session as a manager; no previous output survives.
            admin.request.post(BASE+'/api/logout')
            admin.reload()
            expect(admin.locator('#app')).to_be_hidden()
            assert admin.locator('#floatingConsole').count()==0
            assert admin.request.post(BASE+'/api/login',data={'username':'manager1','password':'offline-password'}).ok
            admin.reload()
            admin.locator('#floatingBall').click()
            expect(admin.locator('#floatingOutput')).to_contain_text('operator 1',timeout=10000)
            assert 'operator 2' not in admin.locator('#floatingOutput').inner_text()
            assert errors==[],errors
            browser.close()
        print('PASS: concurrent starts, dashboard redirect, admin run selector, private logs, targeted stop, mobile fit, logout isolation; no browser errors.')
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__=='__main__':
    serve() if len(sys.argv)>1 and sys.argv[1]=='serve' else check()


