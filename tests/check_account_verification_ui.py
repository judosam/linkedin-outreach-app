"""Verify account health refresh and concise console output using API fixtures."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
BASE=os.environ.get('OCC_TEST_BASE_URL','http://127.0.0.1:8772')
OUT=Path(__file__).parent/'account-verification';OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':950})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE);page.locator('#loginUser').fill('test-admin');page.locator('#loginPass').fill('test-password-only');page.locator('button[type=submit]').click();page.locator('main h1').wait_for()
    account=page.evaluate('(async()=> (await apiGet("/api/accounts"))[0])()')
    account.update(status='active',session_state='ok',session_configured=True)
    page.route('**/api/accounts',lambda route:route.fulfill(json=[account]))
    outcome=['seat_required']
    def verify(route):
        state=outcome[0];account.update(status=state,session_state='ok' if state=='active' else state)
        route.fulfill(status=200 if state=='active' else 422,json={'ok':True,'status':state} if state=='active' else {'detail':'Account does not have a Sales Navigator seat'})
    page.route('**/verify-session',verify)
    page.goto(BASE+'/#/accounts');page.locator('[data-verify]').click()
    row=page.locator('table.data tbody tr').first
    expect(row.locator('td').nth(1)).to_have_text('Sales Nav required')
    expect(page.locator('[data-toggle]')).to_be_disabled()
    page.reload();expect(page.locator('table.data tbody tr').first.locator('td').nth(1)).to_have_text('Sales Nav required')
    page.screenshot(path=str(OUT/'failed-account.png'),full_page=True,animations='disabled')
    page.goto(BASE+'/#/dashboard');expect(page.locator('.account-tile')).to_contain_text('Sales Nav required')
    page.locator('.account-tile').click();expect(page.locator('.account-detail-modal')).to_contain_text('Sales Nav required');page.keyboard.press('Escape');expect(page.locator('[role=dialog]')).to_have_count(0)
    page.goto(BASE+'/#/accounts');page.locator('[data-caps]').click()
    form=page.locator('#accForm');form.locator('[name=daily_invite_cap]').fill('12');page.locator('#modalVerifyBtn').click()
    expect(form.locator('[name=status]')).to_have_value('seat_required');expect(page.locator('#modalVerifyBtn')).to_be_enabled();expect(form.locator('[name=status]')).to_be_disabled()
    expect(form.locator('[name=daily_invite_cap]')).to_have_value('12')
    outcome[0]='active';page.locator('#modalVerifyBtn').click();expect(form.locator('[name=status]')).to_have_value('active');expect(form.locator('[name=status]')).to_be_enabled();expect(form.locator('[name=daily_invite_cap]')).to_have_value('12')
    expect(page.locator('table.data tbody tr').first.locator('td').nth(1)).to_have_text('Active');page.keyboard.press('Escape');expect(page.locator('[role=dialog]')).to_have_count(0)
    snapshot={'run_id':99,'active':False,'job':'check_replies','status':'partial','target':'Fixture account','duration_s':4,'log_text':'[09:25:52] HTTP 403 — session expired or forbidden','errors':['HTTP 403 — session expired or forbidden']}
    page.route('**/api/runs/live',lambda route:route.fulfill(json=snapshot));page.evaluate('openFloatingConsole()');page.evaluate('pollFloatingConsole()')
    expect(page.locator('#floatingStatus')).to_have_text('Completed with warnings');expect(page.locator('#floatingOutput')).to_contain_text('HTTP 403')
    assert page.locator('#floatingErrors').count()==0
    assert page.locator('.floating-content').inner_text().count('HTTP 403')==1
    for width in [375,1440]:
        page.set_viewport_size({'width':width,'height':950});page.screenshot(path=str(OUT/f'console-{width}.png'),animations='disabled')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
    assert not errors,errors
    print('PASS: failed verification refreshes list/modal/dashboard, persists across reload, successful verification restores Active, drafts survive, no duplicate red console output or browser errors.')
    browser.close()
