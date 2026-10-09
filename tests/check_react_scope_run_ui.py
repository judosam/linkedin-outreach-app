"""Classic two-pane scope behavior through the React UI; every run intercepted."""
from react_browser_support import BrowserCheck, OUT, expect


def check():
    with BrowserCheck() as t:
        p = t.page
        d = t.open_worker()
        expect(d.get_by_text('Campaigns', exact=True)).to_be_visible()
        expect(d.get_by_text('Mapped accounts', exact=True)).to_be_visible()
        expect(d.get_by_role('radio', name='All active', exact=True)).to_be_checked()
        expect(d.get_by_role('radio', name='All mapped', exact=True)).to_be_checked()
        expect(d.get_by_text('0 mapped accounts', exact=True)).to_be_visible()
        expect(d.get_by_text('seat required', exact=True)).to_be_visible()
        expect(d.get_by_text('Paused campaign', exact=True)).to_have_count(0)
        expect(d.get_by_text('3 campaigns · 1 account', exact=True)).to_be_visible()
        expect(d.get_by_text('Skipped · no selected active account', exact=True)).to_have_count(2)
        p.screenshot(path=str(OUT/'run-scope-desktop.png'), full_page=True)
        d.get_by_role('radio', name='Select campaigns', exact=True).check()
        expect(d.get_by_role('button', name='Run now', exact=True)).to_be_disabled()
        d.get_by_role('checkbox', name='GCC 2 mapped accounts', exact=True).check()
        d.get_by_role('radio', name='Select accounts', exact=True).check()
        expect(d.get_by_role('button', name='Run now', exact=True)).to_be_disabled()
        expect(d.get_by_role('checkbox', name='Ranganathan A seat required GCC', exact=True)).to_be_disabled()
        d.get_by_role('checkbox', name='Cindy Smith GCC', exact=True).check()
        d.get_by_role('button', name='Run now', exact=True).click()
        expect(p.get_by_role('dialog', name='Live job console', exact=True)).to_be_visible()
        assert t.mutations[-1] == ('/api/jobs/send_connections/run', {'campaign_ids': [1], 'account_ids': [2]}), t.mutations
        p.get_by_role('dialog', name='Live job console', exact=True).get_by_role('button', name='Close', exact=True).click()
        d = t.open_worker()
        expect(d.get_by_role('radio', name='All active', exact=True)).to_be_checked()
        expect(d.get_by_role('radio', name='All mapped', exact=True)).to_be_checked()
        # Omitted IDs mean the server resolves active mapped accounts in user scope.
        d.get_by_role('button', name='Run now', exact=True).click()
        assert t.mutations[-1] == ('/api/jobs/send_connections/run', {}), t.mutations
        p.get_by_role('dialog', name='Live job console', exact=True).get_by_role('button', name='Close', exact=True).click()
        d = t.open_worker()
        d.get_by_role('radio', name='Select campaigns', exact=True).check()
        d.get_by_role('checkbox', name='GCC 2 mapped accounts', exact=True).check()
        d.get_by_role('radio', name='Select accounts', exact=True).check()
        d.get_by_role('checkbox', name='Cindy Smith GCC', exact=True).check()
        d.get_by_role('checkbox', name='GCC 2 mapped accounts', exact=True).uncheck()
        d.get_by_role('checkbox', name='SCM Podcast 1 mapped account', exact=True).check()
        expect(d.get_by_role('button', name='Run now', exact=True)).to_be_disabled()
        d.get_by_role('checkbox', name='GCC 2 mapped accounts', exact=True).check()
        expect(d.get_by_role('checkbox', name='Cindy Smith GCC', exact=True)).not_to_be_checked()
        d.get_by_role('button', name='Cancel', exact=True).click()
        t.goto('jobs')
        p.get_by_role('button', name='Run batch', exact=True).click()
        batch = p.get_by_role('dialog', name='Run batch', exact=True)
        expect(batch.get_by_text('Run batch always covers every mapped active account.')).to_be_visible()
        expect(batch.get_by_role('radio', name='Select accounts', exact=True)).to_have_count(0)
        batch.get_by_role('button', name='Start batch', exact=True).click()
        expect(p.get_by_role('dialog', name='Live job console', exact=True)).to_be_visible()
        assert t.mutations[-1] == ('/api/jobs/batch', {'connections': True, 'followups': False, 'campaign_ids': [1, 2, 4]}), t.mutations
        p.get_by_role('dialog', name='Live job console', exact=True).get_by_role('button', name='Close', exact=True).click()
        p.get_by_role('button', name='Run batch', exact=True).click()
        batch.get_by_role('switch', name='Run Follow-ups', exact=True).click()
        batch.get_by_role('radio', name='Select campaigns', exact=True).check()
        batch.get_by_role('button', name='Cancel', exact=True).click()
        p.get_by_role('button', name='Run batch', exact=True).click()
        expect(batch.get_by_role('radio', name='All active', exact=True)).to_be_checked()
        expect(batch.get_by_role('switch', name='Run Follow-ups', exact=True)).to_have_attribute('aria-checked', 'false')
        batch.get_by_role('button', name='Cancel', exact=True).click()
        assert len(t.mutations) == 3
        print('PASS: scope modes, unavailable accounts, empty scope, pruning, reopened defaults, worker and batch request contracts; all 3 runs stubbed')


if __name__ == '__main__':
    check()
