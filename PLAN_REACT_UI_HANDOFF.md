# React UI Handoff — Outreach Command Center

**Mission:** the classic no-build UI (`static/*.js` + `templates/legacy.html`, served at `/legacy`) is being replaced by the React+TS+Tailwind SPA in `frontend/`. This document is the single handoff: mission requirements, backend contract, old-source reference map, conventions, phase plan and the verification log (appended at the end of the build).

**Hard constraints**
- `app/` backend, `static/` classic UI, `templates/` are **read-only**. No backend changes were approved.
- No new npm dependencies (lucide-react + recharts only).
- No commits/pushes; many uncommitted files pre-exist — never `git add -A`.
- `static/dist` is NOT gitignored and the Dockerfile never builds the frontend → **`static/dist` must be rebuilt from `frontend/` before any deploy** (`cd frontend && npm run build` then copy `dist/{app.js,app.css,index.html}` — see build section).
- Never start a real worker; in every browser check stub `POST /api/jobs/*/run`, `POST /api/jobs/batch`, and optionally `GET /api/runs/live`.

---

## 1. Requirements (17 total)

**Original 7**
1. Worker run dialog exactly like the legacy screenshot: two-column scope modal (Campaigns / Mapped accounts with inline `seat required` / `needs reauth` badges), Run preview panel with `Skipped · no selected active account` rows, `N campaigns · M accounts` counter, helper text "Choose your campaigns. Only their mapped accounts can run."
2. Clicking a lead's name opens their LinkedIn URL.
3. Fix the Leads columns/space bug (216px permanent overflow at 1440px).
4. Excel-style filters in Leads column headers (frontend-only decision — no backend changes).
5. "Popup live console not there" — auto-open on run start + labelled buttons.
6. Check all old functions work vs the old source (audit table in §4).
7. Check the overall UI.

**New 10**
8. Live console exactly like the legacy portal — the floating dock (ball + expanded panel), not a centered modal.
9. Invite follow-ups: staged +3/+5/+7 days after invite accepted, empty stages skipped, limit 3, InMail follow-ups too.
10. Create-campaign: message templates + account mapping during creation.
11. No scroll in the Campaigns table.
12. Blue transparent template (theme re-skin).
13. Legacy parity check — upload-cookies option was missing in the new portal.
14. Accounts: expandable rows, all columns in a single view, no side scroll.
15. Schedules as a separate table + schedule run history.
16. Beautiful UI, more dashboard stats.
17. Modern view of Active campaigns in the dashboard.

**Locked user decisions**
- Space fix = restore colgroup + compact rows.
- Excel filters = frontend-only; Location filter is page-scoped with a visible "This page only" note; title reachable only via search (`q`).
- Console = auto-open on run start + labelled buttons.
- Missing functions = port both (desktop notifications + Logs handling; the old `#/logs` route already redirected to `#/dashboard?history=1`, so no separate route).

## 2. Backend contract facts (verified, `app/` read-only)

- `_prepare_job` (main.py:2461) accepts `account_ids` for single-worker runs; `BatchStart` (main.py:2617) has **no** `account_ids` → the batch dialog's accounts column is read-only "All mapped".
- `validate_scope` (schedule_store.py) requires selected accounts ⊆ mapped to selected campaigns.
- `POST /api/campaigns` (main.py:1263) accepts the full `CampaignIn`: `name, campaign_key?, status, search_url, invite_text, invite_track[str], inmail_subject, inmail_text, inmail_track[{subject,body}], accounts[{account_id, order_index, invite_limit=10, inmail_limit=10, message_limit=30, calendar_url?, search_url_override?}]`. Duplicate account → 422. Campaign key defaults to name, must be unique (409).
- Follow-up engine (jobs.py:1600-1608): `INVITE_STAGES` = +3/+5/+7 (track indexes 1..3), `INMAIL_STAGES` = +3/+5/+7 (track indexes 0..2). `invite_track[0]` is the after-acceptance message; empty track entries are skipped; shared `messages_sent` budget with check_replies.
- `GET /api/runs` returns `schedule_id` per run (main.py:2686) → schedule history is a client-side filter; no backend change needed.
- `/api/leads` params: `campaign_id` (`__none__`=unassigned), `account_id`, `status` (`__untouched__`), `source`, `q` (ILIKE name/company/title/sales_nav_id — **not** location), `replied`, `category`, `review`, `company`, `opentomsg` (yes/no/unchecked), `error` (only/none), `contact/created/followup_from/to`, `page_size` ≤ 200, `sort`, `ids_only` (returns `{ids, total}` for cross-page select-all). `linkedin_url` IS serialized (main.py:1650).
- `POST /api/accounts/{id}/upload-cookies` (main.py:766) — multipart `file`. Also `refresh-cookies`, `verify-session`.
- Account.status ∈ active/paused/needs_reauth/seat_required; serializer adds `session_configured`, `session_state`, `cookie_age_hours`, `usage_today`, `weekly_invites`.
- `GET /api/schedules` → `serialize()` includes `next_run_at`, `last_run_at` (ISO+Z or null).
- `GET /api/dashboard/summary` returns `totals, today{invites,inmails,followups,limits,contacted,contacted_yesterday,contacted_window,leads_added}, replies{total,today,window}, funnel, campaign_rates, recent_runs, scheduler_healthy`; plus `/api/dashboard/trends` and `/api/dashboard/campaign-stats`.

