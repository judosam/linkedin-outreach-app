# Campaign Manager — application audit and handoff

Date: 12 September 2026

This audit continues from the project's existing FastAPI, SQLAlchemy, templates and vanilla JavaScript application. It preserves the other AI's campaign/account changes, user management, reply categories, comments, history and schedule configuration. It does not restore the removed React application or require an npm build.

## Delivered

| Area | Finding and resolution |
|---|---|
| Navigation and stuck panels | Removed page-wide pointer blocking during refresh. Route changes clear refresh state and release modal focus/scroll locks. Replacing or closing a modal now cleans up its listeners and restores the app. Late list, page, log and comment responses are checked before updating their original view. |
| Lead filters | Campaign and account selectors are visible in the page toolbar. **More filters** opens compact stage, source, reply state, category and review controls. Date ranges and the separate company filter were removed; company lookup remains available through search. Apply commits the draft; Close discards it. |
| Reply filters | Campaign and account multi-select dropdowns are visible in the page toolbar. Category, review and sort controls are also visible on the page. The More filters dialog, date controls and Comments filter were removed. Internal comments and manual review actions remain available. |
| Selection and deletion | Select-all captures exact matching IDs in one database query, across every page. Later imports cannot silently join that selection. Counts account for exclusions, header checkboxes reflect selection, and deletion uses the same captured IDs as its exact preview. Old and new delete endpoints share access checks, audit recording, and a lock against worker admission. |
| Comments | Authors come from the signed-in user. Editing/deleting checks access to the comment's lead. Repeated Enter submission and repeated Edit clicks are guarded. Replies changing while comments load cannot mix conversation notes. |
| Imports | Visible names are **Import SavedSearch** and **Import SavedList**. Each opens an account + numeric ID dialog with optional campaign tagging and dry-run mode. These remain manual actions; named schedules still apply to the other workers. |
| Extraction progress | Every imported page publishes and persists real counts: page number, page size, cumulative extracted count, new records and available server totals. Percentage is omitted when the server has not supplied a total. Existing engagement history survives re-imports. |
| Live console | A persistent corner button opens a modeless console across navigation. It shows actual backend status, current action, errors, timestamps, elapsed time, extraction measurements and bounded log output. Supports expand, minimize, auto-scroll, Stop Run and clearing the displayed completed output without deleting history. |
| Run Job Now | Opens configuration before execution: Connections, Follow-ups, searchable campaign checkboxes, Select all, Clear selection, summary and optional dry run. The final Run Job button makes one batch request. The backend validates all steps before starting and executes them sequentially under one lock. |
| Cancellation and batch results | Stop requests are tied to a run where applicable. No subsequent guarded LinkedIn request starts after cancellation. Sleeps wake on cancellation; in-flight requests have a timeout. Running, Stopping and Stopped are synchronized in the console, history and log detail. A successful later batch step cannot mask an earlier failure. |
| Session health | SavedList now uses the same account/session guard as the other workers. HTTP 401/403 marks the account as needing reauthentication and records a useful failed-run error. |
| Restricted users | Omitted worker scopes resolve to the user's allowed campaigns/accounts instead of the entire fleet. Schedule defaults persist those restrictions; restricted users cannot edit a global or inaccessible schedule. Comment and deletion preview/count endpoints enforce lead access. |
| Passwords | Startup no longer resets an existing admin's changed password. New bootstrap passwords are hashed; legacy plaintext rows are converted without changing their value. |
| Notifications | Shared, bounded Campaign Manager formatting covers lifecycle events, metrics, warnings, failures and replies. Start and durable completion/stop messages carry status and available context. Dry runs do not deliver notifications. Removed the hardcoded legacy webhook fallback. Clearing the configured webhook now works. Optional SMTP no longer prevents app startup. |
| Counts and classification | Dashboard capacity respects account caps across multiple campaign mappings. Explicit declines take priority over booking phrases during automatic classification. Manual category choices remain authoritative. |
| Visual polish | Added a local Campaign Manager workflow mark for sidebar, login and favicon. Reused the current navy/violet interface, added responsive dialogs, destructive stop styling and restrained motion. Restored the mobile Run Job Now control and missing SVG icons. Dialogs sit above the floating console, and notifications do not cover dialog actions. |

