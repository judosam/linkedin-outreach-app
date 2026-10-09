"""Nine routes at desktop/mobile and classic UI compatibility, all safely stubbed."""
from react_browser_support import BrowserCheck, BASE, OUT, expect


def check():
    with BrowserCheck() as t:
        p = t.page
        for theme in ['light', 'dark']:
            for width in [1440, 598]:
                p.set_viewport_size({'width':width,'height':900})
                for route in ['dashboard','accounts','campaigns','leads','threads','jobs','salesnav','settings','users']:
                    t.goto(route)
                    p.evaluate('(theme)=>{localStorage.setItem("cm-theme",theme);document.documentElement.dataset.theme=theme}', theme)
                    p.wait_for_timeout(350)
                    assert not p.evaluate('document.documentElement.scrollWidth > innerWidth + 1'), (theme,width,route)
                    if route in ['dashboard','leads','jobs']:
                        p.screenshot(path=str(OUT/f'{route}-{theme}-{width}.png'), full_page=True)
        p.goto(BASE+'/legacy#/dashboard')
        p.wait_for_function("typeof openFloatingConsole === 'function'")
        p.evaluate('openFloatingConsole()')
        expect(p.locator('#floatingConsole')).to_be_visible()
        print('PASS: 9 routes at 1440/598 in both themes, no document overflow or JS errors; classic console still opens')


if __name__ == '__main__':
    check()
