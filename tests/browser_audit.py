"""Shared dialogs, navigation, selection and live-console regressions on fixture."""
from pathlib import Path
from playwright.sync_api import sync_playwright
import json

import os
BASE=os.environ.get('OCC_TEST_BASE_URL','http://127.0.0.1:8769')
LEGACY=BASE+'/legacy'  # classic no-build UI, still served while views migrate
out=Path(__file__).parent/'audit';out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]; failures=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('response',lambda r:failures.append((r.status,r.url)) if r.status>=500 else None)
    page.goto(LEGACY);page.locator('#loginUser').fill('test-admin');page.locator('#loginPass').fill('test-password-only');page.locator('button[type=submit]').click();page.locator('main h1').wait_for()
    def go(route):
        page.goto(LEGACY+'#/'+route);page.locator('main h1').wait_for();page.wait_for_timeout(150)
    go('leads');page.locator('#leadDates').click()
    page.locator('#lfDone').click();assert page.evaluate("leadV2.status===''")
    page.locator('#leadCampaign').select_option('1');page.wait_for_timeout(250);page.locator('#leadStage').select_option('invited');page.wait_for_timeout(350)
    assert 'invited' in page.evaluate('leadQS().toString()')
    page.locator('#leadStage').select_option('');page.wait_for_timeout(350)
    page.locator('#lAll').check();page.locator('#lSelAll').click();page.wait_for_timeout(350)
    assert 'across all pages' in page.locator('.bulkbar').inner_text()
    page.locator('#lDel').click();page.locator('#delGo:not([disabled])').wait_for();page.keyboard.press('Escape')
    go('threads');page.locator('[data-scope=campaignIds] summary').click();page.locator('[data-scope=campaignIds] input').first.check();page.locator('[data-scope=campaignIds] [data-scope-apply]').click();page.wait_for_timeout(350)
    assert '1' in page.locator('[data-scope=campaignIds] summary').inner_text()
    page.locator('[data-thread]').first.click();page.locator('#tCat').select_option('declined');page.wait_for_timeout(350)
    assert page.locator('#tCat').input_value()=='declined'
    page.locator('#tNewComment').fill('Offline audit note')
    page.locator('#tNewComment').press('Enter');page.wait_for_timeout(350)
    assert 'Offline audit note' in page.locator('#tComments').inner_text()
    page.locator('[data-cedit]').first.click();page.locator('[data-cedit]').first.click()
    page.locator('.c-edit').fill('Edited audit note');page.locator('[data-csave]').click();page.wait_for_timeout(350)
    assert 'Edited audit note' in page.locator('#tComments').inner_text()
    for width in [375,768,1440]:
        page.set_viewport_size({'width':width,'height':900})
        go('jobs')
        for key in ['sync_leads','import_list']:
            page.locator(f'[data-import={key}]').click()
            assert page.locator('[role=dialog]').is_visible()
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            page.screenshot(path=str(out/f'import-{key}-{width}.png'))
            page.locator('#importCancel').click()
        page.locator('#runBatchNow').click();page.locator('#batchAll').click();page.locator('#batchFollowups').check()
        assert 'Campaigns: 2 selected' in page.locator('#batchSummary').inner_text()
        page.screenshot(path=str(out/f'run-dialog-{width}.png'))
        page.locator('#batchCancel').click()
    page.set_viewport_size({'width':1440,'height':1000})
    # Actual dry-run batch, one admission request even on a double click.
    admissions=[]
    page.on('request',lambda r:admissions.append(r.url) if r.url.endswith('/api/jobs/batch') else None)
    page.locator('#runBatchNow').click();page.locator('#batchAll').click();page.locator('#batchFollowups').check();page.locator('#batchDry').check()
    page.locator('#batchStart').evaluate('(el)=>{el.click();el.click()}');page.wait_for_timeout(1000)
    assert len(admissions)==1,admissions
    assert page.locator('#floatingPanel').is_visible()
    go('leads');assert page.locator('#floatingPanel').is_visible()
    assert not page.evaluate('document.querySelector("#app").inert')
    # Exercise real import endpoints in dry mode; actual multipage covered in pytest.
    go('jobs')
    for key in ['sync_leads','import_list']:
        if page.locator('#floatingPanel').is_visible(): page.locator('#floatingClose').click()
        page.locator(f'[data-import={key}]').click();page.locator('[name=account]').select_option('1');page.locator('[name=savedId]').fill('123');page.locator('[name=dry]').check();page.locator('#importStart').click();page.wait_for_timeout(700)
    # Backend-driven displayed progress and stopping status, with a deterministic API fixture.
    snapshot={'active':True,'run_id':999,'job':'import_list','status':'running','target':'Fixture account · SavedList 123','started_at':'2026-09-12T01:00:00','log_text':'Page 1: 25 extracted','progress':{'page':1,'page_extracted':25,'extracted':25,'added':25,'total_pages':3,'percent':33}}
    page.route('**/api/runs/live',lambda route:route.fulfill(json=snapshot))
    page.evaluate('pollFloatingConsole()');page.wait_for_timeout(300)
    assert 'Page 1 / 3' in page.locator('#floatingProgress').inner_text()
    snapshot['progress'].update(page=2,extracted=50,added=50,percent=67);snapshot['log_text']='Page 2: 25 extracted · 50 total'
    page.evaluate('pollFloatingConsole()');page.wait_for_timeout(300)
    assert '50 total' in page.locator('#floatingOutput').inner_text()
    for width in [375,768,1440]:
        page.set_viewport_size({'width':width,'height':900});page.locator('#floatingSize').click()
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
        page.screenshot(path=str(out/f'console-{width}.png'))
        page.locator('#floatingClose').click();assert page.locator('#floatingPanel').is_hidden();page.locator('#floatingBall').click()
    snapshot.update(status='stopping');page.evaluate('pollFloatingConsole()');page.wait_for_timeout(200);assert page.locator('#floatingStop').is_disabled()
    snapshot.update(status='stopped',active=False);page.evaluate('pollFloatingConsole()');page.wait_for_timeout(200);assert page.locator('#floatingStop').is_hidden()
    page.locator('#floatingClear').click();assert 'cleared' in page.locator('#floatingOutput').inner_text()
    page.locator('#floatingClose').click();page.unroute('**/api/runs/live')
    # Modal replacement/route transitions must release the application's scroll and input lock.
    page.evaluate("openModal('First','<input>');openModal('Second','<input>');closeModal()")
    page.wait_for_function("document.body.style.overflow !== 'hidden' && !document.querySelector('#app').inert")
    go('leads');page.locator('#leadDates').click();page.evaluate("location.hash='#/logs'");page.wait_for_timeout(400)
    # (route transition closes the app scroll lock; popover needs no extra assert)
    assert page.locator('[role=dialog]').count()==0
    assert page.evaluate("!document.querySelector('#app').inert && !document.querySelector('#main').classList.contains('is-refreshing')")
    assert not errors,errors
    assert not failures,failures
    print(json.dumps({'result':'passed','console_errors':errors,'server_errors':failures,'batch_requests':len(admissions)}))
    browser.close()
