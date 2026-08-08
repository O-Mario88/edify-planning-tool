# Edify mobile UI/UX reference audit

**Date:** 8 August 2026

**Scope:** Entire routed product, all 11 product roles, mobile viewport validation at 390 × 844 px
**Reference designs:** the supplied productivity/mission UI, task-and-calendar UI, and metric-dashboard UI

## Executive conclusion

Edify has a strong responsive foundation, but it is not yet consistently **mobile-first**. Most pages avoid viewport overflow and preserve permissions, actions, data, themes, and accessibility mechanics. The main gap is information architecture: desktop page order is frequently collapsed into one long column, so filters, export controls, KPI strips, and secondary analytics appear before the work a mobile user came to do.

The target should not be a literal visual copy of the references. Edify should adopt their three strongest architectural ideas:

1. **Task-first mobile home** from reference 2: today, next task, calendar strip, project/queue summary, one prominent create action.
2. **Insight-first dashboard** from reference 3: one headline metric or decision, compact 2 × 2 supporting metrics, one trend, one recommendation, progressive disclosure for detail.
3. **Motivational identity layer** from reference 1: role mission, progress, streak/readiness, and branded imagery used selectively on login, onboarding, empty, success, and milestone states—not throughout operational workflows.

The most important redesign rule is the product's own principle: **action first; data justifies the action**. On mobile, the first useful action should normally appear within the first viewport, and the primary work list should begin before roughly 700 px.

## Implementation outcome

The five-phase mobile programme described in this report was implemented on 8 August 2026.

- **Phase 1 — foundation:** reusable role-home, agenda, record, filter-sheet, section-picker and sticky-action patterns; compact 2 × 2 KPI behavior; simplified phone utilities; privacy-safe interaction measurements.
- **Phase 2 — primary role homes:** CCEO, Program Lead, Internal Auditor, Accountant and Partner Field Officer now open on the next role-valid action and queue rather than a metric wall.
- **Phase 3 — remaining role homes:** Admin, Country Director, RVP, HR, Project Coordinator and Partner Admin now use the same task-first anatomy with role-scoped actions.
- **Phase 4 — core workflows:** planning, My Plan, calendar, to-do, directories, finance and verification use compact filter disclosures, prioritized records, touch-safe controls and sticky decisions where the workflow permits them.
- **Phase 5 — long-tail families:** analytics, performance, knowledge/documents, settings/admin, uploads, audit/history and closure share explicit mobile-family contracts, including compact summaries and stacked record tables.

Live 390 × 844 px validation covered every role home and representative pages from every workflow family. The final browser pass found no page-level horizontal overflow; interactive analytics controls measured at least 44 px high. Desktop validation confirmed that mobile role homes and disclosure summaries remain hidden while full filter controls remain available. The automated regression pack contains 118 passing mobile-foundation, micro-interaction and design-system contracts, and all 520 Django templates compile.

The page matrix remains useful as the detailed information-architecture specification for each route. Lower-frequency detail screens inherit the shared shell and family behavior; they should still receive scenario-specific usability testing with real production-sized records before being considered individually optimized.

### Exhaustive micro-UX completion

A final control-level pass followed the five page-architecture phases so that small, repeated interactions did not remain desktop-sized or semantically incomplete.

- Every authenticated page inherits one shell-level micro-UX contract; this does not depend on a page opting into a mobile family.
- Every rendered data table is classified at runtime. Tables with up to five straightforward columns become labeled record cards; dense, spanned, or explicitly matrix-style tables remain real tables inside keyboard-focusable, named horizontal scroll regions. Generated captions and `scope` attributes preserve table meaning.
- Empty table rows with one `colspan` cell are treated as empty states rather than incorrectly forcing a simple table into matrix mode.
- Table selection checkboxes receive a derived record name and a 44 × 44 px label target. The staff directory also carries these labels in source HTML for progressive enhancement.
- All workspace buttons and links have at least a 44 px mobile target. Text actions that previously measured 18–41 px now receive the same touch contract as visible buttons.
- Text, date, select and textarea controls compute to a real 16 px on mobile and at least 44 px high. Adjacent visible labels without explicit `for` attributes are associated safely at runtime; unresolved controls remain exposed through the browser audit marker instead of being silently ignored.
- Page tabs scroll when necessary, remain 44 px high, and implement Left/Right/Home/End keyboard movement.
- The shared pager is named and 44 px at source. The staff pager now exposes previous/next relationships, named page links and `aria-current` on the current page.
- All full-screen overlays found in the template inventory are explicit named dialogs. The ten previously unmarked overlays were corrected. Custom dialogs receive focus entry, focus containment, inert background content, and focus restoration; native and already-managed drawers keep their existing behavior.
- Central polite and assertive live regions announce asynchronous failures. Existing request handling continues to provide action-specific pending labels, `aria-busy`, duplicate-submit prevention and delayed route progress.
- Focus-visible, invalid, disabled, forced-colour and reduced-motion states are centralized rather than being dependent on individual templates.

