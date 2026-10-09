"""Browser mapping checks against the isolated fixture on port 8766."""
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, expect

BASE='http://127.0.0.1:8766'
OUT=Path(__file__).parent/'command-center'
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE);page.locator('#loginUser').fill('test-admin');page.locator('#loginPass').fill('test-password-only');page.locator('button[type=submit]').click()
    expect(page.locator('#dashboardWork')).to_be_visible()
    def post(url,data):
        r=page.request.post(BASE+url,data=data);assert r.ok,r.text();return r.json()
    existing={a['name']:a['id'] for a in page.request.get(BASE+'/api/accounts').json()}
    a=existing.get('Mapping Alex') or post('/api/accounts',dict(name='Mapping Alex'))['id']
    b=existing.get('Mapping Priya') or post('/api/accounts',dict(name='Mapping Priya'))['id']
    key=str(datetime.now().timestamp())
    def campaign(name,ids):
        return post('/api/campaigns',dict(name=name,campaign_key=name+key,search_url='https://www.linkedin.com/sales/search/people?savedSearchId=12',accounts=[dict(account_id=i) for i in ids]))['id']
    c1=campaign('Operations leaders',[a]);c2=campaign('Shared outreach',[a,b]);c3=campaign('Procurement',[b])
    def go(route):
        page.goto(BASE+'/#/'+route);expect(page.locator('main h1')).to_be_visible()
    go('campaigns')
    page.locator(f'[data-edit-campaign="{c2}"]').click();expect(page.locator('#cName')).to_have_value('Shared outreach')
    assert page.locator('#cUrl').count()==0
    assert 'Campaign search URL' not in page.locator('main').inner_text()
    assert page.locator('.acc-select').nth(0).locator(f'option[value="{b}"]').is_disabled()
    assert page.locator('.acc-select').nth(1).locator(f'option[value="{a}"]').is_disabled()
    page.locator('#cSave').click();expect(page.locator('#toastHost')).to_contain_text('Campaign saved')
    assert 'savedSearchId=12' in page.request.get(BASE+f'/api/campaigns/{c2}').json()['search_url']
    go('workers');page.locator('[data-run="check_replies"]').click()
    page.locator('input[name=camp][value=pick]').check();page.locator(f'#campPick input[value="{c1}"]').check()
    expect(page.locator('#acctPick input')).to_have_count(1)
    assert page.locator('#acctPick input').get_attribute('value')==str(a)
    page.locator(f'#campPick input[value="{c2}"]').check()
    expect(page.locator('#acctPick input')).to_have_count(2)
    page.locator('input[name=acct][value=pick]').check();page.locator(f'#acctPick input[value="{a}"]').check()
    expect(page.locator('#scopeMap')).to_contain_text('Operations leaders')
    expect(page.locator('#scopeMap')).to_contain_text('Shared outreach')
    page.locator('#toastHost').evaluate('(el)=>el.replaceChildren()')
    page.screenshot(path=str(OUT/'mapped-worker-desktop.png'),animations='disabled')
    page.set_viewport_size({'width':375,'height':900});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
    page.screenshot(path=str(OUT/'mapped-worker-mobile.png'))
    page.set_viewport_size({'width':1440,'height':1000})
    page.locator(f'#campPick input[value="{c1}"]').uncheck();page.locator(f'#campPick input[value="{c2}"]').uncheck();page.locator(f'#campPick input[value="{c3}"]').check()
    expect(page.locator('#acctPick input')).to_have_count(1)
    assert page.locator('#acctPick input').get_attribute('value')==str(b)
    expect(page.locator('#acctPick input')).not_to_be_checked();expect(page.locator('#wGo')).to_be_disabled()
    page.locator('#acctPick input').check();page.locator('#wDry').check()
    with page.expect_request('**/api/jobs/check_replies/run') as req:page.locator('#wGo').click()
    assert req.value.post_data_json['account_ids']==[b]
    expect(page).to_have_url(BASE+'/#/dashboard')
    expect(page.locator('#liveLogBody')).to_be_visible()
    assert 'Send volume trend' not in page.locator('main').inner_text()
    assert 'Pipeline funnel' not in page.locator('main').inner_text()
    assert page.locator('.dashboard-stats').bounding_box()['height']<150
    page.locator('#toastHost').evaluate('(el)=>el.replaceChildren()');page.wait_for_timeout(200)
    page.screenshot(path=str(OUT/'dashboard-compact.png'),full_page=True,animations='disabled')
    # Successful manual tools redirect without issuing external requests.
    for button,field,value,url in [('syncRun','syncSearch','123','sync_leads'),('impRun','impList','456','import_list')]:
        page.route(f'**/api/jobs/{url}/run',lambda r:r.fulfill(json={'ok':True,'message':'Fixture started'}))
        go('workers');page.locator('#'+field).fill(value);page.locator('#'+button).click();expect(page).to_have_url(BASE+'/#/dashboard')
        page.unroute(f'**/api/jobs/{url}/run')
    # A refused start retains the selection for correction and does not redirect.
    go('workers');page.locator('[data-run="check_replies"]').click();page.locator('#wDry').check()
    page.route('**/api/jobs/check_replies/run',lambda r:r.fulfill(status=409,json={'detail':'Another worker is running'}))
    page.locator('#wGo').click();expect(page.locator('[data-request-error]')).to_contain_text('Another worker is running')
    expect(page).to_have_url(BASE+'/#/workers');expect(page.locator('#wf')).to_be_visible()
    page.keyboard.press('Escape');page.unroute('**/api/jobs/check_replies/run')
    # Newly detected scheduled workers redirect once, not on every status poll.
    j=page.request.get(BASE+'/api/jobs').json()
    j['live']=dict(status='running',job='send_followups',started_at='2026-09-12T12:00:00',run_id=9001)
    page.route('**/api/jobs',lambda r:r.fulfill(json=j))
    go('logs');page.evaluate('pollNav()');expect(page).to_have_url(BASE+'/#/dashboard')
    go('campaigns');page.evaluate('pollNav()');expect(page).to_have_url(BASE+'/#/campaigns')
    j['live']['started_at']='2026-09-12T13:00:00';page.evaluate('pollNav()');expect(page).to_have_url(BASE+'/#/dashboard')
    assert not errors,errors
    browser.close()
    print('PASS: mapped-only account selection, shared accounts, stale selection clearing, edit buttons, hidden URL preservation, compact dashboard, manual and scheduled redirects')
