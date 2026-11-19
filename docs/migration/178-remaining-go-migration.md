# 178 · What is left of the Go migration (2026-11-19)

Owner, 2026-11-19: "when you are done with porting every role, check on the
remaining Go migration, complete and then work on the redesign proposed above
with focus on mobile first experience."

## How it was counted

With the coverage probe (`internal/server/zz_probe_test.go`, build tag
`probe`, never committed), which asks every Go page builder, for one seeded
reader per role, whether it answers each route of
`docs/platform-page-inventory.json`. The probe had fallen behind the gateway:
it lacked six builders (the scope profiles, Visit Requests, the staff logs,
the closure pages, partner users and Platform Health); the first four were
added before counting.

    PROBE_DB=postgresql://edify_gateway@localhost:5432/edify_gorn_dev \
      go test -tags probe -run TestZZProbe -count=1 -v ./internal/server

Result over the dev database: 347 inventory routes, 147 answered by a Go page
builder, 66 detail routes (with an id) not claimed, 134 static routes not
claimed. Every role's Home and To-Do queue is Go's (176.31–176.33). The 134
static routes split as follows.

## A. Answered by Go outside the page builders

Not unported; the probe asks page builders only. Each is confirmed when its
group is next touched.

| Route | Answered by |
|---|---|
| `/home`, `/home/queue`, `/home/todo-figures` | HomeScreenService (`internal/home`) |
| `/messages`, `/messages/new` and its parts | MessagingService (176.28) |
| `/settings` | SettingsScreenService (176.28) |
| `/notifications` | NotificationCenterService |
| `/login`, `/login/verify` | SignInService; the web app's `/auth/*` routes |
| `/partner/users` | `partnerusers` (175; outside the probe's list) |
| `/loan-applications/apply` | the public school loan portal (`internal/loans`) |
| `/offline` | the apps' own offline screen |

To check: `/reset-password`, `/change-password`, `/settings/two-step/app`
(sign-in and account services), `/profile`.

## B. Stays outside Go by design

| Route | Why |
|---|---|
| `/system-health`, `/system-health/notifications` | Django keeps System Health; Go has `/platform-health` |
| `/ia/learning` | Python analytics (owner: Python only for analytics) |

## C. Pages to port (read first; each save cuts over on its own, shadow-proved)

Ordered by family, so one family's services are ported once.

1. **Accounts desks** (Accountant; `finance_operating_views`):
   `/accounts/accountability`, `/advances`, `/audit-log`, `/blocked`,
   `/budget-amendments`, `/cleared`, `/returned`, `/variance-review`,
   `/weekly-requests`.
2. **Finance overviews**: `/budgets/overview`, `/finance/fund-allocation`,
   `/country-budget/history`.
3. **Field work**: `/today`, `/activities/closure`, `/planning/schedule`,
   `/debriefs/submit`, `/debriefs/weekly-report`, `/map`, `/search`.
4. **Partners**: `/partner/activities`, `/partner/assignments`,
   `/partner/schools`.
5. **SSA and data quality**: `/ssa/manual`, `/ssa/upload`,
   `/ssa/upload/history`, `/ssa/unmatched`, `/data-quality/duplicates`,
   `/priorities/ssa-mapping`, `/ia/notifications`, `/ia/school-evidence`.
6. **Admin panel**: `/admin-panel`, `/audit-log`, `/notifications-mgmt`,
   `/page-access-matrix`, `/region-district-setup`, `/school-upload-history`,
   `/workflow-rules`; `/settings/activity-catalogue`.
7. **HR**: `/culture-engagement`, `/payroll-readiness`,
   `/performance-conversation`, `/succession-planning`, `/wellness`.
8. **Business Transformation workspace**: `/business-transformation`.
9. **Knowledge Center and documents**: `/help` and its eight sub-pages,
   `/policy-agreement`, `/policy-agreement/restricted`, `/uploads/new`,
   `/support`.

Each is proved as 176.1 describes: `webpages/testdata/web_page.py` runs the
page's own view for each reader and reads it as the feed reads pages; the Go
builder's answer is compared whole. Readers or queries Go does not build are
handed on, never approximated.

## D. Parts (HTMX fragments, drawers, previews)

About sixty partial routes (dashboard actions, drilldowns, previews, option
lists, drawers). They are ported with the page that loads them, as RPCs of
PageDrawerService or as `later` parts of the page's answer, not as pages of
their own.

## E. Depth still handed on inside Go pages

- pl1's To-Do queue: `_pl_analytics_todos`, the team's core-school
  follow-ups, coverage (176.33).
- The guards in `internal/todos` that pass a reader on whenever a kind of
  record exists (listed per builder in 36-todos and 176.33).
- The hand-ons listed per page in 176 and earlier notes.

## Order of work

C1 → C9, then D with each page, then E. After that the mobile-first redesign
(177, Stage A first).
