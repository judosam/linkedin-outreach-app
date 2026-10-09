# Outreach Command Center — Changes & Handoff

Date: 11 September 2026
Status: Superseded by the verification update below. The original sections are historical handoff notes, not current test results.

## Verification update — 11 September 2026

The no-build Python/templates/static architecture is retained. Workers, Logs, Jobs, and Settings remain separate. The earlier failing test did not reproduce; isolated test setup and login assertions now make failures explicit. See `REMAINING_CHANGES_PLAN.md` for current verification results and `FIXES.md` for the fixes from this continuation. Do not execute the old section 6 as unfinished work without checking those updates.
Audience: the next AI agent (or human) continuing this project. Section 6 is written as a direct executable prompt.

---

## 1. What the user asked for (verbatim requirements)

1. **Workers moved to a separate page** (out of the Jobs & Scheduler page).
2. **Every run shows logs** — a dedicated **Logging menu ("Logs & History")** showing run history and the full console log of every run.
3. **Dashboard filter stats: Today / 7 days / 30 days.**
4. **Set limit per account** (fleet-level daily caps) **and per campaign** (already existed per campaign-account link; must remain and be surfaced).
5. **Add dates for initial invite/InMail and follow-ups in the Leads section.**
6. **Professional UI using the stitch "Outreach Command Center" template theme** (folder `C:\Users\Samuel P\Downloads\stitch_extracted\stitch_outreach_command_center`, DESIGN.md inside it) — Accounts page must match the template's table columns:
   `Account & Identity | Session State | Last Refresh | InMail Usage (Today) | Invite Quota (Today) | Assigned Campaigns | Actions`.
7. **Architecture change (decisive, user repeated it twice):** do NOT use the separate React frontend. Build it like the user's biometric project (`D:\My workspace\Tools\Report Generate\biometric_timechamp_report`): one Python app serving `templates/` + `static/` with a hash-routed vanilla-JS single-page app. No build step. No Node.
8. **Do not change any existing functions/behavior** while doing all of the above.

---

## 2. Architecture decision (read this first)

- **Before:** FastAPI backend (`app/`) + separate Vite/React frontend (`frontend/`, deleted) that had to be built to `frontend/dist` and served by FastAPI.
- **Now:** FastAPI backend serves `templates/index.html` (single HTML shell) and `static/app.js`, `static/views.js`, `static/style.css`. The JS is a hash-router SPA (`#/dashboard`, `#/accounts`, `#/campaigns`, `#/campaign/:id`, `#/leads`, `#/threads`, `#/workers`, `#/jobs`, `#/logs`, `#/settings`). Login is a separate `#login`-less view toggled by auth state. **No build step is required — edit the JS directly and refresh.**
- The React `frontend/` and `frontend.bak/` directories were **deleted**.
- Backend REST API under `/api/*` is **unchanged in contract** except for additive fields listed in section 3.

---

## 3. Files changed — backend (`app/`)

### `app/models.py` (additive only)
- `Account` gained three fleet-level daily caps:
  - `daily_invite_cap` (default 30), `daily_inmail_cap` (default 10), `daily_message_cap` (default 60).
- `Lead` gained contact-date columns:
  - `first_contacted_at` (DateTime, nullable) — when the lead was first contacted (initial invite or InMail).
  - `contact_channel` (String 20) — `'invite'` or `'inmail'`.
  - `last_followup_at` (DateTime, nullable), `last_followup_stage` (String 40) — last follow-up sent and its stage key (e.g. `INVITE_FOLLOWUP_2`).

### `app/database.py`
- `init_db()` now runs lightweight in-place migrations after `create_all`:
  - `_ensure_columns(table, {name: ddl})` helper does `ALTER TABLE ... ADD COLUMN` for the six new columns above (SQLite-compatible).
- **Backfill:** one `UPDATE leads` statement populates `first_contacted_at` from the earliest `lead_events.kind='outbound'` row per lead, and infers `contact_channel` from the status prefix (`INMAIL%` → inmail, `INVITE%` → invite). Idempotent (`WHERE first_contacted_at IS NULL`).