Live 390 × 844 px evidence covered simple table cards, an 11-column access matrix, staff selection and pagination, calendar tab keys, the create-user dialog, the targets form dialog, and all ten roles with seeded users. Across those ten role dashboards the final pass recorded zero horizontal page overflow, zero visible accessible-name warnings, zero workspace targets below 44 px, and zero unenhanced tables. Partner Admin has no seeded user in the local dataset; it shares the partner portal contract exercised by Partner Field Officer and remains covered by source-level contracts, but was not represented as a separate authenticated browser persona.

## Audit coverage and method

The authoritative platform inventory reports:

- 499 routed surfaces across 901 total routes
- 325 full-page route entries
- 84 partials, 74 drawers, and 16 exports
- 145 distinct full-page visual templates
- 304 shared component templates
- 11 roles, 70 permission keys, and 489 permission-gated surfaces
- 463 routed surfaces referenced by automated tests

The audit combined route and permission inspection, sidebar/mobile-navigation generation for every role, template analysis, component/CSS review, and live rendering of representative pages at 390 × 844 px. The companion [page matrix](MOBILE_UI_UX_PAGE_MATRIX_2026-08-08.md) covers every one of the 145 full-page templates. Drawers and partials are addressed through their parent page archetype because they are not independent navigation destinations.

### Live mobile evidence

| Representative page | Mobile content height | First substantive work appears | Main gap |
|---|---:|---:|---|
| Main/Admin dashboard | 7,103 px | Today's priorities at 3,638 px | overview and KPI content bury the operating queue |
| Planning | 2,643 px | planning copilot at 1,805 px | four filters and summary content precede the planner |
| My Plan | 3,231 px | school visits at 1,686 px | weekly work is below export and summary layers |
| Schools | 4,292 px | school records around 2,165 px | actions and filters dominate the first two screens |
| Clusters | 2,878 px | cluster records around 2,070 px | directory content is buried by controls and summaries |
| Analytics | 8,047 px | first performance section around 2,188 px | header actions, ten filters, and section tabs precede insight |
| Accountant dashboard | 3,964 px | weekly queue around 1,290 px | six full-width KPI tiles precede finance work |
| IA dashboard | 7,329 px | verification queue around 1,366 px | a large workload strip precedes the action queue |
| Projects | 6,525 px | project list around 2,234 px | portfolio delivery is buried by top-level controls/summary |
| Field debrief | 3,507 px | action centre around 2,484 px | reporting analytics precede follow-up work |
| Partner Today | 1,057 px | today's activities around 553 px | closest existing Edify model to the target architecture |

All sampled pages had zero page-level horizontal overflow. This confirms that the core issue is prioritization and density, not basic responsive containment.

## What is already working

- Role-aware bottom navigation uses four primary destinations plus **More**, a sound mobile pattern.
- Safe-area handling and large touch targets are already present.
- Desktop tables often convert to cards or remain inside bounded scrollers.
- Dark, blue, and light themes are supported.
- Permissions and data scoping are deeply role-aware and should remain authoritative.
- Shared page headers, KPI components, cards, drawers, and tokens provide a viable migration path.
- `/partner/today` already demonstrates a concise, task-first landing experience.
- Verification and workflow screens already have strong domain state; they mainly need better mobile composition.

## App-wide gaps

### 1. Responsive containment is being mistaken for mobile information architecture

