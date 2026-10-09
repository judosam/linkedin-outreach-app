"""Mutating browser workflows: fixture data only, dry-run workers only."""
from playwright.sync_api import sync_playwright
import time
KEY = 'browser-' + str(time.time_ns())

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width':1280,'height':900})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8769/legacy')
    page.locator('#loginUser').fill('test-admin'); page.locator('#loginPass').fill('test-password-only')
    page.locator('button[type=submit]').click(); page.wait_for_timeout(1000)
    def go(name):
        page.goto('http://127.0.0.1:8769/legacy#/' + name); page.wait_for_timeout(700)
    def get(path):
        return page.request.get('http://127.0.0.1:8769' + path).json()
    go('dashboard')
    for days in [7,30,1]:
        with page.expect_response(lambda r: '/api/dashboard/summary?days=' + str(days) in r.url) as response:
            page.locator(f'[data-range="{days}"]').click()
        assert response.value.json()['window_days'] == days
    go('accounts'); page.locator('[data-caps]').first.click()
    page.locator('[name=daily_invite_cap]').fill('17'); page.locator('#accSave').click()
    page.wait_for_timeout(600); assert get('/api/accounts')[0]['daily_invite_cap'] == 17
    go('campaign/new'); page.locator('#cName').fill('Browser campaign'); page.locator('#cKey').fill(KEY)
    page.locator('#cAddAcc').click(); page.locator('.acc-invite').fill('8'); page.locator('#cSave').click()
    page.wait_for_timeout(700)
    row = next(c for c in get('/api/campaigns') if c['campaign_key'] == KEY)
    assert row['accounts'][0]['invite_limit'] == 8
    page.locator('.acc-invite').fill('6'); page.locator('#cSave').click(); page.wait_for_timeout(500)
    assert get(f'/api/campaigns/{row["id"]}')['accounts'][0]['invite_limit'] == 6
    go('leads'); assert 'initial contact' in page.locator('main').inner_text().lower(); assert 'last follow-up' in page.locator('main').inner_text().lower()
    go('workers'); page.locator('[data-run="send_connections"]').click(); page.locator('#wDry').check()
    page.locator('#wGo').click(); page.wait_for_timeout(1000)
    runs = get('/api/runs'); assert runs and runs[0]['dry_run']; assert runs[0]['status'] == 'success', runs[0]
    page.locator('#floatingClose').click()
    go('logs'); page.get_by_role('button', name='View log').first.click(); page.wait_for_timeout(400)
    assert page.locator('.runlog').count(); page.keyboard.press('Escape')
    go('jobs'); page.locator('#jsNew').click(); page.locator('#sName').fill('Browser schedule')
    page.locator('[data-job="send_connections"]').click(); page.locator('[data-job="check_replies"]').click()
    page.locator('[data-scope="send_connections"]').click()
    page.locator('input[name=camp][value=pick]').check(); page.locator('#campPick input').first.check()
    page.locator('input[name=acct][value=pick]').check(); page.locator('#acctPick input').first.check()
    page.locator('#wGo').click(); page.locator('#sSave').click(); page.wait_for_timeout(600)
    row = next(s for s in get('/api/schedules') if s['name']=='Browser schedule'); assert not row['days_of_week']; assert len(row['job_keys']) == 2
    assert row['scopes']['send_connections']['account_ids'] == [1]
    page.locator(f'[data-active="{row["id"]}"]').click(); page.wait_for_timeout(400)
    assert next(s for s in get('/api/schedules') if s['id']==row['id'])['next_run_at'] is None
    page.locator(f'[data-edit="{row["id"]}"]').click(); page.locator('[data-day="mon"]').click(); page.locator('#sSave').click(); page.wait_for_timeout(500)
    page.on('dialog', lambda d: d.accept()); page.locator(f'[data-del="{row["id"]}"]').click(); page.wait_for_timeout(500)
    assert not any(s['id']==row['id'] for s in get('/api/schedules'))
    go('settings'); page.locator('#nfForm button[type=submit]').click(); page.wait_for_timeout(500)
    assert not errors, errors
    print('PASS: dashboard ranges, caps, campaign create/edit, lead dates, dry run, logs, schedule CRUD, settings')
    browser.close()

