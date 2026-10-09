# Fix-and-polish review — September 11, 2026

## Campaign creator automatically gets access (2026-09-22)

When a restricted (non-admin) user creates a campaign, the new campaign's id is auto-appended to their `allowed_campaign_ids` in `create_campaign` — before this fix the campaign was invisible to its own creator (every view filters by that list). Admins are untouched. Regression: `test_creator_auto_gets_access_to_new_campaign` — 175/175 pass.

## Leads campaign filter includes unassigned pool (2026-09-22)

The Campaign dropdown in Leads & Prospect Pipeline now has a **"— No campaign (unassigned) —"** option. Selecting it sends `campaign_id=__none__` and shows only pool leads with no campaign tag; the filter chip, CSV export, and user scope all honor it (`/api/leads`, `/api/leads/export`). Numeric campaign filtering is unchanged. Regression: `test_leads_campaign_none_sentinel_filters_unassigned_pool` — 174/174 pass.

## Global lead dedupe by Sales Nav ID across every import path (2026-09-22)

**Before:** dedupe was per-campaign — the same person could exist as a pool row AND one row per campaign (or in several campaigns), each getting contacted independently.

**Now:** all three import paths dedupe globally on the bare `sales_nav_id` (ACw token):
- **SavedSearch sync** (`_upsert_lead`) — a person already anywhere in the DB is refreshed (profile fields gap-filled), never re-inserted
- **SavedList import** (`_upsert_lead_untagged`) — same global rule
- **CSV import** (`/api/leads/import-csv`) — snid lookup is global; URL-based dup check likewise

Engagement state (status, follow-ups, replies) is never touched by refreshes; campaign tags stay with the original row. Your current DB is already clean (9,115 leads = 9,115 distinct IDs), so no migration needed.

**Tests:** updated `test_manual_search_and_list_are_distinct` (same person via search+list = 1 row), added 2 regressions (CSV person in another campaign skipped; pool-then-search single row) — 173/173 pass.

## Connections card shows profile-check work even with zero sends (2026-09-22)

**Also:** `invites_sent` and `inmails_sent` are now always-visible counters in per-account stats — they render as `Invites sent: 0 · InMails sent: 0` even when a run sends nothing (new `ALWAYS_SHOW_STAT_KEYS` in `notification_format.py`). All other stats keep strict zero-hiding.

**Symptom:** a 28-minute Connections run sent nothing (budget already used) and the card showed only `NZ-Anne-PDM · Totals — Left for next run: 335` — no sign of what the run actually did.

**Root cause:** the run spent its time on ~200 OpenToMsg profile fetches, but `opentomsg_checked` was never recorded in run stats. The zero-hiding rule then correctly omitted the zero send counts, leaving a card with no evidence of work.

**Fix:**
- `app/jobs.py` — Send Connections now records `opentomsg_checked` per account (`Campaign/Account` key) and rolls it into the campaign Totals.
- `notification_format.py` — new label `opentomsg_checked` → "Profiles checked"; it passes the zero-hider like any outcome, so it shows only when non-zero.

The same scenario now renders:
```
✅ Campaign Manager · Connections
Completed
NZ-Anne-PDM / Anne Davis · All active campaigns · 28m 34s
NZ-Anne-PDM/Anne Davis — Profiles checked: 200
NZ-Anne-PDM · Totals — Profiles checked: 200 · Left for next run: 335
```

171/171 tests pass.

## OpenToMsg check limit: accurate counter + cached logs labeled (2026-09-22)

**Symptom:** the run log showed `OpenToMsg check 203/335` even though the cap is 200 — the limit appeared broken.

**Root cause:** the log printed the lead's *position in the list* (`i/len(remaining)`), not the number of real profile fetches. Cached leads (already checked, or URL backfill done) log the same "check" line without consuming budget, so the visible counter ran past 200 while the real guard (`opentomsg_checks >= 200`) stopped live fetches correctly.

**Fix (`app/jobs.py`):**
- New `OPENTOMSG_CHECK_LIMIT = 200` constant (single source of truth).
- Real fetches now log `OpenToMsg check {n}/200: <name> - checking profile` where n is the actual fetch counter.
- Cached leads now log `OpenToMsg cached (no fetch): <name> - <result>` — clearly not counted.
- Limit-reached message now says `limit reached (200 profile fetches)`.

