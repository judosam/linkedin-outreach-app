"""Browser harness for serve_dashboard_fixture.py; fails closed on mutations.

Start that isolated fixture separately. No worker or licence request can escape
the browser route handler. Only the fake fixture login reaches the server.
"""
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get('OCC_REACT_TEST_URL', 'http://127.0.0.1:8774')
OUT = Path(__file__).parent / 'command-center'
OUT.mkdir(exist_ok=True)


class BrowserCheck:
    def __enter__(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch()
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 900}, timezone_id='Asia/Kolkata', reduced_motion='reduce')
        self.page = self.context.new_page()
        self.errors, self.mutations, self.unexpected, self.lead_queries, self.live_queries = [], [], [], [], []
        self.started = False
        self.finished = False
        self.run_number = 700
        self.run_job = 'send_connections'
        self.handlers = {}
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.context.add_init_script("""window.__permissionCalls=0; window.__notifications=[];
          class FakeNotification { static permission='default'; static requestPermission(){window.__permissionCalls++;FakeNotification.permission='granted';return Promise.resolve('granted');} constructor(title, options){window.__notifications.push({title,...options});} close(){} }
          window.Notification=FakeNotification;""")
        self.context.route('**/api/**', self.route)
        # Browser routing does not cover APIRequestContext. This sole mutation is
        # the explicitly named, local fixture login, never a worker endpoint.
        assert urlparse(BASE).hostname in ('127.0.0.1', 'localhost')
        response = self.context.request.post(BASE + '/api/login', data={'username': 'test-admin', 'password': 'test-password-only'})
        assert response.ok, response.text()
        campaigns = self.context.request.get(BASE + '/api/campaigns').json()
        assert {'GCC', 'SCM Podcast', 'Procurement'} <= {c['name'] for c in campaigns}, 'Use only serve_dashboard_fixture.py'
        return self

    def route(self, route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        if path == '/api/runs/live' or path.startswith('/api/runs/live/'):
            self.live_queries.append(parse_qs(parsed.query))
            active = self.started and not self.finished
            payload = dict(running=[dict(execution_id='fixture-exec', job=self.run_job, run_id=self.run_number, status='running', target='GCC / Cindy Smith')] if active else [],
                running_count=1 if active else 0, execution_id='fixture-exec' if self.started else None, active=active,
                run_id=self.run_number if self.started else None, job=self.run_job if self.started else None, target='GCC / Cindy Smith',
                started_at='2026-10-06T06:00:00Z', status='success' if self.finished else 'running' if active else 'idle',
                seq=1, total_lines=1, log_text='fixture-exec: mocked console output' if self.started else '', finished=self.finished,
                errors=[], duration_s=12)
            return route.fulfill(json=payload)
        if path.startswith('/api/runs/700/log'):
            return route.fulfill(json=dict(id=700, job=self.run_job, status='success', target='GCC / Cindy Smith', started_at='2026-10-06T06:00:00Z', finished_at='2026-10-06T06:00:12Z', duration_s=12, errors=[], stats={'confirmed': 4}, log_text='Mocked full log', dry_run=False))
        if request.method not in ('GET', 'HEAD'):
            body = request.post_data_json if 'application/json' in request.headers.get('content-type', '') else request.post_data
            self.mutations.append((path, body))
            if path in self.handlers:
                return self.handlers[path](route, body)
            if (path.startswith('/api/jobs/') and path.endswith('/run')) or path == '/api/jobs/batch':
                self.started = True
                self.finished = False
                self.run_job = path.split('/')[-2] if path.endswith('/run') else 'send_connections'
                return route.fulfill(json={'message': 'Mock run started', 'execution_id': 'fixture-exec', 'warnings': []})
            self.unexpected.append((request.method, path))
            return route.fulfill(status=409, json={'detail': 'Blocked by browser safety harness'})
        if path.startswith('/api/salesnav/'):
            return route.fulfill(status=502, json={'detail': 'Fixture: licence provider is mocked; no external request made.'})
        if path == '/api/accounts':
            response = route.fetch()
            data = response.json()
            for a in data:
                a['status'] = 'active' if a['name'] == 'Cindy Smith' else 'seat_required'
            return route.fulfill(response=response, json=data)
        if path == '/api/leads':
            self.lead_queries.append(parse_qs(parsed.query))
            response = route.fetch()
            data = response.json()
            for lead in data.get('items', []):
                lead['location'] = 'Austin' if lead['id'] % 2 else 'Boston'
                lead['title'] = 'Senior Director of Supply Chain and Business Operations'
                lead['opentomsg'] = {1: True, 2: False}.get(lead['id'])
                if lead['id'] == 1:
                    lead['linkedin_url'] = 'https://www.linkedin.com/in/fixture-edward/'
                if lead['id'] == 5:
                    lead['sales_nav_id'] = 'invalid-id'
            return route.fulfill(response=response, json=data)
        return route.continue_()

    def goto(self, route):
        self.page.goto(BASE + '/#/' + route)
        expect(self.page.locator('main h1')).to_be_visible()

    def open_worker(self):
        self.goto('dashboard')
        self.page.get_by_role('button', name='Run now', exact=True).first.click()
        dialog = self.page.get_by_role('dialog', name='Run Send Connections', exact=True)
        expect(dialog.get_by_text('Run preview', exact=True)).to_be_visible()
        return dialog

    def __exit__(self, typ, value, traceback):
        try:
            if typ is None:
                assert not self.errors, self.errors
                assert not self.unexpected, self.unexpected
        finally:
            self.browser.close()
            self.pw.stop()
