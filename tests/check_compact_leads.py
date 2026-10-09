"""Visual check against the isolated fixture, using sample leads for long cells."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:8768'
OUT = Path(__file__).parent / 'command-center'
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width':1440,'height':1000}, timezone_id='Asia/Kolkata')
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(BASE)
    page.locator('#loginUser').fill('test-admin'); page.locator('#loginPass').fill('test-password-only')
    page.locator('button[type=submit]').click()
    expect(page.locator('#app')).to_be_visible()
    for key in ['created', 'created_desc']:
        assert page.request.get(BASE + '/api/leads?sort=' + key).ok
    def leads(route):
        response = route.fetch()
        data = response.json()
        sample = dict(data['items'][0], full_name='Alexandra Richardson',title='Senior Director of Global Operations',
                      company='International Manufacturing Group',campaign='Operations Leadership Outreach',
                      associate_account='Priya Sharma',status='INVITE_FOLLOWUP_1',created_at='2026-09-13T20:15:00',
                      first_contacted_at='2026-09-14T08:00:00',last_followup_at=None)
        data.update(items=[dict(sample, id=i+1, sales_nav_id=f'sample-{i}') for i in range(25)], total=25)
        route.fulfill(json=data)
    page.route('**/api/leads?*', leads)
    page.goto(BASE + '/#/leads')
    expect(page.get_by_role('button', name='Sort by Added Date',exact=True)).to_be_visible()
    expected = page.evaluate("fmtD('2026-09-13T20:15:00')")
    expect(page.locator('td[data-label="Added Date"]').first).to_have_text(expected)
    for key in ['created','created_desc']:
        with page.expect_response(lambda r: '/api/leads?' in r.url and f'sort={key}&' in r.url):
            page.get_by_role('button',name='Sort by Added Date',exact=True).click()
    page.locator('[data-sel="1"]').check()
    expect(page.locator('.bulkbar')).to_contain_text('1 selected')
    for width in [1440,1280,1024,768,375]:
        page.set_viewport_size({'width':width,'height':1000})
        if page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'):
            print(page.evaluate("[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,cls:e.className,w:e.getBoundingClientRect().width,text:e.textContent.slice(0,60)})).slice(0,15)"))
            page.screenshot(path=str(OUT / 'leads-overflow.png'))
            raise AssertionError(width)
        box = page.locator('.leads-page .table-wrap')
        assert box.evaluate('(el)=>el.scrollWidth <= el.clientWidth + 1 && el.scrollHeight <= el.clientHeight + 1'), width
        assert box.evaluate('(el)=>getComputedStyle(el).maxHeight') == 'none'
        expect(page.locator('td[data-label="Added Date"]').first).to_be_visible()
        page.screenshot(path=str(OUT / f'leads-compact-{width}.png'), full_page=False, animations='disabled')
    assert not errors, errors
    browser.close()
    print('PASS: Added Date display/sort, selection and no inner scroll at five screen sizes')
