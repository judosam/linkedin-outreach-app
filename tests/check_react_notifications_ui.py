"""Notification permission, completion details, deduplication and preference."""
from react_browser_support import BrowserCheck, OUT, expect


def check():
    with BrowserCheck() as t:
        p = t.page
        d = t.open_worker()
        d.get_by_role('button', name='Run now', exact=True).click()
        console = p.get_by_role('dialog', name='Live job console', exact=True)
        expect(console).to_be_visible()
        assert p.evaluate('window.__permissionCalls') == 1
        console.get_by_role('button', name='Close', exact=True).click()
        t.finished = True
        completion = p.get_by_role('dialog', name='Run completed', exact=True)
        expect(completion).to_be_visible(timeout=16000)
        expect(completion.get_by_text('Send Connections', exact=True)).to_be_visible()
        expect(completion.get_by_text('confirmed: 4', exact=True)).to_be_visible()
        assert p.evaluate('window.__notifications.length') == 0, 'Visible tabs must use the popup'
        p.screenshot(path=str(OUT/'run-completed.png'), full_page=True)
        completion.get_by_role('button', name='Open full log').click()
        log = p.get_by_role('dialog', name='Run #700', exact=True)
        expect(log.get_by_text('Mocked full log', exact=True)).to_be_visible()
        log.get_by_role('button', name='Close dialog', exact=True).click()
        p.wait_for_timeout(3200)
        expect(completion).not_to_be_visible()
        t.goto('settings')
        toggle = p.get_by_role('switch', name='Desktop notification when a run finishes')
        expect(toggle).to_have_attribute('aria-checked', 'true')
        toggle.click()
        assert p.evaluate("localStorage.getItem('cm-desktop-notify')") == 'off'
        p.reload()
        expect(toggle).to_have_attribute('aria-checked', 'false')
        toggle.click()
        assert p.evaluate("localStorage.getItem('cm-desktop-notify')") == 'on'
        assert p.evaluate('window.__permissionCalls') == 1
        print('PASS: permission on start, completion summary/full log, dedupe, no visible-tab desktop notification, persisted setting')

    with BrowserCheck() as t:
        p = t.page
        d = t.open_worker()
        d.get_by_role('button', name='Run now', exact=True).click()
        console = p.get_by_role('dialog', name='Live job console', exact=True)
        expect(console).to_be_visible()
        console.get_by_role('button', name='Close', exact=True).click()
        p.evaluate("Object.defineProperty(document, 'visibilityState', {configurable:true,get:()=> 'hidden'})")
        t.finished = True
        p.wait_for_function('window.__notifications.length === 1', timeout=16000)
        notice = p.evaluate('window.__notifications[0]')
        assert notice['tag'] == 'occ-run' and 'confirmed: 4' in notice['body'], notice
        expect(p.get_by_role('dialog', name='Run completed', exact=True)).not_to_be_visible()
        print('PASS: hidden-tab desktop notification uses the shared tag and summary')

    with BrowserCheck() as t:
        p = t.page
        t.goto('settings')
        p.get_by_role('switch', name='Desktop notification when a run finishes').click()
        d = t.open_worker()
        d.get_by_role('button', name='Run now', exact=True).click()
        console = p.get_by_role('dialog', name='Live job console', exact=True)
        expect(console).to_be_visible()
        console.get_by_role('button', name='Close', exact=True).click()
        assert p.evaluate('window.__permissionCalls') == 0
        t.finished = True
        p.wait_for_timeout(11000)
        expect(p.get_by_role('dialog', name='Run completed', exact=True)).not_to_be_visible()
        assert p.evaluate('window.__notifications.length') == 0
        print('PASS: disabled preference suppresses permission prompts and completion notices')


if __name__ == '__main__':
    check()