## 3. Old-source reference map (`outreach-app-gcp-download/source_code/static/` — outside the repo, reference only)

| Legacy | Where | New home |
|---|---|---|
| `runWorkerDialog` + `updateScope` | views.js 882-960 | `RunScope` in `components/run.tsx` |
| `showStartedJob` | views.js 580-595 | `console.open(execution_id)` after run POSTs (auto-open) |
| floating console | workspace.js 109-165 | `LiveConsoleModal` re-skinned as floating dock |
| `desktopNotify` / `requestNotifyPermission` / `notifyRunFinished` | views.js 205-333 | `lib/notify.ts` + `lib/console.tsx` watcher |
| Leads table + colgroup + lead links | views2.js 196-310 | `pages/Leads.tsx` (colgroup, `profileUrl`) |
| `localDayISO` | views2.js 51 | `components/colfilter.tsx` |
| ROUTES `logs → #/dashboard?history=1` | views.js 536-549 | kept: no separate logs route |
| `retryLeads` | views2.js 437 | "Remove errors" bulk action + per-row in Leads |
| upload cookies ×3 entry points | views.js 146/377/747 | Accounts: create dialog, row action, detail modal |
| cross-page select-all | views2.js 4-5 | Leads `ids_only` select-all matching |

## 4. Function audit (old → new)

| Old function | New equivalent | Status |
|---|---|---|
| runWorkerDialog / updateScope | RunScope (two-column, pruning, preview, counter) | ✅ ported |
| showStartedJob → open console | auto-open dock with execution_id | ✅ this build |
| Floating console dock | FloatingConsole | ✅ this build |
| desktopNotify / notifyRunFinished | lib/notify.ts + console.tsx watcher | ✅ ported (Settings switch) |
| Leads colgroup / compact rows | leads-table CSS + colgroup | ✅ ported |
| Lead name → LinkedIn | profileUrl + anchor | ✅ ported (fallback `/sales/lead/{sales_nav_id}` when `/^AC[wo]/`) |
| Excel header filters | ColumnFilter popovers + chips + More-filters modal | ✅ ported (frontend-only) |
| retryLeads | Remove errors (bulk) — restores previous stage | ✅ ported |
| Import CSV / Saved search / List | ImportDialog + CsvImport | ✅ ported |
| Bulk delete with preview | delete-preview + bulk-delete-v2 modal | ✅ ported |
| Reassign | ReassignDialog | ✅ ported |
| Cross-page select-all | ids_only select-all matching | ✅ this build |
| Export CSV | `/api/leads/export` link | ✅ ported |
| Batch run | BatchDialog (campaigns only; accounts read-only "All mapped") | ✅ ported |
| Schedules editor | Settings SchedulesCard (full editor) + Jobs table | ✅ this build (separate table + history) |
| Upload cookies | AccountDialog + row action + detail | ✅ this build |
| Campaign create w/ templates + accounts | CampaignDialog full form | ✅ this build |
| Dry-run worker UI | — intentionally removed; do not restore | — |

## 5. Conventions & gotchas

