> Latest implementation and verification: [Campaign Manager audit, 12 September 2026](AUDIT_AND_HANDOFF.md). This supersedes earlier implementation/status notes below.

# Outreach Command Center

A full-stack web application wrapping the existing Python LinkedIn Sales
Navigator outreach automation. The database (SQLite by default, Postgres-ready)
is the system of record; the dashboard replaces editing Python dicts, JSON
counter files, and Google Sheets by hand.

Built per the uploaded spec (`2-webapp-code-prompt.md`) with the Stitch
"Outreach Command Center" design (dark slate chrome, indigo primary,
Geist/JetBrains Mono, high-density tables).

## What's inside

```
app/                        FastAPI backend
  models.py                 SQLAlchemy schema (accounts, campaigns,
                            campaign_accounts, leads, daily_send_counts,
                            run_logs, lead_events, notification_settings)
  jobs.py                   The 5 jobs with the exact Part-A budget/status rules
  linkedin.py               LinkedIn client mirroring the legacy endpoints
  runner.py                 Per-account concurrent jobs + private live status
  scheduler.py              APScheduler (fixed slots + jitter, DB-configurable)
  notify.py                 GChat alerts + HTML reply-digest email (DB settings)
  main.py                   REST API + auth + static frontend serving
templates/index.html        React app shell (built bundle)
templates/legacy.html       Classic no-build shell, served at /legacy
frontend/                   React + TypeScript + Tailwind source (Vite)
static/dist/                Vite build output (app.js, app.css) - committed
static/                     Classic JavaScript views, CSS and icons
migrate_sheets_to_db.py     One-time migration from Sheets + campaigns.py
salesApi*.py                Legacy CLI scripts (still runnable, kept as reference)
pipeline_common.py          Shared helpers used by legacy scripts and the app
```

## The five jobs

| Job | Replaces | Trigger model |
|---|---|---|
| Sync Campaign Leads | salesApiLeadSearch.py | Manual: selected account + numeric saved search ID; untagged leads |
| Import from List | salesApiSavedSearch.py | Manual one-off, account + numeric list ID, leads arrive **untagged** |
| Send Connections | salesApiConnection.py | Budget-ordered account fill, OpenLink → InMail else invite |
| Check Replies | salesApiMessagingThreadsCheckingReplies.py | Invite-accept detection + reply detection, digest email |
| Send Follow-ups | salesApiMessagingThreadsSendMessages.py | +3/+5/+7-day staged sequences, both tracks |

Current outreach behavior:

- **Budgets**: `invite_sent_count` and `opentomsg_count` are enforced by Send
  Connections against the account's full limits. `messages_sent` is a **shared**
  counter on the same (campaign, account, day) row, consumed by both Check
  Replies (after-acceptance sends) and Send Follow-ups. **Follow-ups use the full
  remaining effective daily limit**, after accounting for messages already sent
  and the account-wide cap. Check Replies retains its half-limit threshold.
- **Status machine**: `INVITE_SENT → INVITE_AFTER_ACCEPT → INVITE_FOLLOWUP_1..3`
  and `INMAIL_SENT → INMAIL_FOLLOWUP_1..3` (+3/+5/+7 days).
  `received_replies = true` excludes a lead from all further automated sends.
- **Load balancing**: leads fill the campaign's accounts in `order_index`;
  unhandled leads roll to the next account; leftovers stay unassigned.
- **Failure modes**: HTTP 400 → lead marked with a reason, no auto-retry;
  HTTP 429 → stop the account's loop, keep the lead;
  `MESSAGE_VALIDATION_PLUGIN_ERROR` → stop InMail/follow-up sends for that
  account for the run.
- `campaign_key` (e.g. "SCM Podcast") is **immutable** after creation — it is
  the literal tag on lead rows.

## Setup

```bash
# 1. Python deps (3.12)
pip install -r requirements.txt

# 2. Environment
copy .env.example .env        # then edit: admin username/password, sheet ID, SMTP, webhook
#    Occ requires a Google service account at ./credentials.json (same as the
#    legacy scripts) for the legacy scripts and Sheets migration.

# 3. One-time migration (Sheets + campaigns.py -> DB)
python migrate_sheets_to_db.py

# 4. Run (no frontend build required)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000  -> login with OCC_ADMIN_USERNAME (default: admin) and OCC_ADMIN_PASSWORD from .env
```

### Frontend (React)

The UI is a React + TypeScript + Tailwind single-page app under `frontend/`,
routed with `react-router` (hash routes, so `/api/*` and deep links keep
working). It talks to the same FastAPI backend.

