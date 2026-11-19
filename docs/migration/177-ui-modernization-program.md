# 177 · UI/UX modernization program (owner brief, 2026-11-19)

The owner's master instruction "Complete UI/UX Modernization, Current-vs-New
Design Audit, Web & Native Mobile Implementation" (2026-11-19), condensed
here so every later stage works from the same requirements. Section numbers
in brackets are the brief's.

## Direction

- Turn Edify into a premium enterprise product: calm hierarchy (Linear),
  trustworthy financial presentation (Stripe, Ramp), systematic type and
  spacing (Vercel Geist), strong data grids (TanStack Table). Extract
  principles; never copy another company's branding. [1, 4]
- Principle: **SIMPLE → HEALTHY → FOCUSED.** Every screen answers: what needs
  me, what am I responsible for, what changed, what next, how, what happened.
- **This supersedes the 2026-11-19 "exactly like the live system" direction**
  for the web (176.27–176.30): the live system becomes the documented
  *before*; the new Edify Enterprise Design System is the *after*, reviewed
  through previews before the whole application is rebuilt. [3, 18]
- Stack: Next.js App Router + TypeScript (strict) + Tailwind (tokens as theme
  variables) and an accessible component system (evaluate shadcn/ui,
  TanStack Table, a charting library); React Native + Expo + Expo Router;
  Go owns auth, permissions, workflows and transactions; Python only for
  analytics; gRPC/protobuf between them. Next.js stays a presentation layer:
  no business logic, no direct database access. [1, 6, 7, 16]

## Safety (unchanged, absolute) [2, 16, 17]

No change to the production database; no production migrations, test data,
load tests, backfills or dual writes; development on
`feature/edify-go-rn-migration` only; no merge into `main`, no deploy, no
cutover without explicit approval; identifiers and historical, financial and
audit records preserved. Production may only be *read*, with authorization,
for visual baseline capture.

## Stages [22]

| Stage | Scope |
|---|---|
| A | Audit the actual application: architecture, routes, roles, workflows, performance baseline; current screenshots per role at desktop/tablet/mobile; current-vs-proposed comparison per page; role/page inventory and route-by-role permissions matrix (incl. Acting PL/CD). No redesign before this. [3] |
| B | Design system: semantic tokens (colour, type scale, weights, spacing, radius, shadow, borders, focus, states, chart colours) shared web/native as TypeScript; typography with tabular numerals; components (AppShell, Sidebar, PageHeader, Breadcrumbs, ContextSwitcher, CommandSearch, KPIStat/KPIBar, DataTable, StatusBadge, FilterBar, DateRangePicker, ProfileHeader, Timeline, ActivityCard, ApprovalCard, NotificationItem, EmptyState, LoadingSkeleton, ErrorState, ConfirmDialog, FormField, FileUploader, ChartPanel, EvidenceGallery, AuditHistory, DetailDrawer, ActionMenu); a preview environment. [5] |
| C | Next.js foundation: one authenticated shell (collapsible role-aware sidebar, top bar with search/command, notifications, profile), stable layouts, prefetching, filter/scroll preservation, deep links, keyboard shortcuts; RSC for reads, client components for interaction; request-scoped auth, no global caching of user or financial data. [6] |
| D | Core screens: CCEO, PL, CD, IA, Accountant. [8.1–8.6] |
| E | Remaining roles: RVP, BT, HR, Project Coordinator, Admin, Implementation Partner, Lending Partner Admin, Loan Officer, Cluster Leader, Public School Applicant. [8.4–8.15] |
| F | Unified profiles (School, Cluster, Staff, CCEO, PL, Partner, Lending Partner, District, Sub-region, Country, Project): header, compact KPI strip with definitions and drill-down, tabs; provenance, freshness; Python predictions shown apart from verified outcomes. [9] |
| G | Expo mobile: native stack + bottom tabs, safe areas, deep links, push, camera/files, task-first homes, ≥44px targets, low-data. [7] |
| H | Real-time: Go-authoritative events (SSE or WebSockets), authenticated and scope-aware, reconnection, idempotent, published only after commit; pending state until confirmed. [11] |
| I | Optimization: measured, never claimed. [12] |
| J | Quality and release readiness; no merge, no deploy. [21, 23, 24] |