Many pages are technically responsive because grids collapse to one column. The resulting page is still a desktop dashboard, only taller. The global phone rule in `static/css/consistency.css` forces several KPI families into one column and gives every tile a 7.5 rem minimum height. Six metrics can therefore consume about 780 px before the user sees a queue or task.

**Proposal:** use compact 2 × 2 metric tiles, a horizontally paged metric strip, or one hero metric plus two mini-metrics. Only make a metric full width when it contains a chart, recommendation, or decisive status.

### 2. Filters appear before value

Schools, clusters, planning, analytics, accounts, and several oversight pages make users traverse filters before seeing records or insight.

**Proposal:** show one search field and at most three high-value chips inline. Move all other filters to a bottom sheet. Show an active-filter count and removable chips after application.

### 3. Secondary actions compete with the primary task

Export, download, customize, upload, and reporting controls frequently occupy the hero. These are valuable but usually not the most frequent phone action.

**Proposal:** allow one primary hero action and move secondary actions into an overflow menu. Exports should normally live in the overflow or at the end of the page.

### 4. Horizontal section navigation hides the product map

Analytics and IA section bars are much wider than the phone viewport. Users see only the first items and may not discover later sections.

**Proposal:** replace broad section bars with a page-level selector or a compact segmented control containing no more than three options. Put the complete section list in **More sections** or a sheet.

### 5. Operational and analytical modes are mixed

Several role dashboards combine queues, approvals, trends, rankings, tables, and long-range oversight on one page.

**Proposal:** every role home should answer three questions in this order:

1. What needs me now?
2. What is happening today or this week?
3. Is performance moving in the right direction?

Long-range analytics should be one tap away, not appended to the home page.

### 6. The shell consumes too much phone attention

Search, Messages, Notifications, Theme, Account, page header, page actions, and bottom navigation can all appear together.

**Proposal:** use a compact mobile app bar with page title, notifications, and account. Put global search behind a search icon or contextual search field. Move theme controls into account/settings. Keep messages in bottom navigation for roles where it is a top-four task.

### 7. Empty and zero states still occupy full dashboard space

Full-sized KPI tiles containing zero convey little value and push real work down.

**Proposal:** collapse zero-value groups into a single positive status card such as “No requests awaiting approval” with a short explanation. Preserve individual zero metrics in drill-down analytics.

### 8. Visual identity is functional but not memorable

The supplied references use confident typography, constrained color, clear progress visualization, and a strong sense of purpose. Edify is more utilitarian and visually repetitive.

**Proposal:** keep Edify's real-world, mission-led identity. Use one strong accent family, purposeful status color, clearer type scale, and subtle education/field imagery only where it improves emotion or orientation. Avoid anime imagery, glass effects on dense work screens, or decorative charts without decisions.

## Target mobile page architecture

The 145 page templates can be standardized into 12 mobile archetypes.

| Code | Archetype | Mobile composition | Primary reference |
|---|---|---|---|
| H | Role home | greeting/date → next action → 2 × 2 status → today agenda → attention → one trend | task/calendar UI |
| Q | Work queue | title/count → search → status segments → prioritized record cards → batch actions after selection | task/calendar UI |
| C | Calendar | week strip → selected-day agenda → add action → month view on demand | task/calendar UI |
| D | Directory | search → key chips → compact records/map toggle → filter sheet | task/calendar UI |
| R | Record detail | identity/status → key facts → sticky next action → tabs → timeline | task + metric UI |
| P | Planner/workflow | next-step card → compact stepper → period cards → sticky schedule/create action | task/calendar UI |
| A | Analytics | decision headline → hero metric/trend → 2 × 2 metrics → recommendation → drill-down | metric UI |
| F | Finance | actionable amount/stage → queue → sticky approve/return → audit detail | metric + task UI |
| V | Verification/evidence | evidence preview → match summary → checklist → sticky verify/return | task UI |
| U | Upload/import | upload → validate → review → commit stepper; errors first | task UI |
| K | Knowledge/document | search/categories or reader → contents sheet → acknowledge action | restrained mission UI |
| S | Settings/admin | status summary → grouped settings/list → search/filter → guarded dangerous actions | metric + task UI |

### Shared component changes

