"""Verify campaign-only access for a newly created user in an isolated browser."""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8784'
server=subprocess.Popen([sys.executable,str(ROOT/'tests/serve_ui_fixture.py')],cwd=ROOT,
                        env={**os.environ,'OCC_TEST_PORT':'8784'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
try:
    for _ in range(60):
        try:urllib.request.urlopen(BASE+'/',timeout=1);break
        except Exception:
            if server.poll() is not None:raise RuntimeError('Fixture server stopped')
            time.sleep(.2)
    else:raise RuntimeError('Fixture server failed to start')
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        assert page.request.post(BASE+'/api/login',data={'username':'test-admin','password':'test-password-only'}).ok
        page.goto(BASE+'/#/dashboard')
        page.wait_for_function("typeof userEditor === 'function'")
        page.evaluate('userEditor(null)')
        form=page.locator('#userForm')
        expect(page.locator('#uCampsLabel')).to_have_text('None selected — no access')
        form.locator('[name=username]').fill('prabhu')
        form.locator('[name=password]').fill('fixture-password-only')
        page.locator('#uCampsBtn').click()
        popup=page.locator('.scope-pop')
        popup.locator('input[value="2"]').check()
        popup.locator('[data-ok]').click()
        page.locator('#uAcctsBtn').click()
        popup.locator('[data-all]').click()
        popup.locator('[data-ok]').click()
        with page.expect_response(lambda r:r.url.endswith('/api/users') and r.request.method=='POST') as saved:
            page.locator('#userSave').click()
        assert saved.value.ok
        users=page.request.get(BASE+'/api/users').json()['users']
        manager=next(u for u in users if u['username']=='prabhu')
        assert manager['allowed_campaign_ids']==[2]
        assert manager['allowed_account_ids']==[1]  # selecting all must store explicit IDs
        response=page.request.post(BASE+'/api/leads/import-csv?campaign_id=2',multipart={
            'file':{'name':'leads.csv','mimeType':'text/csv','buffer':b'full_name,sales_nav_id\nPrabhu prospect,ACwPRABHU\n'}})
        assert response.ok,response.text()
        manager_context=browser.new_context(viewport={'width':1440,'height':1000})
        member=manager_context.new_page()
        member.on('pageerror',lambda error:errors.append(str(error)))
        assert member.request.post(BASE+'/api/login',data={
            'username':'prabhu','password':'fixture-password-only'}).ok
        member.goto(BASE+'/#/leads')
        expect(member.locator('#leadCampaign option[value="2"]')).to_have_count(1)
        expect(member.locator('#leadCampaign option[value="1"]')).to_have_count(0)
        expect(member.locator('#main')).to_contain_text('Prabhu prospect')
        expect(member.locator('#main')).not_to_contain_text('Fixture lead')
        assert member.request.get(BASE+'/api/leads?campaign_id=1').json()['total']==0
        assert member.request.get(BASE+'/api/leads/1/timeline').status==404
        member.screenshot(path=str(ROOT/'tests/campaign-privacy-ui.png'))
        assert page.request.get(BASE+'/api/leads').json()['total']==2
        # Revoke campaign access using the existing None button, including hidden selections.
        page.evaluate('(user) => userEditor(user)',manager)
        page.locator('#uCampsBtn').click()
        popup.locator('[data-all]').click()
        popup.locator('[data-search]').fill('SCM')
        popup.locator('[data-none]').click()
        expect(popup.locator('.scope-pop-list input:checked')).to_have_count(0)
        expect(popup.locator('[data-count]')).to_have_text('None selected — no access')
        popup.locator('[data-ok]').click()
        expect(page.locator('#uCampsLabel')).to_have_text('None selected — no access')
        with page.expect_response(lambda r:r.url.endswith('/api/users/'+str(manager['id'])) and r.request.method=='PUT') as saved:
            page.locator('#userSave').click()
        assert saved.value.ok
        manager=next(u for u in page.request.get(BASE+'/api/users').json()['users'] if u['username']=='prabhu')
        assert manager['allowed_campaign_ids']==[] and manager['allowed_account_ids']==[1]
        assert member.request.get(BASE+'/api/campaigns').json()==[]
        assert member.request.get(BASE+'/api/leads').json()['total']==0
        page.evaluate('(user) => userEditor(user)',manager)
        page.locator('#uCampsBtn').click()
        expect(popup.locator('.scope-pop-list input:checked')).to_have_count(0)
        page.set_viewport_size({'width':375,'height':812})
        rect=popup.bounding_box()
        assert rect and rect['x']>=0 and rect['x']+rect['width']<=375
        page.screenshot(path=str(ROOT/'tests/no-campaign-access-mobile.png'))
        assert errors==[],errors
        manager_context.close()
        browser.close()
    print('PASS: explicit user grants, account select-all, None button saved and reopened with no campaign access, mobile layout, Prabhu campaign/lead isolation, blocked direct URLs, administrator access; no browser errors.')
finally:
    server.terminate();server.wait(timeout=10)
