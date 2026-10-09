"""Compact filters, account dialogs and schedule cards on the isolated UI fixture."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
BASE=os.environ.get('OCC_TEST_BASE_URL','http://127.0.0.1:8772')
LEGACY=BASE+'/legacy'  # classic no-build UI, still served while views migrate
OUT=Path(__file__).parent/'ui-refinement';OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':950})
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto(LEGACY)
    page.locator('#loginUser').fill('test-admin');page.locator('#loginPass').fill('test-password-only')
    page.locator('button[type=submit]').click();page.locator('main h1').wait_for()
    def go(route):
        page.goto(LEGACY+'#/'+route);page.wait_for_function('(route)=>currentRoute===route',arg=route)
        expect(page.locator('main h1')).to_be_visible();page.wait_for_timeout(450)
    # Fixture schedules only; its scheduler and notifications are disabled.
    ids=page.evaluate('''async()=>{
      const all=await apiGet('/api/schedules');
      for(const s of all) if(s.name.startsWith('UI fixture ')) await apiDelete(`/api/schedules/${s.id}`);
      const ids=[];
      for(const [i,name] of ['Morning outreach','Reply review','Friday follow-ups'].entries()){
        const s=await apiPost('/api/schedules',{name:'UI fixture '+name,run_time:['09:00','13:30','16:00'][i],days_of_week:i===2?['fri']:['mon','tue','wed','thu','fri'],job_keys:[['send_connections','check_replies'][i%2]],scopes:{},active:i!==2,timezone:'Asia/Kolkata',jitter_minutes:0,window_end:null});
        ids.push(s.id);
      }
      return ids;
    }''')
    go('dashboard');page.locator('[data-account-details]').first.click()
    expect(page.locator('.account-detail-modal')).to_contain_text("Today's usage")
    expect(page.locator('.account-detail-modal')).to_contain_text('Fixture SCM')
    page.keyboard.press('Escape');expect(page.locator('.account-detail-modal')).to_have_count(0)
    expect(page.locator('[data-account-details]').first).to_be_focused()
    go('accounts');page.locator('[data-account-details]').first.click()
    expect(page.locator('.account-detail-modal')).to_contain_text('Total runs')
    page.locator('#accountDetailSettings').click();expect(page.locator('#accForm')).to_be_visible();page.keyboard.press('Escape')
    page.locator('[data-campdd]').first.click();expect(page.locator('.account-assignments')).to_contain_text('Fixture Procurement')
    assert page.evaluate('''()=>{const el=document.querySelector('.account-assignments li');const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+20,r.y+15))}''')
    page.keyboard.press('Escape')
    go('threads')
    assert page.locator('#replyFilters, #thComments, input[type=date]').count()==0
    requests=[];page.on('request',lambda r:requests.append(r.url) if '/api/threads?' in r.url else None)
    page.locator('#thCategory').select_option('positive');page.wait_for_timeout(450)
    assert 'category=positive' in requests[-1]
    page.locator('#thReview').select_option('needs_review');page.wait_for_timeout(450)
    assert 'category=positive' in requests[-1] and 'review=needs_review' in requests[-1]
    assert all(key not in requests[-1] for key in ['comments=','replied_from=','replied_to='])
    page.locator('#thClear').click();page.wait_for_timeout(400)
    go('leads')
    assert page.locator('#leadStage').count()==1  # Stage is an inline toolbar select
    page.locator('#leadDates').click()
    assert page.locator('#leadDatesPanel select').count()==0
    assert page.locator('#leadDatesPanel input[type=date]').count()==6
    page.locator('#lfDone').click()
    go('jobs');expect(page.locator('.schedule-card')).to_have_count(3)
    assert page.locator('.schedule-card table').count()==0
    page.locator(f'[data-edit="{ids[0]}"]').click();page.locator('#sName').fill('UI fixture Updated outreach')
    page.locator('#sSave').click();expect(page.locator('.schedule-card').first).to_contain_text('Updated outreach')
    page.locator(f'[data-active="{ids[0]}"]').click();expect(page.locator(f'[data-active="{ids[0]}"]')).to_contain_text('Resume')
    page.locator(f'[data-active="{ids[0]}"]').click();expect(page.locator(f'[data-active="{ids[0]}"]')).to_contain_text('Pause')
    page.wait_for_timeout(5000) # Let confirmation toasts finish before capturing layouts.
    for theme in ['light','dark']:
        page.evaluate('(theme)=>{if(theme==="light")document.documentElement.dataset.theme="light";else delete document.documentElement.dataset.theme}',theme)
        for width in [375,768,1440]:
            page.set_viewport_size({'width':width,'height':950})
            for route in ['dashboard','threads','jobs','leads']:
                go(route)
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1'),(theme,width,route)
                if width>1024:
                    assert page.locator('main .page').bounding_box()['x']>=page.locator('.sidebar').bounding_box()['width']
                if route=='dashboard':
                    page.locator('[data-account-details]').first.click()
                    page.screenshot(path=str(OUT/f'account-{theme}-{width}.png'))
                    page.locator('#accountDetailClose').click();expect(page.locator('.account-detail-modal')).to_have_count(0)
                page.screenshot(path=str(OUT/f'{route}-{theme}-{width}.png'),full_page=True,animations='disabled')
    page.emulate_media(reduced_motion='reduce');go('jobs')
    assert page.locator('.schedule-card').first.evaluate('(el)=>getComputedStyle(el).animationName')=='none'
    page.on('dialog',lambda d:d.accept())
    page.locator(f'[data-del="{ids[2]}"]').click();expect(page.locator('.schedule-card')).to_have_count(2)
    assert not errors,errors
    print('PASS: account details/focus/layering, visible Inbox filters, simplified Leads, schedule edit/pause/resume/delete, 24 responsive/theme pages, reduced motion; no page errors.')
    browser.close()

