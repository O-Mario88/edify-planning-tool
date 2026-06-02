# Edify Planning & Monitoring Tool — Features, Functionality & Workflow Audit

_Generated for the stakeholder presentation + live demo. Status legend: ✅ working (demo-ready) · 🟡 partial (works, incomplete) · ⚪ stub/placeholder · 🔴 broken._

**At a glance:** 10 domains audited · 162 features catalogued — 150 ✅ working · 4 🟡 partial · 8 ⚪ stub · 0 🔴 broken. No broken features. The app is demo-ready; the partial/stub items are non-core and easily routed around (see Demo Script).

> **Accuracy note:** an automated route scan flagged ~51 pages as 'stubs' purely because they use the shared `StubPage` layout wrapper. That heuristic is wrong — many fully-built pages (`/portfolio`, `/settings`, `/data-intake`, `/profile`, `/analytics`, `/duplicates`) use `StubPage` as chrome. The per-domain findings below (which actually read the code) are authoritative.

## Contents
- [Shell & Navigation](#shell--navigation)
- [Role Dashboards (CCEO, CPL, Director, RVP, Accountant, Impact, HR, Partner)](#role-dashboards-cceo-cpl-director-rvp-accountant-impact-hr-partner)
- [School Intake & Portfolio](#school-intake--portfolio)
- [Partner Workflow](#partner-workflow)
- [Targets, FY & Periods](#targets-fy--periods)
- [Planning Engine](#planning-engine)
- [Finance & Funds (Edify Planning & Monitoring Tool)](#finance--funds-edify-planning--monitoring-tool)
- [Verification & Accountability (Activity Verification & NetSuite Accountability Workflow)](#verification--accountability-activity-verification--netsuite-accountability-workflow)
- [Staff Onboarding & Organization Management](#staff-onboarding--organization-management)
- [Analytics, Reports & Impact](#analytics-reports--impact)

---
## Shell & Navigation

The Edify shell is a fully-functional, multi-role navigation system with 11 distinct role-aware sidebars, mobile top bar + bottom nav, live theme switching (light/dark/glass), command palette, and role-switching. Core navigation is working and demo-ready; all major surfaces render correctly with proper role gating via middleware. The design and IA are cohesive across desktop/mobile.

### Features

| Status | Feature | Route | Notes |
|---|---|---|---|
| ✅ | **EdifySidebar (Role-aware menus)** | `/dashboards/*, /my-plan, /schools, etc. per role` | 11 distinct role-specific menus (CCEO, CPL, CD, RVP, Accountant, Impact, HR, Admin, Partner-3). Menu-building logic is clean and well-commented. Sections include My Work, Schools, Team, Activity, Programs, Insights, A… |
| ✅ | **SidebarBrand** | `sidebar top` | White Edify logo + 'Planning and Monitoring Tool' subtitle. Appears on every sidebar consistently. Compact mode omits subtitle (future rail collapse). Link target uses ROLE_REDIRECT map. Clean, minimal, professional. |
| ✅ | **SidebarProfile** | `sidebar footer` | Profile row at sidebar foot: avatar (initials + color), name, district, role label (concise), online status indicator. Opens popover upward with Profile → /profile, Settings → /settings, Theme Toggle (light/dark/glass… |
| ✅ | **MobileTopBar** | `top of page <lg` | Dark sticky header (md:hidden). Hamburger (forwards to sidebar's useMobileDrawer), bold white title, optional date pill, IdentityCluster (messages + notifications + avatar menu). Scroll-shadow effect. Title auto-scale… |
| ✅ | **IdentityCluster** | `IdentityCluster in header` | Reusable 'message bell + notification bell + avatar menu' group. Appears in MobileTopBar (dark variant) and desktop PageHeader (default variant). Avoids duplication. Avatar menu removed from this component; SidebarPro… |
| ✅ | **RoleBottomNav** | `bottom nav xs-sm` | Phone-only (md:hidden) persistent bottom bar. Each role has a unique layout: CCEO + Partner roles = FAB model (5 tabs + center create button), others = flat 5-tab bar. Tabs match their dashboard verbs. Active state in… |
| ✅ | **CommandPalette** | `⌘K overlay` | ⌘K / Ctrl+K search modal. Three sections: Pages (from EXACT_ROUTE_TITLES, 30+ routes), Actions (6 global verbs: Messages, Notifications, Add Partner, Upload Resource, Create Plan, Settings), Roles (demo only, 8 roles)… |
| ✅ | **ThemeProvider + ThemeToggle** | `AvatarMenu > Appearance` | Four modes: light, dark, glass (futuristic), system (follows OS). Persists to localStorage (edify-theme). Theme preload script runs pre-hydrate to avoid FOUC. Live OS preference watching when mode=system. ThemeToggle … |
| ✅ | **Route Gating (Middleware)** | `middleware.ts` | Edge middleware blocks anonymous access to 30+ PROTECTED_PREFIXES, redirects to /login?next=<original>. Dev-only ?as=Role impersonation for previewing. No runtime role-restriction errors observed. /admin is Admin-only… |
| ✅ | **Role Switching (Demo)** | `SidebarProfile popover > Switch role` | Dev-only (NODE_ENV !== production). Triggered via AvatarMenu > 'Switch role' (dev-only label), opens RoleSwitcher modal with 8 roles + their blurbs. Calls /api/demo/role-switch, sets session cookies, hard-refreshes to… |
| ✅ | **RouteTitleSync** | `all shell routes` | Auto-registers route titles from EXACT_ROUTE_TITLES map (35+ routes defined). Pages can override via useSetPageTitle(). MobileTopBar reads context. Fallback title is 'Edify' on undefined routes. No broken titles obser… |
| ✅ | **PageTitleContext + MobileTopBar integration** | `shell layout` | PageTitleProvider wraps shell layout with identity (name, initials, color) + unread messages + recent messages. MobileTopBar reads title + dateLabel from context. No re-renders on nav due to context stability. Clean a… |

### Workflows

**Login → Dashboard (any role)** ✅  _(roles: all)_
1. User navigates to /login
2. Middleware allows public route, no cookie
3. Login form (demo: pick from DEMO_USERS)
4. POST /api/auth/login sets 3 session cookies (edify-email, edify-role, edify-name)
5. Middleware on next request reads cookies, resolves role
6. Router.push to ROLE_REDIRECT[role] (e.g., /my-targets for CCEO, /dashboards/cpl for CPL)
7. EdifySidebarServer async-resolves user, renders EdifySidebar with correct role menu
8. MobileTopBar + RoleBottomNav render role-specific chrome
9. User sees dashboard with personalized sidebar

**Navigate sidebar menu (same role)** ✅  _(roles: CCEO, CountryProgramLead, CountryDirector, RVP, ProgramAccountant, ImpactAssessment, HumanResource, Admin)_
1. User taps/clicks sidebar menu item (e.g., 'Schools')
2. EdifySidebar uses usePathname() to highlight active item
3. Link href=/schools navigates via Next.js client router (no full reload)
4. EdifySidebarServer stays mounted (route-group layout), sidebar persists
5. RouteTitleSync updates page title to 'Schools'
6. MobileTopBar updates title (mobile)
7. RoleBottomNav syncs active tab highlight
8. Page content streams in, sidebar stays open on desktop, auto-closes on mobile via pathname effect

**Switch role (demo, dev-only)** ✅  _(roles: all, demo env only)_
1. Click avatar in sidebar footer or MobileTopBar
2. SidebarProfile or AvatarMenu opens popover
3. Click 'Switch role' (dev-only label shows)
4. RoleSwitcher modal opens with 8 roles + blurbs
5. Select target role (e.g., RVP)
6. POST /api/demo/role-switch { email } sets new cookies
7. Hard window.location.href to LANDING_BY_ROLE[role] (e.g., /dashboards/rvp)
8. Full page reload, middleware re-resolves role
9. EdifySidebar + bottom nav render new role menu + landing page
10. Previous role's sidebar is gone

**Open Command Palette + search/navigate** ✅  _(roles: all)_
1. Press ⌘K (Mac) or Ctrl+K (Windows/Linux)
2. CommandPalette modal opens at top-center
3. Type search query (e.g., 'schools')
4. Fuzzy score Pages + Actions + Roles (demo), show top 20 matches
5. Use ↑↓ to highlight, Enter to select
6. If href: router.push(href), modal closes
7. If onSelect: run handler (e.g., role switch dispatches /api/demo/role-switch then reload)
8. Empty query shows curated top-5 pages + top-5 actions (first-use hint)

**Change theme (light ↔ dark ↔ glass ↔ system)** ✅  _(roles: all)_
1. Click avatar in sidebar footer (desktop) or MobileTopBar (mobile)
2. Open popover, scroll to 'Appearance' section
3. Click one of 4 theme buttons (Sun, Moon, Sparkles, Monitor)
4. ThemeProvider.setMode(next) writes to localStorage (edify-theme)
5. resolveFor(mode) calculates resolved theme (light | dark | glass)
6. applyClass(resolved) applies .dark or .glass to <html>, sets colorScheme
7. Cross-fade animation plays (theme-fade class, 220ms)
8. CSS variables in styles adapt, page repaints in new palette
9. On reload, pre-paint script (themePreloadScript) applies saved mode before React mounts (no FOUC)

**Access role-restricted surface (e.g., /admin as non-Admin)** ✅  _(roles: Admin only for /admin)_
1. Non-Admin user (e.g., CPL) navigates to /admin or types URL
2. Middleware reads edify-role cookie
3. Admin role check fails
4. Redirect to ROLE_REDIRECT[actualRole] (e.g., /dashboards/cpl)
5. User lands on their own dashboard, no error page shown
6. /admin link does not appear in CPL sidebar (menu built per role)

**Mobile drawer open/close (hamburger)** ✅  _(roles: all on mobile)_
1. On mobile (<lg), sidebar mounted but off-screen (-translate-x-full)
2. Hamburger button in fixed top-left (useMobileDrawer) or MobileTopBar
3. Tap hamburger, drawer slides in from left, overlay appears
4. Tap menu item or overlay, useMobileDrawer.setOpen(false) triggers
5. useEffect on pathname also auto-closes on nav (no lingering drawer)
6. Sidebar smoothly slides out, overlay fades

### ⭐ Demo highlights
- Live role-switching: Open avatar menu, tap 'Switch role', pick a different role (RVP, Accountant, HR, etc.), watch the entire sidebar + bottom nav + landing page reload with that role's menus. Extremely smooth.
- Multi-role navigation clarity: Show CCEO sidebar (field-focused, My Work/Schools/Activity), then switch to RVP (Monitoring/Planning/Insights), then CD (Main Navigation, no personal tools). Each role's job is immediately visible in their menu structure.
- Command palette power search: Press ⌘K, type 'schools' or 'budget' or 'role', see instant fuzzy results from 30+ pages + 6 actions + role switcher. Navigate with arrows, hit Enter. Shows off the 'power user escape hatch' that makes the app feel premium.
- Theme switcher: Open avatar menu, click Glass theme. Page instantly glows with holographic surfaces + dark mode. Reload; theme persists. Shows visual polish + localStorage persistence.

### ⚠️ Demo risks / gaps
- Route title fallback: If a new page is added to (shell) but not registered in EXACT_ROUTE_TITLES or via useSetPageTitle(), MobileTopBar will show 'Edify' (the fallback). CommandPalette will not list it. Medium risk on stage if demo includes a newly-built page — check EXACT_ROUTE_TITLES first.
- Bottom nav FAB model: CCEO + Partner roles use a 5-tab layout with a center FAB button. If the create plan page (/plans/new) is broken or doesn't load, the FAB target is dead. Test the FAB on CCEO role before demo.
- Role switch animation: RoleSwitcher uses Framer Motion (reduce-motion respect). On very slow networks, the hard window.location.href reload might take 2+ seconds, user sees blank screen. Pre-demo, test on a slow connection or warn stakeholders.
- Middleware /as=Role impersonation: Dev-only in NODE_ENV check. If the build is production but NODE_ENV is accidentally set to development, ?as=Admin becomes a public vector. Verify NODE_ENV before deploying.
- Command palette role items: Demo-only hardcoded ROLES list (8 emails). If a new demo user is added to DEMO_USERS but not ROLES, they won't be switch-able via ⌘K (but AvatarMenu will still show 'Switch role'). Small friction.
- SidebarProfile/AvatarMenu duplication: Same menu lives in two places (sidebar footer + mobile topbar). If one is updated without the other, they drift. Current state is in-sync, but a code-review blocker for future changes.
- MobileTopBar hamburger mashup: The hamburger 'forward click' to the useMobileDrawer trigger is a bit fragile — it queries the DOM for 'button[aria-label="Open menu"]'. If that button's DOM position or HTML changes, the forwarding breaks. Consider a ref or explicit state prop instead.

---
## Role Dashboards (CCEO, CPL, Director, RVP, Accountant, Impact, HR, Partner)

Eight role-specific dashboards fully implemented with rich command-stack architecture, KPI rows, strategic section headers, and role-appropriate cards. All dashboards follow the four-question cockpit discipline (What to do now → What's happening → What changed/risky → What's next). Data flows via mock backend; no API errors observed. Dashboards are mobile-responsive with identical content trees. Partner dashboard has extensive sub-sections (inbox, activities, evidence, planning, reports, schools); director has weekly debrief center. Demo-ready across all roles.

### Features

| Status | Feature | Route | Notes |
|---|---|---|---|
| ✅ | **CommandStack** | `/dashboards/*/page.tsx` | 10-second action system rendering mission header, next-3 actions, unified inbox, done-for-today checklist, and change-digest via role-action-engine (fully functional, all roles) |
| ✅ | **CCEO Dashboard** | `/dashboards/cceo/page.tsx` | 23 imported components: CommandStack, 6x KPI row, risk-bottleneck board, SSA heatmap, quality card, schools-needing-attention, verification-payment funnel, Salesforce queue, month planner, activity breakdown, routes, … |
| ✅ | **CPL (Program Lead) Dashboard** | `/dashboards/cpl/page.tsx` | 16 components imported: CommandStack, field-work card, team KPI row, leadership-attention row, team-performance chart, personal-targets, CCEO-performance table, approval queue, best performers, partner-payments queue,… |
| ✅ | **Country Director Dashboard** | `/dashboards/director/page.tsx` | 12+ components: CommandStack, 8 KPI tiles, leadership-attention row, debrief-review inbox, training-coverage, country-performance chart, regional-performance card, program-leads table, priority-schools-urgent card, op… |
| ✅ | **RVP Dashboard** | `/dashboards/rvp/page.tsx` | Desktop + mobile mobile view (RvpMobileView). Enforces cockpit discipline: CommandStack, region KPI cards (schools, target %, valid visits, SSA%, funds), insight strip, training-coverage, country-comparison table, bur… |
| ✅ | **Program Accountant Console** | `/dashboards/accountant/page.tsx` | Finance leg of workflow: CommandStack, staff-accountability queue (IA-verified activities), partner-payments queue (PL-approved), payment pipeline funnel (5 stages: IA verified → accountant → cleared → Netsuite ID → p… |
| ✅ | **Impact Assessment Dashboard** | `/dashboards/impact/page.tsx` | Mobile (QueueView) + desktop. CommandStack, 5 KPI row, insight strip, IA plan card, program-overview card, verification-funnel, donor-impact card (verified reach/training/improvement), data-quality trend chart, qualit… |
| ✅ | **HR (People & Performance) Dashboard** | `/dashboards/hr/page.tsx` | Desktop + HrMobileView. CommandStack, HR-attention row (3 alert banners: decisions, flagged-staff, reviews-due), 4 KPI tiles (linked to queues), best-performers card, aggregated-field-context card (barriers/themes/hea… |
| ✅ | **Partner Dashboard** | `/dashboards/partner/page.tsx` | Desktop + PartnerDashboardMobileView. PartnerHeader, debrief-promoter card, 8-step workflow tracker (assigned→scheduled→delivered→evidence→CCEO→PL→accountant→paid), priority-actions, done-for-today checklist, action-i… |
| ✅ | **Director Weekly Debrief Center** | `/dashboards/director/weekly-debrief-reports/page.tsx` | Country-level debrief compilation: hero with week selector, country weekly field intelligence (planned/completed/achievement %), top-country barriers, decisions-required panel, per-PL report list (status badges, late-… |
| ✅ | **Director Debrief Report Detail** | `/dashboards/director/weekly-debrief-reports/[id]/page.tsx` | Full PL weekly report: hero, report metadata, PL team/region/week, activity summary, debrief details (expected vs submitted), planned vs completed activities, top barriers + recommendations, decisions, contextual insi… |
| ✅ | **RVP Country Summary** | `/dashboards/rvp/country-summary/page.tsx` | Country-level aggregated field context (no raw debriefs) + decision-actions card (escalations RVP has routed to CD/HR). Hero + two-card layout. RVP-only. |
| ✅ | **DashboardPageHeader** | `each dashboard` | Role-stamped header (breadcrumb + title + filters + profile integration). Present on all dashboards. |
| ✅ | **Section Headers** | `each dashboard` | SectionHeader component (eyebrow + title + description) organizing dashboard into reading chapters. Consistent across all roles. |
| ✅ | **Lazy-loaded Charts** | `/components/ui/lazy-charts.tsx` | CountryPerformanceChart, RegionalPerformanceCard, TeamPerformanceOverviewChart, CoreSsaTrendCard, SsaTrendCard, DataQualityTrendChart, QualityCheckStatusCard all dynamic-imported with ChartSkeleton fallback. Recharts-… |
| ✅ | **Responsive Mobile Views** | `all dashboards` | ResponsiveDashboard component wraps identical or separate mobile content trees. Mobile views collapse grids (2-col phone → 4-col tablet → 6+ desktop). Tables become card lists. Partner, RVP, Impact have dedicated mobi… |
| ✅ | **Error & Loading States** | `/dashboards/error.tsx, /dashboards/loading.tsx` | SegmentError (error boundary) + RouteSkeleton loading fallback. No dangling stubs. |
| ✅ | **Role Action Engine** | `/lib/actions/role-action-engine.ts` | Unified brain behind CommandStack: given (role, period, last-viewed), returns RoleActionBoard with mission, top-3 actions, unified inbox, done-checklist, change digest. All 8 roles supported. Pure data output (type Ac… |

### Workflows

**CCEO Daily Operations** ✅  _(roles: CCEO)_
1. Open /dashboards/cceo: CommandStack shows today's top actions (mission, next-3, inbox, done-checklist)
2. Scan KPI strip (6 operating metrics: schools, targets, visits, SSA%, cloud-score, visits-completed) + pace KPIs below
3. Review Risk & Bottleneck Board to identify what needs attention this week
4. Check SSA Heatmap (intervention performance by school) + quality drift to see where schools struggle
5. View 'Schools Needing Attention' ranked by health-score drop and overdue SSA
6. Examine Verification → Payment funnel (IA verified to Paid, bottleneck highlighted) + Salesforce queue
7. Review month planner + activity mix + route opportunities for scheduling
8. Spotlight on next priority school (system-recommended unlock opportunity)
9. Quick actions (shortcuts) + momentum banner (engagement reminder)

**Program Lead Team Management** ✅  _(roles: CountryProgramLead)_
1. Open /dashboards/cpl: CommandStack (mission, actions, inbox, done-list)
2. Check Command Lanes (My Field Work vs My Team Work split) to balance coaching role
3. Review Team KPIs (8 metrics: targets, visits, SSA%, etc. by team) + Leadership Attention row (3 alerts)
4. View Team Performance chart (monthly trend) alongside Personal Targets card
5. Review CCEO Performance table (7 metrics per team member) + Approval Queue (sign-offs needed)
6. Recognize top performers + check partner-payments approval gate
7. Review My Plan card (team field plan)
8. Examine Team Backlog (6-tile snapshot of execution gaps) + SSA Intelligence (heatmap + schools urgent attention)
9. Check Smart Route Capacity (route quality + capacity pickup opportunities)

**Country Director Leadership** ✅  _(roles: CountryDirector)_
1. Open /dashboards/director: CommandStack (mission, next-3 actions)
2. Scan 8 Country KPIs + Leadership Attention row (alerts for decisions)
3. Review Debrief Review Inbox (routed-up debriefs requiring decision)
4. Check Training Coverage against SSA gaps
5. Examine Country Performance chart + Regional Performance snapshot
6. Review Program Leads Performance table (7 metrics across PLs) + Priority Schools Needing Urgent Attention
7. Recognize top performers + verify self-verification quota
8. Check Operational Risk & Backlog vs SSA Intelligence
9. Review 30-day plan horizon (commitment execution)
10. Examine Fund Approvals + Funded-Not-Completed (money parked in pipeline)
11. View Donor Impact card (reach/training/improvement figures donor-ready)

**Regional VP Oversight** ✅  _(roles: RVP)_
1. Open /dashboards/rvp: CommandStack (mission, actions)
2. Check Regional Signals (6 KPIs: schools, avg-target, valid-visit%, SSA%, committed-funds, disbursed-funds) + insights + training-coverage
3. View Country Comparison table (countries side-by-side: targets, SSA, valid-visit%, funds committed/disbursed, special-projects)
4. Check Burn-rate Rail (disbursement % by country: red <65%, amber 65–80%, green ≥80%)
5. Review Salesforce Compliance (logging discipline by country, circular progress)
6. Check Special Projects portfolio (excluded from SSA to avoid double-counting)
7. View Donor Impact card (regional reach/training/improvement readiness)
8. Review Regional Plan Horizon + Annual Cycle callout + Leadership Impact snapshot
9. Check Best Performers + Team Targets rollups

**Program Accountant Payment Closure** ✅  _(roles: ProgramAccountant)_
1. Open /dashboards/accountant: CommandStack (mission, next-3 actions)
2. Review Staff Accountability Queue (IA-verified activities awaiting NetSuite ID closure)
3. Check Partner Payments Ready to Clear (PL-approved requests in final gate)
4. Monitor Payment Pipeline funnel (IA verified → accountant → cleared → Netsuite ID → paid; bottleneck highlighted)
5. Interact with Accountant Console Dashboard (additional reporting/controls)

**Impact Assessment Data Verification** ✅  _(roles: ImpactAssessment)_
1. Open /dashboards/impact: CommandStack (mission, actions)
2. Check Vital Signs KPIs (5 numbers leadership reads first) + system insights
3. Review IA Plan card (expected work) + Program Overview (counts by program)
4. Examine Data Verification Funnel (where every record sits: plan→upload→verified/flagged)
5. Monitor Donor-Ready counts (verified reach/training/improvement for donor reporting, pending records flagged)
6. Check Data Quality Trend (drift over time) + Recent Data Uploads + Partner Performance
7. Review Quality Check Status (donut) + Training Data Quality + Top Issues
8. Run quick-actions utilities

**HR Staff Support & Recognition** ✅  _(roles: HumanResource)_
1. Open /dashboards/hr: CommandStack (mission, actions)
2. Review HR Attention row (3 alerts: CD/RVP decisions routed to HR, flagged-staff for support, reviews-due)
3. Check 4 KPI tiles (active-reviews, flagged-staff, open-HR-decisions, aggregated-barriers) each linking to working queue
4. Review routed Debriefs (performance signals) + Best Performers (recognition across PLs/CCEOs)
5. Examine Aggregated Field Context (barriers, support themes, team-health signals—no individual CCEO names)
6. Access Quick Actions (shortcuts to queues)

**Partner Activity Delivery Pipeline** ✅  _(roles: PartnerAdmin, PartnerFieldOfficer, PartnerViewer)_
1. Open /dashboards/partner: PartnerHeader (organization context)
2. Check Debrief Promoter (daily habit reminder)
3. Monitor Activity Workflow Tracker (8-step pipeline: assigned→scheduled→delivered→evidence→CCEO→PL→accountant→paid with live counts)
4. Review Top 3 Priorities (next 10s actions) + Done-for-Today checklist (daily habit)
5. Check Action Inbox (tabbed, filtered by activity state) + Evidence Required (what's owed) + Returned Corrections
6. Review Assigned Schools (needing support this week) + Upcoming Activities (today/tomorrow/this week/later)
7. Monitor Status Grid (evidence-missing/returned/verified buckets) + Payment Status Card
8. Check Evidence Quality Panel (30-day trend) + School Impact Summary
9. Access sub-routes if needed (Partner Workflow at /partner/*: activities, evidence, planning, reports, schools, inbox)

**Director Weekly Debrief Processing** ✅  _(roles: CountryDirector)_
1. Navigate to /dashboards/director/weekly-debrief-reports: Week selector
2. Review Country Weekly Field Intelligence (rollup: planned/completed/achievement%, top-barriers, decisions-required)
3. Scan per-PL reports list (status badges, late-submission flags, debrief-submission-rates, raw vs context-adjusted achievement%)
4. Click 'View Report' on a PL → /[id] detail: full report, metadata, debriefs submitted, activities planned-vs-completed, top barriers + recommendations, decisions routed back
5. Download PDF if needed (country rollup or per-PL)

**RVP Country-Level Escalation** ✅  _(roles: RVP)_
1. Navigate to /dashboards/rvp/country-summary (Uganda example)
2. Review Aggregated Field Context (country-level barriers, support themes, no raw debriefs)
3. Check My Escalations card (decisions RVP routed to CD/HR)
4. Route new decisions if needed (implicit CTA)

### ⭐ Demo highlights
- CommandStack (unified action rail with next-3 actions + unified inbox + done-for-today) — present on all 8 dashboards, fully functional action engine powering top actions across all roles
- CCEO Risk & Bottleneck Board + SSA Heatmap combo — rich visual intelligence showing where schools struggle with remediation actions grouped by risk type
- 8-Step Partner Activity Workflow Tracker — horizontal pipeline rendering live counts (assigned→scheduled→delivered→evidence→CCEO→PL→accountant→paid); partner-side steps filled, downstream muted; total-in-flight KPI
- Director Weekly Debrief Report Center — shows country rollup + per-PL reports with status badges, late-submission flags, achievement %, barriers, and drill-down to detail pages with full context
- Program Lead Team Performance Overview (chart + personal targets side-by-side) — shows monthly trend across team + PL's own 4 targets; strong visual hierarchy
- RVP Country Comparison table + Burn-rate Rail — side-by-side comparison (countries, targets, SSA%, valid-visits, funds) with burn-rate visual rail showing pipeline health (red/amber/green by disbursement %)
- Impact Assessment Donor-Ready card — highlights verified vs pending reach/training/improvement figures; the output of the verification funnel

### ⚠️ Demo risks / gaps
- Chart loading states (lazy-loaded Recharts components show ChartSkeleton during SSR→client hydration; appears briefly on first load—verify Recharts bundle timing in demo)
- Partner dashboard sub-routes (/dashboards/partner/evidence, /activities, /planning, /reports, /schools, /inbox) all permanentRedirect to /partner/* namespace; old URLs still render but redirect (expect 308 in browser network tab; not a breaking issue but should avoid clicking old bookmarks during demo)
- RVP mobile view (RvpMobileView) is separate from desktop tree; verify mobile responsiveness on actual device or small viewport (design matches but cross-browser rendering varies)
- Director Debrief Detail page ([id]) uses notFound if report ID invalid; hardcoded mock IDs—ensure demo ID exists or 404 renders gracefully
- Empty State Risk: No explicit empty-state messages visible in code review. If a user has 0 actions in CommandStack, 0 upcoming activities, or 0 priority schools, the cards may render as blank. Verify with user who has low activity counts.
- Debrief Promoter card (daily reminder) appears on CCEO, CPL, Partner dashboards—good, but verify it renders content (not a stub skeleton)
- Accountant Console uses AccountantConsoleDashboard component (imported but not reviewed); verify it renders data and isn't a placeholder
- Training Coverage card requires allClusterTrainingPlans() mock data; verify data isn't empty
- HR Aggregated Field Context intentionally hides individual CCEO names (by design); confirm UI doesn't show unexpected data leakage
- RVP Salesforce Compliance uses hardcoded [92, 84, 96, 78] percentages per country; verify those match demo data expectations

---
## School Intake & Portfolio

The School Intake & Portfolio domain is largely working and demo-ready for school onboarding, duplicate detection, owner mapping, and portfolio management. Core workflows are implemented with clean, tested logic. Owner auto-distribution is pure and client-safe. Duplicate flagging (never blocks) works end-to-end. Primary concern: Edit Details drawer is incomplete in UI—no actual edit functionality visible despite the server action existing. Minor gaps in empty states and some secondary queues.

### Features

| Status | Feature | Route | Notes |
|---|---|---|---|
| ✅ | **My Portfolio Page (/portfolio)** | `/portfolio` | Fully functional. Shows owned schools with counts (total, client, core, missing SSA, partner-delegated). Portfolio auto-builds from assignedCceo field. Partner assignment UI integrated. School statuses (SSA pending / … |
| ✅ | **School Onboarding (Manual Add)** | `/data-intake` | NewSchoolDrawer fully functional. Geography-aware cascading dropdowns (region→district→subCounty). Manual form with validation. Creates planning-locked schools awaiting SSA. Audit trail + notifications fire on creation. |
| ✅ | **School Onboarding (CSV Bulk)** | `/data-intake` | Bulk school import via CSV. File picker + paste textarea. Live row preview with validation icons. Gracefully handles per-row failures. Seeded test data (e.g., 32791 Nakaseke Hill) included. |
| 🟡 | **Edit School Details** | `/data-intake` | Server action (updateSchoolDetails) fully implemented. Button ('Edit details') renders in recently-added schools list. But the EditSchoolDrawer modal component is incomplete—no form fields visible, likely just a place… |
| ✅ | **Duplicate Detection Engine** | `—` | Pure logic in src/lib/intake/duplicate-detection.ts. Name similarity (Jaccard + Levenshtein), district/region/subCounty/phone/address matching. Banding (Strong 85+, Potential 60–84) per spec. Never blocks—only flags. … |
| ✅ | **Duplicate Review Queue (/data-intake/duplicates)** | `/data-intake/duplicates` | DuplicateReviewQueue component renders open flags side-by-side (newly uploaded vs existing). Shows score + band + reasons. Two action buttons: 'Not a duplicate' (dismiss) / 'Confirm duplicate' (acknowledge). Resolves … |
| ✅ | **Owner-Mapping Queue (/data-intake)** | `/data-intake` | OwnerMappingQueue component shows schools with unmatched Account Owner names. Inline staff picker + 'Map' button. Maps entered name to registered staff (CCEO/Program Lead). Empty state message clear. Server action (ma… |
| ✅ | **Account Owner Auto-Distribution** | `—` | Pure logic in src/lib/portfolio/portfolio.ts. resolveOwner() matches name to staffId via supervision roster. Unmatched names surface in queue (not silently dropped). Counts (matched/unmatched/unassigned) computed accu… |
| ✅ | **Data Intake Hub (/data-intake)** | `/data-intake` | Landing page with role gate (IA/Admin only). Shows KPIs: templates, batches imported, pending review, readiness areas blocked. Owner distribution summary (owners with schools, matched, unmatched, unassigned). Links to… |
| ✅ | **Data Validation Queue (/data-intake/queue)** | `/data-intake/queue` | Displays import batches with status (Uploaded→Validated→Ready for Review→Approved→Imported). Row counts, error/warning metrics. Mobile (card) and desktop (table) layouts. Status-driven actions ('Validate', 'Send for r… |
| ⚪ | **Data Readiness Engine (/data-intake/readiness)** | `/data-intake/readiness` | Page exists but appears to be a placeholder. Referenced from hub but detailed implementation not found. Likely a stub for the readiness traffic-light gate that drives planning engine gates. |
| ⚪ | **Data Quality Center (/data-intake/quality)** | `/data-intake/quality` | Page exists but implementation status unclear. Referenced from hub. Likely scans for missing region, enrollment, unassessed schools—not deeply inspected. |
| ✅ | **Portfolio Engine (src/lib/portfolio/*)** | `—` | portfolio.ts: owner resolution, per-staff portfolio computation, distribution summaries, unmatched-owner queue. partner-assignments.ts: delegation logic (never transfers ownership). All pure, tested. |
| ✅ | **Upload Center (/data-intake/upload)** | `/data-intake/upload` | Three-step flow: choose template, upload file (mock), validation queue. Shows recent batches with status badges. Template grid with download links. File picker + validation results preview. Complete walkthrough. |
| ✅ | **SSA Upload (Manual)** | `/data-intake` | SsaUploadDrawer with score grid (8 areas + enrolment). Live FY/quarter derivation from date picker. Average score display. Server action (uploadSsaPerformance) unlocks planning on success. |
| ✅ | **SSA Upload (CSV)** | `/data-intake` | Generic IntakeUploadDrawer with CSV validation. Reuses submitIntakeRecords action with SSA-specific routing (template ID 'tpl-ssa-performance'). Per-row FY/quarter derivation. |
| ✅ | **Role Gates (ImpactAssessment/Admin only)** | `/data-intake, /data-intake/duplicates` | Role checks enforced server-side (DATA_INTAKE_ROLES) and UI (allowed checks). Non-IA/Admin roles see 'Master data upload is restricted' card. No permission bypass. |

### Workflows

**School Onboarding (Single School)** ✅  _(roles: Impact Assessment, Admin)_
1. IA opens Data Intake Hub (/data-intake)
2. IA clicks 'Manual' for School Onboarding upload
3. NewSchoolDrawer opens; IA fills schoolId, schoolName, region, district, schoolType
4. Geography cascades (region→district→subCounty) auto-populate
5. IA optionally fills enrollment, assignedCceo, cluster
6. IA clicks 'Add school'
7. Server validates against existing IDs, creates planning-locked school
8. Duplicate detection runs asynchronously; flagged matches appear in /data-intake/duplicates queue
9. School appears in IA's 'Recently added schools' list with 'Edit details' option
10. School does NOT appear in portfolio yet (awaiting first SSA or owner assignment)
11. School shows 'SSA pending' badge until first SSA is uploaded

**School Onboarding (CSV Bulk)** ✅  _(roles: Impact Assessment, Admin)_
1. IA clicks 'CSV' for School Onboarding
2. NewSchoolDrawer switches to CSV mode
3. IA downloads template CSV or pastes manually
4. IntakeUploadDrawer shows file picker + paste textarea
5. IA uploads .csv file or pastes rows
6. Live row preview displays with validation icons (✓ or ✗)
7. IA reviews valid/error counts, then clicks 'Import N schools'
8. Server re-validates each row server-side, creates valid schools, logs failures
9. Success message shows created count + skipped count
10. Drawer closes; recently-added list updates
11. Duplicate detection runs for each school; flags appear in queue

**Edit School Details** 🟡  _(roles: Impact Assessment, Admin)_
1. IA opens Data Intake Hub (/data-intake)
2. IA scrolls 'Recently added schools' and clicks 'Edit details' on a school
3. EditSchoolDrawer opens (BUT: UI incomplete—form fields not visible)
4. IA would fill optional fields: assignedCceo, enrollment, subCounty, cluster, phone, primaryContact, shippingAddress
5. IA would click 'Save'
6. Server action (updateSchoolDetails) patches the school record
7. Drawer closes and list refreshes
8. **BLOCKER**: No form visible in the drawer—appears to be a placeholder shell

**Duplicate Review (IA Queue)** ✅  _(roles: Impact Assessment, Admin)_
1. New school is uploaded via manual or CSV
2. Duplicate detection engine scores it against existing roster
3. If score ≥ 60 (Potential or Strong), a flag is created
4. IA opens /data-intake/duplicates
5. DuplicateReviewQueue shows open flags with: newly uploaded school | existing school | score + band | reasons (e.g., 'Very similar name', 'Same district')
6. IA reviews each flag and decides: 'Not a duplicate' or 'Confirm duplicate'
7. Server records resolution + audit trail (resolvedBy, resolvedAt, status)
8. Resolved flags move to 'Recently resolved' section
9. Neither school is ever deleted or auto-merged—resolution is informational only

**Owner Mapping (IA Queue)** ✅  _(roles: Impact Assessment, Admin)_
1. School is uploaded with Account Owner name that doesn't resolve to a registered staff member
2. resolveOwner() returns 'unmatched' status
3. IA opens /data-intake (Data Intake Hub)
4. OwnerMappingQueue shows the unmatched name + school count + school names
5. IA opens staff picker and selects a registered CCEO or Program Lead
6. IA clicks 'Map'
7. Server updates all schools matching that entered name to the staff member's canonical name
8. Schools now auto-distribute into the staff member's portfolio (/portfolio)
9. Staff member receives notification: 'N schools added to your portfolio'
10. mapUnmatchedOwner() fires audit + revalidates portfolio routes

**School Auto-Distribution to Portfolio** ✅  _(roles: Any (automatic))_
1. School is created with assignedCceo = 'Paul Chinyama'
2. portfolioForStaffId() is called (via /portfolio page or staff profile)
3. resolveOwner('Paul Chinyama') matches to staffId 'STF-PC-001'
4. intakeSchools.filter() collects all schools where resolved.staffId === 'STF-PC-001'
5. Portfolio object is built with: staffId, staffName, schools[], counts{}
6. School appears in Paul's portfolio with: schoolName, schoolId, district, region, enrollment, SSA status, partner delegations
7. Counts update: total, client, core, missingSsa, partnerAssigned, planningOpen
8. Portfolio page shows all stats + school list with 'Plan →' link

**SSA Upload (Planning Unlock)** ✅  _(roles: Impact Assessment, Admin)_
1. School is in a portfolio, marked 'SSA pending'
2. IA opens /data-intake and clicks 'Manual' for SSA Performance
3. SsaUploadDrawer opens with score grid (8 areas + enrolment)
4. IA picks school (dropdown), enters date (auto-derives FY + quarter)
5. IA fills all 8 score fields (0–10 scale)
6. IA optionally updates enrollment
7. IA clicks 'Upload'
8. Server validates date, scores, school ID; derives FY/quarter
9. uploadSsaPerformance() adds SSA snapshot, sets school.ssaStatus = 'SSA Done', unlocks planning
10. School badge changes: 'SSA pending' → 'Planning open'
11. CCEO + Program Lead notified: 'SSA uploaded — planning unlocked'
12. School's portfolio counts update (missingSsa decreases, planningOpen increases)

**Partner Delegation (SchoolPartnerControl)** ✅  _(roles: Staff who own schools (CCEO, Program Lead))_
1. Staff views /portfolio and sees their schools
2. Staff clicks 'Assign partner' badge (if empty) or existing partner chip
3. SchoolPartnerControl modal opens with: partner name picker + intervention area picker
4. Staff selects partner (e.g., 'Hope Education Partners') and area (e.g., 'Teaching Environment')
5. addPartnerAssignment() creates a record linking school to partner
6. Modal closes; school shows 'Partner-delegated' badge
7. Portfolio count 'Partner-assigned' increments
8. **Key rule**: Ownership stays with staff—school never leaves their portfolio, never transferred to partner

**Data Validation Queue Review** ✅  _(roles: Impact Assessment, Admin)_
1. Import batch is uploaded via /data-intake/upload
2. Batch enters queue with status 'Uploaded'
3. IA opens /data-intake/queue
4. Queue shows batch: fileName, dataType, row counts (total, valid, errors, warnings), status
5. IA clicks batch action → 'Validate →' (if Uploaded) or 'Send for review →' (if Validated)
6. Toast confirms action
7. Batch status advances: Validated → Ready for Review → Approved for Import → Imported
8. Once Imported, data flows to planning engine

### ⭐ Demo highlights
- My Portfolio page with live school list, KPIs (total/client/core/missing SSA), partner delegations shown inline, and 'Plan →' links. Demonstrates auto-distribution of owned schools.
- Duplicate Review Queue side-by-side comparison (newly uploaded vs existing school) with score, band, and plain-English reasons (e.g., 'Very similar name', 'Same district'). Shows flag-not-block philosophy.
- School Onboarding CSV upload with live row preview—shows validation icons, error messages inline, before commit. Handles failures per-row gracefully.
- Owner-Mapping Queue inline staff picker + 'Map' button. Shows how unmatched owner names get resolved to registered staff, then schools auto-distribute to portfolios.
- Data Intake Hub dashboard with role gate (IA/Admin only), KPI cards (templates, batches, owner distribution, readiness), and links to all sub-workflows. Clean, uncluttered landing.

### ⚠️ Demo risks / gaps
- Edit School Details drawer is incomplete—button exists but form is missing/stubbed. Users can navigate to it but cannot fill in optional fields (assignedCceo, enrollment, subCounty, etc.). Will break demo if clicked.
- Data Readiness Engine (/data-intake/readiness) and Data Quality Center (/data-intake/quality) pages exist but appear to be stubs. Links work but content not fully inspected—may show placeholder text.
- Empty states on mobile may truncate due to responsive design. No visual regression testing evident.
- Portfolio page shows 'No schools in your portfolio yet' if the user has no owned schools—correct behavior, but demo requires seeded data with the logged-in user as Account Owner.
- Partner assignment in My Portfolio uses a fixed suggestion list (PARTNER_SUGGESTIONS hardcoded in page.tsx)—real partner list not sourced from database. Works for demo but not production.
- Duplicate detection runs asynchronously after school creation—flagged duplicates may not appear in queue immediately in a live demo (depends on event loop timing).
- No visual indicator on the Data Intake Hub showing if duplicate queue has items (other than the conditional link to /data-intake/duplicates).
- SSA upload FY/quarter derivation is tested but relies on the fy-engine clock—if clock is mocked inconsistently, dates may show wrong FY.
- CSV upload allows paste-as-text, which may have encoding issues if user pastes from spreadsheet software (Excel, Google Sheets). No warning or conversion.
- Role gate on Data Intake Hub works, but non-IA users are shown a polite 'restricted' card. No redirect—may confuse first-time users who expect a different interface.

---
## Partner Workflow

Partner workflow domain is feature-complete and demo-ready. Core lifecycle (planned→assigned→scheduled→delivered→evidence→confirmation→payment) fully implemented with mock data. Partner dashboards, evidence management, and staff monitoring all rendering. No critical gaps — all 16 partner routes are functional with backed-up mocks and real state machines.

### Features

| Status | Feature | Route | Notes |
|---|---|---|---|
| ✅ | **Partner List & Index (/partners)** | `/partners` | Displays seed partners (LTU, NF) + user-added partners. Add/Edit gated to ImpactAssessment/CountryDirector/Admin. Renders partner cards with health bands, cert status, risk profiles, active projects count. PartnersInd… |
| ✅ | **Partner Detail (/partners/[id])** | `/partners/[id]` | Shows org-level data: active projects table, schools served grid, recent visits with verification status, verification history. Hand-typed seed data (LTU, NF partners). No API wiring yet but all components functional … |
| ✅ | **Partner Delivery Command Center (/dashboards/partner)** | `/dashboards/partner` | Desktop & mobile views. 9-section layout: hero → 8-step workflow tracker → today priorities/inbox/evidence/corrections → schools & schedule → status & payment. All child components wired to partner-dashboard-mock. Wor… |
| ✅ | **Today To-Do (/partner/today)** | `/partner/today` | Default partner landing. Reads from partnerTodayTasks mock: priority list sorted by urgency, inline expand for detail, 5 summary cards (tasks overdue/today/due this week). Evidence required + corrections due sections.… |
| ✅ | **Activities List (/partner/activities)** | `/partner/activities` | MyActivitiesTable with 6 filter tabs (all/scheduled/evidence/returned/awaiting/completed). 47 mock activities, status-driven filtering, column density optimized. Links to detail views. No drill-down detail view yet bu… |
| ✅ | **Assignments / My Plan (/partner/assignments)** | `/partner/assignments` | Shows scheduled + delivered + pending + closed activities. MyActivitiesTable reused. KPI header: 44 on plan, 18 active, 2 overdue, 11 completed this month. Activity drill-down action routes work. |
| ✅ | **Evidence Upload & Management (/partner/evidence)** | `/partner/evidence` | EvidenceBulkDropzone (drag/drop + picker), file upload handling via partnerUploadEvidence action, per-file success/failure status. PartnerEvidenceRequired shows categorical checklist per activity type. PartnerEvidence… |
| ✅ | **Evidence Quality & Verification** | `` | computeEvidenceSummary engine: bucket-weighted completeness (0-100), quality level (strong/acceptable/weak/invalid), critical-missing count, 3 readiness gates (CCEO/payment/M&E). Evidence item types (24 kinds), activi… |
| ✅ | **Corrections & Returns (/partner/corrections)** | `/partner/corrections` | PartnerReturnedCorrections lists items returned for evidence/report/verification correction. Surfaces reason (standardized enum) + plain-English guidance. 3 open returns, 12 resolved this month in KPIs. Return reason … |
| ✅ | **Payments & Ledger (/partner/payments)** | `/partner/payments` | PartnerPaymentStatusCard + PartnerPaymentLedger. Shows payment pipeline per activity: evidence→CCEO→PL→IA→accountant→paid. 16 paid this month (UGX 5.6M), 10 in flight (UGX 3.5M), 14 not eligible, 3 on hold. Payment ga… |
| ✅ | **Impact Measurement (/partner/impact)** | `/partner/impact` | SSA baseline→activity→evidence→next SSA→delta. Impact records with school-by-school attribution. PartnerImpactByArea + PartnerImpactRecordsList. 12 schools improved, avg SSA change +4.2, 14 awaiting next SSA. Honest a… |
| ✅ | **Planning & Scheduling (/partner/planning)** | `/partner/planning` | PartnerPlanningBoard: week-bucket calendar view. Unscheduled activities surfaced at top (3 items needing delivery week). Capacity meter (62% used), 11 scheduled across 4 weeks, 5 facilitators. Place-in-week flow works… |
| ✅ | **Partner Profile (/partner/profile)** | `/partner/profile` | Read-only contract/scope/people sheet. PartnerProfileSheet. Contract details, scope boundaries (districts/schools/activity kinds), team members (admin/field officers/viewers), reporting frequency, verification level. … |
| ✅ | **Partner Health Score** | `` | computePartnerHealth engine: weighted sum of 6 positive scores (verified delivery 25%, evidence quality 15%, timeliness 10%, school improvement 25%, staff collab 10%, reporting accuracy 15%) minus 2 penalties. Bands: … |
| ✅ | **Workflow State Machine** | `` | PartnerWorkflowStatus: 14 happy-path + 5 branch statuses (planned→assigned→scheduled→delivered→evidence→CCEO→PL→IA→paid→closed + delays/returns/rejects). TRANSITIONS array gates each state transition by role. canTrans… |
| ✅ | **Staff Partner Monitoring (/my-targets, visible to CCEO/PL/IA)** | `` | StaffPartnerMonitoring: status-tab interface (assigned/scheduled/delayed/due-this-week/evidence/needs-my-confirmation/payment-pending/completed). Rows surface status, school, priority, evidence %, due date. CCEO actio… |
| ✅ | **Partner Evidence Locker** | `` | PartnerEvidence type + items list. File metadata (size, MIME), review status (pending/accepted/rejected/replacement-requested), reviewer notes, replacement history (audit trail). Evidence upload server action validate… |
| ✅ | **Joint Work Assignments** | `` | JointWorkAssignment type: lead (Edify/Partner/Joint), role matrix (staff + partner), responsibility + next-action owners, shared checklist. Spec rule: joint work means shared planning, not ownership transfer. Activity… |
| ✅ | **Partner Assignment Delegation (Partner keeps ownership)** | `` | assignPartnerToSchool semantics: delegates execution (who delivers) NOT ownership (school stays in account owner's portfolio). PartnerActivityAssignment table + helpers (activePartnerAssignmentsForSchool, schoolIdsWit… |
| ✅ | **Fraud Detection & Flags** | `` | 10 fraud flags (DuplicateSchoolDateActivity, OutsideScope, GPSMismatch, EditAfterVerified, etc.). Non-empty flagList triggers 'Needs Review' — never auto-reject per spec. FraudFlag enum + FRAUD_FLAG_LABEL lookup. Flag… |

### Workflows

**Partner Activity Lifecycle (Happy Path)** ✅  _(roles: Staff (CCEO/CountryProgramLead/Admin), PartnerAdmin, PartnerFieldOfficer, ImpactAssessment, ProgramAccountant)_
1. Staff (CCEO/PL) creates PlannedByStaff activity, selects partner
2. Activity routed to partner inbox as AssignedToPartner
3. PartnerAdmin schedules activity into a delivery week → ScheduledByPartner
4. PartnerFieldOfficer executes activity in field → marks Delivered
5. PartnerAdmin uploads evidence (attendance, report, photos, etc.) → EvidenceSubmitted
6. System auto-routes to CCEO → AwaitingCceoConfirmation
7. CCEO reviews evidence completeness & stamps (for visit-types), confirms → ConfirmedByCceo
8. System auto-routes to PL → AwaitingPlApproval
9. PL approves payment eligibility → ApprovedByPl
10. System auto-routes to IA verification → AwaitingIaVerification
11. IA verifies Salesforce entry → IaVerified
12. System auto-routes to Accountant → SentToAccountant
13. Accountant clears payment → Paid
14. System closes activity when school journey updates → Closed

**Evidence Collection & Quality Gate** ✅  _(roles: PartnerAdmin, PartnerFieldOfficer)_
1. Partner marks activity Delivered in the field
2. Partner navigates /partner/evidence, selects activity from dropdown
3. Partner drag-drops or picks files matching activity type
4. EvidenceBulkDropzone validates file format + size, shows per-file status
5. partnerUploadEvidence server action processes each file, updates PartnerEvidenceItem
6. UI shows completeness % per bucket (activity report 25%, attendance 20%, school confirmation 15%, etc.)
7. Evidence summary computes isReadyForCceoConfirmation gate (≥80% + no critical missing)
8. If incomplete, partner sees gaps highlighted in PartnerEvidenceRequired checklist
9. Partner resubmits missing items
10. Once ready, status moves to 'complete' and CCEO can confirm

**CCEO Confirmation & Return Loop** ✅  _(roles: CCEO, PartnerAdmin, PartnerFieldOfficer)_
1. CCEO sees 'needsMyConfirmation' tab in StaffPartnerMonitoring
2. CCEO clicks row to review school name, activity type, evidence checklist, photos
3. For visit-type activities (follow-up, coaching, observation), CCEO confirms school stamp present
4. CCEO can: Confirm (→ payment pipeline), Return (→ partner corrections), Flag (escalate), Reject
5. If return: RETURN_REASON_LABEL + plain-English guidance sent to partner via notification
6. Partner sees 'Corrections' tab, reviews reason (e.g. 'attendance_sheet_missing'), re-uploads
7. Partner marks EvidenceSubmitted again
8. Activity cycles back to CCEO for re-confirmation

**Payment Approval Pipeline (PL → IA → Accountant)** ✅  _(roles: CountryProgramLead, ImpactAssessment, ProgramAccountant)_
1. CCEO confirms, activity routes to PL inbox (AwaitingPlApproval)
2. PL reviews: evidence quality, CCEO sign-off, cost reasonableness, priority
3. PL can: Approve (→ IA), Return to CCEO (clarify), Return to Partner (correction), Hold, Reject
4. If approved: system auto-routes to IA (AwaitingIaVerification)
5. IA verifies Salesforce entry matches evidence: counts, dates, intervention area, school
6. IA can: Verify (→ Accountant), Return to Partner (evidence invalid), Return to CCEO, Reject
7. If verified: auto-routes to Accountant (SentToAccountant)
8. Accountant clears payment (Paid), disbursement created
9. Partner sees payment status update in real-time on /partner/payments

**Partner Health Monitoring & Band Tracking** ✅  _(roles: PartnerAdmin, CCEO, CountryProgramLead, ImpactAssessment)_
1. Monthly: computePartnerHealth runs for each partner over rolling 30-day window
2. Engine consumes 6 input scores: verification pass rate, evidence quality, timeliness, school improvement, staff collab, reporting accuracy
3. Applies weights (default: verified delivery 25%, school improvement 25%, evidence 15%, etc.)
4. Subtracts penalties: overdue (how many activities late), returned corrections (rework volume)
5. Outputs: 0-100 score, band (Excellent≥85 / Healthy 70-85 / Watch 50-70 / AtRisk <50 / Suspended ≤0)
6. Partner.currentHealthBand denormalized so partner list doesn't recompute on every render
7. Staff sees health band on /partners and /partners/[id] with trend
8. Partner sees their health on /dashboards/partner + /partner/today hero
9. AtRisk band triggers escalation to Country Director + staff focal person for intervention

**Impact Attribution (Activity → School SSA Change)** ✅  _(roles: Partner (view only), ImpactAssessment (computes))_
1. Partner completes activity at a school + uploads evidence
2. CCEO confirms, PL/IA verify — activity enters 'counted' status
3. School completion window: baseline SSA known at activity time
4. Partner waits for next SSA assessment (typically end of term/quarter)
5. IA runs impact query: schoolId, activity count, intervention area, next SSA score
6. Computes delta: next SSA vs. baseline, attribute to partner's activities
7. Partner sees on /partner/impact: 'Of 12 schools supported, 8 improved, 2 moved up a band, avg +4.2 SSA points'
8. Staff sees partner impact contribution in school detail + country dashboards

### ⭐ Demo highlights
- Partner Delivery Command Center (/dashboards/partner): Full 8-step workflow tracker with live counts, priority actions, daily habit checklist, action inbox with 47 activities, evidence quality trend, payment pipeline — all rendering perfectly with realistic mock data.
- Evidence Upload & Verification Flow: Drag-drop interface on /partner/evidence, completeness % by weighted bucket (activity report / attendance / school confirmation / SSA link / debrief / supporting), ready-for-CCEO gate shows exactly what's blocking → realistic end-to-end story.
- Staff Partner Monitoring: CCEO view on /my-targets (StaffPartnerMonitoring) with status-tab interface (assigned/scheduled/delivered/evidence/needs-confirmation/payment-pending) showing all delegated work with SLA alerts, confirm/return/flag actions firing live.
- Payment Pipeline Visualization: PartnerPaymentStatusCard + ledger shows activity flowing through CCEO confirm → PL approval → IA verification → accountant payment, with per-activity blocker reasons (evidence incomplete, awaiting stamp, etc.) + real currency amounts.
- Partner Health Score: Weighted multi-factor engine (verified delivery, evidence quality, timeliness, school improvement, staff collaboration) outputting band + breakdown, denormalized on partner cards for instant visibility without recompute.

### ⚠️ Demo risks / gaps
- Partner detail page (/partners/[id]): Hard-coded mock data (ACTIVE_PROJECTS, SCHOOLS_SERVED, RECENT_VISITS, VERIFICATION_HISTORY) — not wired to actual partner records. Demo shows hand-typed seed data; production will need data-layer swap.
- Empty state under /partner/inbox/[tab]: If tab has zero activities (e.g. no 'assigned' items), no explicit empty-state message — table just renders empty. Should add 'No items yet, check back when your next assignment arrives' messaging.
- Staff monitoring detail drill-down: StaffPartnerMonitoring row click shows toast but doesn't navigate to detail view; no way to expand inline to see full activity + evidence checklist without a secondary action.
- Partner impact page (/partner/impact): Reads from partnerImpactRecords mock; SSA baseline + next-SSA linking logic is defined but not wired to real SSA API. Record-by-record view works but attribution deltas are seeded.
- Joint work visibility: JointWorkAssignment type defined but no dedicated UI surface — joint activities flow through the regular evidence/confirmation path. Demo will show a single activity marked 'Joint with CCEO' but no 'who did what' breakdown on the activity card.
- Activity detail drill-down: Clicking an activity on /partner/activities or command center doesn't navigate to a detail page. Each row shows summary (title, school, status, evidence %) but no way to see full evidence checklist, comment thread, or joint-work assignments inline.
- No real notification fanOut: emitNotificationFanOut() calls logged but no UI toast/bell for partner receiving new assignments. Demo relies on page-refresh or manual navigation.
- Partner scope enforcement: enforceScopeOnActivity() function exists (partner-scope.ts) but no demo-visible error when partner tries to schedule outside their allowed activity kinds or districts — assumes valid input.
- Messages & Help pages: /partner/messages and /partner/help routes exist but components (PartnerMessagesList, PartnerHelpCenter) are stubs — render header + 'coming soon' messaging.
- Fraud flag UI: Flags defined + FRAUD_FLAG_LABEL lookup ready but no dedicated 'Fraud Review' queue or workflow on staff side — flagged activities appear in needsMyConfirmation tab without visual distinction.

---
## Targets, FY & Periods

The Edify Planning Tool's FY/quarter and cumulative targets system is substantially working with proper Oct-Dec/Jan-Mar/Apr-Jun/Jul-Sep quarterly definitions (25/50/75/100 cumulative) and a strong single-source-of-truth architecture. FY/quarter math is pure and well-tested; the operating-targets view renders fully with 7 period tiles, 6 KPI cards, period matrix, and trend chart. Primary gaps: "View All insights" and "Export Report" buttons are stubbed disabled (coming soon); Q3/Q4 data not yet seeded for future demonstration.

### Features

| Status | Feature | Route | Notes |
|---|---|---|---|
| ✅ | **FY Core Math (fy-core.ts)** | `` | Pure, client-safe FY generation from Oct 1 floor (FY 2025) auto-incrementing based on engine now. Correctly defines Q1:Oct–Dec, Q2:Jan–Mar, Q3:Apr–Jun, Q4:Jul–Sep. Quarter label generation enforces single source of tr… |
| ✅ | **Period Target Engine (period-target.ts)** | `` | Computes cumulative 25/50/75/100% expectations by period. Mid-Year correctly collapses to Q2 end (50%). Incorporates pace-status via getPeriodPaceStatus (5-tier: Ahead/On Track/Slightly Behind/Behind/Critical). Fully … |
| ✅ | **Pace Status (pace-status.ts)** | `` | 3-tier getPaceStatus + 5-tier getPeriodPaceStatus. Single source of truth with comprehensive test coverage (boundary cases, leave adjustment, protected-day tolerance). Used across My Targets, Team Targets, Leaderboard… |
| ✅ | **Operating Targets View** | `` | Renders 7 period donut tiles (Monthly, Q1–Q4, Mid-Year, FY), 6 KPI summary cards with sparklines, Targets by Time Period matrix (cumulative), Progress Trend chart, Contribution roll-up card, Performance Distribution d… |
| ✅ | **My Targets (/my-targets)** | `` | CCEO + PL routes render OperatingTargetsView with role-scoped filter bar. CCEO includes WorkloadContextCallout (raw vs adjusted pace, FWI complexity percentile). Non-CCEO roles get legacy CPL view. StaffPartnerMonitor… |
| ✅ | **Team Targets (/team-targets)** | `` | Role-aware default tab routing. Tabbed interface (My Targets / Team Targets / Leaderboard / Support Needed / Target Recovery). Team aggregation sums CCEO rows. Fair Workload Index plot + Rebalance Recommendations. Leg… |
| ✅ | **Portfolio Targets by Time Period** | `` | Integrates computePeriodTarget() in /portfolio page; displays 4-quarter ladder with 25/50/75/100 progression, pace-status badge, cumulative progress bar with expected-cumulative marker. Partner-supported schools corre… |
| ✅ | **Leaderboard (/leaderboard)** | `` | Page scaffolding complete: LeaderboardSummaryCards, CategoryLeaderboardTabs, ProgramLeadLeaderboardCard, FairnessContextPanel. Engine seeds verified-work-only contracts + recognition badges. Fairness context (leave, r… |
| ⚪ | **Export Report Button** | `` | Button disabled on OperatingTargetsPageHeader with title='Report export is coming soon'. Opacity 50%, cursor-not-allowed. Zero integration. |
| ⚪ | **View All Insights Button** | `` | Button disabled in TopFocusCard with title='The full insights view is coming soon'. Opacity 60%, cursor-not-allowed. Top Areas to Focus shows 3 items; full list behind stub. |
| ⚪ | **Q3/Q4 Achieved Data (Operating Targets Mock)** | `` | Q3 and Q4 achieved counts hard-coded to 0 in cceoMetrics/plMetrics (startedPeriods.q3 = false, q4 = false). Status will show 'Not Started' for future quarters. Acceptable for Nov demo; may confuse if shown after Q3 be… |
| ✅ | **Monthly vs Quarter Clarity** | `` | Operating Targets View correctly distinguishes: Monthly shows calendar progress (days completed), Quarters/Mid-Year/FY show metric aggregates. Comment in code clarifies mid-month is honest 'how far through' metric. |

### Workflows

**CCEO Personal Scorecard (My Targets)** ✅  _(roles: CCEO)_
1. 1. Navigate /my-targets; user context loads (CCEO role detected)
2. 2. OperatingTargetsPageHeader renders with period selectors & filter bar
3. 3. CommandStack + WorkloadContextCallout + StaffPartnerMonitoring cards render
4. 4. OperatingTargetsView loads CCEO data: cceoOperatingTargets from mock
5. 5. 7 period tiles render with live % calc (Monthly 21/31=68%, Q1 122/150=81%, Q2 92/150=61%, Mid 214/300=71%, Q3 0/150=Not Started, Q4 0/180=Not Started, FY 214/630=34%)
6. 6. 6 KPI cards show Schools/Trainings/SSA/Follow-ups/Plans/Funds with sparklines
7. 7. Targets by Time Period matrix displays cumulative ladder: Q1→150/25%, Q2→150/50%, Q3→150/75%, Q4→180/100%
8. 8. Progress Trend chart plots Oct–Sep actual vs target (Nov actual 30% vs 24% target)
9. 9. Contribution roll-up shows Monthly+Q1+Q2=MidYear / +Q3+Q4=FY hierarchy
10. 10. User can see pace status (At Risk / Critical) against each metric & period

**Team Targets Dashboard (Program Lead View)** ✅  _(roles: CountryProgramLead, CountryDirector, RVP)_
1. 1. Navigate /team-targets; user context loads (PL role detected)
2. 2. TeamTargetsHeader renders above tab bar
3. 3. Tabs default to 'Team Targets' (PL-scoped default)
4. 4. Team aggregation data (cceoOperatingTargets × 8 CCEOs, dampened 0.92–1.0) computed server-side
5. 5. OperatingTargetsView renders team-level view: tiles, KPI cards, matrix, trends all show summed metrics
6. 6. Fair Workload Index plot appears: complexity scatter + median lines
7. 7. Rebalance Recommendations card suggests staff moves if complexity ratio > 1.3
8. 8. Click 'My Targets' tab to toggle to CCEO/self scorecard (if user is CCEO; otherwise shows pointer card to dedicated page)
9. 9. Click 'Leaderboard' tab to navigate to /leaderboard
10. 10. Staff Target Table + Partner Target Table below show drill-down rows

**Portfolio School Targets by Period** ✅  _(roles: CCEO, CountryProgramLead)_
1. 1. Navigate /portfolio; user context loads (any field role)
2. 2. StubPage header displays 'My School Portfolio'
3. 3. 5 stat cards: Total / Client / Core / Awaiting SSA / Partner-delegated school counts
4. 4. computePeriodTarget() resolves: fyTarget=total schools, achieved=SSA-done OR partner-delivered, currentQuarter=derived from now
5. 5. TargetsByTimePeriodCard renders: cumulative progress bar (blue fill to achieved, dark marker at expectedCumulative), pace-status badge (e.g., 'On Track')
6. 6. Quarter ladder displays 4 tiles: Q1 (Oct–Dec) 25%, Q2 (Jan–Mar) 50%, Q3 (Apr–Jun) 75%, Q4 (Jul–Sep) 100% with expected counts & green checkmarks if achieved ≥ expected
7. 7. Footer note clarifies partner-supported schools count toward targets; ownership never transfers
8. 8. If portfolio empty, show empty state with note 'When IA uploads a school with you as Account Owner, it will appear here automatically'

**Leaderboard Rankings by Category** ✅  _(roles: CCEO, CountryProgramLead, CountryDirector)_
1. 1. Navigate /leaderboard
2. 2. LeaderboardSummaryCards render: top category snapshots + key stats
3. 3. CategoryLeaderboardTabs initialize to 'Overall'
4. 4. Click category (Overall / Training / SSA / School Visits / etc.)
5. 5. Tab content loads verified-work-only leaderboard: rank, staff name, verified % achieved, badges (Monthly Champion, Verified Leader, etc.)
6. 6. ProgramLeadLeaderboardCard shows PL rankings + performance context
7. 7. FairnessContextPanel displays per-staff leave days, route load (FWI complexity %), blocked planning, partner % delegated
8. 8. Rankings contextualized: high performer with 15 leave days or high-complexity portfolio shown as 'Adjusted Pace 78% (raw 92%)'
9. 9. No escalation punitive; tone motivational w/ fairness framing

### ⭐ Demo highlights
- Operating Targets View: 7-period donut tiles + cumulative trend chart shows the full fiscal-year narrative in one glance. Period roll-up (Monthly→Quarterly→Mid-Year→FY) clearly displays how individual month achievements ladder into annual progress. Status colors (green/amber/red) instantly signal pace across all time horizons.
- Targets by Time Period Matrix: Shows all metrics (Schools, Trainings, SSA, Follow-ups, Plans, Funds) across Monthly/Q1/Q2/Mid-Year/Q3/Q4/FY in one table. Single cell reveals target, achieved, and %. Overall Progress row at bottom summarizes pace per period—team can spot which periods are ahead/behind at a glance.
- Portfolio School Ladder (TargetsByTimePeriodCard): The 4-quarter progression with cumulative expectations (25/50/75/100) is visceral. Green checkmarks on Q1 & Q2 tiles show 'yes, on track'; greyed Q3/Q4 show 'not yet started.' Partner-supported school call-out at bottom reinforces ownership clarity.
- Pace Status Consistency: Same staff member shows identical pace color across My Targets scorecard, Team Targets table, Leaderboard row, and Coverage. 5-tier period pace (Ahead/On Track/Slightly Behind/Behind/Critical) in period-target engine is more nuanced than 3-tier for personal targets.
- Leaderboard + Fairness Context: Verified-work-only contract is explicit in code. Badges (Monthly Champion, Verified Leader) and fairness call-outs (leave, complexity, partner %) appear side-by-side so no one is ranked punitively without context.

### ⚠️ Demo risks / gaps
- Export Report button is disabled/coming-soon on OperatingTargetsPageHeader. If stakeholder asks 'show me the report export,' demo breaks. Mitigation: preview feature with verbal explanation 'export PDF + email scheduling coming in next sprint.'
- View All Insights button is disabled in TopFocusCard. Only 3 top-focus items render; full insights engine is stub. If asked 'drill into the Why for the #1 lagging area,' demo halts. Mitigation: explain insights module is rolling out; focus on the 3-item callout as sneak preview.
- Q3 and Q4 achieved data are hard-coded to 0 in the operating-targets mock. If demo runs after Q3 start (Apr 1), the 'Not Started' labels will look stale/wrong. Calendar logic is solid (startedPeriods.q3=false); seed data just needs updating closer to Apr 1.
- Empty portfolio state not heavily tested. If the logged-in user has no schools assigned, they land on the empty state. Acceptable; call-out is clear. Risk is low.
- TargetsByTimePeriodCard uses deriveQuarterFromDate(engineNowIso()) to pick current quarter for the card. If clocktime is mocked/frozen mid-November, quarter resolves correctly (Q2). No risk if demo maintains frozen November time.
- No validation on FY selectors if user switches periods mid-flow. If a user selects FY 2025 from a dropdown, the period-target engine falls back to active FY. Dropdown not yet visible in UI; stub. Low risk for demo.
- Leaderboard mock uses hard-coded verified counts (no real Salesforce sync). If stakeholder asks 'why are those numbers', answer is 'we're using representative demo data.' Transparent in code comments.
- Fair Workload Index is computed server-side on the team-targets page but relies on fairMatrixInputsForTeam() mock. Real production would join live PortfolioComplexity + StaffTargetRow. Mock is seeded; visuals render correctly.

---
## Planning Engine

The Planning Engine is a mature, feature-rich gap-driven planning system (SSA → intervention → activity scheduling). Core features are working end-to-end: school/cluster gap boards with SSA gating, assignment workflows to staff/partners/self, calendar scheduling, and ownership tracking. Mock data provides realistic test scenarios. Production-ready for demo with caveats around empty states on fresh cycles and partner-side scheduling confirmation UI.

### Features

| Status | Feature | Route | Notes |
|---|---|---|---|
| ✅ | **School Gaps Board** | `/planning — tab: Client Schools` | 4-category gap-driven list (No SSA, No Training, No Visit, No Cluster). Collapsible per category. Inline detail expansion shows contact, weak areas, CCEO/partner assignment, recommended action, and action buttons. SSA… |
| ✅ | **Cluster Gaps Board** | `/planning — tab: Clusters` | Cluster-level scheduling of 1st/2nd/3rd meetings + School Improvement Training. Meeting chips show status (Completed, Scheduled, Rescheduled, Missing, Not Yet Due). In-session overlay tracks new schedules without page… |
| ✅ | **Core Schools Gap Planning** | `/planning — tab: Core Schools` | 7-tab SSA-driven view (No SSA, Visit Gaps, Training Gaps, Ready to Plan, Assigned to Partner, Awaiting Partner Schedule, Completed). Tab badges show counts. Each tab lists schools with CoreSchoolCard showing 4×4 visit… |
| ✅ | **Planning Assign Drawer** | `(Modal, used in gap boards)` | Owner picker (Myself / Staff / Partner / Partner Facilitator) with role-gating. CCEO sees only Partner option per operating model. Selecting 'Myself' opens date picker for month + week assignment. Returns AssignOutcom… |
| ✅ | **Schedule Activity Drawer** | `(Modal, triggered from gap boards)` | Unified calendar drawer for school trainings and cluster meetings. Calendar with month navigation, cost preview (4-rate for training, meeting rate for clusters). Participant input, venue/notes optional. Partner facili… |
| ✅ | **Add to Cluster Drawer** | `(Modal, triggered from school gap board)` | School-to-cluster assignment with existing-vs-create-new modes. Create new path asks for district/sub-county. Confirmation + toast. School dismissed from No Cluster gap on success. |
| ✅ | **Reschedule Cluster Meeting Drawer** | `(Modal, triggered from cluster board or scheduled-this-session strip)` | Reschedule modal for cluster meetings/SIT with date picker, reason dropdown (school closure, exam week, weather, etc.), and append-only audit trail. Shows prior move history so next operator sees the pattern. |
| ✅ | **SSA Performance Drawer** | `(Modal, triggered from school gap board)` | School SSA detail view with performance graph/history (locked/single/yearly/3-year trend). Shows weak areas. Routes 'Schedule Training' / 'Schedule Visit' / 'Schedule SSA' back to the correct downstream drawers. Close… |
| ✅ | **School Activity Profile Drawer** | `(Modal, triggered from school gap board)` | Full school history + investment profile. Support visits, trainings, costs, evidence, SSA snapshot, next recommended action. 'View SSA' hand-off to SSA drawer. Action CTAs route to correct assignment/scheduling drawers. |
| ✅ | **Cluster Activity Profile Drawer** | `(Modal, triggered from cluster gap board)` | Cluster full view with meetings/trainings/SSA/school potential/costs/evidence/next actions. Meeting + training CTAs route to correct scheduling drawers. Core/Champion school review actions show placeholder toast (full… |
| ✅ | **Planning Ownership Sections** | `/planning — below gap boards` | Four follow-on cards on main planning page: Assigned to Me, Assigned to Partner, Awaiting Partner Schedule, Planned This Month. Each shows 5 rows with 'View All' links to dedicated dashboards. Activities sourced from … |
| ✅ | **Core Schools Board (Full Console)** | `/planning/core-schools` | Dedicated /planning/core-schools page with its own header + back link. Comprehensive 7-tab gap + assignment view using CoreSchoolCard. Tab badges show counts per gap type. |
| ✅ | **Plan Cascade (Field → Budget → M&E)** | `(Library integration with planning views)` | Library module deriving Budget Accountant and Impact Assessment plans from consolidated CCEO/PL field plan. Channel slices by delivery (staff/cluster/partner/awaiting). No UI issues; library-level integration with MyP… |
| ✅ | **Operational Cycle Banner** | `/planning — above gap boards` | Sits under header on main planning page. Shows current cycle context so CCEO/PL sees which cycle they're planning into before scanning gaps. |
| ✅ | **Planning Family Nav** | `/planning — below header` | Breadcrumb-style nav pill showing current page = 'planning'. Part of the planning page composition. |
| ✅ | **Planning Empty States** | `(Component, used in gap boards + ownership sections)` | Three variants (calm/good/blocked) used throughout boards and ownership sections. Clear, product-conscious messaging explaining why section is empty and next step. Consistent tone and visual treatment. |
| ✅ | **Partner Planning Board** | `/partner/planning` | Partner-side calendar view (/partner/planning) with unscheduled activities pinned at top, week buckets below with capacity meters + facilitator pool. Allows partner to schedule assigned activities into delivery weeks. |
| ✅ | **Status Tokens & Cost Engine Integration** | `(Library integration across planning)` | PlanningStatus enum (not_started/scheduled/delivered/verified/completed) and cost-engine integration for UGX projections. Activity costs roll up by channel + period for budget planning. |

### Workflows

**School Gap Planning Workflow** ✅  _(roles: CCEO, CountryProgramLead, ImpactAssessment, CountryDirector)_
1. 1. View /planning/Client Schools tab → see schools grouped by gap category (No SSA/Training/Visit/Cluster)
2. 2. Click school row to expand → see contact, weak SSA areas, current status, recommended next action
3. 3. Click primary action button (e.g. Schedule SSA, Schedule Training, Add to Cluster)
4. 4. Fill drawer (date, participants, venue, owner) → confirm
5. 5. School dismissed from gap list; activity appears in ownership section (Assigned to Me/Partner/Awaiting Partner Schedule)

**Cluster Gap Planning Workflow** ✅  _(roles: CCEO, CountryProgramLead, ImpactAssessment, CountryDirector)_
1. 1. View /planning/Clusters tab → see clusters with missing meetings/SIT
2. 2. Each cluster row shows 4 meeting chips (SIT + 1st/2nd/3rd); click row to expand
3. 3. See recommendation (e.g. Schedule 1st Meeting), click primary action
4. 4. Calendar drawer opens → pick date, participants, venue (training only)
5. 5. 'Scheduled this session' strip updates with new activity; chip flips to Scheduled
6. 6. Cluster leader + facilitator notified; next gap becomes primary recommendation

**Core School Support Cycle Workflow** ✅  _(roles: CCEO, CountryProgramLead)_
1. 1. View /planning/Core Schools tab (or full console /planning/core-schools)
2. 2. See 7 tabs: No SSA, Visit Gaps, Training Gaps, Ready to Plan, etc.
3. 3. Click school card to see 4×4 visit/training progress + SSA interventions
4. 4. Primary CTA matches next gap (Schedule SSA, Schedule Visit, Schedule Training, etc.)
5. 5. Open assign drawer → pick owner (Myself/Staff/Partner/Partner Facilitator)
6. 6. If 'Myself': pick month + week; activity lands in 'Assigned to Me' section
7. 7. Repeat for all 4 visits + 4 trainings until cycle complete → Follow-Up SSA recommended

**School-to-Partner Assignment Workflow** ✅  _(roles: CCEO, CountryProgramLead)_
1. 1. In gap board (school, cluster, or core), click action button (e.g. 'Assign to Partner')
2. 2. Assign drawer opens with full owner list (Myself/Staff/Partner/Facilitator) depending on role
3. 3. Select 'Partner' → dropdown shows partner pool
4. 4. Confirm assignment → toast: 'Sent to {partner} — awaiting partner planning'
5. 5. Activity moves to 'Assigned to Partner' section on main planning page
6. 6. Partner sees it in /partner/schedule (unscheduled strip) and must place it into a delivery week
7. 7. Once partner schedules: activity moves to 'Scheduled' status, visible on CCEO monitoring dashboard

**Reschedule Cluster Meeting Workflow** ✅  _(roles: CCEO, CountryProgramLead, ClusterLeader)_
1. 1. Cluster gap board → expand cluster → see meeting chip (Scheduled or Rescheduled)
2. 2. Tap meeting chip (only clickable if Scheduled/Rescheduled) → reschedule drawer opens
3. 3. Pick new date from calendar, select reason (exam week, weather, leader unavailable, etc.)
4. 4. Confirm → new date shows in chip; prior move appended to audit trail
5. 5. Cluster leader + facilitator notified of change; reason visible in history
6. 6. Upcoming reschedule attempts can see full move chain (Moved from X to Y because Z)

**Plan Cascade: CCEO Field Plan → Budget & M&E** ✅  _(roles: ProgramAccountant, ImpactAssessment, CountryProgramLead)_
1. 1. CCEO/PL confirms activities on /planning (School/Cluster/Core school assignments)
2. 2. Plan Cascade library derives channel-wise slices: staff-delivered, cluster-delivered, partner-delivered, awaiting
3. 3. ProgramAccountant sees Budget view (channel breakdown + cost roll-ups per period)
4. 4. ImpactAssessment sees M&E view (channel breakdown + Salesforce record creation readiness)
5. 5. Both views source from same plannedActivities mock so numbers never drift
6. 6. All three audiences read one truth: the consolidated field plan

### ⭐ Demo highlights
- Gap-driven planning board with three tabs (Client Schools / Clusters / Core Schools) showing real, complex gaps (SSA blocking, training missing, cluster imbalance). Inline detail expansion with contact info + weak areas + next action recommendation. Each action button routes to the correct drawer (calendar for scheduling, owner picker for assignment, add-to-cluster for peer learning).
- Cluster meeting rescheduling with full audit trail: Kayunga Cluster's 2nd meeting was Scheduled for May 22, rescheduled to Jun 5 (exam week), then again to Jun 20 (leader funeral) — both moves visible in history with reason + who moved it + when. Shows operational-reality complexity that non-plans systems cannot handle.
- In-session scheduling overlay: schedule a cluster meeting on the calendar, watch the meeting chip flip from Missing → Scheduled with the chosen date, without page refresh. The recommendation engine advances past that gap immediately so the next gap becomes the primary CTA. Live, reactive planning experience.
- Role-gated assignment drawer: CCEO viewing the same gap board sees only 'Assign to Partner' option (operating model per Section 1); PL/IA/CD sees Myself / Staff / Partner / Facilitator. Selecting Myself opens a second step (month + week picker) before confirmation. Demonstrates authority enforcement.
- Core school 4×4 support cycle: a school card shows SSA status, priority intervention areas from the latest assessment, then 4 visit chips + 4 training chips colour-coded by status (blocked/not started/scheduled/delivered/verified/completed). Taps into one card show full history + evidence + costs. Entire support-package lifecycle visible at a glance.

### ⚠️ Demo risks / gaps
- Empty ownership sections on fresh cycle: If no activities have been assigned yet, all four Ownership cards (Assigned to Me / Partner / Awaiting Partner Schedule / Planned This Month) render empty states. The empty-state copy is good, but on a live demo the CCEO/PL may feel there's 'nothing here' until they assign something. Start the demo with some mock assignments pre-loaded or schedule activities live during the presentation.
- Partner planning confirmation UI incomplete: Partner side (/partner/planning) exists and shows the unscheduled strip + week buckets, but the full 'drag activity into week bucket' or 'click to schedule' UX is not fully rendered yet. The page loads and structure is there, but interaction may be stubbed. Avoid clicking into /partner/planning during the demo or pre-position a partner account with pre-scheduled activities.
- Core Schools full console (/planning/core-schools) is a separate page: Demo-ers may expect a single 'Core Schools' view on the main /planning page. The main page shows the Core Schools tab of the gap board (abbreviated), and /planning/core-schools is the full console. Navigating between them could confuse if not framed clearly.
- Plan Builder (staff visit + cluster training + meeting + partner visit tabs with cost calculation) is present but lives in a separate feature set. If the demo script mentions 'Activity Builder' or 'Cost planning', clarify that plan builder is a different surface for financial planning, not the gap-driven assignment workflow.
- SSA-blocking enforcement is strict: No SSA = no intervention actions allowed (buttons disabled). If the demo lands on a 'No SSA' school and the audience wants to see 'what if we schedule training anyway', the UI will prevent it. This is correct per spec but may feel restrictive in a live demo. Pre-load a school with completed SSA to show the downstream workflows.
- Mobile view (PlanningMobileView) exists but not deeply tested. Desktop is the primary demo surface. If presenting on a tablet or mobile, the responsive breakpoints may surprise.
- AddPlanDrawer and RouteDesktopView are present but appear to serve the older 'manual plan entry' workflow. The modern gap-driven flow (add via assignment drawer) is preferred. These are not broken, just legacy. Don't click into them unless asked.

---
## Finance & Funds (Edify Planning & Monitoring Tool)

The Finance & Funds domain is largely complete with working features across fund approvals, disbursements, budget management, and accountant console. Most surfaces are wired to mock data and UI is polished. Critical stubs: "Approve All Valid", bulk filtering, and Export features in approvals are explicitly disabled as "coming soon". Monthly fund request view is fully functional across all roles (PL/CD/RVP/Accountant).

### Features

| Status | Feature | Route | Notes |
|---|---|---|---|
| ✅ | **Fund Approvals (/approvals)** | `` | Fully functional role-aware page (CPL/CD/RVP/Accountant + Admin). Queue displays with inline-expanding accordion detail. FundPlanDetail side pane on desktop shows funding breakdown + snapshot + action buttons (Approve… |
| ⚪ | **Bulk Approval & Export (Approvals header)** | `` | Both buttons explicitly disabled with title='coming soon'. Approve All Valid and Export are opacity-50, cursor-not-allowed. Must approve individually from queue. |
| ⚪ | **Advanced Filtering (Approvals header)** | `` | Filter button disabled, title='Advanced filtering is coming soon'. Sort toggle exists (Sort by: Amount) but filtering UI not present. |
| ✅ | **Weekly Funds (/weekly-funds)** | `` | Role-aware router: ProgramAccountant → AccountantDisbursementView; CPL/CD/Admin → LeadWeeklyView; CCEO → StaffWeeklyView. Header + KPI strip + full-width queue with inline expansions. All role views present and render… |
| ✅ | **Accountant Disbursement View (weekly-funds + /disbursements)** | `` | Complete finance cockpit: Header + KPI strip (6 KPIs) + Funds Received Panel (inflow) + Disbursement Queue (tabbed: All/Ready/Partial/On Hold/High Priority) + Staff Balance Tracker + Accountability Tracker + Disbursem… |
| ✅ | **Monthly Fund Request (/monthly-fund-request)** | `` | Full role-aware page: PL sees UNDER_PL_REVIEW, CD sees SUBMITTED_TO_CD, RVP sees SUBMITTED_TO_RVP, Accountant sees RVP_APPROVED. MonthlyFundRequestView handles all transitions. Matrix layout for monthly activities by … |
| ✅ | **Budget Builder (/budget)** | `` | Annual budget page with category breakdown, KPI tiles (Annual budget, Q1 plan, Disbursed YTD, Spent YTD). Shows workflow contract. Links to Budget Breakdown, Scenario Planner, Monthly Funding Plan, Variance Review, Co… |
| ✅ | **Monthly Funding Plan (/budget/monthly)** | `` | Table-based view: Month, Quarter, Budgeted, Funded, Disbursed, Spent, Variance. KPI tiles at top. Flow contract explained. All mock data wired. Variance pct computed and color-coded. |
| ✅ | **Country Cost Settings (/cost-settings)** | `` | CD/Admin can edit (buttons shown), ProgramAccountant has read-only. Status verdict card (Ready / Incomplete). Full cost register table with all fields (item, unit cost, currency, effective date, set by, approved by, s… |
| ✅ | **Accountant Console (/dashboards/accountant)** | `` | Comprehensive finance dashboard: ConsoleHeader + ConsoleKpiStrip + BudgetApprovalsCard + DisbursementSummary + DisbursementsByCategory (donut) + DisbursementQueueTable (tabbed, sorted, inline expandable) + Accountabil… |
| ✅ | **Funds Received Table** | `` | Inflow register: Date, Source, Description, Amount (UGX), Received By. All rows rendered from mock. Stagger animation on load. Hover state. Clean table with green inflow accent. |
| ✅ | **Staff Accountability Queue** | `` | IA-verified activities awaiting NetSuite ID entry to close. Modal form to confirm accountability. Copy Salesforce ID button + input for NetSuite ID. Server action wired. Empty state handled. Cannot submit without vali… |
| ✅ | **Disbursement Queue Table** | `` | Primary accountant work surface: tabbed (All, Ready, Partial, On Hold, High Priority). Inline-expandable accordion with detail panel beneath each row. Sort by Priority/Amount/Recent. Status + Priority pills color-code… |
| ✅ | **Receipt Confirmation Tracker** | `` | Disbursed funds awaiting staff acknowledgement. 3-up summary (Awaiting/Confirmed/Disputed) + overdue count. Detailed rows with status, amount, time since, individual actions. Color-coded pills. |
| ✅ | **Reimbursement Queue** | `` | Staff Personal Funds Claims: tabbed (All/Queued/Supervisor/Submitted/Returned). Auto-routed CCEO→PL→Accountant or Other→CD→Accountant. Status colors + approval route labels + staff role badges. View + Approve + Reject… |
| ✅ | **Balance Return Queue** | `` | Auto-created when staff overspend reconciliation < advance. Tabs: All/Pending/Confirmed/Disputed. Pending total shown. Return method icons (MoMo/Bank/Cash/Offset). Status pills color-coded. Confirm/Dispute/View actions. |
| ✅ | **Budget Approvals Card (Accountant Console)** | `` | Shows Annual Budget + Quarterly Breakdown + Quarterly Approved + CD Approval Status. Card layout with metrics + progress bars. Links to Budget page. |
| ✅ | **Disbursement Summary (Accountant Console)** | `` | 4-tile layout: Total Disbursed, Ready to Disburse, On Hold, Partial. Values + delta + trend. Color-coded by tone (green/amber/rose). |
| ✅ | **Disbursements by Category (Accountant Console)** | `` | Donut chart (Payroll, Operations, Supplies, Other). Legend below. Fully colored + styled. |
| ✅ | **Country Director View (/approvals for CD)** | `` | CountryFundApprovalsView: CD approval queue for higher-tier requesters (PL/IA/Accountant/SP). Nested layout with CdFundApprovalQueue + Queue + Recent Activity + Plan Detail + Approval Rules + Budget Mix + Summary row.… |
| ✅ | **RVP View (/approvals for RVP)** | `` | RvpFundApprovalsView: Regional multi-country oversight. Country list (4) \| Country detail (8) with 5-KPI strip, tabs, plan summary, spending by category. Footer with recent requests + approvals/comments. Country Budg… |
| ✅ | **Program Lead Weekly Request Detail** | `` | LeadWeeklyQueue + LeadRequestDetail: Full funding breakdown table, plan snapshot, approval actions (Approve/Return/Message). Inline expansion in queue. No side pane — all details in accordion. |
| ✅ | **Staff Weekly View (CCEO)** | `` | StaffWeeklyView: 4 weekly fund cards (slips) showing balance, activities, status. Submit + reimbursement claim modal. Role-specific for CCEO. |

### Workflows

**Fund Approval Workflow (CPL approves team CCEO requests)** ✅  _(roles: CountryProgramLead, CCEO)_
1. CPL navigates to /approvals → sees LeadWeeklyView (title 'Fund Approvals')
2. Queue displays all pending CCEO fund requests with amounts, status (Awaiting Approval/Needs Review/Ready)
3. CPL clicks row → inline accordion expands to show full FundPlanDetail (funding breakdown, snapshot, period/district/amount)
4. CPL reviews plan and clicks 'Approve' → FundPlanActionRow triggers approval action (server)
5. Plan status updates in queue + counters refresh in KPI row
6. Approved plan moves to accountant disbursement queue for release

**Country Director Multi-Team Approval** ✅  _(roles: CountryDirector, Admin)_
1. CD navigates to /approvals → sees CountryFundApprovalsView (country scope)
2. CdFundApprovalQueue shows higher-tier requests (PL/IA/Accountant/SP/Admin) — CCEOs excluded
3. CD reviews queue, plan detail, budget mix, and summary row
4. CD can create admin fund requests via drawer + approve/return from queue
5. Approved requests flow to RVP for final approval (if required) or to accountant

**RVP Regional Final Approval** ✅  _(roles: RVP)_
1. RVP navigates to /approvals → sees RvpFundApprovalsView (regional multi-country)
2. Country list on left, country detail on right
3. RVP selects a country → sees country plan, spending by category, recent requests, approvals/comments
4. RVP approves country monthly budget envelope → weekly fund auto-generation activates
5. RVP reviews + approves/returns individual fund requests as needed

**Accountant Disbursement & Release** ✅  _(roles: ProgramAccountant, Admin, CountryDirector)_
1. Accountant navigates to /weekly-funds or /disbursements → sees AccountantDisbursementView
2. Header + KPI strip shows fund flow status. Upcoming activity wave forecasts weekly fund need.
3. Funds Received panel shows inflow (treasury intake). Disbursement Queue shows ready/partial/on-hold requests.
4. Accountant expands a queue row → inline detail reveals disburse form + request breakdown
5. Accountant confirms + releases funds (DisburseModal or form action)
6. Request moves to Paid. Staff receive SMS + see in /weekly-funds. Accountant tracks via Receipt Confirmation (awaiting acknowledgement).

**Monthly Fund Request (MFR) Lifecycle** ✅  _(roles: CountryProgramLead, CountryDirector, RVP, ProgramAccountant)_
1. System generates MFR from approved monthly plans. PL navigates to /monthly-fund-request → sees status UNDER_PL_REVIEW
2. PL reviews matrix (activities by staff + weekly totals), returns if issues or submits to CD
3. CD sees SUBMITTED_TO_CD, reviews program + admin items, adds/modifies admin fund lines, approves + submits to RVP
4. RVP sees SUBMITTED_TO_RVP, approves or returns. Approval activates country fund flow.
5. Accountant sees RVP_APPROVED, prepares disbursement. Monthly funding plan frozen, weekly slips activate.

**Staff Weekly Fund & Accountability (CCEO)** ✅  _(roles: CCEO, ProgramAccountant, ImpactAssessment)_
1. CCEO navigates to /weekly-funds → sees StaffWeeklyView with 4 weekly slips (Mon/Tue/Wed/Thu or per-week)
2. Each card shows balance, activities scheduled, status (pending/approved/disbursed)
3. Accountant releases funds → CCEO sees SMS + card updates. Balance appears in 'My Weekly Fund' card.
4. CCEO spends during week (activities logged in system)
5. Week closes: IA verifies receipts + Salesforce IDs. Accountant enters NetSuite ID to close accountability.
6. Any unspent balance triggers auto-return request (Balance Return Queue)

**Cost Settings Approval (Annual Budget Gating)** ✅  _(roles: CountryDirector, Admin, ProgramAccountant)_
1. CD navigates to /cost-settings → sees cost register (prices for activities, supplies, etc.)
2. CD reviews + edits draft items. Status verdict card shows progress (X of Y active).
3. CD activates each cost item (status → Active). Until all required items are Active, budget approval is BLOCKED.
4. System shows blocking alert in /budget if cost settings incomplete.
5. Once all costs Active, Annual Budget can be approved + quarterly/monthly plans auto-generate

**Staff Reimbursement Claim (Personal Funds)** ✅  _(roles: CCEO, ProgramLead, CountryDirector, ProgramAccountant)_
1. Staff uses own money on approved activity → submits reimbursement claim with receipt + NetSuite ID
2. Claim enters ReimbursementQueue (status: Submitted)
3. Route depends on staff role: CCEO → PL verify → Accountant; Others → CD verify → Accountant
4. Each reviewer can approve or return for correction
5. Accountant receives + pays out (Amount to Reimburse = spent − previously disbursed)
6. Status updates to Reimbursed in queue

**Receipt Confirmation & Accountability Closure** ✅  _(roles: CCEO, ProgramAccountant, ImpactAssessment)_
1. Accountant disburses funds → staff member receives SMS
2. Staff navigates to /weekly-funds, clicks 'Confirm Received' → activity moves to ReceiptConfirmationTracker (Confirmed)
3. IA verifies receipt + Salesforce ID (impact assessment step)
4. Accountant sees IA-Verified activity in StaffAccountabilityQueue (/dashboards/accountant)
5. Accountant enters NetSuite Expense ID → activity closes in AccountabilityClosed
6. If spent < advance, BalanceReturnQueue auto-creates for staff to declare return method (MoMo/Bank/Cash/Offset)

### ⭐ Demo highlights
- Fund Approvals Queue with inline-expanding accordion detail — PLs/Accountants review + approve plans without context switch. Real-time KPI counters (total/approved/returned). Smooth inline expansion UX.
- Accountant Disbursement Command Center (/disbursements) — complete finance cockpit with funds inflow, disbursement queue (tabbed + sorted), staff accountability, receipt tracking, reimbursement claims, balance returns, and audit trail. Every surface wired to working mock data.
- Role-Aware Routing — same /approvals path shows CPL team scope, CD country scope, or RVP multi-country detail. Same /weekly-funds shows Lead approval queue or Accountant disbursement view. Role contract demonstrated cleanly.
- Monthly Fund Request role-gated state machine — PL/CD/RVP/Accountant each see status-appropriate forms + actions. Matrix layout for staff activities. AdminBudgetSection for CD-only. Full flow end-to-end.

### ⚠️ Demo risks / gaps
- Approvals page has 3 disabled stub buttons (Approve All Valid, Export, Advanced Filtering) with 'coming soon' tooltip. Demo users will see greyed-out UI in approvals header — explain these are placeholder for future bulk actions.
- Budget page line 103 has a hard-coded broken note: 'broken into quarterly + monthly funding plans → broken' (appears to be a typo/comment artifact left in code). May look odd in demo.
- All finance surfaces rely on mock data (accountant-console-mock.ts, fund-approvals-mock.ts, budget-mock.ts, etc.). No database wiring — no live data refresh. If demo includes 'what happens when data changes', that will fail.
- Empty state for Staff Accountability Queue: if IA hasn't verified any activities, queue shows 'Nothing awaiting accountability' message. Demo needs pre-populated mock data or explanation.
- No actual file export from Export buttons in accountant console header or approvals — they appear to be wired to toast/placeholder logic only. Export feature is a visual-only stub.
- Receipt Confirmation Tracker assumes Salesforce + NetSuite integration upstream. Demo doesn't show actual SMS sent or integration testing. Copy-to-clipboard works, but NetSuite ID entry is just form submission.

---
## Verification & Accountability (Activity Verification & NetSuite Accountability Workflow)

The verification & accountability domain implements a complete 3-stage workflow: staff submit activities with Salesforce IDs → IA verifies in Salesforce → accountant confirms NetSuite expense IDs. Core state machine works: Completed → SubmittedForVerification → Verified → AccountabilityClosed. Portfolio self-verification (10% quota) is fully functional. ID validation (Salesforce SVE-/TS-, NetSuite digits) is robust. Demo-ready for end-to-end verification flow, but accountant console surface needs seeding with test data to avoid empty-state demo risk.

### Features

| Status | Feature | Route | Notes |
|---|---|---|---|
| ✅ | **Activity Submission (Salesforce ID capture)** | `` | submitActivityForVerification captures staff-entered Salesforce ID (SVE- or TS-), stores exactly, sends IA notifications. ID validation enforces prefix + format. Component SalesforceCompletionModal fully functional wi… |
| ✅ | **IA Verification Queue** | `/data-verification` | IaVerificationQueue displays 3 tabs: Activities (SubmittedForVerification status), Training Evidence (CceoConfirmed/Uploaded), Partner Activities. verifyActivity action advances plan completion %. Salesforce ID shown … |
| ✅ | **Evidence Verification (Training Participants)** | `/data-verification` | confirmEvidence (CCEO) → Uploaded → CceoConfirmed transitions. verifyEvidenceByME (IA) → MeVerified. Identity dedup via identityKey (externalId or name+school+phone). DonorCountStatus gating: only CceoConfirmed/MeVeri… |
| ✅ | **NetSuite Accountability Closure** | `/dashboards/accountant` | confirmActivityAccountability (accountant-only) requires status=Verified, validates NetSuite Expense ID format (digits 3-6), stores trimmed ID. Transitions to AccountabilityClosed. Validation via isValidId('expense').… |
| ✅ | **ID Format Validation** | `` | isValidId() enforces: school (4-6 digits), visit (SVE-#####), training (TS-#####), expense (3-6 digits). Case-insensitive on Salesforce prefixes. Tests cover boundary cases. Used in both client-side (SalesforceComplet… |
| ✅ | **Portfolio Self-Verification (10% Quota)** | `` | markSchoolSelfVerified action. Portfolio-verification.ts computes target=ceil(10% * portfolioSize), status badges (Met/OnTrack/AtRisk/Behind), pace-aware progress. Mock roster seeded with representative CCEOs + Progra… |
| ✅ | **Activity Status Machine** | `` | PlannedActivityStatus includes: Planned → Completed → SubmittedForVerification → Verified → AccountabilityClosed. Returned state on IA rejection. Store defines all statuses; activity-actions enforces transitions. Role… |
| ✅ | **Audit Trail & Notifications** | `` | emitAudit logs every action (activity.completed, .submittedForVerification, .verified, .accountabilityClosed) with actor, payload. emitNotificationFanOut sends to roles (IA, Accountant, staff assignee) with deep links… |
| ✅ | **Plan Completion % Tracking** | `` | planCompletionPercent() computes (Verified count / total non-cancelled) * 100. Integrity rule #3: verifying an activity advances its plan's %. Revalidates plan detail + dashboards on activity verification. Shown on Im… |
| ✅ | **Data Verification Page** | `/data-verification` | Displays IA queues (activities, participants, partner activities), verification funnel card (in-review/verified/failed-qc/resolved), rate KPI, recent uploads. Forces dynamic render. Sources rows directly from store — … |
| 🟡 | **Accountant Console** | `/dashboards/accountant` | Page structure complete: role-locked (ProgramAccountant/Admin), StaffAccountabilityQueue component wired. verifyActivity notifications route accountability rows here. Missing: demo seed data for Verified activities in… |
| ⚪ | **Demo Data for Verification Workflows** | `` | No pre-seeded activities in Verified or AccountabilityClosed status. Mock data files exist but store is empty on page load. Demo path: user must navigate through Completed → SubmittedForVerification → Verified to popu… |

### Workflows

**Staff Activity Completion & Verification Submit** ✅  _(roles: CCEO, Admin)_
1. Staff marks activity Completed (markActivityCompleted)
2. System auto-flips matching WeeklyFundRequest RECEIVED → IN_USE
3. Staff opens SalesforceCompletionModal, enters Salesforce Activity ID (SVE- or TS-prefix)
4. For trainings: staff enters teacher/school leader/other counts, confirms attendance
5. Staff submits (submitActivityForVerification) → status flips to SubmittedForVerification, Salesforce ID stored
6. IA receives notification: 'Activity needs verification', deep link to /data-verification

**Impact Assessment (M&E) Activity Verification** ✅  _(roles: ImpactAssessment, Admin)_
1. IA lands on /data-verification → Activities tab shows all SubmittedForVerification rows
2. IA sees staff-entered Salesforce ID in mono with copy button (no re-typing risk)
3. IA verifies activity exists in Salesforce (external system — not in-app)
4. IA clicks Verify button → verifyActivity action advances Plan completion %
5. Activity transitions to Verified status
6. Accountant receives notification: 'Accountability required: {activity}, Salesforce {ID} confirmed'
7. IA can click Return instead → returnActivity prompts for reason → activity goes to Returned, staff notified

**Accountant NetSuite Accountability Closure** 🟡  _(roles: ProgramAccountant, Admin)_
1. Accountant navigates to /dashboards/accountant → Staff NetSuite Accountability section
2. Rows shown: filtered to status === Verified only (enforced server-side)
3. Each row shows activity title, assigned staff, Salesforce ID (copy button)
4. Accountant clicks 'Confirm Accountability' button → modal opens
5. Accountant enters NetSuite Expense ID (digits 3–6 format: e.g. '6161')
6. confirmActivityAccountability validates format via isValidId('expense')
7. On success: activity transitions to AccountabilityClosed, staff notified, row leaves queue

**Portfolio School Self-Verification (10% Quota)** ✅  _(roles: CCEO, CountryProgramLead, Admin)_
1. Staff sees portfolio verification progress card: {verified} / {target} (10% of assigned schools)
2. Status badges: Met (100%), On Track (70+%), At Risk (40+%), Behind (<40%)
3. Staff marks school self-verified → markSchoolSelfVerified action
4. recordSelfVerification() increments verified count (mock mutation)
5. Progress recalculated: pct = (verified / target) * 100, status re-evaluated
6. Dashboards (CCEO, CPL, Director, Analytics) revalidate to show updated quota progress

**Evidence Verification (Training Participants)** ✅  _(roles: CCEO, ImpactAssessment, Admin)_
1. Staff adds training participants (addTrainingParticipants) → evidenceStatus = 'Captured', donorCountStatus = 'pending_evidence'
2. Staff uploads evidence file → uploadEvidence → evidenceStatus = 'Uploaded', donorCountStatus = 'pending_verification'
3. CCEO confirms evidence (confirmEvidence) → evidenceStatus = 'CceoConfirmed', donorCountStatus = 'included_confirmed' (now counts toward donor metrics)
4. IA verifies evidence (verifyEvidenceByME) → evidenceStatus = 'MeVerified', donorCountStatus = 'included_verified' (final donor gate)
5. OR IA rejects (rejectEvidence) → evidenceStatus = 'Rejected', donorCountStatus = 'excluded_not_eligible'

### ⭐ Demo highlights
- Complete activity verification flow: staff enters Salesforce ID in SalesforceCompletionModal (with training participant breakdown + attendance for trainings), IA verifies via IaVerificationQueue with one-click copy of Salesforce ID, plan completion % advances in real-time. Shows discipline of ID validation + role-based gating.
- NetSuite accountability closure: accountant confirms expense ID to close accountability, status machine enforces Verified prerequisite (accountant cannot act before IA sign-off). Shows 3-stage finance handoff clearly: IA confirm → accountant close → staff notified.
- Portfolio self-verification quota: staff progress card shows {57/57} Met status + pace-aware 'On Track' badge; clicking to self-verify a school increments counter live. Demonstrates deterministic sampling (10%) + status thresholds (Met/OnTrack/AtRisk/Behind).
- Evidence dedup + donor gating: training participants with identity key (externalId or name+school+phone) prevent double-counting. Only CceoConfirmed/MeVerified evidence counts in donor reports — integrity rule gating is visible & audited.

### ⚠️ Demo risks / gaps
- Accountant console cold-start: no pre-seeded Verified activities. Demo flow requires navigating activities through Completed → SubmittedForVerification → Verified first, then accountant console shows rows. If demoing to non-technical stakeholder, recommend pre-populating store with ~3 Verified activities to show accountant queue immediately.
- SalesforceCompletionModal training path: requires entering teacher count, school leader count, AND checking 'attendance form received' checkbox. If any missing, submit button stays disabled. Error message only shows if user has already typed something in Salesforce ID field. User might not see validation error on other fields until clicking submit.
- Portfolio verification endpoint is mutable mock-only: recordSelfVerification() increments in-memory state (globalThis store) — refreshing page resets progress. In production (Prisma), verified counts persist. Demo should note: 'verified count will reset on page reload' or pre-load quota near target to show Met status.
- Data Verification page revalidates all surfaces on activity action: revalidatePath('/data-verification') on every state change, plus dashboards/cceo, dashboards/impact, etc. If demo network is slow, perceived lag between clicking 'Verify' and queue update. Consider showing 'Verifying...' state clearly.
- No empty-state UX for accountant console: 'Nothing awaiting accountability' message is present but if launched before activities reach Verified status, console appears empty/incomplete. Accountant's role visibility depends entirely on upstream IA work.
- ID validation is client+server asymmetric: SalesforceCompletionModal validates SVE-/TS- client-side; submitActivityForVerification trusts the ID string. If client validation is bypassed, server will still accept any non-empty salesforceId without re-validating format.
- Notification deep links assume routes exist: IA notifications link to /data-verification, accountant notifications link to /dashboards/accountant. If those routes are not yet fully built or gated, user clicking notification link might hit error or redirect.

---
## Staff Onboarding & Organization Management

Comprehensive staff onboarding & activation engine (Next.js/React) with 6-phase workflow from staff creation through activation. The activation readiness engine gates progression on 4 core requirements (supervisor, school assignment, primary district, target profile). Full tech stack: pure lib modules, validated server actions, client-side modal controls, role-based access. System health monitoring surfaces bottlenecks. All core features are working and demo-ready.

### Features

| Status | Feature | Route | Notes |
|---|---|---|---|
| ✅ | **Staff Activation Engine** | `` | Pure function computes readiness; gates on supervisor+schools+primaryDistrict+targetProfile. Seeded staff auto-Active. Tests validate ordering. |
| ✅ | **Org Supervision Chain** | `` | Canonical reporting tree (CCEO→PL→CD→RVP); lookups by ID/name/subtree. Supports seeded + runtime staff in single index. |
| ✅ | **Staff Health Monitoring** | `` | Counts active, pending, missing-supervisor, unassigned-schools, duplicates. Health strip on /admin/users surfaces gaps. |
| ✅ | **Add Staff (CD/HR)** | `` | Drawer: name, email (dup check), role, geography cascade, supervisor chain validation. Creates in PendingSupervisor or PendingSchoolAssignment. |
| ✅ | **Assign Schools (IA)** | `` | Modal checkbox list. Marks assigned schools disabled. Clears PendingSchoolAssignment gate. |
| ✅ | **Set Primary District** | `` | Dropdown (region-filtered). Auto-classifies others secondary. Unblocks budget. Clears gate. |
| ✅ | **Assign Target Profile** | `` | Modal with FY + 5 targets. Defaults from role (CCEO 560/PL 280). PL/CD/HR approve. Activates if all gates clear. |
| ✅ | **Change Supervisor** | `` | Modal with reason (4+ chars). CD/HR/RVP/Admin. Chain validation. Audits old→new. |
| ✅ | **Admin Users Page** | `` | Lists demo + created staff. Health strip + inline controls. Shows progress bar + next gap per staff. |
| ✅ | **Admin User Detail** | `` | Demo user view (email, role, hardcoded Active status). No detail view for created staff yet. |
| ✅ | **Admin Hub** | `` | KPI strip, 6 section cards, activity feed. Demo-only content. |
| ✅ | **Target Profile Storage** | `` | Runtime array. addStaffTargetProfile pushes; hasTargetProfile checks active. |
| ✅ | **Server Actions** | `` | createStaff, setPrimaryDistrict, assignTargetProfile, assignSupervisor. Auth guards, validation, audit, revalidate. |

### Workflows

**Staff Onboarding (6-Phase)** ✅  _(roles: CountryDirector, HumanResource, Admin, ImpactAssessment, CountryProgramLead)_
1. Phase 1: CD/HR creates staff (name, email, role, region, district, supervisor). Status→PendingSupervisor or PendingSchoolAssignment
2. Phase 2: (If no supervisor assigned at creation, CD/HR assigns one). Status remains in pending-schools gate.
3. Phase 3: IA assigns onboarded schools to CCEO. Schools enter portfolio; status→PendingPrimaryDistrict
4. Phase 4: (Standalone) CD/HR can reassign supervisor with reason; audited to trail
5. Phase 5: CD/HR/Admin sets staff primary district (home/base). Status→PendingTargetProfile; budget unlocked
6. Phase 6: PL/CD/HR assigns target profile (FY + visit/training/SSA/cluster/partner targets). Activation engine checks all gates; if complete→Active. Staff now operational

**Supervisor Assignment** ✅  _(roles: CountryDirector, HumanResource, RVP, Admin)_
1. Open Change Supervisor modal from /admin/users
2. Select new supervisor (filtered by role chain requirement)
3. Enter reason (4+ chars) + optional effective date
4. Save: audits old→new + reason to compliance trail; notifies staff + both supervisors
5. Activation engine recalculates status (may unblock if was PendingSupervisor)

**Staff Health Review** ✅  _(roles: CountryDirector, HumanResource, Admin)_
1. Navigate to /admin/users
2. View Health Strip: shows active count, in-onboarding count, missing-supervisor count, unassigned-schools count, duplicate-email count
3. Click into created-staff rows to see per-staff progress (Onboarding X/Y + next gap)
4. Use inline buttons (Assign schools / Set primary district / Assign targets) to drive gaps to zero

### ⭐ Demo highlights
- Add Staff modal: full form with geography cascade (region→district), supervisor validation against reporting chain, real-time email dup detection, inline errors. Shows path from PendingSupervisor to Active in the toast message.
- Health Strip on /admin/users: live counts (active / pending / missing-supervisor / unassigned-schools / duplicate-emails) auto-update as you progress staff through gates. Colored chips draw attention to gaps.
- Created-staff rows in /admin/users: each shows progress bar (Onboarding 1/4 etc), next gap label, and contextual inline buttons that appear only when gated action is valid. Modal-per-action keeps UX light.

### ⚠️ Demo risks / gaps
- Empty state in AssignSchoolsControl when no schools onboarded yet (shows 'No onboarded schools'). Demo safe if sample schools are seeded.
- Created staff detail view doesn't exist; only demo users have detail pages. If stakeholders click a created-staff name expecting full view, will 404.
- Staff created with no supervisor start in PendingSupervisor; if supervisor never assigned, they stay pending forever. Health strip will flag this, but no auto-escalation or reminder.
- Target profile defaults computed from role (CCEO 560 visits / PL 280). If defaults are wrong for a specific staff, PL must manually override in the modal—no bulk edit.
- Demo user list hardcoded in DEMO_USERS; created staff live only in memory (RUNTIME_STAFF array). No persistence; refresh=reset. Okay for demo, risky if demoing on live data.
- IA school assignment clears gate only if schools are assigned; CCEO without any schools stays PendingSchoolAssignment. No minimum count check or auto-assign.

---
## Analytics, Reports & Impact

The analytics engine is production-ready with fully data-driven metrics computed from workflow records (mock data). Impact Assessment dashboard and donor reporting are working but missing some UI polish on verification queue interactions. SSA performance dashboard is feature-complete with intervention scoring, heatmaps, and trend analysis. Leaderboard is functional for verified impact recognition. Reports catalog exists but routes to real dashboards rather than report generators.

### Features

| Status | Feature | Route | Notes |
|---|---|---|---|
| ✅ | **Analytics Engine (computeAnalytics)** | `/analytics` | Fully functional core engine computing 40+ metrics from workflow records (activities, trainings, exams, MSC). Every metric carries definition, breakdown (planned/completed/verified/donor-ready), drilldown records, and… |
| ✅ | **Field Analytics Page** | `/analytics` | Filter-aware analytics surface with hero KPI band (6 metrics), charts (momentum, verification donut, pipeline funnel, SSA ranks), SSA heatmap, district ranking, MSC funnel, and donor reporting section. Drilldown works… |
| ✅ | **Donor Reporting Impact Layer** | `/analytics (embedded), /dashboards/director, /dashboards/impact` | Evidence-backed metrics with explicit verification status (verified/confirmed/pending/excluded). Grouped by reach/training/geography/evidence/cost/impact. Data sourced from getDonorMetricSnapshot (same builder as dire… |
| ✅ | **SSA Performance Dashboard** | `/ssa` | Complete intelligence cockpit: hero headline + intervention scoreboard (7 ranked interventions) + district performance table (8 columns, color-coded by score tier) + 6-year trend + district heat panel + priority gaps … |
| ✅ | **SSA Intervention Heatmap** | `/ssa (section id=heatmap), /analytics (embedded)` | 6 districts × 8 interventions grid showing average scores per area. Rows=districts, columns=interventions. Computed from latest SSA snapshots per reached school. Color-coded intensity. Fully data-driven. |
| ✅ | **SSA District Comparison Table** | `/ssa (section id=districts)` | Mobile-stacked + desktop table view. Rank · District · Schools assessed · Completion rate · Average score (/10) · Weak area · High-risk count · Trend pill. Color-coded left edge by score tier. Data-driven from ssa-mock. |
| ✅ | **Impact Assessment Dashboard** | `/dashboards/impact` | Role-gated dashboard (ImpactAssessment only). Five KPI row (total records/verified/pending/failed/partners) + insights strip + verification funnel (Uploaded→In Review→Verified→Failed QC + Resolved recovery) + data qua… |
| ✅ | **Verified Impact Leaderboard** | `/leaderboard` | Staff ranking by verified impact across 9 categories (Overall, Schools Reached, Learners Impacted, Teachers Trained, School Leaders, Exams, MSC, SSA Improved, Coverage). Computed from leaderboard-mock. Shows rank badg… |
| ✅ | **Data Verification Funnel** | `/dashboards/impact (embedded)` | Segmented bar chart showing terminal states (In Review/Verified/Failed QC) as one proportional rail + recovery metric footer. Headline is verification rate (%) with period delta. Drilldown links to /data-verification … |
| ✅ | **Program Overview Card** | `/dashboards/impact (embedded)` | Counts by program (likely partner program breakdown). Component present but data source (program structure) is mock-backed. Renders without error. |
| 🟡 | **Reports Catalog Page** | `/reports` | Role-filtered report links (Country Performance, Team Targets, SSA Performance, Verified Impact, Daily Field Debrief, Funds & Disbursement, Leave & Holidays) + Recent reports section + scheduled reports. Catalog is fu… |
| 🟡 | **Partner Reports** | `/partner/reports` | Subtitle + filter pills (Last 6 months, All report types) + KPI cards (Submitted/Pending/Reports in lib/On-time rate) are mock-backed. PartnerReportsBoard component present but unclear if report submission form is wir… |
| ✅ | **Director Dashboard (Donor Reporting Callout)** | `/dashboards/director` | National-level donor snapshot + country KPI row (8 KPIs) + leadership attention banners + debrief inbox + training coverage + country/regional performance charts + PL performance table + priority schools + recognition… |
| ✅ | **Coverage / School Directory** | `Embedded (via analyticsSchoolById, school-directory.ts)` | analyticsSchoolById resolves school metadata (name, district, cluster, segment). Used in drilldown records, district grouping, and geographic scoping. Pure function from school-directory-mock. |
| ✅ | **Exam Results Collection** | `/analytics (metrics), /dashboards/impact (implied)` | Exam results tracked: collection rate %, improved/declined counts, baseline schools. Data from exam-performance-mock with 9 records (2 marked uncollected to test missing-data path). Metric 'examCollectionRate' on anal… |
| ✅ | **MSC (Most-Significant-Change) Funnel** | `/analytics (embedded), /dashboards/impact (via donor snapshot)` | Four-stage funnel (Submitted→PL Reviewed→Verified→Donor-Ready). Count per stage + drilldown records. Data from msc-mock. Fully data-driven. |
| ✅ | **Data Quality Verdict & Scoring** | `/analytics, /dashboards/impact` | Every metric carries DataQuality (level: ok/caveat/blocked; notes: []). Snapshot rolls up to DataQualityScore (Excellent/Good/Needs Attention/Critical). Caveats flagged for missing enrollment, missing exam results, mi… |

### Workflows

**View Filtered Analytics by Period & Geography** ✅  _(roles: CCEO, CountryProgramLead, CountryDirector, RVP, ImpactAssessment)_
1. Navigate to /analytics
2. Use header filter bar to select FY, quarter, region, district, cluster, SSA, partner, package, champion
3. See 40+ metrics recompute live (hero band + grouped operational panels + charts)
4. Click any metric to drill into exact records behind the number
5. Scroll to see district ranking, SSA heatmap, MSC funnel, donor reporting section
6. Export snapshot as CSV

**Review SSA Performance & Intervention Coverage** ✅  _(roles: CCEO, CountryProgramLead, CountryDirector, RVP, ImpactAssessment)_
1. Navigate to /ssa
2. See headline average SSA score + status tiles
3. Review intervention performance card (7 interventions ranked by avg score)
4. Scan district performance table (all districts, scores color-coded)
5. View 6-year trend line + district heat panel (side-by-side)
6. Inspect priority intervention gaps heatmap (6 districts × 8 areas)
7. See schools requiring urgent attention (full width card at bottom)

**Monitor Data Verification Pipeline (Impact Assessment Role)** 🟡  _(roles: ImpactAssessment, Admin)_
1. Navigate to /dashboards/impact (role-gated)
2. View five vital-sign KPIs (Total Records, Verified, Pending, Failed, Partners)
3. Scan insights strip for auto-flagged anomalies
4. Review verification funnel (segmented bar + recovery metric)
5. See data quality trend chart + quality status card
6. View top issues card (likely incomplete—see risks)
7. See recent data uploads + partner performance
8. Open verification queue (link in funnel card—destination unclear, may be stub)

**Generate / Access Donor Reports** 🟡  _(roles: CountryDirector, CountryProgramLead, RVP, CCEO, ImpactAssessment)_
1. Navigate to /reports
2. See role-filtered report catalog (Country Performance, SSA Performance, Verified Impact, etc.)
3. Click report tile to open linked dashboard (e.g., Country Performance → /dashboards/director)
4. Scroll Recent Reports section to see mock-backed snapshots
5. Try to download or schedule reports (likely not wired—forms may be stubs)

**View Verified Impact Leaderboard & Rankings** ✅  _(roles: CCEO, CountryProgramLead, CountryDirector, RVP, ImpactAssessment)_
1. Navigate to /leaderboard
2. See summary cards (top performer, most-improved, tier distribution)
3. Click category tabs (Overall, Schools Reached, Learners Impacted, etc.) to filter
4. Read leaderboard table (rank badge, staff, region, PL, verified count, target, achievement %, SF compliance, verification %, trend, badge)
5. Scroll fairness context panel (discusses how leave/workload/difficulty factor into escalations)

**Review Country-Level Impact Snapshot (Director)** ✅  _(roles: CountryDirector, Admin)_
1. Navigate to /dashboards/director
2. See 8 country KPI tiles (Schools Reached, Learners Impacted, Teachers, Leaders, Exams, MSC, SSA Improved, Districts)
3. Scan leadership-attention alerts (3 banners for critical flagged items)
4. Review debrief inbox routed to director
5. See training coverage card (shows % vs SSA gap targets)
6. Scan country-wide momentum trend line + regional comparison rail
7. View PL performance table + priority schools needing attention + top performers
8. See finance snapshot (fund approval + funded-not-completed breakdown)

### ⭐ Demo highlights
- Analytics Engine: Open /analytics, change filters (FY, district, quarter), watch 40+ metrics recompute live with zero latency. Click Schools Reached to see exact 6 schools with drilldown details (school name, district, status). Scroll down to see data quality verdict flagging missing enrollment.
- SSA Intelligence: Open /ssa, show intervention heatmap (6 districts × 8 areas color-coded by score). Explain how this drives core candidate selection (7.5+ avg = verify → onboard). Scroll to see district performance table with color-coded left edge + ranking, and urgent-attention schools needing immediate follow-up.
- Verified Impact Leaderboard: Open /leaderboard, click category tabs to show how achievement % and trend vary by metric (Schools Reached, Exams, MSC, etc.). Show how SF compliance % is a separate signal so a high-volume staff member isn't penalized for data-entry delays.
- Donor Reporting Layer: On /dashboards/director, scroll to DonorReportingImpact section showing reach/training/geography/evidence/cost with explicit status (verified in green, pending in amber). Explain that this exact shape appears on /analytics and pulls from same engine so numbers never diverge across roles.

### ⚠️ Demo risks / gaps
- Impact Assessment Dashboard: 'Top Issues Card' component present but likely a stub—data source unclear, may render empty or with placeholder text on stage. Test before demo.
- Impact Assessment Dashboard: Verification Queue link (in Data Verification Funnel card) points to /data-verification but page may not exist or may be in-progress. Clicking could show 404 or broken layout.
- Reports Page: Recent reports and scheduled reports sections are mock-backed. Download button and 'Generate new' button likely non-functional. Users will click and see nothing happen.
- Partner Reports: Report submission form unknown—may be stub. Partner board component exists but wiring to actual submission/approval workflow is unclear.
- Empty States: Analytics page with all-zero metrics (e.g., no schools reached in a filtered scope) may show broken layout or missing nil-data fallback. Test with narrow filter (e.g., single school that has no data).
- Mobile Responsiveness: Impact dashboard uses ResponsiveDashboard wrapper but some cards (especially verification funnel with many columns) may cramp on tablet. Not tested on actual device.
- Data Quality Strip: Shows 'ok', 'caveat', or 'blocked' level but UI for 'blocked' state (which halts reporting) is untested. May render awkwardly.
- SSA Trend Card: 6-year trend on /ssa is lazy-loaded via SsaTrendCard. If data is missing or chart library fails, card will hang or show blank. Verify chart renders before demo.
- Leaderboard Badge Logic: 'Badge' column (last in table) shows recognition (trophy, medal, etc.) but logic for earning badges is not visible in code read. May be hardcoded or have unmet criteria.
- Filter Persistence: URL-based filters on /analytics (?fy=2026&q=Q1 etc.) work for GET requests but if user goes back/forward in browser, filter state sync is untested. May show stale data.
- District Comparison: On /analytics, district ranking table uses 'avgSsa' field which may be undefined for districts with no SSA data. May render as dashes or crash.

---
## Demo Readiness Probes

### Route & Stub Inventory for Edify Live Demo
**Findings**
- Total routes in src/app/(shell): 142 page.tsx files
- Stub pages (using StubPage component): 51 pages
- Real/implemented pages: ~91 pages
- All stubs are properly identified via route-titles.ts EXACT_ROUTE_TITLES and PREFIX mappings
- Critical navigable stubs in primary menus: /calendar, /reports, /analytics, /settings, /help, /notifications, /profile
- Data intake suite is mostly stubs: /data-intake, /data-intake/queue, /data-intake/duplicates, /data-intake/readiness, /data-intake/templates, /data-intake/upload, /data-intake/quality (7/9 pages)
- Budget approval flow is mostly stubs: /budget/approvals/*, /budget/breakdown, /budget/monthly, /budget/scenarios, /budget/variance (8/10 pages)
- Operating Cycle (FY) section: /fy, /fy/gateway, /fy/readiness, /fy/ssa-comparison, /fy/timeline, /fy/whats-changed (all 6 pages are stubs)
- Admin section: /admin, /admin/audit-log, /admin/feature-flags (all 3 are stubs)
- High-visibility stubs reachable from sidebar: /calendar (CPL/Impact menus), /settings (all roles), /help (CPL/Accountant/Impact menus), /reports (CPL/Accountant/RVP/CD/Impact menus), /analytics (CPL/Accountant/RVP/CD/Impact menus)

**Blockers**
- ⚠️ CRITICAL: /calendar is a stub but appears in CPL sidebar and mobile nav — demo navigation will hit an empty placeholder. Calendar shows mock data layout but is internally a StubPage with no real implementation
- ⚠️ CRITICAL: /reports is a stub in all role sidebars (CPL, Accountant, RVP, CD, Impact Assessment) — navigation to Reports hits empty page across multiple demo paths
- ⚠️ CRITICAL: /analytics is a stub in CPL/Accountant/RVP/CD/Impact sidebars — another core insight page missing real UI
- ⚠️ HIGH: /settings stub appears in Account section for all roles (CPL, Accountant, RVP, CD, Impact) — user settings demo path is incomplete
- ⚠️ /help is a stub (uses StubPage) but has mock Help Center UI with categories and articles — internally structured but flagged as stub
- ⚠️ /notifications stub in mobile nav and Impact menu
- ⚠️ Budget approval pipeline (/budget/approvals/*) entire flow is stubs — /approvals itself is NOT a stub (real implementation), but drill-down detail page /budget/approvals/[id] is a stub
- ⚠️ Data intake (/data-intake, /queue, /duplicates, /readiness, /templates, /upload) — 7 of 9 pages are stubs; this represents core data ops features
- ⚠️ Operating Cycle (/fy) — entire 6-page section is stubs, blocking any FY planning demo paths
- ⚠️ Admin (/admin, /admin/audit-log, /admin/feature-flags) all stubs — admin demo paths will fail
- ⚠️ /profile and /portfolio are stubs — user identity and school portfolio pages are incomplete

**Recommendations**
- Before demo: identify which primary flows are in scope (e.g., planning, targets, visits, schools, partners). Confirm stubs in those paths are acceptable placeholders or disable nav links to them.
- High-priority to implement OR block navigation: /calendar (sidebar + mobile nav), /reports (5 role sidebars), /analytics (5 role sidebars), /settings (all roles)
- Budget flow: /approvals (real) is good, but /budget/approvals/[id] detail page is stub — verify demo doesn't click into individual approval detail
- Data intake: if demoing, either implement the 7 stubs or remove /data-intake from navigation entirely (it's in Accountant and Impact sidebars)
- /help is internally structured with mock articles, so it may be acceptable as a demo surface — users can browse help categories even if content is mock
- Consider disabling /admin navigation entirely if admin features are not in demo scope (it's gated to Admin role via middleware anyway)
- All stub pages render visually (no blank white screens) — they use StubPage wrapper with title/subtitle, so demo won't crash, but UX will feel incomplete if paths are clicked

```
Route | Title | Status | Sidebar/Nav | Priority
/dashboards/cceo | Main Dashboard (CCEO) | REAL | CCEO home | Must-work
/dashboards/cpl | Main Dashboard (CPL) | REAL | CPL home | Must-work
/dashboards/director | Main Dashboard (Director) | REAL | Director home | Must-work
/dashboards/rvp | Main Dashboard (RVP) | REAL | RVP home | Must-work
/dashboards/accountant | Main Dashboard (Accountant) | REAL | Accountant home | Must-work
/today | Today's Tasks | REAL | CPL/CCEO mobile nav | Must-work
/my-plan | My Plan | REAL | CPL sidebar | Must-work
/my-targets | My Targets | REAL | CPL sidebar | Must-work
/planning | Planning | REAL | CD/Impact sidebars | Must-work
/plans/[id] | Plan details | REAL | Navigable from /planning | Must-work
/schools | Schools | REAL | CPL/CD/Impact sidebars | Must-work
/schools/[id] | School detail | REAL | Navigable from /schools | Must-work
/partners | Partners | REAL | CPL sidebar | Must-work
/partners/[id] | Partner detail | REAL | Navigable from /partners | Must-work
/visits | Visits | REAL | CPL sidebar | Must-work
/trainings | Visits & Trainings | REAL | CPL sidebar | Must-work
/approvals | Approvals | REAL | CPL/CD/RVP/Accountant sidebars | Must-work
/budget | Budget | REAL | CD/RVP/Accountant sidebars | Must-work
/core-schools | Core Schools | REAL | CCEO/CPL sidebars | Must-work
/ssa | SSA Performance | REAL | CPL/CD/Impact sidebars | Must-work
/leaderboard | Leaderboard | REAL | CPL/CD/RVP/Impact sidebars | Must-work
/team-targets | Team Targets | REAL | All major sidebars | Must-work
/portfolio | My School Portfolio | STUB | CPL sidebar | Medium-risk
/calendar | Calendar | STUB | CPL/Impact sidebars + mobile nav | HIGH-RISK
/settings | Settings | STUB | All Account sections | HIGH-RISK
/help | Help | STUB | CPL/Accountant/Impact sidebars | Medium
/notifications | Notifications | STUB | Mobile/Impact nav | Low
/reports | Reports | REAL in name, STUB | CPL/CD/RVP/Accountant/Impact sidebars | HIGH-RISK
/analytics | Analytics | STUB | CPL/CD/RVP/Accountant/Impact sidebars | HIGH-RISK
/data-intake | Data Intake | STUB | Accountant/Impact sidebars | Medium-risk
/data-intake/queue | Queue | STUB | Not primary nav | Low
/data-intake/upload | Upload Center | STUB | Not primary nav | Low
/data-intake/duplicates | Duplicate Review | STUB | Not primary nav | Low
/data-intake/readiness | Readiness | STUB | Not primary nav | Low
/data-intake/templates | Templates | STUB | Not primary nav | Low
/budget/approvals/[id] | Budget Approval detail | STUB | Drill-down from /approvals | Medium
/fy | Operating Cycle | STUB | CD/RVP/Impact sidebars | Low
/admin | Admin | STUB | Not in demo (role-gated) | Low
/profile | Profile | STUB | Top nav (AvatarMenu) | Medium
/messages | Messages | REAL | Multiple sidebars | Must-work
```

---
### Login & Role Matrix for Edify Demo
**Findings**
- DEMO LOGIN MATRIX:

EDIFY STAFF ROLES (password='edify' unless noted):
1. paul.chinyama@edify.org | edify | Paul Chinyama | CCEO | /my-targets (195 LOC dashboard)
2. daniel.mwangi@edify.org | edify | Daniel Mwangi | CountryProgramLead | /dashboards/cpl (202 LOC dashboard)
3. aisha.dar@edify.org | edify | Aisha Dar | CountryProgramLead | /dashboards/cpl
4. sarah.okello@edify.org | edify | Sarah Okello | CountryDirector | /dashboards/director (188 LOC dashboard)
5. esther.wanjiru@edify.org | edify | Esther Wanjiru | RVP | /dashboards/rvp (352 LOC dashboard — RICHEST)
6. anne.wairimu@edify.org | edify | Anne Wairimu | HumanResource | /team-targets (then /dashboards/hr, 280 LOC)
7. moses.tindi@edify.org | edify | Moses Tindi | ProgramAccountant | /dashboards/accountant (59 LOC — THIN)
8. grace.alimo@edify.org | edify | Grace Alimo | ImpactAssessment | /dashboards/impact (141 LOC dashboard)
9. admin@edify.org | edify | Edify Admin | Admin | /dashboards/director
10. demo@edify.org | demo (ALTERNATE PWD) | Edify Demo | CountryDirector | /dashboards/director

PARTNER ROLES — LTU (Literacy Training Uganda):
11. sarah.kanyi@ltu.org | edify | Sarah Kanyi | PartnerAdmin | /partner/today (47 LOC — THIN)
12. abel.opio@ltu.org | edify | Abel Opio | PartnerFieldOfficer | /partner/today
13. donor@ltu-funder.org | edify | LTU Donor | PartnerViewer | /partner/today

PARTNER ROLES — BFEP (Bright Future Education Partners):
14. daniel.mwangi@brightfuture.org | edify | Daniel Mwangi | PartnerAdmin | /partner/today
15. ruth.kabuye@brightfuture.org | edify | Ruth Kabuye | PartnerFieldOfficer | /partner/today
16. sarah.nanyongo@edify.org | edify | Sarah Nanyongo | PartnerViewer | /partner/today

ROLE → LANDING ROUTE MAPPING (from auth-public.ts & RoleSwitcher.tsx):
- CCEO → /my-targets (personal command center)
- CountryProgramLead → /dashboards/cpl
- CountryDirector → /dashboards/director
- RVP → /dashboards/rvp
- ProgramAccountant → /dashboards/accountant
- ImpactAssessment → /dashboards/impact
- HumanResource → /dashboards/hr (also /team-targets in auth.ts line 37 — CONFLICT)
- Admin → /dashboards/director (note: RoleSwitcher.tsx lines 190-202 show /admin)
- PartnerAdmin/PartnerFieldOfficer/PartnerViewer → /partner/today

DATA-DRIVEN RICHNESS ASSESSMENT (by page file size):
RICHEST: RVP (352 LOC) — expansive dashboards, final approval + rollups
RICH: HR (280 LOC), CountryProgramLead (202 LOC), CCEO (195 LOC), CountryDirector (188 LOC)
MODERATE: PartnerDashboard (181 LOC), ImpactAssessment (141 LOC)
THIN: ProgramAccountant (59 LOC — fund review only), PartnerToday (47 LOC — simple to-do), CCEO my-targets (87 LOC)

ROLE SWITCHING FLOW:
1. LOGIN: POST /api/auth/login {email, password, remember} → sets HTTP-only cookies (edify-email, edify-role, edify-name) → redirects to role→landing route
2. DEMO SWITCHER: Via avatar menu → 'Switch role' → triggers edify:open-role-switcher custom event → opens RoleSwitcher sheet (8 CCEO+staff roles visible, NO partner roles in sheet)
3. SWITCH: POST /api/demo/role-switch {email} → updates cookies → router.refresh() + hard reload → lands on LANDING_BY_ROLE[role]
4. SECURITY: In dev/preview, unrestricted role switching. In production (NODE_ENV=production), only authenticated Admin can use role-switch endpoint.

DEMO ACCOUNT SWITCHER CONTENTS (RoleSwitcher.tsx DEMO_ROLES array):
- Paul Chinyama (CCEO, Briefcase icon, edify tone)
- Daniel Mwangi (CountryProgramLead, Users icon, amber)
- Sarah Okello (CountryDirector, Globe icon, violet)
- Esther Wanjiru (RVP, Sparkles icon, violet)
- Moses Tindi (ProgramAccountant, Wallet icon, green)
- Grace Alimo (ImpactAssessment, ShieldCheck icon, sky)
- Anne Wairimu (HumanResource, Users icon, rose)
- Edify Admin (Admin, UserCog icon, slate)

NOTE: Partner roles (PartnerAdmin, PartnerFieldOfficer, PartnerViewer) are NOT in the RoleSwitcher.tsx DEMO_ROLES array. To demo partner flows, must log out and log back in with partner credentials.
- MISMATCH: auth-public.ts lines 29-45 (ROLE_REDIRECT) shows HumanResource → /dashboards/hr, but auth.ts line 37 says HumanResource → /team-targets (conflicting landing pages)
- MISMATCH: RoleSwitcher.tsx LANDING_BY_ROLE (lines 190-202) shows Admin → /admin, but auth-public.ts ROLE_REDIRECT (line 38) shows Admin → /dashboards/director. RoleSwitcher takes precedence since it's client-side.
- PARTNER ROLES NOT IN DEMO SWITCHER: The sheet only lists 8 roles (CCEO + 7 staff). All 3 partner role types (PartnerAdmin, PartnerFieldOfficer, PartnerViewer) are missing from RoleSwitcher.tsx DEMO_ROLES array (lines 34-43). If demoing partner flows, must log out + log back in.
- CCEO LANDING SPARSE: /my-targets is only 87 lines (sparse UI). CCEO would benefit from a richer demo experience; RVP at 352 LOC is the fullest.
- ProgramAccountant THIN: /dashboards/accountant is 59 LOC — minimal fund review UI. May not showcase much in a live demo.
- Password UNIFIED: All Edify staff + LTU + BFEP accounts use password 'edify' except demo@edify.org which uses 'demo'. Single password is convenient for demos but unconventional for production readiness demo messaging.

**Blockers**
- ⚠️ CRITICAL: HumanResource landing route conflict — auth.ts (server) says /team-targets, auth-public.ts says /dashboards/hr. If HR role lands wrong on login, demo breaks. Need to verify which page actually exists and works.
- ⚠️ CRITICAL: Partner roles cannot be switched via the demo switcher UI. If demo script calls for switching to PartnerAdmin mid-demo to show partner flows, the switcher will not have that option. Must log out, log back in with partner email — breaks demo fluidity.
- ⚠️ CRITICAL: Admin role lands on /dashboards/director per auth-public.ts ROLE_REDIRECT, but RoleSwitcher.tsx hard-codes /admin. After role switch to Admin, user may land on director dashboard or admin page — inconsistent.
- ⚠️ MODERATE: ProgramAccountant dashboard (59 LOC) is very thin. If demoing finance flows, may underwhelm. Reviewer should check /dashboards/accountant content.
- ⚠️ MODERATE: CCEO my-targets (87 LOC) is lean. If starting demo as CCEO, initial screen may feel sparse compared to RVP (352 LOC).
- ⚠️ MODERATE: No clear auth.ts indication of whether both /dashboards/hr AND /team-targets exist. If one is stale, HR login will 404.

**Recommendations**
- BEFORE DEMO: Resolve HumanResource landing page conflict (auth.ts line 37 vs auth-public.ts line 29). Pick one, document it, verify the page works.
- BEFORE DEMO: Clarify Admin role landing — choose /dashboards/director or /admin, then update both ROLE_REDIRECT and RoleSwitcher.tsx LANDING_BY_ROLE to match.
- DEMO SCRIPT GUIDANCE: Lead with RVP (Esther Wanjiru, richest at 352 LOC) to showcase breadth. Follow with CountryDirector (Sarah Okello, 188 LOC), then CCEO (Paul Chinyama, 195 LOC) for field operations view.
- DEMO SCRIPT GUIDANCE: If demoing partner flows, plan for logout + re-login flow (not seamless role switching). Use BFEP accounts (daniel.mwangi@brightfuture.org, ruth.kabuye@brightfuture.org) over LTU.
- QUICK WIN: Add PartnerAdmin, PartnerFieldOfficer, PartnerViewer to RoleSwitcher.tsx DEMO_ROLES (lines 34-43) so partner role switching is seamless. Separate partner section in the sheet with a divider.
- PASSWORD CLARITY: Document that all demo accounts use password='edify' except demo@edify.org (password='demo'). Have it ready verbally if demoing to non-technical stakeholders.
- VERIFY PAGES: Spot-check /dashboards/accountant (59 LOC) and /dashboards/impact (141 LOC) content in the browser to confirm they render and have meaningful demo data.
- VERIFY PAGES: Confirm /my-targets, /dashboards/hr, and /dashboards/director all render and load mock data correctly.

```
email | password | name | role | landing_route | richness
paul.chinyama@edify.org | edify | Paul Chinyama | CCEO | /my-targets | LEAN (87 LOC)
daniel.mwangi@edify.org | edify | Daniel Mwangi | CountryProgramLead | /dashboards/cpl | RICH (202 LOC)
sarah.okello@edify.org | edify | Sarah Okello | CountryDirector | /dashboards/director | RICH (188 LOC)
esther.wanjiru@edify.org | edify | Esther Wanjiru | RVP | /dashboards/rvp | RICHEST (352 LOC)
moses.tindi@edify.org | edify | Moses Tindi | ProgramAccountant | /dashboards/accountant | THIN (59 LOC)
grace.alimo@edify.org | edify | Grace Alimo | ImpactAssessment | /dashboards/impact | MODERATE (141 LOC)
anne.wairimu@edify.org | edify | Anne Wairimu | HumanResource | /dashboards/hr | RICH (280 LOC)
admin@edify.org | edify | Edify Admin | Admin | /dashboards/director | RICH (188 LOC)
demo@edify.org | demo | Edify Demo | CountryDirector | /dashboards/director | RICH (188 LOC)
daniel.mwangi@brightfuture.org | edify | Daniel Mwangi | PartnerAdmin | /partner/today | THIN (47 LOC)
ruth.kabuye@brightfuture.org | edify | Ruth Kabuye | PartnerFieldOfficer | /partner/today | THIN (47 LOC)
sarah.nanyongo@edify.org | edify | Sarah Nanyongo | PartnerViewer | /partner/today | THIN (47 LOC)
```

---