## Main implementation locations

### Compact UI follow-up — 12 September 2026

- Run Job Now uses denser, two-column campaign rows, a bounded scrolling body and a footer that stays visible.
- The live console has a navy/violet status header, terminal styling and compact controls. Removed the duplicate worker-name heading below the header; backend status and live logging remain connected.
- Added restrained entrance, hover and running-status animations with reduced-motion support in `static/compact-polish.css`.
- Validation: browser workflow audit passed with no console or server errors. Layout checks passed at 375, 768 and 1440 pixels, including visible Run Job Now actions with seven campaign rows, no horizontal overflow and no page errors. Checks used an isolated fixture with notifications disabled.

- `app/runner.py`, `app/jobs.py`, `app/linkedin.py`: execution, cancellation and page progress.
- `app/main.py`: API validation, batch admission, live snapshots, selection, access checks and password bootstrap.
- `app/notify.py`, `gchat_notifier.py`, `notification_format.py`: notification lifecycle and shared message formatting.
- `static/app.js`, `static/views.js`, `static/views2.js`: navigation, existing views, filters and selection. Removed superseded lead/reply view implementations and the old dashboard-only live polling implementation.
- `static/workspace.js`, `static/workspace.css`, `static/campaign-manager.svg`: shared dialogs, floating console and branding.
- `templates/index.html`: current asset loading and app shell. The existing `static/command-center.css` remains the base design layer.

## Verification

- **55 backend regression tests**: authentication, password persistence, campaign/account mapping, budgets, schedules, scope enforcement, imports, pagination, real page events, deduplication, missing totals, cancellation between pages, failed sessions, duplicate admission, batch failure propagation, logs, selection, comments and notification formatting.
- **50 page/viewport combinations** across Dashboard, Accounts, Campaigns, Campaign detail, Leads, Replies, Workers, Jobs, Logs and Settings at 375, 768, 1024, 1440 and 1920 pixels. No page errors, document overflow or missing icons in the verified run. Keyboard drawer/modal and reduced-motion checks passed.
- Browser workflow coverage for account caps, campaign create/edit, dry-run workers, log detail, named schedule scope editing/pause/delete and notification settings.
- Dedicated browser checks for draft filters, all-page selection preview, both import dialogs, actual dry-run import endpoints, one-request batch submission, persistent console, page updates, stopping/completed display, minimize/expand, comments and route/modal cleanup.
- Test databases are temporary. Notification delivery is mocked in the test suite. Live-console presentation scenarios use explicit API fixtures; actual multipage worker events are exercised separately by backend tests.
- Screenshots are in `tests/audit/` and `tests/presentation/`. They contain fixture data and are verification artifacts, not production metrics.

## Deployment and remaining limits

1. Restart the Python app and refresh the browser to load backend changes and updated assets. No frontend build is needed. This audit did not restart the production scheduler or migrate outreach records.
2. Real LinkedIn authentication and delivery were not exercised. Missing cookie files and expired sessions still require a valid replacement session through Accounts; software changes cannot renew revoked cookies.
3. Stop is cooperative. An already accepted outreach action is not undone, and the current network request may need to finish or time out before the run becomes Stopped.
4. Use one server process. Batches run sequentially; a separate concurrent job is rejected. Scheduled overlaps retain the existing skipped-run behavior. There is no durable multi-job queue or distributed execution lock.
5. Imports retain the existing 2,500-result ceiling. A full final page at that ceiling records a warning; use a narrower search for additional results. Total-page/percentage displays depend on the response actually including a total.
6. Google Chat formatting was verified with mocked delivery; webhook delivery and SMTP delivery remain environment-dependent. The legacy webhook previously embedded in source should be rotated in Google Chat if it was exposed outside trusted storage.
7. Reply classification is deterministic rule matching, not a guarantee of intent. Manual classifications are preserved. Existing naive-UTC database handling remains; the test suite still reports `datetime.utcnow()` deprecation warnings.

