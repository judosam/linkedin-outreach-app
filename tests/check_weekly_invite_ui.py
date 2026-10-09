"""Verify the Accounts weekly invitation slider against an isolated server."""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8786'
server=subprocess.Popen([sys.executable,str(ROOT/'tests/serve_ui_fixture.py')],cwd=ROOT,
                        env={**os.environ,'OCC_TEST_PORT':'8786'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
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
        page.goto(BASE+'/#/accounts')
        page.locator('[data-caps="1"]').click()
        slider=page.get_by_role('slider',name='Weekly invitation limit')
        expect(slider).to_have_value('100')
        slider.focus();slider.press('Home')
        expect(slider).to_have_value('0')
        expect(page.locator('#weeklyInviteValue')).to_have_text('0')
        slider.press('End');slider.press('ArrowRight')
        expect(slider).to_have_value('150')
        slider.fill('70');slider.dispatch_event('input')
        expect(page.locator('#weeklyInviteValue')).to_have_text('70')
        page.set_viewport_size({'width':375,'height':812})
        slider.scroll_into_view_if_needed()
        rect=slider.bounding_box()
        assert rect and rect['x']>=0 and rect['x']+rect['width']<=375
        save_rect=page.locator('#accSave').bounding_box()
        assert save_rect and save_rect['y']+save_rect['height']<=812
        page.screenshot(path=str(ROOT/'tests/weekly-invite-slider-mobile.png'))
        with page.expect_response(lambda r:r.url.endswith('/api/accounts/1') and r.request.method=='PUT') as saved:
            page.locator('#accSave').click()
        assert saved.value.ok
        assert saved.value.request.post_data_json['weekly_invite_cap']==70
        page.set_viewport_size({'width':1440,'height':1000})
        page.reload()
        expect(page.locator('thead')).to_contain_text('Invites / 7 days')
        page.locator('[data-caps="1"]').click()
        expect(slider).to_have_value('70')
        slider.fill('0');slider.dispatch_event('input')
        with page.expect_response(lambda r:r.url.endswith('/api/accounts/1') and r.request.method=='PUT') as saved:
            page.locator('#accSave').click()
        assert saved.value.ok
        account=page.request.get(BASE+'/api/accounts').json()[0]
        assert account['weekly_invite_cap']==0
        assert account['weekly_invites']=={'used':0,'limit':0,'remaining':0}
        assert errors==[],errors
        browser.close()
    print('PASS: weekly invitation slider 0–150, keyboard bounds, save/reload, zero disables, seven-day usage, mobile layout; no browser errors.')
finally:
    server.terminate();server.wait(timeout=10)