1. Add `mobile_role_home`, `mobile_action_card`, `mobile_metric_grid`, `mobile_agenda`, `mobile_record_card`, `mobile_filter_sheet`, `mobile_section_picker`, `mobile_sticky_action_bar`, and `mobile_empty_state` components.
2. Replace the global one-column KPI phone rule with component-owned responsive variants.
3. Add `density="compact|standard|insight"` to KPI/card components.
4. Standardize phone spacing: 16 px page gutters, 12–16 px card padding, 12 px section gaps, 24–32 px major section gaps.
5. Use 16–20 px section titles and reserve larger display type for one home-page mission or headline insight.
6. Keep minimum 44 × 44 px interaction targets while making the visual body compact.
7. Make the bottom action bar contextual and above the existing safe-area navigation.

## Role-by-role redesign proposal

### 1. Admin — Platform Operations

**Current mobile navigation:** Dashboard, Support, Health, Messages, with the full programme, finance, verification, quality, platform-ops, administration, people, talent, performance, employee-relations, rewards, transition, and audit catalog under More.

**Gap:** the current main dashboard is a comprehensive 7,103 px report. Today's priorities begin only after several screens, and the next recommended action is even lower. Admin’s operational work is mixed with programme analytics and HR oversight.

**New home: “Operations Today”**

- Hero: current platform status plus one highest-severity incident or “All systems operational.”
- First action: oldest support ticket, active incident, overdue maintenance, or data-repair item.
- Compact metrics: open support, active incidents, scheduled maintenance, failed jobs.
- Today: maintenance windows, uploads, approvals, and escalations.
- Insight: one platform-health trend; programme and people summaries become links.

**Page-family priorities:** Support/Incidents/Maintenance/Data Repair become Q/S archetypes; Users and Permissions become D/R/S; System Health becomes A; admin planning/my-plan become P; audit/history become Q/R. Programme pages remain available but should not dominate the Admin home.

### 2. CCEO — Field Execution

**Current mobile navigation:** Dashboard, My Plan, Schools, Messages.

**Gap:** the dashboard is conceptually task-oriented but KPI tiles and week-level tables still precede or over-expand field actions. The phone experience does not yet feel like a daily route/agenda.

**New home: “My Field Day”**

- Date, greeting, offline/sync status, and next scheduled activity.
- Primary CTA changes by state: Start visit, Continue evidence, Submit completion, or Schedule work.
- Horizontal day strip and agenda cards with travel/location context.
- Compact 2 × 2: completed, in progress, planned, overdue.
- Urgent school card shows reason, last SSA, recommended intervention, and Schedule/Assign.
- End-of-day debrief appears after the agenda, not in the global hero.

**Page-family priorities:** My Plan, Planning, Calendar, Visits, Trainings and To-Do use P/C/Q; Schools/Clusters use D/R; evidence and completion use V; weekly fund request uses F. This role should resemble reference 2 most closely.

### 3. Program Lead — Team Mission Control

**Current mobile navigation:** Dashboard, My Plan, Targets, Messages.

**Gap:** team delivery, approvals, targets, planning quality, HR/performance tools, and analytics compete on the same surfaces. Supervisory decisions are not consistently first.

**New home: “Team Mission Control”**

- First card: oldest approval, overdue CCEO work, or school requiring assignment.
- Team day strip: CCEO field activity and leave/coverage exceptions.
- Compact metrics: approval queue, overdue work, CCEOs active today, target pace.
- CCEO cards sorted by action needed, not alphabetically.
- One seven-day execution trend and one coaching recommendation.

**Page-family priorities:** Team Targets/Team Planning/Actions Sent/Approvals become Q/P; Coverage/Availability become C/A; Priority Dashboard and PL Analytics become A; people/performance pages should link out from a small team-health summary rather than lengthen the home.

### 4. Country Director — Country Pulse

**Current mobile navigation:** Dashboard, Budget, CD Analytics, Messages.

**Gap:** national oversight is correct in scope, but dashboard controls, metrics, approvals, targets, compliance, and operational risks create an executive report rather than a decision cockpit.

**New home: “Country Pulse”**

