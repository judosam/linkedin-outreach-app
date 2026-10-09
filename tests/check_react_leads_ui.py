"""Leads density, links, committed header filters, safe actions and dates."""
from react_browser_support import BrowserCheck, OUT, expect


def check():
    with BrowserCheck() as t:
        p = t.page
        t.goto('leads')
        expect(p.locator('.leads-table tbody tr')).to_have_count(5)
        metrics = p.locator('.dt-wrap').evaluate('(e)=>({scroll:e.scrollWidth,client:e.clientWidth})')
        assert metrics['scroll'] == metrics['client'], metrics
        heights = p.locator('.leads-table tbody tr').evaluate_all('(rows)=>rows.map(r=>r.getBoundingClientRect().height)')
        assert max(heights) <= 48, heights
        assert p.locator('.leads-table th').count() == 12
        # Header text must fit its assigned cell, including the small Reply cell.
        clipping = p.locator('.leads-table th').evaluate_all('''els=>els.filter(e=>{const b=e.querySelector('.th-sort');return b && b.scrollWidth>b.clientWidth+1}).map(e=>e.innerText)''')
        assert not clipping, clipping
        direct = p.get_by_role('link', name='Open Edward Keefe on LinkedIn')
        expect(direct).to_have_attribute('href', 'https://www.linkedin.com/in/fixture-edward/')
        expect(direct).to_have_attribute('target', '_blank')
        fallback = p.get_by_role('link', name='Open Jeffrey Dunn on LinkedIn')
        expect(fallback).to_have_attribute('href', 'https://www.linkedin.com/sales/lead/ACw2')
        expect(p.get_by_role('button', name='Sarah Jenkins', exact=True)).to_be_visible()
        expect(p.locator('.leads-table').get_by_text('Not open', exact=True)).to_have_count(0)
        p.get_by_role('button', name='Filter by Company', exact=True).click()
        panel = p.get_by_role('dialog', name='Filter Company', exact=True)
        expect(panel.get_by_label('Company contains', exact=True)).to_be_focused()
        p.keyboard.press('Shift+Tab')
        expect(panel.get_by_role('button', name='Apply', exact=True)).to_be_focused()
        p.keyboard.press('Tab')
        expect(panel.get_by_label('Company contains', exact=True)).to_be_focused()
        panel.get_by_label('Company contains', exact=True).fill('YOOBIC')
        panel.get_by_role('button', name='Cancel', exact=True).click()
        expect(p.locator('.leads-table tbody tr')).to_have_count(5)
        p.get_by_role('button', name='Filter by Company', exact=True).click()
        expect(panel.get_by_label('Company contains', exact=True)).to_have_value('')
        panel.get_by_label('Company contains', exact=True).fill('YOOBIC')
        p.screenshot(path=str(OUT/'leads-header-filter.png'), full_page=True)
        panel.get_by_role('button', name='Apply', exact=True).click()
        expect(p.locator('.leads-table tbody tr')).to_have_count(1)
        assert any(q.get('company') == ['YOOBIC'] for q in t.lead_queries)
        p.get_by_role('button', name='Remove Company filter').click()
        expect(p.locator('.leads-table tbody tr')).to_have_count(5)
        p.get_by_role('button', name='Filter by Location', exact=True).click()
        panel = p.get_by_role('dialog', name='Filter Location', exact=True)
        expect(panel.get_by_text('This page only')).to_be_visible()
        panel.get_by_label('Location contains', exact=True).fill('Austin')
        panel.get_by_role('button', name='Apply', exact=True).click()
        expect(p.locator('.leads-table tbody tr')).to_have_count(3)
        expect(p.get_by_text('Location: Austin (page)', exact=True)).to_be_visible()
        p.get_by_role('button', name='Remove Location filter').click()
        p.get_by_role('button', name='Filter by Added', exact=True).click()
        panel = p.get_by_role('dialog', name='Filter Added', exact=True)
        panel.get_by_label('Added from', exact=True).fill('2026-10-01')
        panel.get_by_label('Added to', exact=True).fill('2026-10-31')
        panel.get_by_role('button', name='Apply', exact=True).click()
        p.wait_for_timeout(500)
        assert any(q.get('created_from') == ['2026-09-30T18:30:00.000Z'] and q.get('created_to') == ['2026-10-31T18:29:59.999Z'] for q in t.lead_queries), t.lead_queries
        p.get_by_role('button', name='Remove Added filter').click()
        expect(p.locator('.leads-table tbody tr')).to_have_count(5)
        # Keyboard dismissal returns focus to the trigger.
        p.get_by_role('button', name='Filter by Stage', exact=True).click()
        p.keyboard.press('Escape')
        expect(p.get_by_role('button', name='Filter by Stage', exact=True)).to_be_focused()
        t.handlers['/api/leads/reset-errors'] = lambda r,b: r.fulfill(json={'reset': 1, 'skipped': 0})
        p.get_by_label('Select Edward Keefe', exact=True).check()
        p.get_by_role('button', name='Remove errors', exact=True).click()
        p.wait_for_timeout(300)
        assert ('/api/leads/reset-errors', {'ids': [1]}) in t.mutations
        t.handlers['/api/leads/delete-preview'] = lambda r,b: r.fulfill(json={'existing': 1, 'missing': 0, 'campaigns': [{'campaign':'GCC','count':1}], 'comments_to_remove':2,'events_to_remove':3})
        t.handlers['/api/leads/bulk-delete-v2'] = lambda r,b: r.fulfill(json={'deleted': 1, 'skipped': 0})
        p.get_by_label('Select Edward Keefe', exact=True).check()
        p.get_by_role('button', name='Delete', exact=True).click()
        deletion = p.get_by_role('dialog', name='Delete selected leads')
        expect(deletion.get_by_text('2 comments and 3 lead events will be removed. Run logs are retained.')).to_be_visible()
        deletion.get_by_role('button', name='Delete 1 leads').click()
        expect(deletion).not_to_be_visible()
        assert t.mutations[-1] == ('/api/leads/bulk-delete-v2', {'ids': [1]})
        # Native multipart upload; campaign belongs in the query, not the form.
        def csv_result(route, body):
            assert 'campaign_id=1' in route.request.url
            assert 'full_name,sales_nav_id' in body
            route.fulfill(json={'added': 1, 'skipped': 0, 'errors': []})
        t.handlers['/api/leads/import-csv'] = csv_result
        p.get_by_role('button', name='Import CSV', exact=True).click()
        csv = p.get_by_role('dialog', name='Import CSV', exact=True)
        csv.locator('input[type=file]').set_input_files({'name':'fixture.csv','mimeType':'text/csv','buffer':b'full_name,sales_nav_id\nFixture Person,ACwTEST\n'})
        csv.get_by_label('Destination campaign').select_option('1')
        csv.get_by_role('button', name='Import CSV', exact=True).click()
        expect(csv.get_by_text('1 imported · 0 skipped')).to_be_visible()
        csv.get_by_role('button', name='Close', exact=True).click()
        p.get_by_role('button', name='Import CSV', exact=True).click()
        expect(csv.get_by_label('Destination campaign')).to_have_value('')
        expect(csv.locator('input[type=file]')).to_have_value('')
        csv.get_by_role('button', name='Close', exact=True).click()
        p.screenshot(path=str(OUT/'leads-desktop.png'), full_page=True)
        p.set_viewport_size({'width':598,'height':900})
        assert not p.evaluate('document.documentElement.scrollWidth > innerWidth'), 'Page overflow at 598px'
        p.get_by_role('button', name='Filters (0)', exact=True).click()
        more = p.get_by_role('dialog', name='Lead filters', exact=True)
        expect(more.get_by_text('OpenToMsg', exact=True)).to_be_visible()
        more.get_by_role('checkbox', name='Saved search', exact=True).check()
        more.get_by_role('button', name='Cancel', exact=True).click()
        p.get_by_role('button', name='Filters (0)', exact=True).click()
        expect(more.get_by_role('checkbox', name='Saved search', exact=True)).not_to_be_checked()
        more.get_by_role('button', name='Cancel', exact=True).click()
        p.screenshot(path=str(OUT/'leads-598.png'), full_page=True)
        print('PASS: compact leads, all columns, links, filters, local dates, keyboard, reset errors, preview/delete, CSV, mobile')


if __name__ == '__main__':
    check()
