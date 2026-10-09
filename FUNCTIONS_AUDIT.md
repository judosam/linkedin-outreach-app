# React function parity audit

Scope: the React frontend, its generated `static/dist/` bundle, tests, and this report. Backend, classic JavaScript/CSS, and templates are preserved. This audit describes the local checkout, not a deployment.

## Implementation

| Classic function or flow | React status | Equivalent and notes |
|---|---|---|
| `viewAccounts`, `accountHealth`, `accountStatusOptions`, `accountDetails` | Existing | `pages/Accounts.tsx`; unchanged this turn. |
| `viewCampaigns`, `viewCampaignDetail`, `copyCampaignDialog` | Existing | `pages/Campaigns.tsx`, `CampaignDetail.tsx`; unchanged. |
| `viewLeads`, `leadQS`, `leadFilterCount`, `leadChips`, `leadSortHead`, `drawLeads`/`drawLeads2`, `pagerHTML` | Repaired | Fixed-width 12-column table; separate sort/filter targets; committed header filters, removable chips, shared toolbar state, page size, honest server/page counts. All columns retained. |
| Lead profile link and detail popup | Repaired | HTTPS LinkedIn URL, then validated ACw/ACo Sales Nav identity fallback; missing/invalid links open details. Explicit details button remains available for linked leads. |
| `retryLeads` / Remove errors | Restored | Selected IDs sent to `/api/leads/reset-errors`; server restores prior stages and returns actual reset/skipped counts. |
| CSV import (`#lImport`) | Restored | Native file picker, multipart `file`, optional `campaign_id` query parameter, server result/errors. See API limitation below. |
| Bulk delete safeguards | Restored | Freeze selected IDs, fetch `/delete-preview`, show campaign/count/comment/event impact, then `/bulk-delete-v2`. Run logs are retained; server enforces worker guard. |
| `leadSel.allMatching` | Deferred, optional | Selection is explicitly limited to this page and cleared when filters, sorting, or pagination change. No misleading all-matching action. Existing list `total` supplies authoritative server-filtered counts. |
| `viewThreads`, `threadDetailHTML`, `loadThreadComments` | Existing | `pages/Threads.tsx`; unchanged. |
| `runWorkerDialog` | Repaired | `RunScope` + `RunJobDialog`: campaign/account radios, mapped accounts only, unavailable statuses, preview, empty-scope guard, pruning, and clean reopen defaults. |
| `viewLogs` / `renderLogs` | Equivalent | Dashboard Worker runs and Jobs history + `RunLogModal`. No separate Logs tab or route added. |
| `viewWorkers`, `viewWorkerStrip`, `workerStripHTML`, `wireWorkerStrip` | Existing | `WorkersPanel` in Dashboard; worker start opens shared console. |
| `viewJobs`, `scheduleEditor` | Existing | Jobs and `SchedulesCard` in Settings. |
| `viewSettings`, `viewUsers`, `userEditor`, access-scope popup | Existing | Settings and Users; permissions continue to be enforced by unchanged APIs. |
| `filtersDialog` | Equivalent | Worker scope controls and `MoreFilters`/header filters; one filter state per Leads view. |
| `batchDialog` | Repaired | Campaign scope, Connections/Follow-ups switches, read-only mapped accounts. Always sends explicit nonempty campaign IDs; never sends account IDs. |
| `importDialog` | Repaired | Saved Search/List imports retain separate mandatory import and optional outreach accounts; fields reset on reopen; successful start opens its console without navigation. |
| `ensureFloatingConsole`, `openFloatingConsole`, `selectConsoleExecution` | Restored | One `LiveConsoleProvider` owns the modal, open state, and selected execution across all routes. Header triggers on Dashboard/Jobs, global chip, mobile terminal button. |
| `pollFloatingConsole` | Existing polling retained | Console polls every 1.5s active, 8s idle, 6s after errors. SSE was optional and unnecessary in fixture verification. |
| `minimizeFloatingConsole` | Deliberate equivalent | Close/reopen via the persistent console triggers; no minimized duplicate window. |
| `resetJobConsole` | Repaired | Clear completed output; reopening resets the clear filter/stopping state. New runs with no persisted run ID still display output. |
| `showStartedJob` | Restored | Worker, batch, and import success open the exact returned execution, retain warning toasts, refresh callers, and request notification permission when enabled. |
| `desktopNotify`, `requestNotifyPermission` | Restored | `lib/notify.ts`; permission requested only from user actions, notifications only for hidden tabs, shared `occ-run` tag, click focuses app. |
| `notifyRunFinished`, `showRunCompletedDetails`, `runSummaryText` | Restored | Provider watches individual executions, deduplicates run IDs, queues visible-tab completion summaries, links full logs, and sends hidden-tab notifications. Settings preference gates both surfaces. |
| `openDashboardHistory` | Deferred, optional | Run history remains reachable from Dashboard and Jobs; automatic `?history=1` scrolling is not implemented. |
| `campaignStats`, `reassignLeadsDialog`, `renderUserActivityCompact`, `viewUserActivity` | Existing | Dashboard, Leads bulk Reassign, Users. Reassignment dialog now also resets on reopen. |
| `pill`, `statusPill`, `fmtDT`, `fmtD`, `ago`, `initials`, `avatarColor`, `quotaBar`, `runStatus`, `errText` | Existing | `lib/{format,constants,api}.ts` and shared UI primitives; untouched leads no longer claim “Not open.” |
| `apiGet`, `apiSend`, `toast`, `openModal`, `closeModal`, `passwordDialog`, `route` | Existing | API/toast/auth helpers, Modal, AppShell, React router. Existing native dialogs retain focus management and Escape. |
| `patchLiveRuns`, `pollNav`, `setBadge`, `startPolling` | Existing + extended | `lib/jobs.tsx` remains unchanged; console provider separately watches completion and counts live executions. |
| `activityFeedHTML`, `workerFeedHTML`, `refreshDashboardFeed`, `statCard`, `runTable`, `fmtDur`, `runResultText`, `openRunLog`, `refresh` | Existing | Dashboard, shared run modals, format/hooks/jobs modules. |
| Dry run (`#wDry`) | Intentionally absent | Not restored to the web UI. |
| Sales Nav licence actions | Existing | No live enterprise operation was attempted; route checks stub provider access. |