- Decision digest first: fund approvals, escalations, performance exceptions, and planning gaps.
- Hero metric: country delivery against plan with a small trend.
- 2 × 2: budget utilization, schools at risk, SSA coverage, overdue actions.
- Compact region/district exception list; full ranking belongs in analytics.
- One “recommended next decision” card with rationale.

**Page-family priorities:** Country Planning and Budget use P/F; CD Analytics and performance agreements use A/R; escalation, approval, and workforce pages use Q. Filters for FY/month should sit in a period selector, not a multi-control hero.

### 5. Regional Vice President — Regional Executive Digest

**Current mobile navigation:** Dashboard, Budget, Analytics, Messages.

**Gap:** the RVP dashboard contains ten numbered analytical sections plus approval, recommendations, intelligence, and notes. This is useful on desktop but far beyond a mobile home.

**New home: “Regional Executive Digest”**

- Pending country decision or critical escalation first.
- Hero regional performance trend and country comparison strip.
- 2 × 2: pending budgets, delivery pace, critical risks, SSA coverage.
- Country exception cards with one sentence explaining change.
- Strategy notes and full tables move to dedicated pages.

**Page-family priorities:** Budget submissions and approvals use F; country planning and decision log use Q/R; analytics uses A; strategy notes use a dedicated K/R page. Do not render the ten-section executive report on the home route.

### 6. Impact Assessment — Verification Desk

**Current mobile navigation:** Dashboard, Verify, SSA, Messages.

**Gap:** the 7,329 px dashboard begins with six workload metrics; the actual verification queue starts around 1,366 px. Long regional/district/leader tables make the same route both an operating desk and a national report.

**New home: “Verification Desk”**

- First card is the oldest/most at-risk verifiable record.
- Status segments: Activities, SSA, Evidence, Duplicates, Returned.
- Compact metrics: overdue, missing Salesforce ID, unmatched SSA, returned.
- “Needs attention” exceptions immediately after the first queue.
- Verification performance and national monitoring move to IA Analytics.

**Page-family priorities:** verification queues use Q; review workspace, comparison, evidence, and timeline use V/R; SSA upload/import uses U; IA Analytics uses A. Sticky Verify/Return actions must remain visible while reviewing evidence.

### 7. Accountant — Finance Queue

**Current mobile navigation:** Dashboard, Disburse, Payments, Messages.

**Gap:** six full-width KPI cards consume most of the first screen, even when values are zero. The weekly advance queue starts around 1,290 px.

**New home: “Finance Queue”**

- First item ready for disbursement or reconciliation, with amount and age.
- Status segments: Ready, Awaiting, Returned, Accountability, Paid.
- Hero metric: amount ready today; mini-metrics for count and cash position.
- Recent payment and proof exceptions, then one reconciliation trend.
- Rules, broad status charts, and audit history become drill-downs.

**Page-family priorities:** accounts dashboard and every finance status list use F/Q; disbursement detail uses F/R; evidence/accountability uses V/F; batch payments use Q/F; approvals/audit/history use Q/R.

### 8. Human Resources — People Operations

**Current mobile navigation:** Dashboard, People, Leave, Messages.

**Gap:** HR owns a large second application—people directory, structure, workforce planning, recruitment, onboarding, CPD, performance, relations, policies, offboarding, and audit. A broad regional overview cannot also serve as a daily HR queue.

**New home: “People Operations”**

- First action: onboarding blocker, leave approval, review due, or employee-relations follow-up.
- 2 × 2: active staff, onboarding, coverage gaps, high-risk cases.
- Today/this week timeline: starts, leave, reviews, interviews, deadlines.
- Workforce trend and one policy/compliance alert.
- Directory and strategic analytics remain separate destinations.

**Page-family priorities:** People Directory uses D/R; leave uses C/Q; recruitment/onboarding/offboarding use P/Q; performance cycle/reviews/recovery use P/R/A; policy/documents use K; employee relations uses Q/R with strong privacy states.

### 9. Project Coordinator — Project Delivery

**Current mobile navigation:** Dashboard, Projects, My Plan, Messages.

**Gap:** project list and delivery detail are buried on long portfolio pages. The role needs milestone and task orientation, not only counts of projects, schools, and partners.

**New home: “Project Delivery”**