No claim is made that an offline audit can prove every live third-party workflow or every possible production data condition. The tested changes and these boundaries are the basis for this handoff.


## UI refinement — 13 September 2026

- Account tiles on Dashboard and account names on Accounts open an accessible detail dialog with session health, last refresh, daily usage, lifetime runs and assigned campaigns. Account settings remain one click away.
- Campaign counts on Accounts now open a dialog above the table, avoiding row stacking and scroll clipping.
- Inbox exposes campaign/account, category, review and sorting controls. Removed date and Comments filters; retained internal notes.
- Leads retains core pipeline filters and searchable company text while removing separate company/date controls.
- Jobs now shows a scheduler overview, responsive schedule cards with selected weekdays and timing, and compact manual import shortcuts. Existing edit, pause/resume, delete, scope configuration and dispatch behavior are retained.
- Dashboard adds interactive profile styling and staggered metric entrances. New styles use the existing light/dark theme tokens and respect reduced motion.
- Isolated UI checks passed for account detail focus/layering, filter requests, schedule editing/pause/resume/deletion and 24 page/theme/viewport combinations at 375, 768 and 1440 pixels. Screenshots in `tests/ui-refinement/` contain fixture data. No LinkedIn outreach or notifications were sent.
- The shared browser workflow audit also passed: draft filters, all-page selection, internal comments, manual dry-run imports, one-request batch admission and live-console/modal cleanup, with no console or server errors.
- Refresh the browser to load assets version 33. This follow-up changes frontend presentation and controls only.

### Compact Jobs follow-up

Reduced the scheduler overview to a slim status strip, tightened schedule cards and weekday controls, and reduced import spacing. Verified six light/dark layouts at 375, 768 and 1440 pixels with no overflow or browser errors; edit and import dialogs still open. Desktop fixture overview is 93px tall and cards are 261px tall. Assets use version 34 for the updated Jobs markup and theme styles.

### India-only schedule timezone

Schedules now use Asia/Kolkata (IST, UTC+05:30) exclusively. The editor has no timezone field; create/update rejects other timezone values. Existing schedule rows normalize to IST while retaining selected clock times and weekdays, and future triggers are recalculated once. Historical UTC run timestamps remain intact. Jobs formats next/last run dates explicitly in IST even outside India. Verification: 60 backend tests passed, including defaults, rejected zones, local weekday boundaries, legacy migration, idempotence and partial edits; New York/Tokyo browser checks passed for create, scope-dialog return and consistent IST display. Restart the Python app and refresh the browser for backend changes and views asset version 35.

### Denser Jobs layout

Version 36 combines schedule times/weekdays into one row, adds an expandable last-run/timing line, and replaces import cards with a compact action bar. The desktop fixture overview is 41px tall (previously 93px) and schedule cards are 180px (previously 261px). Six light/dark responsive checks passed with no overflow or page errors; keyboard disclosure, edit, both imports and Run Now dialogs were checked. IST remains fixed.

## Verification status and console cleanup — 14 September 2026

- Verification persists missing-seat failures as `seat_required` and expired/forbidden sessions as `needs_reauth`; missing session files are also recorded. Accounts deliberately paused remain paused, including after verification. Transient network errors do not revoke otherwise valid accounts.
- Account rows, dashboard tiles and detail dialogs share health labels. Both Verify buttons refresh the displayed state on failure and success, preserving unsaved settings. A stale settings form cannot reactivate an account marked as needing access; successful verification restores it. Caps-only edits retain the existing status.
- Worker session guards recognize `SALES_SEAT_REQUIRED` separately from other HTTP 401/403 responses and prevent further requests with that session. Workers skip accounts marked as lacking a seat.
- Removed the duplicate red error paragraph beneath the live console. Worker output, completion-with-warnings status and stored run errors remain available.
- Validation: 73 backend tests passed; targeted browser checks passed for failed/successful verification, reload persistence, account labels, modal draft preservation and console cleanup. All checks used isolated fixtures and mocked LinkedIn responses.
- Restart the Python app, refresh the browser for asset version 37, and verify previously affected accounts again to record their current health. Earlier verification failures did not persist a state to migrate.