### `app/jobs.py` — behavior-preserving enforcement + bug fixes
New helpers:
- `_effective_limits(link)` — returns `(invite, inmail, message)` effective budgets = **min(campaign-link limit, account cap)**. This is how "set limit each account AND each campaign" combines; neither value is overridden, the stricter one wins.
- `_stamp_first_contact(lead, channel)` — sets `first_contacted_at` (only if empty) + `contact_channel`.
- `_stamp_followup(lead, stage)` — sets `last_followup_at` + `last_followup_stage`.
- `_AccountSession(session, account_id, db=None)` — wrapper (FIXES.md item B10): any 401/403 from `get/post/put/delete` marks the account `needs_reauth` in DB, poisons the wrapper so subsequent requests fail fast, and raises `LinkedinError`. Unknown attributes proxy to the wrapped session. **NOTE: it is defined but not yet wired into the job send-paths — see issue #2.**

Changed call-sites (all inside existing functions, semantics preserved):
- `send_connections` (Job 3): uses `_effective_limits(link)` for both budget checks and logging; on successful InMail send calls `_stamp_first_contact(lead,'inmail')`; on successful invite send calls `_stamp_first_contact(lead,'invite')`.
- `check_replies` (Job 4): shared message budget now `round(msg_cap/2)` where `msg_cap` comes from `_effective_limits`; after-accept sends call `_stamp_followup(lead,'INVITE_AFTER_ACCEPT')`.
- `send_followups` (Job 5): same shared-budget change; successful follow-ups call `_stamp_followup(lead, result_status)`.
- `_Run.finish()`: **central B8 rule** — a run that has recorded errors can never finish `success`; it is downgraded to `partial` automatically.
- `notify_run_summary_and_errors(run, label)`: **B2 fix (pre-existing bug)** — the error digest (`notify.notify_send_errors(label, run.errors)`) is now sent even when the summary notification raises; each notification failure is caught and printed, never propagated.
- `load_session_ref(account)`: rewritten (B-item behavior):
  1. `account.session_ref` file exists on disk → `_session_from_files({'cookies_file': session_ref})`.
  2. Account name registered in `get_cookies.ACCOUNTS` → `_session_from_files` with that registered `cookies_file` (never `load_session`, so no browser launch from the web app).
  3. Conventional guess `./cookies_files/<first_name_lower>_cookies.json` if it exists.
  4. Otherwise raise `LinkedinError` with a clear "capture cookies locally with get_cookies.py first" message.
  - Required `import os` at top of file.
- `send_followups` **dry-run purity fix (pre-existing bug)**: a dry run previously set `ok=True` and ADVANCED lead state (status → follow-up stage, counters incremented). Now dry run `continue`s before any send/state change. This fixed `test_dry_run_does_not_advance_leads`.
- `send_followups` **rate-limit scope fix (pre-existing)**: a 429 (`err_kind == 'rate_limited'`) or validation error now sets `account_stopped = True`, which breaks out of **all remaining stages** for that account, not just the current stage list. This fixed `test_followup_rate_limit_stops_all_stages` (send called exactly once).

### `app/main.py` — API additions (all additive; existing routes unchanged unless noted)
- `GET /api/dashboard/summary?days=1|7|30` — new `days` query param (clamped to 1/7/30, default 1):
  - `window_start = today - (days-1)`; `DailySendCount` rows summed over the window instead of only today.
  - `replies.window` — replies received within the window.
  - `today.contacted_window` — invites+InMails across the window; `today.leads_added` — leads created in the window; `today.contacted_yesterday` kept (delta only meaningful at `days=1`).
  - Response now includes `window_days`.