- Next milestone or overdue project action first.
- Today agenda and project-specific tasks.
- Compact metrics: active projects, milestones due, at-risk, budget variance.
- At-risk project cards with owner, reason, and next action.
- One impact/budget trend; full analytics remains separate.

**Page-family priorities:** Projects index/planning/my-plan use P/Q; project detail uses R; project analytics uses A; schools/partners/coverage use D; follow-ups and debrief use Q.

### 10. Partner Admin — Portfolio Day

**Current mobile navigation:** Dashboard, My Plan, Clusters, Messages. The current demo database has no seeded Partner Admin account, but route permissions and navigation are defined.

**Gap:** Partner Admin and Partner Field Officer share the same landing architecture even though one manages organization workload and the other executes assigned work.

**New home: “Portfolio Day”**

- Organization workload and evidence/payment exception first.
- Field-officer assignment/load cards.
- Today's partner activities across the organization.
- Compact metrics: assigned, completed, evidence due, returned.
- Cluster and school coverage exception list.

**Page-family priorities:** Partner Today should branch its composition by role. Partner Admin receives organization segments and assignment controls; Field Officer identity remains visible on every activity card.

### 11. Partner Field Officer — My Partner Field Day

**Current mobile navigation:** Dashboard, My Plan, Clusters, Messages.

**Gap:** `/partner/today` is already concise, but it can become more actionable with a date strip, activity state, route context, and stronger evidence handoff.

**New home: “My Partner Field Day”**

- Next activity, location, and Start/Continue action first.
- Horizontal date strip and today/upcoming agenda.
- Compact metrics: today, completed, evidence due, returned.
- Assigned schools/clusters below the agenda.
- Evidence capture and completion use a sticky action bar and explicit sync state.

**Page-family priorities:** keep Partner Today as the internal reference implementation; redesign My Plan as P, activities as Q, evidence as V/U, schools/clusters as D/R.

## Cross-role page-family recommendations

### Authentication, agreements, and onboarding

The login page should use the motivational identity layer: Edify mission, restrained field imagery, secure access, and a short role-neutral value statement. Required policy agreements are real entry gates and should show estimated reading time, sticky progress, save/resume, downloadable source, and a clear “Acknowledge and continue” action. Password/MFA errors must stay adjacent to the affected field.

### Dashboards

Create distinct mobile home compositions rather than stacking the desktop body. Server-side role scoping stays unchanged; only ordering and component presentation change. A home should contain no more than one headline, four compact metrics, one primary queue/agenda, one attention section, and one trend.

### Planning, My Plan, Work Plan, To-Do, Calendar

These should converge on one workday model: date/period selector, next action, agenda/queue cards, and a floating or sticky add action. Planning Copilot becomes the first recommendation, not a late section. Calendar defaults to agenda/week on phones; month grid is optional.

### Schools, clusters, districts, partners, staff, people, projects

All directory pages should share search, filter sheet, saved view, count, list/map toggle, and compact record cards. Each card needs one status, one contextual metric, and one primary action. Record detail pages need identity/status, key facts, next action, and tabs for history/evidence/finance.

### Analytics, targets, quality, system health

Adopt reference 3's hierarchy but retain Edify semantics: decision statement, trend, compact KPI grid, recommendation, then supporting breakdowns. Tables remain drill-downs. Default charts should show comparison or change—not decoration—and include an accessible text summary.

### Finance and approvals

Amounts, stage, age, responsible person, and next decision must appear before policy/rules. Use sticky Approve/Return/Reject actions with confirmation and reason capture. Keep audit trail below the decision surface and make status transitions visually explicit.

### Verification, evidence, uploads, and data repair

Use evidence-first layouts. Display the submitted artifact, canonical record, mismatch summary, checklist, and decision in that order. Upload flows need a four-step state machine with resumable progress, error-first review, and a safe commit summary.

### Documents, help, policies, and knowledge

Use search-first hubs and focused readers. Move table of contents into a drawer on phones. Required acknowledgement stays sticky; edit/manage controls are hidden from ordinary readers and secondary on admin phones.

### Settings, administration, and audit

Use grouped, searchable lists rather than dashboard grids. Show current status and effect of a setting before editing it. Place destructive or access-changing operations in a guarded section with confirmation and audit visibility.

## Visual direction

### Keep

