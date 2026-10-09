"""Run against the isolated serve_dashboard_fixture.py; no outbound requests."""
from pathlib import Path
from playwright.sync_api import sync_playwright
out=Path(__file__).parent/'presentation';out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8774/legacy')
    page.locator('#loginUser').fill('test-admin');page.locator('#loginPass').fill('test-password-only')
    page.locator('button[type=submit]').click();page.locator('[data-campaign-stats="1"]').wait_for()
    assert page.locator('[data-nav="logs"]').count()==0
    assert page.locator('[data-range="0"]').count()==0
    assert page.locator('.campaign-overview').count()==3
    assert page.locator('.dashboard-workers').bounding_box()['y'] < page.locator('#dashboardTotals').bounding_box()['y']
    assert page.locator('.outreach-total').first.bounding_box()['height'] < 120
    assert page.locator('.campaign-overview').first.bounding_box()['height'] < 165
    assert 'Paused campaign' not in page.locator('#campaignStats').inner_text()
    assert page.locator('.outreach-total strong').all_text_contents()==['17','6','19','0']
    assert page.locator('main').get_by_role('heading',name='Live job console').count()==0
    page.wait_for_timeout(300);page.screenshot(path=str(out/'compact-dashboard-desktop.png'),full_page=True,animations='disabled')
    page.locator('[data-campaign-stats="1"]').click()
    assert page.locator('.account-performance').count()==2
    assert 'Ranganathan A' in page.locator('.account-performance-list').inner_text()
    assert page.locator('.account-performance dd').all_text_contents()==['4','2','6','8','3','9']
    page.screenshot(path=str(out/'campaign-account-popup.png'),animations='disabled')
    page.locator('#campaignStatsClose').click()
    page.locator('[data-range="7"]').click()
    page.wait_for_function("document.querySelector('.outreach-total strong').textContent === '24'")
    page.locator('#floatingBall').click()
    assert page.locator('#floatingPanel').is_visible()
    page.wait_for_function("Math.abs(document.querySelector('#floatingPanel').getBoundingClientRect().height - 620) < 1")
    assert page.locator('#floatingPanel').bounding_box()['width']==850
    assert abs(page.locator('#floatingPanel').bounding_box()['height']-620)<1
    assert page.locator('#floatingSize').count()==0
    assert page.locator('#floatingClose').count()==1
    assert page.locator('#floatingBall').get_attribute('aria-label')=='Minimize live job console'
    page.screenshot(path=str(out/'compact-console-desktop.png'),animations='disabled')
    page.locator('#floatingClose').click()
    assert page.locator('#floatingPanel').is_hidden()
    page.locator('#floatingBall').click()
    page.locator('#floatingBall').click()
    assert page.locator('#floatingPanel').is_hidden()
    assert not page.locator('#main').evaluate('(el)=>el.inert') if page.locator('#main').count() else True
    page.get_by_role('button',name='Run history',exact=True).click()
    page.locator('.history-row').first.wait_for()
    page.screenshot(path=str(out/'compact-run-history.png'),animations='disabled')
    page.locator('#historyWorker').select_option('send_followups')
    page.wait_for_function("document.querySelectorAll('.history-row').length === 1")
    page.locator('.history-row').click();page.locator('#runOutput').wait_for()
    page.wait_for_function("document.querySelector('#runOutput').textContent.includes('Fixture console output')")
    page.wait_for_timeout(300)
    assert page.locator('.log-dialog').bounding_box()['width']==880
    assert abs(page.locator('.log-dialog').bounding_box()['height']-640)<1
    page.locator('#runClose').click()
    page.goto('http://127.0.0.1:8774/legacy#/activity');page.locator('.user-timeline-event').first.wait_for()
    page.wait_for_timeout(300);page.screenshot(path=str(out/'modern-user-activity-desktop.png'),full_page=True,animations='disabled')
    page.locator('#uaAction').select_option('login');page.locator('#uaApply').click()
    page.wait_for_function("[...document.querySelectorAll('.timeline-event-heading strong')].every(e=>e.textContent==='Login')")
    for route in ['dashboard','activity']:
        page.set_viewport_size({'width':390,'height':844})
        page.goto('http://127.0.0.1:8774/legacy#/'+route);page.locator('main h1').wait_for();page.wait_for_timeout(300)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'),route
        if route == 'dashboard':
            assert page.locator('#campaignStats').evaluate('(el)=>el.scrollHeight>el.clientHeight')
            assert page.locator('#campaignStats').bounding_box()['height'] <= 310
        page.screenshot(path=str(out/f'compact-{route}-mobile.png'),full_page=True,animations='disabled')
    page.locator('#floatingBall').click()
    assert page.locator('#floatingPanel').bounding_box()['width']==366
    page.screenshot(path=str(out/'compact-console-mobile.png'),animations='disabled')
    page.keyboard.press('Escape');assert page.locator('#floatingPanel').is_hidden()
    page.goto('http://127.0.0.1:8774/legacy#/logs');page.locator('#historyWorker').wait_for()
    assert '#/dashboard' in page.url
    page.keyboard.press('Escape')
    page.goto('http://127.0.0.1:8774/legacy#/leads');page.locator('[data-sel]').first.wait_for()
    assert page.locator('[data-reassign]').count()==0
    page.locator('[data-sel]').first.check();page.locator('#lReassign').click()
    page.locator('#moveCampaign').wait_for();page.locator('#moveCancel').click()
    assert not errors,errors
    print('PASS: active campaign cards, exact totals and account breakdown, date ranges, compact console and close control, compact history output/filters, bulk-only reassignment, activity filters, legacy links, desktop/mobile; no browser errors')
    browser.close()