- `GET /api/dashboard/trends?days=7|30` — trend series length is now 7 or 30 daily buckets (was hard-coded 7). Response shape unchanged (`days`, `runs_24h`).
- `GET /api/accounts` — each row now also returns `daily_invite_cap`, `daily_inmail_cap`, `daily_message_cap`, and `usage_today: {invites, inmails, messages}` (summed from `DailySendCount` for today across all of the account's campaign links). Powers the template's "InMail Usage (Today) / Invite Quota (Today)" columns.
- `POST /api/accounts` and `PUT /api/accounts/{id}` — `AccountIn` now accepts `daily_invite_cap`, `daily_inmail_cap`, `daily_message_cap` (ge=0, defaults 30/10/60); update persists them. **Note:** the Jobs page's quick pause/resume previously sent only `{name,status}` — the new AccountIn defaults would zero the caps, so the UI always sends the current cap values back (see `views.js` toggle handler).
- `GET /api/leads` serializer now includes `first_contacted_at`, `contact_channel`, `last_followup_at`, `last_followup_stage`.
- `GET /api/runs` default `limit` raised 50 → 100 (cap still 200).
- **Static serving replaced**: was `frontend/dist` React SPA; now mounts `/static` from `static/` and serves `templates/index.html` for all non-API, non-file paths. Guard rejects traversal outside project root and never serves files from `templates/` directly.

---

## 4. Files changed — frontend (new, vanilla JS)

### `templates/index.html`
Single shell: dark sidebar (`#0F172A`) with brand "Outreach Command / Sales Nav Core / Ops v2.4", nav items with live badges (`navScheduler`, `navAccounts`, `navCampaigns`, `navUnread`, `navWorkers`, `navJobsHealth`), user/logout chip; topbar with global search + live chip + "Run Jobs Now" + notifications popover; `<main>` where views render; separate login view (dark brand panel + sign-in card); toast + modal hosts. Loads Google fonts (Geist, JetBrains Mono, Material Symbols) and `/static/style.css`, then `app.js` + `views.js` (cache-busted with `?v=2`).

### `static/style.css`
Full stitch-theme implementation:
- Palette: chrome-900/800/700/400, canvas `#F8FAFC`, hairline `#E2E8F0`, accentline `#CBD5E1`, primary `#4F46E5`, ok/warn/crit/idle semantic tints.
- Components: `.card`, `.btn-primary/secondary/danger/ghost`, `.input`, `.seg` (segmented control), `.pill-*` status pills with dots, `.tag`, `.quota-track/.quota-fill` (warn ≥80%, crit ≥100%), `.stat-card` metric cards, `table.data` (32px header, 40px rows, hover `#F8FAFC`, mono numerics), `.toolbar`, `.bulkbar`, `.banner-*`, `.modal-*`, `.toast`, `.tabs`, `.runlog` (dark console viewer), `.who` identity cells, `.date-cell`, `.bar-row` trend bars, `.funnel-row`, login split view, responsive sidebar drawer at ≤1024px, `prefers-reduced-motion` respected.

### `static/app.js` (core)
- Helpers (`$`, `$$`, `esc`, `pill`, `statusPill`, `fmtDT/fmtD/ago/fmtDur`, `initials/who` with deterministic avatar colors, `quotaBar`, `runStatus`), STATUS_META and JOB_LABELS maps, WORKERS/DAYS constants.
- `apiGet/apiSend` with 401 → auto `showLogin()`.
- `toast(message, tone)`, `openModal/closeModal` (backdrop + Escape close).
- Auth: `showLogin/showApp`, login form submit, logout button, route memory in `sessionStorage`.
- Hash router `route()` + `ROUTES` map + error banner fallback; mobile sidebar toggle with scrim.
- `pollNav()` every 10 s → `/api/jobs` nav payload drives sidebar badges, live chip ("Running: Send Follow-ups" / "Scheduler live/off"), notification dot.
- Global search popover (`/api/search?q=`) with Leads/Campaigns/Accounts groups; notifications popover.
- **Dashboard view** (`viewDashboard`): Today / 7 days / 30 days segmented filter (persisted in `dashRange`), 4 stat cards with quota bars, window-aware reply card ("N in window / M all-time", lifetime rate), CSS-bar send-volume trend (uses `/api/dashboard/trends`), pipeline funnel list, recent-activity table (5 most recent runs) linking to Logs.
- `runTable(runs, compact)` shared renderer; `openRunLog(runId)` modal that fetches `/api/runs/{id}/log` and renders Stats (kv grid), Errors, and the full console log in a dark terminal block.

### `static/views.js` (views; declares functions the router references)
- **Accounts (`viewAccounts`)** — template-faithful table: Account & Identity (avatar+name+session sub), Session State pill (Active / Cookie expiring / Needs re-auth / Paused; row tinted amber when stale), Last Refresh (relative + absolute), **InMail Usage (Today)**, **Invite Quota (Today)**, **Messages (Today)** — each a quota bar `used/cap` with cap caption, Assigned Campaigns tags, Actions (Limits / Pause-Resume / Verify session). Warning banner listing accounts needing attention. "Limits" opens `accountEditor` modal to set the three daily caps (create-account modal also includes name/status/session_ref).
- **Campaigns (`viewCampaigns`)** — table with Status, Campaign (+ immutable key), Load Balancer chips showing per-account order and `invite/inmail/msg` limits, Leads, Contacted, Reply Rate; "New Campaign" → `#/campaign/new`.
- **Campaign detail (`viewCampaignDetail`)** — identity card (name, key, search URL, status), **Accounts & quota balancing** editor (ordered rows; per-account Invite/day, InMail/day, Msg/day, calendar URL; effective-budget hint), and 4-tab template editor (Connection Invite; Invite Follow-ups +3/+5/+7 incl. after-accept; InMail subject/body; InMail Follow-ups ×3). Placeholder validation `{first_name}`/`{calendar_url}` only; create → redirect, edit → save.
- **Leads (`viewLeads`/`renderLeads`)** — URL-deep-link `?q=`, toolbar (search debounce, campaign/status/source/replied filters), table with **Initial Contact** column (date + channel Invite/InMail + relative) and **Last Follow-up** column (date + stage), Stage pill, Reply pill, pagination, Export CSV (same filters), Import CSV modal (optional campaign tag).
- **Threads (`viewThreads`)** — channel segments (All / Last 7 days / Mentions booking — booking regex client-side), reply list + detail pane with campaign/account attribution.
- **Workers (`viewWorkers`)** — NEW SEPARATE PAGE: three worker cards (Send Connections / Check Replies / Send Follow-ups) with description, last-run status pill + time, schedule summary, **Run now** (scope dialog: all-or-selected campaigns × all-or-selected accounts, dry-run checkbox) and Last-log shortcut; live "Running: X" banner disables run buttons; manual tools section (Sync Campaign Leads: account + numeric Search ID; Import from List: account + numeric List ID — unchanged server-side validation).
- **Logs & History (`viewLogs`/`renderLogs`)** — NEW MENU PAGE: filter by worker + status, most recent 200 runs, client-side pagination (25/page), columns Run # / Worker / Target / Schedule id / Started / Duration / Status / **View log** → `openRunLog` modal with full console output.
- **Jobs & Scheduler (`viewJobs`)** — now scheduler-only: schedules table (name, worker tags, time+timezone+jitter/window, days, active pill, next/last run, Edit/Pause-Resume/Delete), `scheduleEditor` modal (name, time, day toggles, worker order-preserving toggles, timezone/jitter/window-end, active). Links to Workers page.
- **Settings (`viewSettings`)** — dark zero-storage-credential banner, Google Chat webhook (masked, Test button), email-recipient chips (add via Enter, remove), four trigger-category toggles, save.
- Boot: probes `/api/me`; shows app + routes + starts polling, else shows login.

### Deleted
- `frontend/` (React app incl. node_modules, dist, tsconfig, tailwind config, all pages), `frontend.bak/`.

---

## 5. Tests — current status

Command: `python -m pytest tests/ -q`

| Scope | Result |
|---|---|
| `tests/test_schedule_store.py` alone | **3 passed** |
| `tests/test_polish.py` alone | **9 passed, 1 failed** (`test_active_budgets_only`) |
| Full suite together | **12 passed, 1 failed** (same single failure) |

**Fixed during this session** (were failing at session start):
- `test_digest_still_runs_when_summary_fails` → B2 digest fix in `notify_run_summary_and_errors`.
- `test_dry_run_does_not_advance_leads` → dry-run purity fix in `send_followups`.
- `test_followup_rate_limit_stops_all_stages` → 429 now stops all stages for the account.
- `test_reauth` → added `_AccountSession` (passes; wrapper not yet wired into send paths).
- 3 × test-isolation failures (`unable to open database file`) → env-var `setdefault` in `tests/test_polish.py` + removed `tearDownModule` temp-dir cleanup so both modules share one engine/tmpdir safely.

**Still failing:**

### Issue #1 (OPEN): `test_active_budgets_only` — `KeyError: 'today'`
- `tests/test_polish.py:121` asserts `/api/dashboard/summary` → `today.invites_limit == 10` after seeding, and `== 0` after pausing the account.
- The request returns **401 Not authenticated** in the pytest run (hence `KeyError: 'today'`), but the **exact same flow works when reproduced standalone** (verified with a scripted TestClient: login 200, summary 200, `invites_limit == 10`).
- Not yet root-caused. Leading hypothesis: the `setdefault` change means `OCC_ADMIN_USERNAME/PASSWORD` env vars set by whichever test module imports first are used, but that matches for both files ('test-admin'/'test-password-only'). Second hypothesis: session store state pollution across modules — `app.auth._sessions` is module-global; `test_schedule_store` importing `app.main` first does not clear it, and something in the earlier module's teardown (engine.dispose) may make an in-session DB write fail *inside the login route before the cookie is set*, returning 401. Needs a debug print / `-pdb` run under full-suite ordering (`pytest -q tests/ -k budgets --tb=long` plus printing `response.text`).
- Safe fix direction: in the test, log in again (or assert `response.status_code == 200` first to get a useful failure). Do not change app code to chase this.

### Issue #2 (OPEN, code gap): `_AccountSession` exists but is not wired in
- FIXES.md B10 wants jobs' LinkedIn HTTP calls guarded. `jobs.py` currently passes raw `curl_cffi` sessions to `li.*` functions. To complete: in `send_connections`/`check_replies`/`send_followups`, after `session = load_session_ref(account)`, wrap with `jobs._AccountSession(session, account.id)` and use the wrapper for all `li.*` calls in that loop (they take `session` as first arg, so it's a one-line wrap per account loop). Keep dry-runs from loading sessions at all (already true).