- Edify navy/blue as the brand base
- Green for verified/success, amber for attention, red for blocking risk
- Current card radii and restrained elevation
- Dark and light theme support
- Real role language, currencies, school/cluster names, workflow states, and evidence

### Change

- Use larger type only for a single mission or insight; reduce repeated oversized headings.
- Prefer off-white/light-neutral page canvases with high-contrast cards; in dark mode, preserve visible surface separation.
- Introduce compact progress rings, sparklines, and status bars only when they answer a question.
- Use field/education illustrations on login, onboarding, milestone, empty, and success states; keep lists and review screens utilitarian.
- Replace generic decorative icon patterns with role-meaningful symbols.

### Do not copy

- Anime character imagery or the futuristic theme from reference 1
- Health-domain units and biometrics from reference 3
- Low-contrast pastel text, tiny labels, or glass effects that reduce accessibility
- Floating center actions when the action is not truly global
- Charts that do not lead to a decision or drill-down

## Accessibility and field conditions

- Maintain WCAG 2.1 AA contrast in all themes.
- Keep 44 × 44 px minimum targets and visible keyboard focus.
- Do not rely on color alone for state.
- Provide chart summaries and table/card equivalents.
- Keep labels visible; placeholders are not labels.
- Support text zoom without clipped controls.
- Treat intermittent connectivity as a first-class field constraint: show sync state, preserve drafts, retry evidence uploads, and explain when data is stale.
- Keep pages lightweight; illustrative assets should be optional and optimized.

## Recommended implementation sequence

### Phase 1 — Mobile foundation (1–2 sprints)

- Replace the global one-column KPI override with compact component variants.
- Simplify the mobile top bar.
- Add filter sheet, section picker, compact metric grid, agenda card, record card, and sticky action bar.
- Define instrumentation: time to first action, queue completion, filter usage, scroll depth, task abandonment, and error recovery.

### Phase 2 — Highest-frequency role homes (2 sprints)

- CCEO, PL, IA, Accountant, and Partner Field Officer.
- Move actionable content into the first viewport.
- Split operating home from long-range analytics.

### Phase 3 — Executive and people homes (2 sprints)

- Admin, CD, RVP, HR, Project Coordinator, Partner Admin.
- Introduce decision digests and compact exception lists.

### Phase 4 — Core workflow families (3–4 sprints)

- Planning/My Plan/Calendar/To-Do
- Schools/Clusters/Partners/Projects/People directories
- Finance approvals and disbursement
- IA verification/evidence/SSA

### Phase 5 — Long tail and polish (2–3 sprints)

- Analytics, HR performance, documents/help, settings/admin, uploads, audit/history, closure workflows.
- Add selective mission imagery, empty/success states, offline recovery, and final accessibility/performance testing.

## Acceptance criteria

A redesigned mobile page is complete when:

1. The primary action or first actionable record is visible in the first 844 px under ordinary data conditions.
2. The page exposes no more than one hero action and four compact summary metrics before its main work.
3. Advanced filters are in a sheet and active filters remain visible/removable.
4. No essential section is discoverable only through horizontal scrolling.
5. Tables have a tested mobile card or bounded drill-down treatment.
6. Empty/zero groups collapse to an informative state.
7. Sticky actions do not collide with bottom navigation or safe areas.
8. All role permissions and data scopes remain unchanged.
9. Light/dark themes, 200% text zoom, keyboard focus, and screen-reader labels are verified.
10. The page records a measurable reduction in scroll depth or time to first action versus the current version.

## Highest-priority changes

1. Put Today/Queue/Next Decision before metrics on all role homes.
2. Replace phone KPI stacks with compact mobile variants.
3. Move advanced filters to bottom sheets on Planning, Schools, Clusters, Analytics, Accounts, and HR directories.
4. Split IA, RVP, Admin, CD, and HR dashboards into operational home plus analytics drill-down.
5. Use `/partner/today` as the internal task-first model, then strengthen it with agenda/date/evidence states.
6. Make verification and finance decisions sticky and evidence/amount-first.
7. Add role-specific empty states and sync/offline feedback.

The result should feel like **Edify's own field-operations product**, not a generic dashboard skin: calm, decisive, data-grounded, and optimized for the next useful action.
