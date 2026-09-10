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
  runner.py                 Single-flight threaded job execution + live status
  scheduler.py              APScheduler (fixed slots + jitter, DB-configurable)
  notify.py                 GChat alerts + HTML reply-digest email (DB settings)
  main.py                   REST API + auth + static frontend serving
frontend/                   React 18 + TypeScript + Tailwind (Vite)
migrate_sheets_to_db.py     One-time migration from Sheets + campaigns.py
salesApi*.py                Legacy CLI scripts (still runnable, kept as reference)
pipeline_common.py          Shared helpers used by legacy scripts and the app
```

## The five jobs

| Job | Replaces | Trigger model |
|---|---|---|
| Sync Campaign Leads | salesApiLeadSearch.py | Batch: every active campaign in one run |
| Import from List | salesApiSavedSearch.py | Manual one-off, account + numeric list ID, leads arrive **untagged** |
| Send Connections | salesApiConnection.py | Budget-ordered account fill, OpenLink → InMail else invite |
| Check Replies | salesApiMessagingThreadsCheckingReplies.py | Invite-accept detection + reply detection, digest email |
| Send Follow-ups | salesApiMessagingThreadsSendMessages.py | +3/+5/+7-day staged sequences, both tracks |

Behavior preserved exactly (per spec Part A):

- **Budgets**: `invite_sent_count` and `opentomsg_count` are enforced by Send
  Connections against the account's full limits. `messages_sent` is a **shared**
  counter on the same (campaign, account, day) row, consumed by both Check
  Replies (after-acceptance sends) and Send Follow-ups, **each capped at
  `round(message_limit / 2)`**.
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
copy .env.example .env        # then edit: admin password, sheet ID, SMTP, webhook
#    Occ requires a Google service account at ./credentials.json (same as the
#    legacy scripts) for Sync Campaign Leads + the migration.

# 3. One-time migration (Sheets + campaigns.py -> DB)
python migrate_sheets_to_db.py

# 4. Frontend (Node 18+)
cd frontend
npm install
npm run build                 # outputs frontend/dist, served by FastAPI
cd ..

# 5. Run
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000  -> login with OCC_ADMIN_PASSWORD from .env
```

Development mode for the frontend (hot reload, proxies /api to :8000):
`npm run dev` in `frontend/`.

### Optional environment flags

| Variable | Purpose |
|---|---|
| `OCC_ADMIN_PASSWORD` / `OCC_SESSION_SECRET` | Login + session signing |
| `OCC_DB_URL` | e.g. `postgresql+psycopg://user:pass@host/occ` for Postgres |
| `OCC_DISABLE_SCHEDULER=1` | Run the API without cron jobs (dev) |
| `OCC_DRY_RUN=1` | Global dry-run for legacy CLI scripts |
| `MASTER_SHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_FILE` | Sheets migration source |
| `NOTIFY_SENDER_EMAIL` / `NOTIFY_SENDER_APP_PASSWORD` | SMTP sender (server-side, not UI-editable) |

## Security notes

- Login is a single admin password → HTTP-only session cookie; all `/api/*`
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
  campaigns, per-account browser re-capture button.
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
  routing flags, and per-job UTC schedule slots.

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