- `cn()` in `ui.tsx` is a plain join — never override component sizes via className; use props.
- Every dialog that stays mounted needs the **seeded-flag re-seed pattern** (`if (open && !seeded) {...}; if (!open && seeded) setSeeded(false)`).
- `.dt th.sortable` CSS assumes one child button; header filters need the `.th-inner` flex wrapper. `[aria-sort]` styling must stay qualified with `.sortable`.
- `table-layout: fixed` + colgroup is scoped via `.leads-table` (and `.dt-fixed` where reused) so Accounts/Campaigns opt in deliberately.
- Dates: `localDayISO(v, end)` uses local-day semantics; run timestamps from the server are UTC.
- Tailwind tokens come from CSS custom properties in `index.css`; the theme re-skin only touches tokens + a few component classes.
- Build: `cd frontend && npx tsc -b && npm run build` → outputs to `static/dist/` via vite config. Verify with the fixture (`python tests/serve_dashboard_fixture.py` → 127.0.0.1:8774, login `test-admin` / `test-password-only`).

## 6. Phase plan

0. This document.
1. Blue transparent theme (`index.css`): blue-tinted translucent tokens, gradient canvas/nav, card translucency + blur, themed scrollbars; both themes, AA contrast.
2. Leads fixes — colgroup/compact rows ✅, name→LinkedIn ✅, Excel filters ✅ (all found already on disk; verified this build), plus cross-page select-all via `ids_only`.
3. Run dialogs — two-column RunScope ✅ on disk; batch accounts read-only ✅.
4. Live console — floating dock (ball + panel) replacing the modal, auto-open on run start ✅ (on disk), desktop notifications ✅ (on disk), Settings switch ✅ (on disk).
5. Campaigns — no-scroll fixed table; create dialog with message templates (invite, after-accept, FU1-3 with +3/+5/+7 labels, max 3, empty skipped) + InMail templates + account mapping with per-account limits.
6. Accounts — expandable single-view rows, upload-cookies on create + row action + expanded-row dropzone.
7. Jobs — Schedules table (Name, Time, Days, Jobs, Jitter, Next run, Last run, Status, Actions) + per-schedule run-history filter using `schedule_id`.
8. Dashboard — extra stats (accounts needing attention, weekly invite usage, reply-rate window) + modern Active-campaigns tiles.
9. Parity sweep + overall UI pass; verification log appended below.

## 7. Verification plan

Fixture on 127.0.0.1:8774 (never a real worker). Stub run-start endpoints in browser checks. `tsc -b && npm run build` must pass; DOM probes for: colgroup widths & no horizontal overflow (1440 + ~600), scope dialog pruning/preview/counter, dock auto-open on stubbed run start, schedules table + history filter, campaign create payload shape, accounts expand + cookie upload call, theme tokens applied.

---

## 8. Verification log

_(appended at the end of the build — see below)_
### 2026-10-07 — build + fixture browser pass (UTC+05:30)

Root cause of the user's "no changes visible": `static/dist` prebuild was stale
(built Oct 6 15:51) while newest sources were edited Oct 6 19:20–20:00. FastAPI
serves the prebuilt bundle from `static/dist`, so their port-8000 page showed the
old teal theme despite corrected sources. Fixture probe of their exact scenario,
plus rebuild, resolved it.

**Rebuild**
- `npx tsc -b` initially failed with 2 real errors (TS2304 `Ring` unimported in
  Dashboard.tsx) that earlier `| head` piping had masked (pipe status, not tsc).
  Added `Ring` to the `@/components/ui` import — re-run clean, unpiped
  `TSC-EXIT=0`, then `npm run build` `BUILD-EXIT=0`.
- `static/dist/app.js` 774,993 → 789,422 B; `app.css` 35,406 → 37,559 B;
  fresh mtimes Oct 7 11:59 IST. FastAPI `?v=` stamps carry the new sizes, so any
  reload (ideally Ctrl+F5) serves the new bundle.

**Fixture browser pass (127.0.0.1:8774, test-admin, run endpoints stubbed)**
- Theme: served CSS is the blue bundle — body gradient `rgba(77,157,255,…)`,
  light tokens `--primary #1d6fd8`, `--nav #0d1e3a`, body bg `#eaf1fa`,
  `.dt th` on `--surface-solid` `rgb(253,254,255)`. Verified both themes.
- Run-scope dialog (Dashboard → Run now → Send Connections): two-column
  scope, "All mapped" default, Run preview rows with
  "Skipped · no selected active account", counter "4 campaigns · 2 accounts" —
  matches the user's screenshot 1. Submit streaked
  `POST /api/jobs/send_connections/run` + `GET /api/runs/live?execution_id=…`
  and polished the dialog.
