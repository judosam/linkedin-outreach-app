"""Browser regressions against the isolated UI server; live responses are simulated.

Start tests/serve_ui_fixture.py with OCC_TEST_PORT=8766 first. No LinkedIn traffic.
"""
from pathlib import Path
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, expect

OUT = Path(__file__).parent / 'command-center'
OUT.mkdir(exist_ok=True)
BASE = 'http://127.0.0.1:8766'
now = datetime.utcnow()
events = [
    dict(id=6,kind='outbound',detail='Connection invite sent by Alex Morgan',lead_name='Jordan Lee',company='VP Engineering · Northstar',account='Alex Morgan',job='send_connections'),
    dict(id=5,kind='reply',detail='Sounds interesting. Happy to learn more next week.',lead_name='Taylor Chen',company='Operations Director · Meridian',account='Priya Shah',job='check_replies'),
    dict(id=4,kind='outbound',detail='InMail sent by Priya Shah',lead_name='Morgan Davis',company='Head of Data · Summit',account='Priya Shah',job='send_connections'),
    dict(id=3,kind='outbound',detail='Invite follow-up 1 sent',lead_name='Casey Rivera',company='Procurement Lead · Atlas',account='Alex Morgan',job='send_followups'),
    dict(id=2,kind='error',detail='Session needs re-authentication before outreach can continue.',lead_name='Jamie Park',company='Director · Horizon',account='Sam Patel',job='send_connections'),
    dict(id=1,kind='outbound',detail='Connection invite sent by Alex Morgan',lead_name='Riley Brooks',company='Founder · Cedar',account='Alex Morgan',job='send_connections'),
]
for i,e in enumerate(events):
    e.update(campaign='Operations Leaders',campaign_id=1,created_at=(now-timedelta(minutes=3+i*7)).isoformat())
accounts = [dict(id=i+1,name=name,status='active',session_configured=True,
    session_state='ok',usage_today=dict(invites=12+i*3,inmails=2+i,messages=8),
    daily_invite_cap=30,daily_inmail_cap=10,daily_message_cap=60)
    for i,name in enumerate(['Alex Morgan','Priya Shah','Chris Wilson','Sam Patel'])]
live = dict(active=True,run_id=9001,job='check_replies',target='Operations Leaders',dry_run=True,
            status='running',started_at=now.isoformat(),log_text='[10:00:01] Checking replies\n[10:00:02] Connected to account',total_lines=2,seq=2)
full = dict(id=9001,status='running',job='check_replies',target='Operations Leaders',dry_run=True,
            stats={'checked':12,'replies':1},errors=[],log_text=live['log_text'])
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('**/api/dashboard/activity', lambda r:r.fulfill(json=events))
    page.route('**/api/accounts', lambda r:r.fulfill(json=accounts) if r.request.method=='GET' else r.continue_())
    page.route('**/api/runs/live', lambda r:r.fulfill(json=live))
    page.route('**/api/runs/9001/log', lambda r:r.fulfill(json=full))
    page.goto(BASE)
    page.locator('#loginUser').fill('test-admin');page.locator('#loginPass').fill('test-password-only')
    page.locator('button[type=submit]').click()
    expect(page.locator('#liveLogBody')).to_contain_text('Connected to account')
    work=page.locator('#dashboardWork').bounding_box();console=page.locator('#liveLogPanel').bounding_box()
    assert .47 < console['width']/work['width'] < .51
    expect(page.locator('.activity-item')).to_have_count(6)
    for width in [1440,1280,768,375]:
        page.set_viewport_size({'width':width,'height':1000})
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
        page.screenshot(path=str(OUT/f'dashboard-running-{width}.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.locator('#liveScroll').click();expect(page.locator('#liveScroll')).to_have_attribute('aria-pressed','false')
    live.update(run_id=9002,log_text='New job first line',total_lines=1,seq=1)
    expect(page.locator('#liveLogBody')).to_have_text('New job first line',timeout=6000)
    live.update(run_id=9001,log_text='Back to first job',total_lines=1,seq=1)
    expect(page.locator('#liveLogBody')).to_have_text('Back to first job',timeout=6000)
    page.locator('#liveExpand').click();expect(page.locator('#fullRunOutput')).to_contain_text('Connected to account')
    full.update(status='partial',log_text='Final output after completion',errors=['Fixture error'],stats={'checked':20,'replies':2})
    expect(page.locator('#fullRunOutput')).to_have_text('Final output after completion',timeout=6000)
    expect(page.locator('#runErrors')).to_contain_text('Fixture error')
    page.screenshot(path=str(OUT/'full-log.png'))
    with page.expect_download() as download: page.locator('#runDownload').click()
    assert Path(download.value.path()).read_text()=='Final output after completion'
    page.keyboard.press('Escape')
    live.update(active=False,status='partial',log_text=full['log_text'],total_lines=1)
    expect(page.locator('#liveLogBody')).to_have_text('Final output after completion',timeout=6000)
    expect(page.locator('#liveLogTitle')).to_have_text('Latest job')
    page.goto(BASE+'/#/logs');expect(page.locator('#lgJob')).to_be_visible()
    positions=[page.locator('#'+i).bounding_box()['y'] for i in ['lgJob','lgStatus','lgSince']]
    assert max(positions)-min(positions)<2
    page.locator('#lgJob').select_option('send_connections')
    expect(page.locator('#lgJob')).to_have_value('send_connections')
    page.locator('#lgStatus').select_option('success')
    expect(page.locator('#lgStatus')).to_have_value('success')
    page.locator('#lgSince').select_option('1')
    expect(page.locator('#lgSince')).to_have_value('1')
    page.locator('#lgDry').click();expect(page.locator('#lgDry')).to_have_attribute('aria-pressed','true')
    page.screenshot(path=str(OUT/'logs-desktop.png'),full_page=True)
    page.locator('#lgReset').click();expect(page.locator('#lgJob')).to_have_value('')
    expect(page.locator('#lgStatus')).to_have_value('');expect(page.locator('#lgSince')).to_have_value('')
    for width in [768,375]:
        page.set_viewport_size({'width':width,'height':900})
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
        page.screenshot(path=str(OUT/f'logs-{width}.png'),full_page=True)
    assert not errors,errors
    browser.close()
    print('PASS: half-width console, activity feed, run switching, final lines, live dialog, download, filters and responsive layouts')
