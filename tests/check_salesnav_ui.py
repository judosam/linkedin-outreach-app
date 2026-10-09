"""Browser regression checks; only use serve_salesnav_fixture.py (mocked provider)."""
from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path(__file__).parent / 'presentation'
out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width':1440,'height':1000}, reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8775')
    page.locator('#loginUser').fill('test-admin')
    page.locator('#loginPass').fill('test-password-only')
    page.locator('button[type=submit]').click()
    page.locator('.dashboard-page').wait_for()
    page.goto('http://127.0.0.1:8775/#/salesnav')
    page.locator('.sn-table').first.wait_for()
    anne = page.locator('tr[data-sn-email="annedavis@vservesolution.com"]')
    assert anne.locator('[data-sn-check],[data-sn-remove]').count() == 0
    assert 'Protected admin' in anne.inner_text()
    page.locator('#snSelectAll').check()
    assert page.locator('[data-sn-check]:checked').count() == 2
    page.locator('#snRemoveSelected').click()
    assert page.locator('[role=alertdialog]').count() == 1
    assert 'annedavis@' not in page.locator('.sn-confirm-list').inner_text()
    page.locator('#snConfirm').click()
    page.locator('.sn-results').wait_for()
    assert page.locator('.sn-results .pill').all_text_contents() == ['failed','failed']
    assert page.locator('.sn-roster').first.locator('tbody tr').count() == 3
    assert page.locator('.sn-summary strong').first.inner_text().startswith('3')
    page.locator('#snDismissResults').click()
    page.locator('[data-sn-link]').first.click()
    page.locator('[data-sn-copy]').wait_for()
    page.locator('#snDismissResults').click()
    page.locator('#snOpenAdd').click()
    page.locator('#snEmails').fill('bad-address')
    page.locator('#snAdd').click()
    assert 'valid email' in page.locator('#snEmailError').inner_text()
    page.keyboard.press('Escape')
    page.locator('#snRefresh').click()
    page.wait_for_function('!salesNavState.loading')
    page.screenshot(path=str(out/'salesnav-desktop.png'),full_page=True)
    for theme in ['dark','light']:
        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
        for width in [1440,768,390]:
            page.set_viewport_size({'width':width,'height':1000 if width>390 else 844})
            for route in ['dashboard','accounts','campaigns','leads','threads','jobs','settings','salesnav']:
                page.goto('http://127.0.0.1:8775/#/'+route)
                page.wait_for_timeout(500)
                assert page.locator('main h1').count(),(route,theme,width)
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'),(route,theme,width)
                if route=='salesnav':
                    assert page.locator('.sn-table tbody tr').evaluate_all('rows => rows.every(row => [...row.children].every(cell => cell.getBoundingClientRect().bottom <= row.getBoundingClientRect().bottom + 1))'),(theme,width)
                    page.screenshot(path=str(out/f'salesnav-{theme}-{width}.png'),full_page=True)
                if width==1440 and theme=='dark' and route in ['dashboard','settings','campaigns']:
                    page.screenshot(path=str(out/f'polished-{route}.png'),full_page=True)
    # Roster errors remain on the page with a retry action.
    page.route('**/api/salesnav/licenses', lambda r:r.fulfill(status=502,json={'detail':'Admin session expired. Refresh Anne’s cookies.'}))
    page.locator('#snRefresh').click()
    page.locator('.salesnav-page [role=alert]').wait_for()
    assert 'Admin session expired' in page.locator('.salesnav-page [role=alert]').inner_text()
    assert page.locator('#app').is_visible()
    assert not errors,errors
    print('PASS: protected admin, safe bulk selection, confirmation, failed-removal state, links, validation, error recovery; eight pages at desktop/tablet/mobile in dark/light; no overflow or browser errors')
    browser.close()