### Issue #3 (OPEN, cosmetic/runtime): new UI not yet verified in a browser
- `tests/serve_ui_fixture.py` still works as a fixture server (`python tests/serve_ui_fixture.py` → http://127.0.0.1:8765) and now serves the new templates automatically. Not yet smoke-tested; see section 6 task 4.

### Issue #4 (known limitation, by design): paused-account API contract
- `PUT /api/accounts/{id}` now requires/defaults the three caps; any **older** caller that PUTs only `{name,status}` will reset caps to defaults (30/10/60). The new UI always echoes current values, but re-check any external scripts that call this endpoint.

---

## 6. Remaining work — instructions for the next agent (copy as prompt)

> **CONTEXT**
> Project root: `D:\My workspace\Linkedin Automation\Linkedin Automation Project`.
> FastAPI app in `app/` (run with `uvicorn app.main:app`, scheduler auto-starts unless `OCC_DISABLE_SCHEDULER=1`; requires `OCC_ADMIN_PASSWORD` in `.env`).
> Frontend is a NO-BUILD vanilla-JS SPA: `templates/index.html` + `static/style.css` + `static/app.js` (core/router/dashboard) + `static/views.js` (all other views). Edit and refresh — never reintroduce React/npm.
> Theme: stitch "Outreach Command Center" (dark slate sidebar `#0F172A`, light workspace `#F8FAFC`, indigo `#4F46E5`, JetBrains Mono metrics). Keep all existing backend behavior — additive changes only.
> Read `CHANGES_AND_HANDOFF.md` sections 3–5 first.

> **TASK 1 — Fix the last failing test**
> `python -m pytest tests/ -q` must end `13 passed`. Only `tests/test_polish.py::RegressionTests::test_active_budgets_only` fails (`KeyError: 'today'` because `/api/dashboard/summary` returns 401 under full-suite ordering, though the same flow passes standalone).
> Steps: run `python -m pytest tests/test_polish.py -q --tb=long -k budgets` alone (passes?), then `python -m pytest tests/ -q --tb=long -k budgets` and print `response.status_code`/`.text` by temporarily extending the assertion. Inspect `app/auth.py` `_sessions` and `tests/test_schedule_store.py` module-level env setup for cross-module pollution. Preferred fix is TEST-side (re-login in the test or make each module's `setUp` log in again), not app-side. Do not weaken the assertion — keep both the 10 and the 0 (paused) checks.

> **TASK 2 — Wire `_AccountSession` into the three send workers (FIXES.md B10)**
> In `app/jobs.py`, in `job_send_connections`, `job_check_replies`, `job_send_followups`: after each successful `session = load_session_ref(account)` (non-dry-run paths only), wrap: `session = _AccountSession(session, account.id)`. All `li.*` calls in that account loop then automatically mark the account `needs_reauth` + raise `LinkedinError` on 401/403. Confirm `except li.LinkedinError` blocks still skip the account gracefully (they already append run errors). Run `python -m pytest tests/ -q` — all 13 must still pass, including `test_reauth`.

> **TASK 3 — Browser smoke-test the new UI and fix what breaks**
> Start the fixture: `python tests/serve_ui_fixture.py` (port 8765, login `test-admin` / `test-password-only`). With a headless browser, verify: login flow; Dashboard renders with Today/7/30 toggle switching numbers; Accounts table shows quota bars and the Limits modal saves caps (then `GET /api/accounts` shows them); Campaign create/edit round-trip incl. per-account limits; Leads shows Initial Contact / Last Follow-up columns; Workers page Run-now dialog opens and (dry-run) starts a run; Logs page lists the run and View log shows the console modal; Jobs scheduler create/edit/delete; Settings save. Watch console for JS errors; check layout at 1280px and 768px; confirm no horizontal overflow. Fix only frontend files; re-run the suite after any backend touch.

> **TASK 4 — End-to-end sanity with the real (local) server**
> `uvicorn app.main:app` from project root with real `.env`. Confirm: scheduler init message; `/` serves the shell; `/static/*` 200; login with real admin creds; dashboard counts match DB; a dry-run of Send Connections from Workers completes and appears in Logs with log text. **Do NOT run live (non-dry) LinkedIn sends or hit real Google Chat/email webhooks.**

> **TASK 5 — Small correctness sweep before handoff**
> (a) `GET /api/threads` in `views.js` requests `page_size=100`; server caps page_size at 200 — fine, but confirm 100 > default 25 actually returns up to 100 rows. (b) Confirm `templates/index.html` cache-busting `?v=2` is bumped whenever style/app/views change. (c) `REMAINING_CHANGES_PLAN.md` still references the React frontend — update or delete it, and append a dated section to `FIXES.md` describing this session's changes (models caps + lead dates, min(link,cap) budgets, B2/B8/B10/dry-run/rate-limit fixes, templates+static UI, deleted frontend/).

> **CONSTRAINTS**
> Do not rename `campaign_key`s, do not change lead-status values, keep Sync/Import manual-only, keep the single-flight lock, never log or expose cookie values, and never send real LinkedIn messages or notifications during verification.

---

## 7. Quick reference — where everything lives now

| Feature | File |
|---|---|
| Dashboard range filter (Today/7/30) | `static/app.js` `viewDashboard` + `app/main.py dashboard_summary` |
| Workers page (separate) | `static/views.js` `viewWorkers`, `runWorkerDialog` |
| Logs & History menu | `static/views.js` `viewLogs`, `openRunLog` (in app.js) |
| Per-account limits | `app/models.py Account.daily_*_cap`, `app/main.py AccountIn`, `static/views.js accountEditor`, enforced by `app/jobs.py _effective_limits` |
| Per-campaign limits (existing) | `campaign_accounts.invite_limit/inmail_limit/message_limit`; edited in campaign detail |
| Initial invite/InMail + follow-up dates | `app/models.py Lead.first_contacted_at/...`, stamped in jobs 3/4/5, shown in `static/views.js renderLeads`, backfilled in `app/database.py init_db` |
| Accounts template table | `static/views.js viewAccounts` |
| Theme tokens/components | `static/style.css` |
| App shell / nav | `templates/index.html`, `static/app.js` Shell logic + `pollNav` |
