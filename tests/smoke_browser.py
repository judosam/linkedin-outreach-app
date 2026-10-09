"""No-build UI smoke check against the isolated fixture server."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8766/legacy')
    page.locator('#loginUser').fill('test-admin')
    page.locator('input[type=password]').fill('test-password-only')
    page.locator('button[type=submit]').click()
    page.wait_for_timeout(1500)
    assert page.locator('#loginView').is_hidden()
    page.reload(); page.wait_for_timeout(1000)
    assert page.locator('#loginView').is_hidden()
    for width in [1280, 768]:
        page.set_viewport_size({'width': width, 'height': 900})
        for name in ['dashboard', 'accounts', 'campaigns', 'leads', 'threads', 'workers', 'jobs', 'logs', 'settings']:
            page.goto(f'http://127.0.0.1:8766/legacy#/{name}')
            page.wait_for_timeout(700)
            assert page.locator('main').inner_text().strip(), name
            assert "Couldn't load this page" not in page.locator('main').inner_text(), name
            overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
            print(width, name, 'overflow=' + str(overflow))
            page.screenshot(path=str(Path(__file__).parent / f'vanilla-{name}-{width}.png'))
    print(json.dumps(errors))
    assert not errors
    browser.close()
