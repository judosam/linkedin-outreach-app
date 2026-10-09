"""Browser checks against tests/serve_ui_fixture.py on an isolated database."""
from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path(__file__).parent / 'presentation'
out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8773')
    page.locator('#loginUser').fill('test-admin')
    page.locator('#loginPass').fill('test-password-only')
    page.locator('button[type=submit]').click()
    page.locator('#campaignStats').wait_for()
    assert page.locator('.dashboard-stats').count() == 0
    assert 'Fixture SCM' in page.locator('#campaignStats').inner_text()
    page.locator('[data-range="7"]').click()
    page.wait_for_function("document.querySelector('.campaign-performance').textContent.includes('last 7 days')")
    page.screenshot(path=str(out / 'campaign-stats-desktop.png'), full_page=True)
    page.goto('http://127.0.0.1:8773/#/leads')
    page.locator('[data-sel]').first.check()
    page.locator('#lReassign').click()
    page.locator('#moveCampaign').select_option('2')
    page.locator('#moveAccount').select_option('1')
    page.locator('#moveSave').click()
    page.locator('#moveSave').wait_for(state='detached')
    page.wait_for_function("document.querySelector('.leads-table').textContent.includes('Fixture Procurement')")
    page.locator('[data-sel]').first.check()
    page.locator('#lReassign').click()
    assert page.locator('#moveCampaign').count() == 1
    page.locator('#moveCancel').click()
    page.goto('http://127.0.0.1:8773/#/activity')
    page.locator('#uaApply').wait_for()
    assert 'Reassign leads' in page.locator('.user-activity-timeline').inner_text()
    page.wait_for_timeout(400)
    page.screenshot(path=str(out / 'user-activity-desktop.png'), full_page=True, animations='disabled')
    for route in ['dashboard', 'activity', 'leads']:
        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto('http://127.0.0.1:8773/#/' + route)
        page.locator('main h1').wait_for()
        page.wait_for_timeout(250)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'), route
        if route == 'dashboard':
            assert page.locator('.campaign-overview').first.bounding_box()['height'] > 100
        if route == 'activity':
            assert page.locator('.user-timeline-event').first.bounding_box()['height'] > 100
        assert "Couldn't load this page" not in page.locator('main').inner_text()
        page.screenshot(path=str(out / f'operations-{route}-mobile.png'), full_page=True)
    page.locator('[data-sel]').first.check()
    page.locator('#lReassign').click()
    page.screenshot(path=str(out / 'reassign-mobile.png'), full_page=True)
    assert page.locator('#moveSave').is_visible()
    assert not errors, errors
    print('PASS: dashboard ranges, individual and bulk reassignment, activity history, mobile layouts; no browser errors')
    browser.close()