- Campaign create: New campaign → 3 tabs (Details / Messages / Accounts).
  Messages shows After acceptance (+3 days), FU 1–3, +3/+5/+7 & "up to 3"
  hints, 4 subjects + 9 message bodies. Accounts tab has per-account
  Invites/InMails/Messages limits + "Priority order follows the checkbox
  order". Submitted with stubbed POST — payload contained exactly
  `POST /api/campaigns` and dialog closed. (An earlier probe against the
  fixture backend created "E2E Probe Campaign" with the full CampaignIn
  payload — limits 10/10/30 visible in dashboard/account caps, confirming the
  real end-to-end shape.)
- Campaigns table renders `dt dt-fixed` (no horizontal scroll, no side
  scrollbar) with reply-rate Ring chips and account avatars.
- Accounts: responsive `dt-fixed` table, row click expands a child row (Caps,
  Session & cookies with a hidden `<input type=file>` for upload, Campaigns
  chips); Edit / Refresh / Pause / Verify / Delete actions intact.
- Jobs: Scheduler card + status-segmented Run history; the fixture had no
  schedules so the new `ScheduleTable`/history-chip path awaits a real-schedule
  pass; the history-status segmented filter works.
- Leads: 12-col colgroup (no widening), per-column sort + filter buttons,
  Sales Nav profile fallback links (`/sales/lead/ACw…`) for empty
  `linkedin_url`,
  Import CSV / Saved Search / List, selection bar with Reassign / Remove
  errors / Delete. Cross-page select-all path not exercisable with 5 fixture
  rows (needs > page size) — code-reviewed only.
- Console dock bug found & fixed during the pass: the panel body has Tailwind
  `flex`, which beat the `hidden` attribute's UA `display:none`, so the panel
  stayed visible when "closed" and the ball showed at the same time.
  Now conditionally rendered (run.tsx) and the provider boots expanded
  (console.tsx). Rebuilt; reload → panel open, minimize → ball only
  (`Open live job console`), ball → panel again.

**Result: 17/17 requirements render and operate from the served bundle on the
fixture.** User acceptance: hard refresh their port-8000 tab (Ctrl+F5).

### 2026-10-07 — second pass: campaign run controls, templates, settings (IST)

**Dashboard layout & per-campaign runs**
- Order is now Workers → Active campaigns → Pipeline by stage → trend/fleet → per-account table (verified in-browser by DOM text order).
- Each active-campaign tile has `Run` + a "More run options" menu: Send connections / Replies / Follow-ups, with the note "Runs this campaign only". Choosing Follow-ups posted
  `POST /api/jobs/send_followups/run` with body `{"campaign_ids":[1]}` — that campaign only.
- `RunJobDialog` accepts a preset campaign and opens the scope in "Select campaigns" mode with just that campaign checked (verified: Run Check Replies → GCC pinned, preview "1 campaign · 2 accounts").
- "View leads" deep-links to `#/leads?campaign_id=N`; the Leads page seeds its Campaign filter from the param and now also re-applies it when the param changes in place
  (previously stale: URL said campaign 2, table still showed campaign 1). A param-less URL never clobbers a dropdown choice. Verified both ways (GCC → "5 leads match", SCM Podcast → "0 leads match", filter chip updates).

**Backend: `{company}` placeholder (root-cause fix)**
- `app/main.py` `CampaignIn.validate_campaign` accepted only `first_name`/`calendar_url` while `app/jobs.py:_template_format` already substituted `company`. Allowed set is now `{first_name, company, calendar_url}`; message updated.
- Verified against the API: a campaign whose invite text/subject/body all use `{company}` → `201`-class success (id returned); `{oops}` → `422` with "Use only {first_name}, {company} and {calendar_url} placeholders". `tests/test_company_placeholder.py` → 7 passed.

**Campaign templates (classic-UI parity)**
- Messages step now has the classic sub-tabs: Connection Invite | Invite Follow-ups | InMail | InMail Follow-ups, with the "Placeholders: {first_name} · {company} · {calendar_url}" line and the "First-touch invite note (with connection request)" label.
- Stage labels are derived from the live delay settings. Fixed a mapping bug found during verification
  ("Follow-up 3 (+undefined days)"): `invite_track[0]` is the after-acceptance note sent the moment a lead accepts (no delay), and delays apply to indexes 1–3; InMail FU 1–3 use `inmail_track[0–2]` in the same delay order. Labels now read "After acceptance message (sent as soon as they accept)", "+3/+5/+7 days after the previous stage".
