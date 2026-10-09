# CSV import and workflow audit — approved fixes implemented

Original audit: 15 September 2026

Updated: 17 September 2026. The user approved all eight fixes. All are implemented locally. The deployed Cloud Run website still runs the earlier code; deployment is blocked by expired Google Cloud authentication.

## Changes requested directly and implemented

- **Upload CSV** selects a file and shows its name/size. It does not add leads.
- **Import leads** is a separate button, disabled until a file is selected. You can choose the campaign after selecting the file.
- Import runs only on that second click. Controls prevent duplicate clicks, failed imports retain the file, and the result shows added/skipped counts and returned row errors.
- OpenToMsg logging now includes campaign, account, lead number/name, the profile-check start, the saved result, and cached results. Existing failure output remains available.
- All eight business-rule fixes below are implemented. Original reference scripts remain unchanged by this pass.

## Approved findings and implemented fixes

These eight findings now have passing offline regressions in `tests/test_audit_fixes.py`; no expected-failure markers remain.

| ID | Priority | Confirmed problem and evidence | Implemented fix |
| --- | --- | --- | --- |
| B1 | High | Importing two different URL-only leads into one campaign returns HTTP 500. Both receive an empty Sales Nav ID, which collides with the unique `(sales_nav_id, campaign_id)` index. CSV instructions currently make the ID optional. | Make uniqueness apply to populated Sales Nav IDs, retain URL-based duplicate detection, and allow multiple leads without IDs. Validate eligibility before attempting outreach to a lead without an actionable ID. Review the index migration on a database copy before applying it. |
| B2 | Medium | CSV accepts an `opentomsg` column in its documented backend contract but discards its value. A row with `true` is stored as unchecked. | Parse supported true/false/unknown values, preserve them on new rows, and fill only missing values on duplicates. Return a row error for invalid values. |
| B3 | High | A campaign manager restricted to campaign 1 can import into campaign 2 by changing `campaign_id` in the request; the endpoint returns HTTP 200. | Enforce the user's campaign scope in CSV import, including the existing policy for the untagged pool. Reject unauthorized imports before any write. |
| B4 | High | Run Connections can send to a lead with `received_replies=True` when its outreach status is empty. The reproduction supplies a reply saying “Please stop” and observes an invitation attempt. | Exclude replied leads from the initial connections query, as the follow-up and reply-check workers already do. Add a regression for imported/reassigned replied leads. |
| B5 | High | The original connection script stops after 200 new OpenToMsg checks per campaign/account pass. The web worker has no equivalent limit: the fixture makes 201 profile calls. | Restore a limit of 200 profile-fetch attempts per campaign/account pass, log that the limit was reached, and retain all remaining leads for later processing. Count URL-backfill fetches too. |
| B6 | Medium | An OpenToMsg profile failure appears in the text log, but the run is marked successful with an empty error list. A mocked HTTP 500 reproduces this. | Append the failure to the run's errors with lead/account/campaign context, so the outcome becomes “Completed with warnings” and remains visible in history. Keep the lead eligible for retry. |
| B7 | Medium | Stopping manual SavedSearch during its page delay references `log` before that variable is assigned. The run records an `UnboundLocalError` instead of a clean stopped outcome. | Use `run.log` in this branch and preserve the successfully imported first page when stopping. |
| B8 | Medium | After an HTTP 429 during connections, only the current lead is carried to the next account. Unvisited leads disappear from this run's remaining list. With three leads, the second account receives only one. Database rows are not deleted. | Preserve the current lead and every unvisited lead exactly once before leaving the rate-limited account. Report the correct remaining count. |

The partial unique-index migration was rehearsed twice on a database copy, then applied to the local database with a backup. All 9,119 local lead rows were unchanged. Cloud startup will apply the same migration after deployment; the local database must not replace the cloud database.

## Comparison with the five original scripts

| Reference | Web implementation | What was checked |
| --- | --- | --- |
| `salesApiLeadSearch.py` | `app/linkedin.py:search_leads`, `app/jobs.py:job_sync_leads` | SavedSearch endpoint, 25-row pagination, 2,500-result boundary, extracted fields, campaign tagging, stop handling. B7 fixed the manual branch. |
| `salesApiSavedSearch.py` | `app/linkedin.py:people_search_by_list`, `app/jobs.py:job_import_list` | Despite the legacy filename, this is the saved-list workflow: list-pivot query, numeric List ID, pagination and untagged/campaign import behavior. |
| `salesApiConnection.py` | `app/jobs.py:job_send_connections` | OpenToMsg lookup/cache, InMail versus invitation choice, quotas, account rollover and response handling. B4–B6 and B8 are fixed. |
| `salesApiMessagingThreadsCheckingReplies.py` | `app/jobs.py:job_check_replies` | Campaign/account ownership, invitation acceptance detection, reply-author checks, shared message counter and zero-activity Google Chat suppression. |
| `salesApiMessagingThreadsSendMessages.py` | `app/jobs.py:job_send_followups` | Invite/InMail tracks, 3/5/7-day stage intervals, reply exclusion, shared budget, success-only state updates and rate-limit stop behavior. |

