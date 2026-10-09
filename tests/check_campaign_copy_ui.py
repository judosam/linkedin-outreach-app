"""Exercise Copy campaign through the UI against an isolated local fixture."""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8781'
env={**os.environ,'OCC_TEST_PORT':'8781'}
server=subprocess.Popen([sys.executable,str(ROOT/'tests/serve_ui_fixture.py')],cwd=ROOT,env=env,
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE+'/',timeout=1);break
        except Exception:
            if server.poll() is not None:raise RuntimeError('Fixture server stopped')
            time.sleep(.2)
    else:raise RuntimeError('Fixture server failed to start')
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        assert page.request.post(BASE+'/api/login',data={'username':'test-admin','password':'test-password-only'}).ok
        original=page.request.get(BASE+'/api/campaigns/1').json()
        original.update(invite_text='Hello {first_name}',invite_track=['Accepted','First follow-up'])
        original['accounts'][0]['message_limit']=31
        assert page.request.put(BASE+'/api/campaigns/1',data=original).ok
        source=page.request.get(BASE+'/api/campaigns/1').json()
        page.goto(BASE+'/#/campaigns')
        page.locator('[data-copy-campaign="1"]').click()
        expect(page.locator('#copyName')).to_have_value('Fixture SCM copy')
        page.locator('#copyName').fill('Cloned campaign')
        page.locator('#copyKey').fill('cloned-campaign')
        page.locator('#copySave').click()
        expect(page.locator('#cName')).to_have_value('Cloned campaign')
        expect(page.locator('#cStatus')).to_have_value('paused')
        cid=int(page.url.rsplit('/',1)[1])
        copy=page.request.get(BASE+f'/api/campaigns/{cid}').json()
        assert copy['accounts']==source['accounts'] and copy['invite_track']==source['invite_track']
        campaigns=page.request.get(BASE+'/api/campaigns').json()
        assert next(c for c in campaigns if c['id']==cid)['leads']==0
        assert page.request.get(BASE+'/api/campaigns/1').json()==source
        page.locator('#cCopy').click()
        page.locator('#copyKey').fill('cloned-campaign')
        page.locator('#copySave').click()
        expect(page.locator('#toastHost')).to_contain_text('already exists')
        expect(page.locator('#copySave')).to_be_enabled()
        assert len(page.request.get(BASE+'/api/campaigns').json())==3
        page.locator('#copyCancel').click()
        page.goto(BASE+'/#/campaigns')
        page.set_viewport_size({'width':375,'height':812})
        page.locator('[data-copy-campaign="1"]').click()
        expect(page.locator('#copySave')).to_be_visible()
        rect=page.locator('#modalHost .modal').bounding_box()
        assert rect and rect['x']>=0 and rect['x']+rect['width']<=375
        page.screenshot(path=str(ROOT/'tests/campaign-copy-mobile.png'))
        page.locator('#copyCancel').click()
        assert errors==[],errors
        browser.close()
    print('PASS: list/detail Copy actions, editable name/key, paused independent copy, preserved templates/mappings, no copied leads, conflict handling, mobile dialog; no browser errors.')
finally:
    server.terminate();server.wait(timeout=10)