```bash
cd frontend
npm install
npm run dev      # Vite dev server on :5173, proxies /api to :8000
npm run build    # typechecks, then writes app.js/app.css into ../static/dist
```

FastAPI serves `templates/index.html`, which loads `/static/dist/app.js` and
`/static/dist/app.css`. Every `/static/...` reference is stamped with its
mtime+size at request time, so a rebuilt bundle is never served stale — no
manual `?v=` bump is required.

Every view is ported to React: Dashboard, Accounts, Campaigns (list + detail
editor), Leads, Threads & Replies, Jobs & Scheduler, Sales Nav Licences,
Settings and Users. Both apps share the same API, auth session and data.

The classic no-build interface is still served at `/legacy` as a fallback — it
is fully functional and unchanged, so it can be removed once the React app has
been in use for a while.

### Optional environment flags

| Variable | Purpose |
|---|---|
| `OCC_ADMIN_USERNAME` / `OCC_ADMIN_PASSWORD` | Administrator login; password is required |
| `OCC_DB_URL` | e.g. `postgresql+psycopg://user:pass@host/occ` for Postgres |
| `OCC_DISABLE_SCHEDULER=1` | Run the API without cron jobs (dev) |
| `OCC_DRY_RUN=1` | Global dry-run for legacy CLI scripts |
| `MASTER_SHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_FILE` | Sheets migration source |
| `NOTIFY_SENDER_EMAIL` / `NOTIFY_SENDER_APP_PASSWORD` | SMTP sender (server-side, not UI-editable) |

## Security notes

- Login requires an admin username and password → HTTP-only session cookie; all `/api/*`
  routes (except `/api/health` and `/api/login`) require auth.
- Session cookies live only in `cookies_files/*.json` on the server; the API
  never returns them, and `session_ref` stores only a file path.
- The GChat webhook is masked in GET responses; the UI sends a real URL only
  when changing it. SMTP sender/password stay server-side (env).
- Every outbound LinkedIn action is recorded as a `LeadEvent` and the run in
  `run_logs` (with full log text) for auditability.

## Using the dashboard

- **Dashboard** — today's invites/InMails/follow-ups vs. fleet budgets, replies,
  per-campaign reply-rate chart, pipeline funnel, recent runs.
- **Accounts** — session health (cookie age → "Cookie expiring" flag), assigned
  campaigns, local browser capture instructions and a session verification button.
- **Campaigns** — list + detail editor: account load-balancer with per-account
  daily budgets and calendar URLs, and the 4-tab message-template editor
  (Connection Invite / Invite Follow-ups / InMail / InMail Follow-ups).
  Empty stages are skipped, never an error.
- **Leads** — filterable pipeline (campaign, stage, source toggle, reply state,
  text search). Untagged list-import leads can be assigned to a campaign
  inline. Click a lead's history via `/api/leads/{id}/timeline`.
- **Threads & Replies** — reply inbox with campaign/account badges and a full
  message view.
- **Jobs & Scheduler** — dispatch any job (with dry-run toggle), Import-from-List
  form (account + list ID), live status, and the run-history audit table with
  per-run logs.
- **Settings** — webhook URL (masked) + test button, email recipients, alert
  routing flags, and multiple named schedules with weekdays, time, timezone and campaign selections.

## Legacy scripts

The original `salesApi*.py` scripts still run standalone via Task Scheduler
(`python salesApiConnection.py` etc.) — they share `pipeline_common.py` and
`.env` with the web app, support `dry_run`, and read campaign edits written by
the dashboard (via `campaign_overrides.json` + `campaigns.effective_campaigns()`).
Once jobs run through the web app, disable those Task Scheduler entries; both
systems writing simultaneously would double-send.

## Recommended next steps

- Switch `OCC_DB_URL` to Postgres before scaling beyond one server.
- Add authentication in front of the app if exposing it beyond localhost
  (reverse proxy + TLS).
- Schedule a daily cookie-refresh check (Accounts page flags >7-day-old cookies).

## Fix-and-polish verification (September 2026)

Sync Campaign Leads is manual-only, using one selected account and numeric
savedSearchId. Results are untagged and can be assigned from Leads. List import
remains a separate manual action with its own numeric List ID and endpoint.
This follows the confirmed product choice from September 11, 2026.

Configure `OCC_ADMIN_USERNAME` (defaults to `admin`) and a unique
`OCC_ADMIN_PASSWORD` in `.env`. No password fallback is accepted. Sessions use
random opaque tokens, so the unused session-signing secret has been removed.
`NOTIFY_SENDER_APP_PASSWORD` enables email digests. Missing SMTP credentials disable
email delivery without blocking the app. Admin credentials seed the first account;
password changes made in the app are hashed and preserved across restarts.
The `.env` password no longer overwrites an existing account password.