The cap itself was working; only the labels lied. Tests updated (`test_opentomsg_logging_live_and_saved` now asserts both variants' exact lines) — 171/171 pass.

## Follow-ups use the full remaining daily allowance (2026-09-22)

`send_followups` no longer applies a half-limit. It draws from the shared
`messages_sent` budget up to the **full effective daily limit** (per-campaign
`message_limit` bounded by the account's `daily_message_cap` minus what other
campaigns already sent for that account today). Example: limit 30 with 12
messages already sent now allows 18 more follow-ups (was 3 under half-cap).
The dashboard `followups_limit` reports the full cap; Check Replies keeps its
existing after-acceptance half-limit threshold, and the total across both
jobs can never exceed the account's daily cap.

Covered by `tests/test_followup_budget.py` (10 parametrized budget cases +
dashboard total test). Full suite: 171 passed.

## HTTP 400 reads as "Email is required to connect" (2026-09-22)

The run log, lead errors, and the GChat card showed raw responses like
`Invite failed for …: HTTP 400: {"value":"-1"}`. LinkedIn's generic rejection
never names a cause, but the legacy scripts (salesApiConnection.py) treat every
HTTP 400 as "Email is required to connect" — so the app now does the same:

- `app/linkedin.py::_interpret()` classifies **all HTTP 400s** as
  `email_required` with the friendly detail `Email is required to connect`
  (explicit email phrasing in the body still resolves to the same result).
- Lead blocking behavior is unchanged: these leads keep getting
  `BLOCKED_ERROR` + `last_error = Email is required to connect` and are skipped
  in future runs; 429/500 handling untouched.
- GChat / run log now read:
  `GCC/Ranganathan A: Invite failed for Lakshmi Kanta Nandi: Email is required
  to connect`

Test updated: `test_http_400_maps_to_email_required_with_friendly_detail`
(parametrized over `{"value":"-1"}`, invalid-request, EMAIL_REQUIRED code,
plain-English body, and empty body). Full suite: 151 passed.

## Connections GChat card: per-account lines + Totals (2026-09-21)

Send Connections now renders like Follow-ups — one bold line per account, plus
a campaign Totals line:

```
*CXO Podcast/Andrew Dreger* — Contacted: 62 · Invites sent: 42 · InMails sent: 20
*CXO Podcast · Totals* — Contacted: 102 · Invites sent: 72 · InMails sent: 30 · Left for next run: 153
```

- `job_send_connections` now tracks per-account counters (`contacted`,
  `invites_sent`, `inmails_sent`) keyed `campaign/account`, and stores the
  campaign aggregate under `campaign · Totals` (including `leftover`).
- The formatter hides zero-send accounts and all zero stats, so quiet accounts
  never appear; the Totals line always shows when anything was attempted.
- Regression: `test_connections_card_splits_by_account_with_totals`; the audit
  stats assertion was updated to the new keys. 149/149 tests pass.

## GChat card v2 — outcomes only, zeros never shown (2026-09-20)

Refinement of the friendly-notification rework: the card now leads with what
actually happened and omits every zero and every plumbing metric.

- `accepts_found` removed from the card entirely ("Accepts Found: 1 · Accepts
  Messaged: 1" → just "1 invite accept messaged"); hidden plumbing keys are now
  records_to_check, pending_invites, threads_fetched, threads_matched,
  accepts_found, accepts_skipped_blank.
- Zero guard (`_is_zero`) applies to per-account stats AND top-level metrics —
  "Leads added: 0" / "Skipped: 0" lines disappear; budget forms ('5/30') stay.
- All-zero (idle) account lines are omitted from the card completely.
- Natural verb phrasing with correct singular/plural: "1 invite accept
  messaged · 2 new replies received"; bold account names preserved exactly
  ('GCC/Ranganathan A' no longer smashed to 'Gcc/...').
- Compact meta line: context and duration merged ("All campaigns/accounts ·
  45.6s"); per-account lines use an em-dash separator.
- Tests: updated test_per_account_stats_are_friendly_outcomes,
  test_summary_is_fancy, test_notification_format_is_bounded_and_hides_zero_metrics;
  added test_zero_top_level_metrics_are_hidden — 149/149 pass. Restart server to load.


## GChat notifications rewritten to plain outcomes (2026-09-20)

Per-account lines in the completion card now read like outcomes, not plumbing:

Before:
- Cxo Podcast/David Bodiford: Records To Check: 126 - Pending Invites: 72 - Threads Fetched: 90 - Threads Matched: 50 - Accepts Found: 0 - Accepts Messaged: 0 - New Replies: 1

After:
- Cxo Podcast/David Bodiford: New replies: 1
- Cxo Podcast/Kimberly Morrison: Invite accepts found: 1 - Accepts messaged: 1
- GCC/Ranganathan A: Contacted: 3 - Invites sent: 2 - InMails sent: 1 - Left for next run: 12

Changes: notification_format.py gained ACCOUNT_STAT_LABELS + _format_account_stats();
plumbing keys (records_to_check, pending_invites, threads_fetched, threads_matched)
and zero-value outcomes are hidden from GChat; send_connections now reports split
invites_sent/inmails_sent alongside contacted. Idle-account omission for
check_replies unchanged (reply_activity filter). Regression:
test_per_account_stats_are_friendly_outcomes - 148/148 pass. Restart server to load.

## Confirmed behavior

The user explicitly confirmed that **Sync Campaign Leads stays manual**, taking
one account and a numeric savedSearchId. This overrides the pasted checklist's
scheduled-batch requirement. Search results arrive untagged for assignment.
`job_sync_leads` (`app/jobs.py:182`) and `job_import_list` (`app/jobs.py:221`)
remain separate functions, job URLs and UI forms. List import continues to use
the independent List-pivot endpoint, one account and a numeric List ID.
Neither tool can be scheduled.

Named schedules apply to Send Connections, Check Replies and Send Follow-ups.
Each entry has a name, weekdays Monday–Sunday, time, timezone, selected campaigns,
enabled switch, and optional timing controls. Multiple entries can target different
campaigns. Paused campaigns are skipped; an empty selection never means all campaigns.
Existing schedules migrate once to named entries, preserving UTC times and timing
options while excluding sync. New schedules default to Asia/Kolkata with no delay.

## Checklist implementation

| Item | Change and location |
|---|---|
| B1 | `app/config.py:21` requires an administrator password without a built-in fallback. `app/notify.py:24` requires SMTP credentials with a clear startup error. Removed the unused weak session-signing helper; sessions use random opaque tokens. Legacy notifier password fallback and unused encrypted literals were removed. Credential-like assignments in application and top-level Python files were scanned without exposing their values. |
| B2 | `app/jobs.py:583` sends the dedicated error digest independently of the summary, including when the summary raises an exception. Verified with mocked notifications and an intentional error; real dry runs suppress external notifications. |
| B3 | `app/scheduler.py:145` supports full configured jitter (15 minutes remains 900 seconds), weekdays and timezone. `app/scheduler.py:115` persists a random daily-window instant so restarting does not choose another run for that day. |
| B4 | `app/runner.py:41` claims the single-flight lock before spawning the worker, releases it in finally, and exposes the current job state. Jobs disables all dispatch controls while starting/running and displays elapsed time. |
| B5 | `app/jobs.py:321` normalizes pending-invitation comparisons by case and whitespace; replied leads are also excluded. |
| B6 | `app/main.py:75` counts budget limits only from active campaigns and active accounts. |
| B7 | `app/main.py:249` no longer launches a browser from the refresh request. Accounts explains local capture and provides Verify session (`app/main.py:256`) with bounded LinkedIn requests. `get_cookies.py` supports one-account capture, waits for login and verifies captured credentials before replacing the file. |
| B8 | `app/jobs.py:116` centrally finishes as partial whenever errors were recorded, for all five jobs. |
| B9 | `app/scheduler.py:96` records skipped scheduled runs, including overlaps and no active selected campaigns, with the schedule name and reason. |
| B10 | `app/jobs.py:536` marks accounts needs_reauth on HTTP 401/403 and prevents subsequent requests through that rejected session. |

UI changes cover job dispatch, schedule editing, account verification and pause/resume,
campaign saving, lead assignment, CSV actions, settings saves and refresh controls.
Loading/disabled states, error feedback, destructive-action confirmations, validation,
empty states, status text, keyboard focus and responsive tables are retained or improved.
`frontend/src/ScheduleEditor.tsx:13` implements the named schedule editor.

## Verification

- 16 backend regressions passed in isolated SQLite with mocked LinkedIn calls.
- Production TypeScript/Vite build passed.
- Browser checks passed on Dashboard, Accounts, Campaigns, Campaign editor, Leads,
  Threads, Jobs and Settings at 1280px and 768px using seeded fixture data.
- No page-level horizontal overflow or JavaScript runtime errors in those checks.
- Browser workflow verified two schedules with different days/campaigns, persistence
  after reload, disabling, deletion, and manual search submitting only account/Search ID.
- A manual-search dry run was executed against the isolated fixture without live requests.
- Unit tests verified selected-campaign dispatch, weekday/timezone conversion,
  manual-only API validation, lock overlap, pending invitations, dry-run preservation,
  notification failures, expired sessions, missing SMTP startup, and window persistence.

## Limits and operation

Live LinkedIn sends, interactive login/2FA, actual Google Chat delivery and SMTP delivery
were not exercised. Their network responses and account state still need live verification.
Cookie refresh requires human login where LinkedIn requests it; the web app does not
promise one-click hosted browser authentication. The Ranganathan cookie path was corrected
to ranga_cookies.json; a load test does not establish that those cookies are still valid.

Restart the backend to load these changes and migrate schedules. Use one backend worker:
job locking and login sessions remain process-local. The named configuration uses the
existing settings table, so no database schema migration was required at that earlier stage. Existing user edits
and original reference files outside this project have been preserved.

## 11 September 2026 — Python/static handoff verification

The current UI is served from `templates/index.html` and `static/`. The prior React frontend was removed before this continuation; no npm/build step was reintroduced. Workers and Logs have separate menus; Jobs manages schedules. Account fleet caps and initial-contact/follow-up date fields remain in the models/UI. Current additive schema migrations supersede the older no-migration note above.

- **Verification:** 18 backend tests passed. The reported dashboard authentication failure did not reproduce; pytest now establishes one isolated environment/database lifetime, login setup asserts success, and cleanup releases SQLite before removing test storage.
- **B10:** all three send workers wrap loaded sessions with `_AccountSession` and the same DB session. Tests verify 403 marks the account for reauthentication in each worker.
- **Budgets:** campaign limits are bounded by the account's remaining capacity after other campaigns' usage. Existing shared half-message-budget behavior remains. Partial account PUTs preserve omitted caps.
- **Dry runs:** Send Connections no longer loads sessions or stamps/increments persistent send state. Summary/error/critical notifications are suppressed for dry runs. The earlier Follow-ups dry-run and account-wide rate-limit fixes remain covered, as do B2 digest independence and B8 partial status.
- **Manual tools and logs:** the web API's account + Search ID arguments now reach a supported manual Sync branch; imported leads stay untagged. Send Connections accepts account scope. All normal scheduled worker records carry schedule context, and fatal rows retain available console output.
- **Public files:** only the explicit static mount serves files; the SPA fallback cannot expose .env, source, cookie captures, or database files.
- **UI fixes:** deferred router references and an authenticated startup probe fix first load/refresh. Hidden login content stays hidden. Leads/Logs no longer crash when pagination is absent. Campaign identity and quota edits survive account changes and template-tab navigation. Dialogs trap/restore focus, block busy dismissal, and show inline request errors; closing a loading log viewer no longer updates a removed element. Schedule scope dialogs persist campaign/account selections.
- **Browser verification:** all nine pages rendered without page-error fallbacks or page-level overflow at 1280px and 768px. Account limits, campaign create/edit, dashboard range requests, lead date columns, dry-run/log viewer, schedule CRUD/scopes/pause, and settings save passed against an isolated fixture.
- **Local verification:** a backed-up real SQLite database was used with a temporary Uvicorn server. Static files, real admin authentication, DB/dashboard lead counts, scheduler initialization, and a Send Connections dry run/history/log request passed. Scheduled dispatch, live sessions, and every notification channel were blocked. Verification servers were stopped afterward.
- **Contrast:** primary 6.29:1, muted/canvas 4.55:1, success 7.29:1, warning 6.84:1, error 7.60:1, idle 6.92:1. Faint secondary text now uses the readable muted token.

Real outbound delivery was not tested. Expired sessions require local refresh. Use one backend process because job locking/auth sessions remain in memory. Datetime deprecation warnings remain as maintenance work. See `REMAINING_CHANGES_PLAN.md` for the current handoff rather than the historical React plan.

## 11 September 2026 — Replies/Leads filter polish + UI fixes (v6)

- **Replies:** campaign/account multi-select popovers convert to proper dropdown buttons
  (`dd-btn` + checkbox panels with All/None); category, review state, comments and sort
  are native selects. Active-filter count and Clear verified in the browser.
- **Merge Excel outreach history removed from the UI** (`#lXlsx` button and dialog deleted);
  `merge_xlsx_history.py` remains a CLI-only tool.
- **Logs & Run History:** status dropdown no longer offers a nonexistent `skipped` state;
  new **Last 24 hours / 7 days / 30 days** time filter backed by `since_days` on `/api/runs`.
- **Leads:** header nesting bug fixed (columns had doubled/shifted). Added all requested
  filters: company contains, account, reply category, review state, initial-contact /
  last-follow-up / date-added ranges, page sizes 25/50/100, approved server-side sorts
  with direction arrows and `newest` default. Filters apply to CSV export too.
- **Dashboard:** modernized with Today / 7 days / 30 days segmented range control,
  live "Current job" panel and richer stat cards.
- **Verification:** 18 backend tests pass; all JS parses; browser-verified against the
  fixture: leads header/filter/sort roundtrip, threads dropdown label update, category
  save with manual source, comments panel, dashboard range switch, logs time filter.

## 11 September 2026 — Filter system redesign (v8)

Skills applied: ui-ux-pro-max (design-system query: "Trust & Authority" navy/indigo
palette, dashboard font pairing), Ultra Web Design (preserve-mode refinement, truth
labels, inspect-rendered-output loop), ui-website-style (one accent per region,
token discipline), frontend-design (no AI-gradient tells, motion answers actions).

- **New `.filterbar` system** replaces the ragged 4-row toolbar on Leads and Threads:
  one consistent control height (34px), custom-styled selects with SVG chevrons
  (`.filter-select`), matching text inputs (`.filter-input`), and dropdown trigger
  buttons (`.dd-btn`).
- **Active-state tinting:** controls with a value get the indigo subdued background
  (`has-value` / `.active` + `.dd-dot`), so open filters are visible at a glance
  without relying on color alone (labels remain).
- **Removable filter chips** under both bars: each active filter shows as a chip
  (`Stage: Untouched ×`) that removes just that filter; date-range chips clear both
  endpoints. Chips carry `role="list"` and aria-labels.
- **Popover panels** for date ranges (Leads: contact/follow-up/added; Threads: reply
  date) and multi-select campaign/account pickers, with open/close animation that
  respects `prefers-reduced-motion`, `aria-expanded`/`aria-haspopup`, outside-click
  close, and mutually-exclusive open state.
- **Responsive recompose:** at ≤760px the bar becomes an intentional 2-up grid with
  full-width search instead of random wrapping; popovers clamp to the viewport.
- **Global reduced-motion rule** and visible `.th-sort` focus rings added.
- Search inputs gained inline clear (×) buttons.
- Verified in the fixture browser: chip add/remove roundtrips on both pages, popover
  exclusivity, aria-expanded state, 2-up mobile grid, no horizontal page overflow at
  606px; tables scroll inside their cards. 18 backend tests pass.

## 12 September 2026 — Reference-shape UI port
Ported the button/control shape language from the Attendance Workbench
reference project (`D:\My workspace\Tools\Report Generate\biometric_timechamp_report`)
onto the existing indigo Stitch theme — no rebrand, shape + depth only:
- Buttons: 36px tall (36px default), 12px corners, vertical-gradient primary
  that lifts on hover (`translateY(-1px)` + soft indigo shadow) and presses
  on click (`translateY(1px)`); gradient danger variant; ghost → soft-indigo hover
- Inputs/filters: 36px tall, 10px corners (was 32px/6px)
- Segmented controls: pill group on inset track with white active tab + shadow
  (matches the reference nav pills) instead of hard-cornered fill
- Chips: full 999px pills at 28px; bulk bar also pill-shaped
- Cards: 16px corners (was 12px)
- Kept the indigo palette, JetBrains Mono metrics, 40px table rows, sidebar shell
Verified in the browser (gradient primary, pill seg active tab, filter selects
36px/10px, chip add/remove roundtrip) + 18 backend tests pass.

## 12 September 2026 — Dashboard polish + run-log cleanup
- Removed the raw JSON "Stats" block from the run-log modal (it printed
  `{"contacted":0,"leftover":106}` dumps). Console log + Errors remain.
- "Current job" log is now a terminal-style window (traffic-light dots,
  dark console, rounded 10px) docked in a sticky RIGHT rail next to the
  stat cards; stacks below content on narrow screens.
- Dashboard hero strip now styled in style.css directly (the old styles
  lived in presentation.css which is not loaded — hero cards rendered raw).
- Trend-chart legend spaced properly (Invites / InMails / Messages with
  color dots); funnel rows got gradient fill bars.
- Removed link underlines globally (nav items + text links no longer
  underline on hover).
- Login verified end-to-end in the browser: real form → POST /api/login →
  cookie → app shell + dashboard. Note: single-worker uvicorn only — the
  session store is in-process, so multi-worker gunicorn would reject the
  cookie half the time (documented constraint in app/auth.py).

## 12 September 2026 — Multi-user access + Accounts/Settings cleanup

**Users & Access (new)**
- Real multi-user logins: `users` table (PBKDF2-hashed passwords, stdlib only), per-user sessions, roles `admin` / `campaign_manager`. The `.env` admin is seeded on first run and stays authoritative; additional users are created in the UI.
- New **Users & Access** page (admin-only, hidden in nav for managers): create, edit, deactivate, delete users; reset passwords; role descriptions; last-login column.
- Guardrails: cannot delete/demote/deactivate yourself; instance always keeps ≥1 active admin; deactivation or password reset signs the user out everywhere; min 8-char passwords; duplicate usernames rejected.
- **Change password for every user**: sidebar user menu → "Change password…" (current + new + confirm, inline validation, other sessions revoked, current session kept).

**Accounts page**
- Compacted: 34px rows, slimmer quota bars, shorter labels, tighter action buttons.
- Assigned campaigns now render as a **"N campaigns" dropdown** per row — click to see the list instead of a wall of tags.
- Account settings modal: "Assign Campaigns" checkbox wall → **dropdown multi-select** with All/None shortcuts and a live "N campaigns assigned" label; removed the internal "Session reference" field (managed by cookie upload).
- Settings page: removed the "Zero-Storage Credential Policy" banner.

**Verified:** 40 backend tests pass; UI roundtrips in the live preview — user create/delete via UI, manager role sees no Users nav + denied page + 403 API, manager password change via dialog (old password rejected, new works), campaign dropdown open/close, All/None label updates.

### Addendum (same day) — Remove accounts & login users
- New `DELETE /api/accounts/{id}`: removes a LinkedIn account, cascades its campaign links, nulls lead ownership (lead history is kept), and deletes its uploaded cookies file (only if it lives in `cookies_files/`). Blocked with a clear 409 while a job is running for that account.
- Accounts table gains a trash **Remove** action with a confirm dialog spelling out the consequences; success/error toasts included.
- Removing **login users** was already available on **Users & Access** (Edit/Delete per row, self-delete and last-admin protection). Verified again with the UI roundtrip.
- Verified: 40 tests pass; UI roundtrip removed the fixture account (empty state shown) and backend smoke covered 401/404/409/guard/cascade/cookie-cleanup paths.

## 12 September 2026 — Navigation regroup + scoped access + UX pass

**Navigation**
- **Workers** removed from the sidebar; the three workers now live as a compact strip at the top of the Dashboard (icon + name + last-run status pill). Clicking a worker opens a popup with its description, last run, Last-log and Run-now actions. The full Workers page is still reachable from the strip's header link.
- **Manual tools** moved from Workers to **Jobs & Scheduler** as a single inline row (worker type → account → campaign tag → ID → Run). The worker-type select relabels the ID field, and both sync/import accept an optional **campaign dropdown** that tags imported leads to that campaign (backend + jobs updated).
- **Users & Access** moved into the **Settings** page (admin-only section under notifications). The standalone nav item is gone; `#/users` still works as a deep link.

**Users & Access — scoped campaign/account access**
- Admins can restrict each user to specific **campaigns** and **accounts** via dropdown multi-selects in the user editor (All/None shortcuts; empty = full access).
- Enforcement is server-side: restricted users see only their campaigns in `/api/campaigns`, only their accounts in `/api/accounts`, and Leads/Threads are filtered to their scope. Campaign detail and job runs targeting out-of-scope items return 403.

**Campaigns page — modern redesign + delete**
- Hero banner with fleet totals (campaigns / active / leads / reply rate), card grid with per-campaign stat blocks (Leads · Contacted · Replies), account chips, hover elevation, staggered entrance, and an empty state. New **Delete** action per campaign (confirm dialog; leads kept untagged; 409 while a run for that campaign is active).

**Accounts**
- **Dropdown transparency bug fixed** (panels had no background — text bled through rows).
- Edit-account modal is now **compact**: 2-column grid (620px), name+status side-by-side, tighter cookie row, one-line cap note.

**App-wide motion system**
- Staggered card entrance per page view, button lift/press micro-interactions, modal scale-in, stat pop, row/nav/pill transitions — all disabled under `prefers-reduced-motion`.

**Verified:** 40 backend tests pass; live checks — workers strip + popup on Dashboard, manual tools with campaign dropdown + validation on Jobs, Users section embedded in Settings with scoped-editor roundtrip, scoped user saw only 1 campaign/1 account and got 403s out of scope, campaign delete via UI, opaque dropdown panels, compact modal grid.

### Hotfix — startup migration for existing databases
- `init_db()` now adds the `users.allowed_campaign_ids` / `users.allowed_account_ids` columns to databases created before the scoped-access release (`ALTER TABLE ... ADD COLUMN` with `[]` defaults = full access, matching prior behaviour). Existing users, roles and passwords are untouched. Verified by booting the app against a simulated pre-scope schema.

## 12 September 2026 — Popup notifications for success & error

- **Run-completion popups**: the app now tracks the active job via the existing 10s poller; when a run finishes it pops a toast with the outcome — success (green, with a stats summary like "invites sent: 12"), finished-with-errors (amber, error count), failed (red, first error message), or stopped. When the tab is in the background a desktop notification is also shown (permission requested on first "Run now"; click focuses the app). Identity-checked against the run list so stale polls never misreport.
- **Global error safety net**: any failed POST/PUT/DELETE outside a modal now pops a red error toast even if the calling code swallows the exception (modal forms keep their inline error text; the duplicate was fixed instead by a 2s toast dedupe).
- **Background-refresh failures surfaced**: silent `viewX().catch(() => {})` reloads now call `quietToast` — a throttled amber "Refresh failed: …" notice (max 1 per 10s) instead of invisible breakage.
- **Toast upgrades**: tone accent bar, 6s lifeline animation, stronger text colors for success/warn/error; all motion disabled under `prefers-reduced-motion`.
- Verified live: success toast on campaign delete, red toast from the safety net on a failed delete, dedupe (2 identical calls → 1 popup), and success/error run-completion popups with stats and error text.

## 12 September 2026 — Settings/Leads compaction + scope popup

- **System Configuration** redesigned compact: webhook + email recipients now sit **side by side** in a two-column grid (stacks below 860px), trigger categories in a 2-up grid, right-aligned save.
- **"Operational email recipients" got a visible add option**: proper input + **Add** button (Enter still works); chips render above.
- **Campaign/Account access in the user editor** now opens a **searchable popup dialog** (layered above the modal) instead of a clipped inline dropdown — search filter, All/None, live "N of M selected" count, Done commits the selection to the trigger button ("N selected" + active tint). Verified end-to-end: selection persists through save (`allowed_campaign_ids: [1]` on a fresh user).
- **Leads & Prospect Pipeline filter bar compacted**: 30px controls, and the four lower-frequency filters (source, reply state, category, review) moved into a **"More" popover** with a single Apply. Visible bar is now: search · campaigns · accounts · stages · More · Dates · company · page-size. Active state shows a dot on the More button; chips still list every active filter.
- Verified live: More-panel apply roundtrip (category chip appeared, More button tinted, chip removal cleared), email add via button, scope popup search/select/None roundtrip, 40 tests pass.

### Pagination moved to the top
- Leads and Threads pagination now lives **in the page header** (next to Import/Export/Refresh): "Page N of M · total" + compact arrow buttons. The bottom pager rows are gone. Threads keeps the pager hidden when everything fits on one page; on narrow screens the label hides and only the arrows remain. Verified: top pager renders in the header, Next/Prev page roundtrip works, helper renders correct labels.

### Settings — Alerts compact + side-by-side Users (12 Sep 2026)
- Alerts & Notifications compacted: panel-boxes for webhook/email, 1-column trigger grid, tighter paddings.
- Settings page is now a two-column grid at >=1100px: Alerts & Notifications (left) beside Users & Access (right); stacks below.
- Users table scrolls inside its card in the narrower column; no page-level horizontal overflow.

### Leads/Jobs freeze + sort-delay fix (12 Sep 2026)
- Backend: 6 new indexes on leads sort/filter columns (last_followup_at, first_contacted_at, created_at, company, full_name, associate_account_id) — sort clicks were full table scans. `init_db()` creates them idempotently (`CREATE INDEX IF NOT EXISTS`) so existing DBs get them on next start.
- Frontend: request-generation guard — the newest filter/sort/page click always wins; slow older responses are discarded instead of overwriting fresh results (the "stale freeze").
- Selection clicks (row checkboxes, select-all, clear) re-render from cached data with zero refetches.
- In-place refreshing state: table dims + corner spinner during fetch (pointer-events blocked so double-clicks can't stack), fully disabled under prefers-reduced-motion.
- Route changes invalidate in-flight list requests so a slow response can never land on the next page.
- Threads view: same stale-response guard.

### Leads pipeline: activity sort, date-filter TZ fix, strict scope (12 Sep 2026)
- Default sort ("newest") is now ACTIVITY-based: most recent of (last follow-up, status change, first contact, date added) — the pipeline always opens with the lead touched/added last.
- Date filters ("Added/Contacted/Follow-up From/To") now send local-time ISO instants and the backend converts to UTC correctly — "today" in the UI means today on the user's machine, not server-UTC midnight.
- Strict associated-only scope for restricted users: they see ONLY leads linked to their campaigns/accounts (untagged pool leads are hidden), in the table, threads, exports, and delete-preview. Exports now enforce scope (they previously ignored it); single-lead endpoints (timeline, category, review, comments, bulk delete) 404/403 out-of-scope ids without leaking existence.
- Performance: leads page eager-loads campaign+account (removes ~2N lazy queries per page), all popover outside-click handling consolidated into ONE delegated document listener (previously every re-render attached another listener).
- Refreshing watchdog: a hung request can never leave the table pointer-locked (auto-unlock after 15s).

### Date filter correctness + panel layout fix (12 Sep 2026)
- localDayISO double-converted: it produced wall-clock time labelled Z, so on UTC+5:30 "today" started at 00:00Z instead of 18:30Z(prev day) — early-morning local leads were excluded. Now the Date parses locally and toISOString() emits the correct instant.
- Dates popover had the generic 280px popover cap squeezing two date inputs per row (inputs clipped — "date filter not showing properly"). New .dd-dates sizing: 320-360px panel, 118px date inputs, wraps on small screens.

### Dashboard send counts survive campaign deletion + More panel clipping (12 Sep 2026)
- ROOT CAUSE of "sent connections/follow-ups today but dashboard shows 0": DailySendCount rows are keyed by campaign_id with ondelete=CASCADE, so deleting a campaign erased its historical send counts. Dashboard summary + trends now count from the LeadEvent audit trail (immutable, keyed to leads, survives deletion): invites/InMails from send_connections events (split by detail text), follow-ups from send_followups + check_replies events.
- Verified with dedicated smoke: 2 invites / 1 InMail / 3 followups counted, still identical after deleting the campaign.
- "More" filter popover clipped off-screen when its trigger sat near the right edge: new placePanel() flips any popover to right-anchoring when it would overflow the viewport (applied to all four popovers).

### List-import duplicate crash + activity feed descriptions (12 Sep 2026)
- Import-from-list crashed with "UNIQUE constraint failed: leads.sales_nav_id, leads.campaign_id": _upsert_lead deduped on (id, campaign, source) but the UNIQUE index is (id, campaign) — same person arriving via a different source blew up the INSERT. Dedupe is now index-exact (source-agnostic), and job_import_list uses the campaign-aware upsert when a campaign tag is requested (it previously always checked the untagged pair).
- Recent activity feed showed raw "send_connections" for older rows stored without a real description: the activity endpoint now maps bare-job details to human text ("Connection invite sent by Cynthia David"), enriched with the account name when known.

### Duplicate stop logs + Account Run Count tracking
- **Stop log dedupe (root cause):** `🛑 Job stopped by user.` was logged inline at 21 separate
  nested-loop sites in `app/jobs.py` — when a stop unwound through campaign → account → stage
  loops, each level printed it again (3 identical lines per stop). All sites now call
  `_stop_note(run, log)`, which emits the line **once per run** (`run.stop_noted` flag); the
  other sites unwind silently. `runner.stop_job()` is idempotent too: the `[STOP]` live-tail
  marker is appended only on the running→stopping transition and only if absent — repeated
  clicks/polls never duplicate it.
- **Deadlock fix:** `stop_job()` briefly called `publish_log()` while holding the non-reentrant
  `_state_lock` → live lock-up of the status endpoint. Marker append now happens after the
  lock block releases.
- **Lost-send-on-stop fix:** in send_connections / send_followups / check_replies the polite
  sleep sat BETWEEN the LinkedIn send and its commit — a stop during the sleep discarded an
  already-delivered message (never committed, never counted). Sends now commit + count first,
  then pace; a stop during pacing can no longer lose a delivered action.
- **Account run count:** new `accounts.total_runs` column (auto-migration). Counted at the
  exact successful-action commit points — invites, InMails, after-accept messages, follow-up
  stages, import/sync pages — via `complete_account_action(run, account_id, action_id)`,
  idempotent on (execution token, account_id, action_id). Never incremented on job start,
  failure, or stop-before-completion. Published live through the runner so open pages update
  without refresh.
- **Frontend:** Stop buttons (topbar / floating console / worker banner) single-flight with
  "Stopping…" loading state and a 1.5s latch — duplicate clicks send one request. Workers page
  got an "Account run counts" strip and Accounts a "Runs" column, both live-patched by the
  10s poll with a bump animation (disabled under prefers-reduced-motion). `/api/jobs` exposes
  `live.account_runs`; `/api/accounts` merges live totals over stored ones.
- Verified: 20-check smoke (normal completion, stop-after-1, immediate-stop idempotency,
  duplicate stop clicks, duplicate completion events, refresh recovery) + 55/55 suite.

### Premium dark-first redesign (UI pass)
New layer: `static/redesign.css` (+ `static/motion.js` utilities) — token-driven dark theme by default,
light theme preserved behind the new topbar toggle (persisted), zero changes to business logic.
- Dark canvas `#0B0E15` with layered surfaces, indigo/violet primary, teal live accents; soft-glow
  hover borders, glass topbar; legacy hardcoded white surfaces (topbar, account tiles, worker feed,
  activity items, logs filters, floating panel, camp "New Campaign" inline style) all remapped dark.
- Motion: view cross-fades, staggered row entrance (`row-in` + `--i`), badge pop, modal scale+fade
  with backdrop blur, toast slide in/out, count-up stats, running-worker pulse — every animation has
  a `prefers-reduced-motion` fallback.
- Sidebar collapse (persisted) + responsive drawer; modals fit at tablet width; no horizontal overflow.
- Verified: light-leak scan clean on all 7 pages in dark mode, console clean, modals/toasts/sidebar
  live-tested, 55/55 tests pass. Caches: redesign.css?v=3, motion.js?v=2, views.js?v=32.

### GChat: no more "Started" ping + premium completion summary
- Removed the `▶ … / Started` message sent when a job began (`_Run.__init__` in `app/jobs.py`). Notifications now go out **once, on completion** only.
- `notify_lifecycle` now dedupes per run id — the dedicated summary + `_finish` path could double-send; a second call for the same run is a no-op. Stopped runs stay silent.
- `notification_format.py` rewritten: status emoji (✅ ⚠️ 🚫 ⏹), bold header/status, human metric labels (`Invites sent: 12` instead of `invites_sent: 12`), smart durations (`2m 15s`, not `135.0s`), and an indented, deduplicated "— Attention needed —" error block.
- New tests: `tests/test_notify_premium.py` (5 tests: no starter, single summary, fancy format, silent on stopped/dry).

### Leads: "More filters" redesigned as a compact popover
- Removed **Source**, **Reply state**, **Reply category**, **Review state**, **Stage** from the toolbar dialog — the old 5-select modal is gone.
- The remaining controls live in a compact **"More filters" popover** in the toolbar: three date-range rows (Contacted / Added / Follow-up — real `<input type=date>` pairs) and four engagement selects (Stage, Reply state, Category, Review). Apply/Done commit together; Clear all resets.
- Active-filter count badge on the button + grouped range chips ("Contacted: 2026-09-01 → 2026-09-13") with compound removal (clears both bounds).
- Date values convert via local-day ISO (midnight/end-of-day in the user's timezone) into the existing `contact_from/to`, `created_from/to`, `followup_from/to` API params — the previously unused backend date filters are now wired.
- Panel auto-clamps inside the viewport on narrow screens.
- Updated two browser tests that asserted the old modal (`tests/ui_refinement.py`, `tests/browser_audit.py`) for the new popover contract.

**Verification:** 65/65 tests pass; live browser check of popover open/apply/chips/reset/clamp, query-string correctness, console clean.

### Leads toolbar simplification (round 2)
- Fully removed the four dialog filters — **Source, Reply state, Reply category, Review state** — from state, query builder, chips, and UI.
- The "More filters" button is **gone**. The remaining filters are now direct toolbar controls: **Stage** (inline select, filters instantly) and **Dates** (compact popover with the three date ranges + Apply/Done/Clear all).
- Toolbar is now: Search · Campaign · Account · Stage · Dates · page-size.
- Tests updated for the new contract; 65/65 pass.

### Account verification: status shown wrongly after Verify (frontend race + missing persist)

- **Stale repaint race (views.js)** — the Verify button's `finally` re-rendered
  the table without awaiting it, and the 20s account-health poller could paint
  a pre-verify snapshot in between. The row could flip back to "Active"/stale
  health even when verification had just failed (or vice versa). The verify
  handler now blocks all concurrent renderers for the whole request and
  repaints once with fresh data.
- **Success did not persist the session (app/main.py + app/jobs.py)** — if the
  session was resolved via the legacy/filename fallback (`cookies_files/<first>_cookies.json`),
  a successful Verify still left `session_ref` empty, so the row kept showing
  "Session missing" with a disabled Verify button. `load_session_ref(persist=True)`
  now writes the resolved path back and the endpoint commits it.
- Covered by the new `test_verify_persists_fallback_resolved_session`; the
  full suite (83 tests) and the Playwright account-verification browser check
  both pass. Cache bumped to `views.js?v=38`.

### Accounts table: header alignment + compact density

- **Numeric headers now align with their data** — InMail/Invites/Messages/Runs
  are right-aligned in both `th` and `td` (mono numbers sit under their labels),
  quota bars shrunk to fixed 30px tracks so they no longer stretch the columns.
- **Row actions compacted to icon-only ghost buttons** (Settings, Upload
  cookies, Pause/Resume, Verify, Remove — each with tooltip + aria-label).
  Kills the horizontal cutoff of the old labeled buttons.
- **Density**: account cell is a single line (the redundant "session configured"
  subtitle is gone), row height 68px → 48px (`command-center.css` was forcing
  14px vertical cell padding; compact tables now override to 4px).
- Table min-width 1160px → 980px, sticky header while scrolling.
- 83/83 tests pass; caches bumped (`views.js?v=39`, `redesign.css?v=41`).

### Accounts table: tighter columns + labeled Pause/Verify
- Inter-column padding cut from 12px to 7px (14px at the table edges), quota columns narrowed 104px→72px, Runs 56px→44px — min-width 980px→860px so more fits on screen without horizontal scroll.
- Actions cell: **Pause/Resume** and **Verify** are now labeled secondary buttons (icon+text, 28px tall); Settings / Upload / Remove stay compact icon buttons. Verify restore text matches the labeled style.
- Fixtures verified live: labels render, disabled states intact, row height stays 48px, no page overflow. 83/83 tests pass.

### Accounts table: taller, airier rows
- Row padding-block 4px→9px (rows ~58px), header 28px→34px, avatar 22px→28px.
- Body text 12px→12.5px, account names 13px, quota numbers 11px with 5px rounded tracks; Pause/Verify buttons bumped to 32px to match.
- Column spacing from the previous pass is untouched. 83/83 tests pass.

### Accounts page: compact attention banner + full-size table
- "N accounts need attention" banner collapsed to a single 12.5px line (icon + bold count + names inline, ellipsis-overflow with a hover tooltip carrying the full list); View run logs is a small button beside it. ~104px → ~56px on desktop; wraps gracefully under 900px.
- Table scaled up: rows 64px, header 40px, avatars 32px, body text 13px, quota numbers 11.5px with 6px bars, Pause/Verify 34px. Column spacing untouched. 83/83 tests pass.

### Accounts table: no inner scrollbar
- Removed the fixed max-height/inner scroll on the Accounts table wrap — the table renders full height and the page itself scrolls; sticky header disabled there accordingly.

### Workbook merge (standalone script)
`merge_xlsx_history.py` now accepts both pool-sheet names ('Overall Leads' and the newer 'Leads'). Merged "LinkedIn Outreach Automation (2).xlsx": 561 new leads, 1,306 enriched, 6,942 duplicates skipped, 6 replies imported — DB backed up to app_data/app_data.before-xlsx-merge-20260915-092527.db first. Campaigns "GCC-Cynthia"/"GCC-Ranganathan" in the sheet don't exist in the app and were NOT auto-created (by design); create them and re-run the script to attach those leads.

Usage:
  python merge_xlsx_history.py "<file>.xlsx"            # preview (nothing written)
  python merge_xlsx_history.py "<file>.xlsx" --apply    # write

### Workbook merge v2: replies-by-message, Processed-only leads, URL backfill (2026-09-15)
`merge_xlsx_history.py` extended (still standalone, not integrated into the app):
- **Replies detected by message text** — exports often carry a `Reply messages`
  value without the `✅Yes` flag; any non-empty message now counts as a reply.
- **Pass 3: Processed-only leads** — 114 leads existed only in the `Processed`
  sheet and were invisible to the merge. They're now created (29 new, incl. the
  missing Sneha Agarwal podcast reply) or enriched.
- **LinkedIn URL gap-fill** — URLs from the pool/Processed sheets backfill DB
  leads that lack one (never overwrites): 1,173 filled this run.

Applied with backup `app_data.before-reply-merge-20260915-115750.db`.

### Leads UI: profile links + reply modal
- Lead names with a known LinkedIn URL render as links (new-tab, rel noopener,
  hover arrow icon, keyboard focus ring); names without stay plain text.
- The "Replied" pill is now a button: opens a modal with the full reply text,
  campaign/account/category meta, LinkedIn link, and the lead's recent activity
  timeline (`/api/leads/{id}/timeline`). Flag-without-text shows an explanatory
  empty state. 84/84 tests pass.

### Leads Profile column + Threads click-to-profile (v41)
- **Leads table**: new **Profile** column (3rd) renders a compact `↗ Profile` link when the lead has a LinkedIn URL — plain `—` otherwise. 11 columns total, colgroup rebalanced.
- **Threads list**: sender names link to the LinkedIn profile when a URL exists (same `lead-link` style as Leads).
- **Threads detail panel**: the lead name links to the profile, plus an explicit **Profile** button next to the Replied pill.
- Fixture leads carry no URLs so the preview shows the `—` fallback; real merged leads (1,599 with URLs) render the links.

### Leads: name-is-the-link + OpenToMsg check badge (v48)
- **Lead name opens the profile** — the name in the Lead column is the LinkedIn link (hover arrow); redundant Profile column removed (back to 10 columns).
- **OpenToMsg badge** — leads confirmed open-to-message get a green `InMail` badge next to their name; checked-but-closed leads get a grey "Not open"; unchecked leads show nothing.
- **OpenToMsg filter** — new tri-state toolbar select (Open to messages / Not open / Not checked) wired through `/api/leads` (`opentomsg=`) and CSV export.
- **URL backfill on OpenToMsg check** — `send_connections` now fetches the profile URL when a lead's `linkedin_url` is empty even if `opentomsg` was already set (one-time backfill for leads checked before URL capture existed); existing URLs are never overwritten.

### Lead dedupe + CSV round-trip (2026-09-15)

**Root cause of duplicates:** `app/jobs.py` stored the raw `entityUrn`
(`urn:li:fs_salesProfile:(ACwXXX,NAME_SEARCH,zz)`) as `sales_nav_id`, so the
same person existed twice — once as the urn and once as the bare `ACwXXX`
token — and the two rows never matched the `(sales_nav_id, campaign_id)`
unique key. Fixed at the source: `_lead_from_element` now normalizes every ID
to the bare ACw token via `extract_profile_id`.

**`merge_xlsx_history.py --dedupe [--apply]`** (standalone, no xlsx needed):
- Normalizes urn-format snids in place
- Merges twin rows: same normalized snid OR same normalized LinkedIn URL
  (query string stripped). The most-engaged row is kept (replied > deepest
  stage > oldest); reply text, campaign/account assignment, follow-up dates
  and profile fields merge into the keeper; events + comments are re-parented.
  The twin row is deleted BEFORE the keeper takes its campaign (unique-index
  safety — caught by regression test).
- Clears junk URLs ('0', '-', 'n/a'...) so the OpenToMsg backfill can recapture
- Preview mode writes nothing; every run is idempotent

**Real DB result:** 9,218 → 9,119 leads (99 twins removed), 67 junk URLs
cleared, 0 duplicate snid groups, 0 duplicate URL groups. Backup:
`app_data.before-dedupe-20260915-180230.db`.

**CSV import hardening (`/api/leads/import-csv`):** urn snids normalized on
ingest; URL-only rows now dedupe against existing leads by normalized profile
URL (query stripped); snid gap-filled onto URL-matched duplicates.

**CSV export:** already includes the `linkedin_url` column (verified) —
export → import round-trip preserves profile links and re-dedupes on the way
back in.

**Tests:** new `tests/test_dedupe_and_csv.py` (6 tests: urn twin merge,
reply rescue, event/comment re-parenting, junk URL cleanup + URL matching,
preview no-write, CSV import dedupe). Full suite: 90/90 pass.

### Campaign retag from workbook (2026-09-15)

The original merge treated campaigns missing from the app as report-only, so
thousands of imported leads sat "untagged" in the UI even though the workbook's
`Campaigns` column knew their campaign.

**`merge_xlsx_history.py <file.xlsx> --retag [--create-campaigns] [--apply]`**
attaches the sheet's campaign to untagged DB leads (matched by normalized
Sales Nav ID), never re-tags an already-tagged lead, and optionally creates
missing campaigns with the exact sheet name as campaign_key.

**Applied result:** untagged 7,660 → 348 (the 348 have no campaign in the
sheet either); campaign `GCC` created; per-campaign: Sales Outsourcing 2,494,
SCM Podcast 2,479, CXO Podcast 1,068, CXO - Operating Partner 1,048,
Distriops 848, Procurement 588, GCC 246. Backup:
`app_data.before-retag-20260915-181121.db`. 90/90 tests pass.

### Replace mode in merge_xlsx_history.py (xlsx = source of truth)
`--replace` overwrites DB values from the workbook for every lead the sheet
contains: profile fields, LinkedIn URL, OpenToMsg, stages (even downgrades),
replies, and campaign/account tags taken from any sheet row for that person
(pool `Campaigns`/`Associate Account` cells included). Unknown campaign/account
names are auto-created so sheet names always resolve. DB-only leads are never
touched. Also fixed a pre-existing `map_status` prefix bug that flattened every
historical "Sent Invite Follow-up N" row to bare INVITE_SENT/INMAIL_SENT
(longest-prefix matching now; 303 stages restored on apply).
Usage: `python merge_xlsx_history.py <file.xlsx> --replace` (preview) /
`--replace --apply`. Backup used: app_data.before-replace-20260917-135744.db.

### Exact Sales Nav URN storage + raw-script parity (HTTP 500 fix)
New `leads.sales_nav_urn` column stores the exact sheet/inbox identity
('urn:li:fs_salesProfile:(ACw…,NAME_SEARCH,…)'), byte-for-byte from
"LinkedIn Outreach Automation (5).xlsx" (98% of leads now carry it) and from
live campaign sync. Matching still uses the bare token in sales_nav_id, so
dedupe/unique-key behavior is unchanged. Message recipients now mirror the
raw scripts: createMessage/connectV2 calls send the stored URN when present
(bare token fallback) — the raw scripts always sent the full URN from the
sheets, which is the difference most likely causing the app-only
"HTTP 500: {status:500}" follow-up failures. Every send failure now also
prints to the run log ("-> send failed (…), status not updated"), matching
salesApiMessagingThreadsSendMessages.py, instead of only reaching the GChat
error digest. Covered by tests/test_reply_identity.py (URN recipient test).

### Send-error blocking + campaign edit inline + pause/verify-all (2026-09-17)

**Leads blocked on send errors (HTTP 400 "Email is required to connect" etc.)**
- Any lead-level send failure in Send Connections (invite or InMail) or Send Follow-ups now marks the lead
  `BLOCKED_ERROR`, stores the reason in the new `leads.last_error` column (auto-migrated), and writes an error event.
- `BLOCKED_ERROR` leads are excluded automatically: send_connections only picks `status = ''` leads and follow-ups
  match exact stage statuses, so a blocked lead is never retried until you clear it.
- Rate-limit (429) and template-validation failures stay account-level — they do NOT block individual leads.
- Leads page: "Error" pill + reason sub-line on the row; new **Errors: all / with / without** filter (also in the
  CSV export); select rows and hit **Retry selected** to clear the error and re-queue (`POST /api/leads/reset-errors`,
  worker-guarded).
- Every failure still logs to the run console + errors digest as before.

**Campaign editable from the Leads row** — the Campaign column is now a dropdown per lead
(`PUT /api/leads/{id}/assign`); change it inline to re-tag or untag a lead. Failures revert the select.

**Campaigns: Pause/Resume button** on every campaign card (`PUT /api/campaigns/{id}/pause`). Paused campaigns are
skipped by all workers (they already filter `status == 'active'`).

**Campaign editor: Add-account popup** — when every existing account is already assigned, "Add" opens a compact
quick-add modal (name + caps + optional cookies upload); the created account is assigned to the campaign automatically.

**Accounts: Verify All** — one button verifies every configured session sequentially with per-row and button progress
(LinkedIn-safe pacing), then refreshes health state.

Tests: 7 new regressions (blocking, non-blocking 429, reset endpoint, pause endpoint, error filter/API). Full suite: 137 pass.

### Manual block list applied (2026-09-17)

`mark_blocked_leads.py <ids-file> [--apply] [--include-active]` — standalone tool (like the merge script) that reads
Sales Nav URNs (or bare tokens), matches leads by the bare token, and marks them `BLOCKED_ERROR` with
"Email is required to connect". Safety defaults: preview-only until `--apply`, never touches leads that already
have a stage (use `--include-active` to override) or that have replies, idempotent re-runs.

Applied `blocked_ids.txt` (91 URNs from the user's failed-send list; backup `app_data.before-blockmark-*.db`):
**90 marked, 1 protected** (Krishna Reddy Vangapati — invite already sent, status INVITE_SENT). Each lead got a
status_change audit event. They now show in Leads with the Error pill + reason, are excluded from all future runs,
and can be re-queued any time with **Retry selected**.

### URN backfill batch 2 + Remove-error row action + popup always-open (2026-09-17)

- **99 bare IDs** from the user filled with the exact-format URN
  `urn:li:fs_salesProfile:(<id>,NAME_SEARCH,uAs5)` (direct SQL, gap-fill only — existing URNs never overwritten).
- **Leads: per-row "Remove error"** button in the Stage column on every BLOCKED_ERROR lead (same reset endpoint as
  the bulk Retry; toast confirms re-queue).
- **Campaign editor: Add account popup is now the only path** — always opens with a pick-list of free existing
  accounts *and* a create-new form (name + caps + optional cookies); both assign the account to the campaign at the
  next position. The old behaviour (silently adding an inline row when free accounts existed) was why the popup
  appeared "not working".


### GChat single-card dedupe + restricted-user dashboard scoping (2026-09-18)

**1. Warnings/summary no longer triple-posted to GChat.**
Every run completion now sends exactly ONE card - the lifecycle card (status,
duration, per-campaign stats and the "Attention needed" error block, from
`_finish` -> `notify_lifecycle`). The separate "Run summary" and "Execution
warnings" cards sent by `notify_run_summary_and_errors` duplicated it on every
run, so that function is now a documented no-op and its four call sites were
removed. `check_replies` no longer sends a standalone error digest either.
`notify_send_errors` also honors the Settings toggle now (the unchecked
"Send-error digest" box was ignored before). `notify_run_summary` /
`notify_send_errors` remain available for ad-hoc digests but must not be called
on run completion.

**2. Restricted users see only their allocated campaigns/accounts everywhere.**
Prabhu-type users (role `campaign_manager` with campaign/account allocations)
now get scoped numbers on every read API - previously only Leads was scoped:

- `GET /api/dashboard/summary`: lead totals, untagged, replies (all-time/today/
  window), funnel, campaign reply rates, new-leads window, active campaign/
  account counts, budget limits and recent runs are all filtered to the user's
  allocations. Send counts (invites/InMails/follow-ups) join the lead audit
  trail so only the user's own sends count.
- `GET /api/dashboard/activity`: feed shows only events on in-scope leads.
- `GET /api/dashboard/trends`: daily send-volume buckets and 24h run health
  scoped the same way.
- `GET /api/runs` and `GET /api/runs/{id}/log`: history lists only runs touching
  the user's campaigns/accounts plus fleet-wide scheduler runs (NULL ids);
  opening another campaign's run log returns 404.
- `GET /api/jobs`: Workers-strip "last run" info and nav badge counts scoped.

New helper `_run_scope_filter(stmt, campaign_ids, account_ids)` in `app/main.py`
is the single filter for all RunLog scoping. Targeted runs (single campaign or
account) now record that id on their RunLog row (`send_connections`,
`send_followups`, `check_replies`) so history filtering can attribute them;
fleet runs stay NULL and remain visible to everyone (their logs contain no
scoped lead data).

Admins and users without allocations still see the whole fleet - unchanged.

**Tests:** new `test_single_gchat_card_per_run`,
`test_digest_flag_off_blocks_standalone_alerts`,
`test_dashboard_summary_scoped_for_restricted_user`,
`test_runs_and_run_log_scoped_for_restricted_user`. Full suite 139/139.
Restart the server to load the new behavior.


### Dashboard: worker cards with Run now + Account run counts strip (2026-09-18)

The Command Dashboard's Workers section now uses the same compact worker cards
as the Workers page - each card shows the worker name, status pill, last-run
line and primary "Run now" (opens the campaign/account scope dialog) plus
"Last log" buttons. Below them sits the "Account run counts" strip (one chip
per account, live-updating via the existing data-live-runs patching while a
job runs). Both sections are scoped automatically for restricted users.
Static caches bumped (app.js v40, redesign.css v52). Full suite 139/139.


### Campaign-scoped users now see untouched leads (2026-09-18)

Lead access scoping changed from AND to OR: a user allocated to a campaign now
sees **every lead in that campaign - including untouched pool leads that no
account owns yet** - plus any leads owned by their allowed accounts (even in
campaigns outside their list). Previously a lead was visible only if BOTH its
campaign and its owning account were allocated, which hid the untouched pool.

Applied through one shared helper (`_lead_scope_conditions`) at every
lead-scoped query: leads list, CSV export, threads/replies, dashboard counts,
send counters, funnel, campaign rates, activity feed, trends and the jobs
unread badge. Import-CSV matches the same rule. Admins and users without
allocations are unchanged.

**Verified on a copy of the real database:** user prabhu (campaign 8) now sees
1,852 leads (was hiding 307 untouched pool leads); admin still sees 9,119.

**Tests:** `test_scoped_user_sees_untouched_pool_leads_of_their_campaigns`,
`test_scoped_user_account_access_covers_other_campaign_leads`; updated the
CSV-import scope test to OR semantics. Full suite 141/141. Restart the server
to load the new behavior.


## Account stops only after 5 consecutive HTTP 429s (2026-09-18)

A single HTTP 429 no longer stops an account mid-run. One 429 is treated as
transient: the lead is retained for rollover (or keeps its trigger status in
follow-ups) and sending continues. Only **5 consecutive 429s** - no successful
send in between - mark the account rate-limited and stop it for the rest of
the run. Any successful send or non-429 outcome resets the streak counter.

Implemented via a shared `_RateLimitGuard` (`RATE_LIMIT_429_THRESHOLD = 5`)
applied at all four stop sites: send_connections InMail path, send_connections
invite path, check_replies after-acceptance path, and send_followups. Log line
now shows the streak, e.g. `HTTP 429 (2/5) on John Doe - lead retained,
continuing`; the stop line reads `rate-limited (5 consecutive HTTP 429) -
stopping this account`.

**Tests:** updated `test_rate_limit_rolls_all_remaining_leads_to_next_account`
and `test_followup_rate_limit_stops_all_stages` to the threshold semantics;
added `test_single_429_does_not_stop_account`,
`test_non_consecutive_429s_never_stop_account` and
`test_followup_single_429_continues`. Full suite 144/144.


## Blank follow-up templates never send (2026-09-18)

The follow-ups job only checked whether a track slot EXISTED - not whether it
had content. A stage left empty in the campaign editor (e.g. InMail Follow-up 3
when only 2 follow-ups were configured) was sent as an **empty message**.

Now a missing or blank template skips the stage entirely: leads keep their
trigger status and are retried once a template is filled in. Nothing is
blocked or advanced. Applies to invite and InMail follow-up stages, plus the
after-acceptance message in check_replies (blank template = no message sent,
lead stays INVITE_SENT). Run log shows the skip count per stage.

**Tests:** added `test_blank_inmail_followup3_never_sends` and
`test_blank_invite_followup_never_sends`. Full suite 146/146.


## Fixed-name cookies per account (2026-09-18)

Web uploads saved cookies as `<slugified full name>_cookies.json`
(`kimberly_morrison_cookies.json`) while get_cookies.py used its own registry
name (`kimberly_cookies.json`) - accounts accumulated two competing files and
`load_session_ref` had to pick a winner by mtime.

Now every account has exactly ONE canonical cookies file:
`canonical_cookies_path()` prefers the get_cookies.py registry path, falling
back to `./cookies_files/<slugified name>_cookies.json`. The upload endpoint
always writes there regardless of the uploaded filename (returns `saved_as`),
deletes this account's stale differently-named copies inside `cookies_files/`,
and repoints `session_ref`. `load_session_ref` checks the canonical path first.

**Tests:** added `test_upload_cookies_saves_fixed_name_and_cleans_old`.
Full suite 147/147.