## Deliberate differences and actual API limits

- Successful starts open the console in place. They do **not** redirect to Dashboard.
- No standalone `#/logs` route is added; the classic build had already redirected Logs into Dashboard history.
- Location is client-side and explicitly marked **This page only**. The server-side follow-up would add location/title parameters to `list_leads` and corresponding `ilike` predicates to `_lead_filters`; no backend changes were made here.
- OpenToMsg is also **This page only**: although `list_leads` declares its parameter, it does not forward it into `_lead_filters`. The UI filters the returned `opentomsg` values and displays the page count separately from the server total. Export is explicitly labelled “server matches” when either page-only filter is active.
- The actual CSV endpoint accepts `file` and an optional **query** `campaign_id`. It accepts no `outreach_account_id`. The CSV dialog explains that imported leads start unassigned and can be reassigned afterward. Saved Search/List imports retain their separate optional outreach account.
- `/api/leads/count` counts an explicit ID list, not arbitrary filters. The table uses the list response's `total`; no incompatible count body is sent.
- Batch account scope is unsupported by the current API. Its preview is read-only and its payload contains only worker switches plus campaign IDs.
- Single-select categorical header filters match the API's scalar fields. “All values” clears that filter. The shared component also supports multi-select lists for future callers.
- The existing design tokens and other page layouts are preserved; no frontend dependency was added. A temporary formatter was used outside the project manifest.

## Verification

Baseline before edits: **341 passed, 1 failed**. The failure was an obsolete test expecting classic assets at `/`. That test now verifies versioned, uncached React assets at `/` **and** all previous classic assets at `/legacy`; none of its cache assertions were removed.

Browser checks in `tests/check_react_{leads,scope_run,console,notifications,routes}_ui.py` cover the changed flows. The previous mapped-run/import check entry points now invoke React checks rather than timing out against retired selectors. The shared harness intercepts every worker start, batch request, live-log poll, provider request, and UI mutation. It fails closed on unexpected mutations. No live outreach or licence change is used for verification.

Screenshots: `tests/command-center/`. Desktop Leads has no horizontal overflow at 1440×900 and rows are at most 48px; all 12 headers fit. Nine routes are checked at 1440px and 598px in both themes. Classic `/legacy` and its floating console are also checked.

Final build, regression results, and protected-file verification are recorded in `tests/command-center/verification.json`. Work is uncommitted and not deployed.