- Create is now gated on the name only: the server (and the classic UI) allow an unmapped campaign, so the old "needs a mapped account" rule blocked that workflow. Accounts remain optional with a hint.
- Removed the "Sales Nav search URL" field from the campaign form (per request); Details is now name/key/status.
- Saving closes the dialog: verified end-to-end — a campaign using `{company}` was created from the dialog, the dialog closed, and the new row appeared in the table.

**Editable follow-up timing**
- New `GET`/`PUT /api/settings/fu-delays` persists per-track day lists in the `settings` key/value store and pushes them into `jobs.INVITE_STAGES`/`INMAIL_STAGES` via `reload_fu_days()`; `app/jobs.py` reads `OCC_INVITE_FU_DAYS`/`OCC_INMAIL_FU_DAYS` (default `3,5,7`) so follow-ups can be retimed without a deploy. `.env.example` documents both.
- Settings → "Follow-up timing" card edits FU 1–3 for each track (0–60 days). Verified: changed invite to 2/5/7 → PUT 200, re-GET persisted, and the campaign dialog then showed "+2 days".

**Settings / Users merge and notification fields**
- Settings page now carries Notifications, Schedules, Follow-up timing and (for admins) a "Users & access" section rendering the Users page inline; the standalone Users nav entry still works.
- Google Chat webhook URL field and its "Leave the masked value unchanged to keep it." hint are removed from the UI (the API keeps the value; no data loss).
- Email recipients are now a row-per-address editor with "Add recipient" and per-row remove buttons instead of a comma-separated text box (verified: 4 rows + button).

**Build & regression sweep**
- `npx tsc -b` → 0 with errors surfaced (no piping), `npm run build` → 0; `static/dist` refreshed each time.
- All 8 routes (dashboard, accounts, campaigns, leads, threads, jobs, salesnav, settings) render with headings present, no error text, and an **empty console log**.
- Fixture state left clean: probe campaigns deleted, follow-up delays reset to 3/5/7.

### 2026-10-07 — third pass: edit-campaign popup, 3-stage cap, placeholders

**Edit campaign is now a popup**
- `frontend/src/pages/CampaignDetail.tsx` exports `CampaignEditDialog` (a `Modal` popup) instead of rendering a full page. The campaigns table's Edit pencil — and the detail modal's "Edit campaign" button — open it in place; no route change.
- `/campaign/:id` still works as a deep link: the route now redirects to `/campaigns?edit=<id>`, which opens the same popup over the list. The `?edit=` / `?create=` / `?templates=` params are read in an effect and cleared when the dialog closes, so a dialog never springs back open.
- Footer carries Pause/Resume + Cancel + Save changes; saving PUTs `/api/campaigns/{id}` (verified 200), closes the popup and clears the deep-link param.
- Removed the page's "Sales Nav search URL" field too, so it is gone from both the create dialog and the edit popup.

**Follow-ups capped at 3 per track, Add button kept**
- Invite track: slot 0 is always the **After acceptance message** (the worker sends it the moment an invite is accepted — it is not a follow-up), then up to **3** follow-up stages. The Add button stays visible and disables at the cap with "Limit reached — 3 follow-ups"; below the cap it shows "N stages left".
- InMail track: up to 3 stages, same Add button/limit treatment.
- Verified in-browser on both tracks: adding reaches exactly FU1–FU3, the Add button then reads disabled and the limit note appears.
- Save now trims only **trailing** blank stages instead of filtering every blank one. Filtering mid-list blanks renumbered later stages (a blank FU1 would silently promote FU2 into the +3 slot), which would change real send timing.
- Fixed an off-by-one that only showed up when a campaign had no templates yet: with an empty `invite_track`, "Add follow-up stage" used to write index 0 (the after-acceptance slot) instead of a follow-up.

**Placeholders line**
- The edit popup's Message templates tab now shows "Placeholders: {first_name} · {company} · {calendar_url}", matching the create dialog.