Settings supports multiple named schedules for Send Connections, Check Replies,
and Send Follow-ups. Each has weekdays (Mon–Sun), time, timezone, selected
campaigns and an enabled switch. New entries default to Asia/Kolkata and exact
time (zero jitter). Optional random windows and jitter remain available.
Existing schedules migrate to named daily entries with their original UTC times,
campaign selections captured at migration, and jitter/window behavior preserved.
Sync and list import are excluded. Empty selections never run all campaigns;
paused campaigns are skipped. Overlapping runs are recorded as skipped.
Use one backend worker: job locking and login sessions are process-local.

Cookie capture needs a local interactive browser. Run
`python get_cookies.py --account "Account Name"` from the project directory,
then choose **Verify session** on Accounts. The API never opens a browser.
Verification confirms access at that moment; cookies can subsequently expire.

Offline regression checks: `python -m pytest tests/ -q`.
For isolated browser checks, set `OCC_TEST_PORT=8766`, start
`python tests/serve_ui_fixture.py`, then run `python tests/smoke_browser.py`
and `python tests/browser_workflows.py` (requires Python Playwright + Chromium).
Live LinkedIn sends, real cookie capture, and external notification delivery
are not exercised by these checks.


## Concurrent runs and log access

Different LinkedIn accounts can execute jobs simultaneously. Each execution
reserves every selected account through the end of its batch. Connection jobs
also reserve their campaign's shared untouched-lead pool to avoid duplicate
outreach. Conflicts return a clear message without starting another worker.

Administrators can select and inspect every running job. Other users can read
and stop only jobs they started, even when they have unrestricted campaign
access. This applies to the console, streaming output, history, and dashboard
run summaries. Unattributed legacy and scheduled logs are admin-only. Deleting
a user keeps their historical logs admin-only; finish or stop their jobs first.

Run one application server process (one Uvicorn worker / one instance). Account
reservations are process-local; do not scale server workers against a shared
database without introducing distributed reservations. Startup adds execution
and owner columns automatically; it does not guess owners for old logs.

Offline verification: `python -m pytest -q --disable-warnings` and
`python tests/check_concurrent_ui.py`. The browser check uses a temporary local
database and simulated workers; it sends no outreach.


Sales Nav imports require an import account to access Sales Nav. The separate
optional outreach account defaults to "No account assigned" and can differ from
the import account. Selecting an outreach account limits campaign choices to
that account's mappings. Untagged leads also retain their selected outreach
account when assigned to a mapped campaign later. Leave the dropdown empty to
keep new leads unassigned and use the campaign's normal account order. Existing
leads keep their account assignments and history. During connection runs,
assigned leads never move to another account when their sender is paused,
unmapped, excluded from the run, or out of budget.

Campaign managers see tagged leads only in their explicitly assigned campaigns.
Sharing a LinkedIn account does not grant access to another campaign's leads.
Account grants cover untagged leads owned by those accounts. Empty campaign or
account selections grant no access; only administrators have unrestricted access.
The user editor stores selected IDs explicitly, including when selecting all
current items, so newly created campaigns are not automatically granted.

For manual and batch runs, "All mapped" selects only active accounts mapped to
the selected active campaigns and allowed for the signed-in user. Unrelated
account grants do not enter validation or session checks. Explicit account
selections are still rejected if they are unauthorized, inactive, or unmapped.

Saved Search, Saved List, and CSV imports identify a duplicate by Sales Nav ID
plus the destination campaign. The same ID may exist once per campaign and
separately in the untagged pool. Reimports preserve existing outreach history
and account assignments and do not refresh leads in other campaigns. CSV URL
fallback also stays within the destination and never merges distinct IDs.

Accounts have a weekly invitation slider from 0 to 100 (default 100); 0 disables
connection invitations. The worker enforces a rolling seven-day limit across
all campaigns on that account, in addition to daily and campaign limits.
Successful app invitations have account-level receipts that survive deleting
leads/campaigns and restarting the app. Failed sends, dry runs, InMails and
follow-ups do not consume this invitation allowance. The first upgrade carries
forward recent audit events and daily invite totals without counting them twice;
daily-only historical counts expire conservatively at that day's end plus seven
days. Manual invitations or sends from other tools are not tracked. This is an
application limit, not a guarantee against LinkedIn restrictions.
