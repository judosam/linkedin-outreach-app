> Latest implementation and verification: [Campaign Manager audit, 12 September 2026](AUDIT_AND_HANDOFF.md). This supersedes earlier implementation/status notes below.

# Outreach Command Center — product interface

## Product truth and preservation
Internal operations app for managing LinkedIn accounts, campaigns, leads, replies, workers and schedules. All metrics come from the API. Preserve all nine routes, campaign detail, login, IDs/form contracts, selection/delete safeguards, comments, filters, Excel tools and live logs. No marketing claims, customer proof, artificial statistics or public landing page. Authentication surface uses noindex metadata.

## Direction
Refined operations workspace: navy rail, deep teal actions, pale neutral canvas and white content. The dashboard's three-column activity ledger is the signature; restrained borders, compact SVG icons and generous reading space provide continuity elsewhere. No decorative gradients, glass panels or entrance animations. Keep existing Geist and JetBrains Mono fonts to avoid additional downloads.

UI/UX Pro Max supplied dashboard density, typography hierarchy and accessibility guidance; its sales/hero templates were rejected as inappropriate to an authenticated tool. Ultra Web Design provides preservation and rendered QA gates. JetBrains style guidance contributes consistent semantic tokens and page structure; its React stack and sketch treatment are not applicable. Frontend Design contributes deliberate hierarchy and disciplined spacing. Stitch's dark navigation / light content split is retained.

## Tokens
Primary #146A62; hover #10544E; primary tint #E8F3F0. Navigation #12252D, secondary #243C44. Canvas #F4F6F7; surface #FFFFFF; inset #F0F4F5. Text #172B33; secondary #3D535D; muted #586C76; borders #DCE4E7. Green/amber/red retain semantic status meaning; muted blue is a chart series only.

Body 14px/1.55 Geist; headings 24–30px/1.2; labels 12–13px; mono for actual numeric data. Spacing 4/8/12/16/24/32/48. Controls 8px radius; panels 12px; status capsules full radius. Controls 40px desktop, 44px touch. Shadows limited to dialogs/popovers and small surface separation.

## Surface briefs
- Dashboard: evaluate activity, capacity and current execution, then inspect logs or open Workers. Real activity ledger, four capacity metrics, trend/funnel, live terminal and history.
- Accounts/Campaigns/Leads/Logs: title/action, filters, count/selection feedback, scroll-contained table. Preserve every data column and action.
- Replies: filters, conversation list and focused detail; stack on narrow displays. Comments/category controls stay functional.
- Workers/Jobs: clear worker controls and schedule configuration, distinguish manual import tools.
- Settings: readable notification form, accurate session-storage explanation.
- Login: real product identity and concise description; no fabricated proof.

## Responsive and states
1440/1920: 248px rail, content max-width 1600. 1024/768: drawer navigation and two-column metrics. 375: search remains available; actions wrap; one-column forms, stacked conversation detail, two-column compact metrics; table scrolling remains inside its container. Keyboard-visible focus, focus-trapped dialogs, aria-current navigation, reduced motion, loading labels and genuine empty/error states.

## Implementation boundary
Preserve the FastAPI backend, its REST contract and all outreach behavior.

The interface is migrating to a React + TypeScript + Tailwind SPA (`frontend/`,
built by Vite into `static/dist/`), served from `templates/index.html`. The
classic no-build interface remains reachable at `/legacy` until every view is
ported; both apps share the same API and auth session. No backend migration is
required for this visual pass. Test using the isolated fixture, never real
outbound sends.Design-system rules for the React surface: semantic tokens in `src/index.css`
(single source of truth for light and dark), Tailwind utilities mapped onto
those tokens, concentric radii (outer = inner + padding), layered transparent
shadows in place of decorative borders, `:focus-visible` rings, tabular figures
on every changing number, native `<dialog>` for modals, 0.96 press feedback, and
transitions that name exact properties rather than `all`. Motion is limited to
functional state changes.

Shared dense-listing primitives live in `src/index.css` and `src/components/ui.tsx`
so Accounts, Campaigns, Leads and Sales Nav do not each reinvent them:

- `.dt` / `.dt-wrap` — sticky-header compact table with tabular numerics, one-line
  `.sub` secondary text and horizontal scrolling inside its container.
- `SortHeader` — a sortable column header. The whole cell is the hit target and
  `aria-sort` sits on the `<th>`. Only an actual `ascending`/`descending` state is
  tinted; a bare `[aria-sort]` selector must not be used, because every other
  header carries `aria-sort="none"`.
- `.chip` — micro status capsule for the outreach channel a lead is on. Tone is
  carried by `data-tone` and always paired with a label and icon.
- `Ring` — radial ratio for a dense cell where a bar would be too wide; the value
  is printed inside the ring, never colour-only.
- `Avatar` — initials identity, shared with the sidebar.
- `IconButton` takes a `size` prop rather than a size `className`: `cn()` is a
  plain join, so a passed-in `h-7 w-7` would silently lose to the base size.

Licence actions are status-driven: a Sales Nav activation link only exists while
the invitation is outstanding, so its control is rendered for `INVITED` and
hidden otherwise.