## Role requirements (summary) [8]

- **CCEO** task-first: Due Today, Planned This Week, Awaiting Evidence,
  Cluster Support Requests, School Follow-ups, Pending Partner Activities,
  loan follow-ups where permitted, compact target progress; actions My Plan,
  Start/Complete Activity, Plan School Visit, My Schools. Planned never
  counts as completed; targets and eligibility rules unchanged.
- **PL**: My Work vs Team Oversight kept apart; approvals, CCEO follow-ups,
  team activity, support requests, overdue evidence, team targets, budget and
  advances; CCEO performance table with drill-downs.
- **CD**: executive KPI strip, main trend, priority decisions, district /
  sub-region comparisons, exceptions; consistent month/quarter/FY filters.
- **RVP**: consolidated performance, targets, budget approvals, risks, loan
  and partner trends; no field controls on the default page.
- **IA**: SSA verification queue, Salesforce ID pending, coverage, trends,
  intervention-level SSA, Core readiness, data quality, exports; no System
  Settings or Users.
- **Accountant**: advances pending disbursement, approved budgets, payments,
  verified completion, partner payment readiness, exceptions, history,
  reconciliation; UGX formatting, totals, requested/approved/disbursed kept
  distinct.
- **BT**: loan applications through repayment follow-ups, lender
  responsiveness, school financial health, compliance; full timelines.
- **Project Coordinator**: assigned projects, targets, schools, planned and
  completed activities, evidence, milestones, dependencies, outcomes.
- **HR**: review cycles, development, leave, PD, policies, PIPs, pending
  actions; sensitive data restricted.
- **Admin**: users, roles, acting leadership, partner access, uploads,
  settings, imports, audit logs.
- **Cluster Leader**: four large actions (Plan Meeting, My Schools, Cluster
  Actions, Mobilize Schools) and Needs Your Attention; the cluster-action
  loop Meeting → Need → CCEO Request → Planned → Implementation → Evidence →
  Follow-up → Closure; no confidential loan servicing.
- **Implementation Partner**, **Lending Partner Admin**, **Loan Officer**:
  case and activity workspaces as listed in the brief.
- **Public School Applicant**: no-signup application, tracking, agreement,
  statement and dispute pages with recipient verification.

## Standards

- Tables: server-side pagination, sorting, filters, column visibility and
  justified pinning, density, selection and authorized bulk actions,
  filtered export, saved views, mobile row alternatives; every school export
  carries the Edify School ID (leading zeros kept, never the Salesforce ID).
  [10]
- States: loading skeletons matching final size, background refresh, empty,
  sparse, error, permission denied, stale, validation, concurrent conflict,
  confirmed success. [13]
- Responsive at 320, 375, 390, 768, 1024, 1440, 1920. [14]
- WCAG 2.2 AA on web; native accessibility on iOS/Android. [15]
- Performance targets (measured against a recorded baseline): LCP ≤ 2.5 s
  p75, INP ≤ 200 ms p75, CLS ≤ 0.1, light API p95 ≤ 500 ms, cached
  navigation p95 ≤ 300 ms; 500 concurrent users validated, stress toward
  1,000 / 2,500 / 5,000, staging only. [12]
- Review rubric (internal, never fabricated): hierarchy 15, workflow 20,
  consistency 15, responsive 15, accessibility 10, data integrity 10,
  performance 10, errors 5; target ≥ 90 on critical screens. [19]
- Workflow validation per role, measuring steps, time and mistakes. [20]

## Deliverables [23]

Current application audit; before/after comparison; design system; Next.js
web app; Expo app; shared contracts and real-time events; performance report;
test results; production safety report; final implementation summary.
Nothing is claimed verified without evidence.

## Where it stands

- Work already on the branch that carries forward: the Go gateway's native
  pages and Home (176.31); the Next.js app with the existing web's markup
  (176.27–176.30) and the phone design from the Expo app;
  `components/ds` and `/design-system` (176.30); the Expo screens.
- Stage A starts next, from `06-ui-inventory.md` and the local development
  environment (existing app on 8010, Go gateway on 8090, Next.js on 3000,
  the Expo app in the iOS simulator), with seeded accounts for every role.
