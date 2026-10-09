"""Presentation checks against the isolated fixture (no real account traffic)."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

out = Path(__file__).parent/'presentation'
out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]; failures=[]; missing=set()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8769/legacy')
    page.locator('#loginUser').fill('test-admin');page.locator('#loginPass').fill('test-password-only')
    page.screenshot(path=str(out/'login-1440.png'))
    page.locator('button[type=submit]').click();page.wait_for_timeout(700)
    routes=['dashboard','accounts','campaigns','campaign/1','leads','threads','workers','jobs','logs','settings']
    for width in [375,768,1024,1440,1920]:
        page.set_viewport_size({'width':width,'height':1000})
        for route in routes:
            page.goto('http://127.0.0.1:8769/legacy#/'+route);page.wait_for_timeout(220)
            try: page.locator('main h1').wait_for(timeout=10000)
            except Exception:
                print('FAILED',width,route,page.locator('main').inner_text(),errors,flush=True)
                raise
            if page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'):
                failures.append((width,route,'overflow'))
            if "Couldn't load this page" in page.locator('main').inner_text(): failures.append((width,route,'error'))
            if route in ['dashboard','accounts','threads','workers','leads']:
                page.screenshot(path=str(out/f'{route}-{width}.png'),full_page=True)
            symbols=page.locator('.msym svg use').evaluate_all('(els)=>els.map(e=>e.getAttribute("href").split("#")[1])')
            sprite=page.request.get('http://127.0.0.1:8769/static/icons.svg').text()
            missing.update(s for s in symbols if f'id="{s}"' not in sprite)
    page.set_viewport_size({'width':375,'height':812})
    page.goto('http://127.0.0.1:8769/legacy#/accounts'); page.locator('[data-caps]').first.wait_for()
    page.locator('#sidebarToggle').click(); page.keyboard.press('Tab')
    assert page.evaluate('document.querySelector("#sidebar").contains(document.activeElement)')
    page.keyboard.press('Escape'); assert page.locator('#sidebarToggle').get_attribute('aria-expanded') == 'false'
    page.locator('[data-caps]').first.click()
    for _ in range(20): page.keyboard.press('Tab')
    assert page.evaluate('document.querySelector("#modalHost").contains(document.activeElement)')
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
    page.screenshot(path=str(out/'account-dialog-375.png'))
    page.keyboard.press('Escape'); assert page.locator('[role=dialog]').count()==0
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('.sidebar').evaluate('(el)=>getComputedStyle(el).transitionDuration') == '0s'
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto('http://127.0.0.1:8769/legacy#/dashboard');page.locator('main h1').wait_for()
    page.screenshot(path=str(out/'dashboard-final.png'),full_page=True)
    print(json.dumps({'pages_checked':50,'errors':errors,'failures':failures,'missing_icons':sorted(missing),'keyboard_modal_reduced_motion':'passed'}))
    browser.close()
    assert not errors and not failures and not missing
