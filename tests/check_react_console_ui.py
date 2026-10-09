"""Run start, execution selection, discovery and import dialog parity."""
from react_browser_support import BrowserCheck, OUT, expect


def check():
    with BrowserCheck() as t:
        p = t.page
        d = t.open_worker()
        d.get_by_role('button', name='Run now', exact=True).click()
        console = p.get_by_role('dialog', name='Live job console', exact=True)
        expect(console).to_be_visible()
        expect(console.get_by_text('fixture-exec: mocked console output', exact=True)).to_be_visible()
        assert any(q.get('execution_id') == ['fixture-exec'] for q in t.live_queries)
        console.get_by_role('button', name='Close', exact=True).click()
        t.goto('jobs')
        expect(p.locator('button[title="Open live job console"]').first).to_contain_text('Live console')
        p.locator('main').get_by_role('button', name='Live console', exact=False).click()
        expect(console).to_be_visible()
        p.screenshot(path=str(OUT/'live-console-desktop.png'), full_page=True)
        console.get_by_role('button', name='Close', exact=True).click()
        for label, dialog_name, field, job_key, external_key in [
            ('Import Saved Search', 'Import from Saved Search', 'Saved search ID', 'sync_leads', 'saved_search_id'),
            ('Import List', 'Import from List', 'List ID', 'import_list', 'list_id'),
        ]:
            t.goto('leads')
            p.get_by_role('button', name=label, exact=True).click()
            d = p.get_by_role('dialog', name=dialog_name, exact=True)
            expect(d.get_by_label('Import account', exact=False)).to_have_value('')
            expect(d.get_by_label('Outreach account', exact=False)).to_have_value('')
            d.get_by_label('Import account', exact=False).select_option('2')
            d.get_by_label(field, exact=False).fill('123456')
            d.get_by_label('Tag leads to a campaign', exact=False).select_option('1')
            d.get_by_role('button', name='Start import', exact=True).click()
            expect(console).to_be_visible()
            assert t.mutations[-1] == ('/api/jobs/'+job_key+'/run', {'account_id':2, 'campaign_id':1, 'outreach_account_id':None, external_key:'123456'}), t.mutations
            assert p.url.endswith('#/leads'), p.url
            console.get_by_role('button', name='Close', exact=True).click()
            p.get_by_role('button', name=label, exact=True).click()
            expect(d.get_by_label('Import account', exact=False)).to_have_value('')
            expect(d.get_by_label(field, exact=False)).to_have_value('')
            expect(d.get_by_label('Tag leads to a campaign', exact=False)).to_have_value('')
            d.get_by_role('button', name='Cancel', exact=True).click()
        print('PASS: auto-open, execution-specific console, Jobs trigger, topbar, both import payloads and reset; no redirect or real worker')


if __name__ == '__main__':
    check()