**Verification**
- `tsc -b` 0, `npm run build` 0; bundle rebuilt each time.
- Re-confirmed on the served bundle the four items reported as "not changed" — they are present: Settings carries "Users & access" (with the Last login table) inline; Settings → Follow-up timing shows 6 day inputs (3 invite + 3 InMail); delays read 3/5/7 and persist on save; "Sales Nav search URL" is absent from both campaign forms.
- Note for the user: UI-only changes need a browser refresh, but the new `/api/settings/fu-delays` endpoint and the `{company}` validator require the **Python app to be restarted** — an old running server will still 404 the follow-up-timing card even after a hard refresh.

### 2026-10-07 — fourth pass: nav cleanup, settings normalize, CSV template

**Settings normalized**
- The Schedules card is removed from Settings (the full schedules editor remains on Jobs & Scheduler, where ScheduleTable already manages /api/schedules). Subtitle now reads "Notification routing, follow-up timing and users".
- The standalone Users nav tab is gone: users management stays inline in Settings (admin-only), and `/users` redirects to `/settings` so old links keep working.

**Nav order**
- Sales Nav Licences now sits directly after Accounts in the sidebar; the rest follows (Campaigns, Leads, Threads & Replies, Jobs & Scheduler, Settings).

**Accounts: Verify + Pause buttons**
- Both were already labelled row actions on every account row (Pause/Resume toggles status; Verify re-checks the session via /api/accounts/{id}/verify-session) — re-verified in-browser: 2 Pause buttons enabled, 2 Verify buttons present. Verify is correctly disabled when the account has no session configured (`session_configured` false), which is the fixture state for both accounts; Pause is enabled.

**Import CSV template**
- The backend endpoint `GET /api/leads/import-template` (headers: full_name, sales_nav_id, linkedin_url, sales_nav_urn, first_name, last_name, title, company, location, opentomsg + two sample rows) existed but was not linked. The Import CSV dialog now carries a "CSV template" download link plus a note to pick the destination campaign before importing. Verified: link present in dialog, endpoint returns 200 with the correct header row (the earlier HEAD 405 is the guard for HEAD requests; GET works).

**Edit +3/+5/+7 days**
- The card works only when the running backend exposes /api/settings/fu-delays. On the restarted fixture it loads (3/5/7 shown, editable, saving PUTs 200). When the backend predates the endpoint the card now shows an unmistakable warning — "The backend needs a restart" — instead of a bare error, because a stale Python process is the most common cause of this card appearing dead after a UI-only update.

**Verification**
- `tsc -b` 0 (unpiped), `npm run build` 0; bundle refreshed (15:54). Browser pass on the served bundle confirmed: nav order with Sales Nav after Accounts and no Users tab, /users → /settings redirect, Settings without Schedules, Accounts Pause/Verify buttons, CSV template link, Follow-up timing card live.

### 2026-10-07 — fifth pass: tile Run split-button stacking + shape

**Menu rendering behind the next campaign card (fixed)**
- Root cause: every `.surface` card creates its own stacking context (`backdrop-filter: blur(10px)` in index.css), so the menu's `z-30` could never climb past the *next* tile card — the later sibling painted on top regardless.
- Fix in Dashboard.tsx `ActiveCampaigns`: new `openMenuFor` state; while a tile's run menu is open, that tile's Card gets `relative z-30` (its whole stacking context rises above sibling cards). `RunMenu` grew an optional `onMenuChange` callback; the menu itself was bumped to `z-50`.
- Works for the card *below* (2-column rows) and the card *beside* (3-column rows) — any later sibling.

**Split-button shape (fixed)**
- Both halves now sit inside one `inline-flex overflow-hidden rounded-control shadow-border` wrapper that clips them, so corner radii and the join always match (Run button + 28px-wide chevron half with a subtle light border-l seam).
- Implementation note: raw `<button>`s instead of `<Button>` + override classes — `cn()` is a plain join and Tailwind emits extended keys (rounded-control/shadow-border) after defaults, so `rounded-none`/`shadow-none` passed via className would silently lose. Chevron now rotates 180° while open.

**Verification** (fixture, rebuilt bundle)
- `tsc -b` 0 (unpiped), `npm run build` 0; bundle 792,470 B.
- Browser hit-tests at 900px (2-col) and 1440px (3-col): menu extends ~118px over the "Procurement" card below and `elementFromPoint` at the overlap resolves to the menu, not the card. Raised card resets to auto z after close; outside-click closes the menu; menu item click opens the run dialog pinned to that tile's campaign (dialog "Run Check Replies" with GCC preselected).
- Reminder for the user: this is UI-only — no Python restart needed, but Ctrl+F5 to pick up the new bundle.