The app intentionally uses database records instead of Google Sheets. Manual account + Search ID/List ID imports remain manual-only. Named schedules and the fixed India timezone remain as requested. Browser cookie capture is not automatically launched by web jobs. The old scripts are references, not an instruction to restore their known side effects or failed-send counting.

## Historical audit verification (before approval)

- Existing suite: 90 tests passed after using `-s` to avoid an existing stdout-capture issue.
- New targeted audit run: 2 logging tests passed; all 8 bug reproductions failed in the expected way.
- Pre-approval combined run: **92 passed, 8 expected failures** in 54.18 seconds. B1–B8 were pending approval at that time; all eight now pass. Historical evidence: `tests/audit-final-results.txt`.
- Browser fixture: selecting a CSV left the database at its original one lead; clicking Import added exactly two leads to the selected campaign. The result displayed “2 added · 0 skipped”; repeated import was disabled until another file was selected.
- JavaScript syntax and Python compilation passed for the modified files.
- All outreach and notification calls in test workers were mocked. No original script was run against LinkedIn or Google Sheets. No live campaigns were started, and the production database was not changed by these tests.
- This is code review and isolated workflow verification, not proof that every live LinkedIn session or external service currently works.

Additional tooling observation, now fixed: `merge_xlsx_history.py:30` replaces `sys.stdout` when imported. The ordinary pytest capture run failed; `pytest -s` completed. Stdout setup now runs only in the script entry point; normal captured pytest runs pass.

Andrew session follow-up: the earlier read-only check of the saved Andrew session returned HTTP 403 with `SALES_SEAT_REQUIRED`; the local cookie file was dated 13 August. This establishes rejection of that saved session, not the current subscription state in Andrew's browser. Resolving that discrepancy requires a fresh Andrew session and verification, rather than forcing the status to Active.

## Completion checks — 17 September 2026

- Full isolated suite: **112 passed**, no expected failures, in 171.03 seconds.
- After adding accurate HTTP 400 classification: **26 targeted regressions passed** in 35.22 seconds, including the four new response-classification cases.
- Python compilation and JavaScript syntax checks passed.
- No real outreach, profile probes, Google Chat messages, or emails were sent by these checks.
- Local database migration backup: `app_data/app_data.before-approved-fixes-20260917-131624.db`. All 9,119 lead rows matched exactly before/after; populated Sales Nav IDs remain unique within a campaign.
- Added stop handling during the OpenToMsg delay, so pressing Stop cannot proceed to the pending outbound send.

## Today's deployed run #60

Inspected the authenticated deployed website and its read-only run/lead APIs at `https://outreach-app-7zc5l7znlq-uc.a.run.app`.

- Started 17 September at 13:01 IST (07:31 UTC); stopped by user after 3m 52s.
- Three invitations were recorded as successful: Phil Damiano / Andrew Dreger, Vince Buffa / Anne Davis, Jim Dovey / Cynthia David.
- Tom Dailey's campaign lead (6643) has three error events at 07:31:12, 07:31:47, and 07:32:28 UTC: `Invite failed: HTTP 400: {"value":"-1"}`. His stage remains untouched, with no owner. This response does not identify why LinkedIn rejected him or establish an email requirement.
- The repeated name represents failed attempts rolling over through the campaign's ordered accounts. It is not three recorded successful invitations. Existing account rollover behavior is preserved.
- The deployed statuses for Ranganathan, Nandhini and Cindy are `seat_required`; the old worker incorrectly calls every unavailable account “paused.” A saved-session rejection is not proof of the owner's subscription status.
- CXO Podcast finished with 3 contacted and 643 remaining; the stopped run did not reach later campaigns. The three other campaign pools were skipped because their accounts were unavailable.
- The deployed database has 18,048 leads, while this local copy has 9,119. Do not upload the local database as a replacement or enable a database-reset deployment.

## Logging corrections implemented locally

- Show the actual skip reason: user pause, session refresh required, or saved-session Sales Navigator access required.
- Label outbound attempts separately from confirmed success; include account, campaign, lead, and rejection details for failed sends.
- Add failures to run warnings instead of silently reporting clean success. Stopped runs retain their stopped status.
- Describe remaining leads as retained for a future run, without falsely claiming every account exhausted its budget.
- Generic HTTP 400 responses remain generic rejections; only explicit email-required responses receive that explanation.

## Deployment handoff

Code is ready locally. Google Cloud CLI read-only inspection failed because its authentication expired (`Reauthentication failed; cannot prompt during non-interactive execution`). No deployment was attempted and no cloud data/settings were changed.

Before deployment, renew Google Cloud authentication, inspect the current service configuration/revision, preserve the cloud database and existing cookie source, and ensure no outreach job is running. Deploy the updated application code without replacing the cloud database or using `FORCE_RESET_DB=1`. Verify the loaded application and migration with read-only checks; do not launch outreach as a deployment test.
