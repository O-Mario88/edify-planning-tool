// Route → default page title map.
//
// The shell-level RoutePageTitle component watches usePathname() and
// stamps the MobileTopBar title from this map so every page in the
// (shell) group gets a sensible title for free — no per-page wiring.
//
// Individual pages can still override the title for richer context
// (entity name, period label) by calling `useSetPageTitle()` from
// any client component. Page-level overrides win because they run
// after this default in render order.
//
// Match order: exact match first, then longest-prefix match. The
// map covers every route that exists in src/app/(shell) so a typo
// or new route gets flagged as "Edify" (the provider default), not
// the wrong neighbouring page's title.

export type RouteTitle = {
  title:      string;
  dateLabel?: string;
};

// ────────── Exact matches ──────────
// Exported so the command palette can enumerate every reachable page.
export const EXACT_ROUTE_TITLES: Record<string, RouteTitle> = {
  "/dashboards/cceo":      { title: "Main Dashboard" },
  "/today":                { title: "Today's Tasks", dateLabel: "Mon, May 12 · Wk 3" },
  "/my-plan":              { title: "My Plan" },
  "/my-targets":           { title: "My Targets" },
  "/my-team":              { title: "My Team" },
  "/team-targets":         { title: "Team Targets" },
  "/route":                { title: "Routes" },
  "/calendar":             { title: "Calendar" },
  "/core-schools":         { title: "Core Schools" },
  "/schools":              { title: "Schools" },
  "/ssa":                  { title: "SSA Performance" },
  "/ssa/core-candidates":  { title: "Champion Pipeline" },
  "/clusters":             { title: "Clusters" },
  "/coverage":             { title: "Coverage" },
  "/coverage/recommendations": { title: "Coverage recommendations" },
  "/visits":               { title: "Visits" },
  "/trainings":            { title: "Visits & Trainings" },
  "/partners":             { title: "Partners" },
  "/staff":                { title: "Staff" },
  "/leaderboard":          { title: "Leaderboard" },
  "/approvals":            { title: "Approvals" },
  "/weekly-funds":         { title: "Weekly Funds" },
  "/fund-requests":        { title: "Fund Requests" },
  "/disbursements":        { title: "Disbursements" },
  "/budget":               { title: "Budget" },
  "/budget/breakdown":     { title: "Budget breakdown" },
  "/budget/monthly":       { title: "Monthly budget" },
  "/budget/scenarios":     { title: "Budget scenarios" },
  "/budget/variance":      { title: "Budget variance" },
  // Deprecated: /budget/approvals (bare) now redirects to /approvals.
  // Sub-pages live on; their titles below.
  "/budget/approvals/active":         { title: "Active budget approvals" },
  "/budget/approvals/amendments":     { title: "Budget amendments" },
  "/budget/approvals/funds-matching": { title: "Funds matching" },
  "/budget/approvals/rvp-queue":      { title: "RVP approval queue" },
  "/cost-settings":        { title: "Cost Settings" },
  "/planning":             { title: "Planning" },
  "/plans":                { title: "Plans" },
  "/plans/new":            { title: "Create / Edit Plan", dateLabel: "May 2025" },
  "/special-projects":     { title: "Special Projects" },
  "/quality-checks":       { title: "Quality Checks" },
  "/discipleship-clubs":   { title: "Discipleship Clubs" },
  "/exam-scores":          { title: "Exam Scores" },
  "/field-intelligence":   { title: "Field Intelligence" },
  "/debriefs":             { title: "Debriefs" },
  "/decisions":            { title: "Decisions" },
  "/fy":                   { title: "Operating Cycle" },
  "/fy/gateway":           { title: "FY gateway" },
  "/fy/readiness":         { title: "FY readiness" },
  "/fy/ssa-comparison":    { title: "SSA comparison" },
  "/fy/timeline":          { title: "FY timeline" },
  "/fy/whats-changed":     { title: "What's changed" },
  "/data-intake":          { title: "Data Intake" },
  "/data-intake/queue":    { title: "Data intake queue" },
  "/data-intake/readiness":{ title: "Data intake readiness" },
  "/data-intake/templates":{ title: "Data intake templates" },
  "/data-intake/upload":   { title: "Upload Center" },
  "/data-verification":    { title: "Data Verification" },
  "/queue":                { title: "Salesforce Queue" },
  "/analytics":            { title: "Analytics" },
  "/reports":              { title: "Reports" },
  "/map":                  { title: "Map" },
  "/dashboards/partner":      { title: "Partner" },
  "/dashboards/cpl":          { title: "Main Dashboard" },
  "/dashboards/director":     { title: "Main Dashboard" },
  "/dashboards/rvp":          { title: "Main Dashboard" },
  "/dashboards/rvp/country-summary":            { title: "Country summary" },
  "/dashboards/director/weekly-debrief-reports": { title: "Weekly Debrief Reports" },
  "/dashboards/hr":           { title: "People & Performance Dashboard" },
  "/dashboards/impact":       { title: "Main Dashboard" },
  "/dashboards/accountant":   { title: "Main Dashboard" },
  "/program-lead/weekly-report": { title: "Weekly Report" },
  "/admin":                { title: "Admin" },
  "/admin/audit-log":      { title: "Audit Log" },
  "/admin/feature-flags":  { title: "Feature Flags" },
  "/admin/users":          { title: "Users & Access" },
  "/activity-log":         { title: "Activity Log" },
  "/alerts":               { title: "Alerts" },
  "/changelog":            { title: "Changelog" },
  "/onboarding":           { title: "Onboarding" },
  "/demo-guide":           { title: "Demo Guide" },
  "/messages":             { title: "Messages" },
  "/notifications":        { title: "Notifications" },
  "/resources":            { title: "Resources" },
  "/leave":                { title: "Leave & Holidays" },
  "/help":                 { title: "Help" },
  "/settings":             { title: "Settings" },
  "/profile":              { title: "Profile" },
  "/search":               { title: "Search" },
  "/more":                 { title: "More" },
  "/districts":            { title: "Districts" },
};

// ────────── Prefix matches for dynamic routes ──────────
// Longest-prefix match wins. Stored ordered most-specific-first.
const PREFIX: { prefix: string; title: string }[] = [
  { prefix: "/dashboards/director/weekly-debrief-reports/", title: "Debrief Report" },
  { prefix: "/data-intake/templates/", title: "Data Template" },
  { prefix: "/budget/approvals/",      title: "Budget Approval" },
  { prefix: "/admin/users/",   title: "User Profile" },
  { prefix: "/clusters/",      title: "Cluster" },
  { prefix: "/data-intake/upload/", title: "Upload detail" },
  { prefix: "/debriefs/",      title: "Debrief" },
  { prefix: "/districts/",     title: "District" },
  { prefix: "/fund-requests/", title: "Fund Request" },
  { prefix: "/help/",          title: "Help Article" },
  { prefix: "/messages/",      title: "Message Thread" },
  { prefix: "/partners/",      title: "Partner" },
  { prefix: "/plans/",         title: "Plan" },
  { prefix: "/projects/",      title: "Project" },
  { prefix: "/schools/",       title: "School" },
  { prefix: "/staff/",         title: "Staff Member" },
];

/** Resolve the default title for a path. Falls back to "Edify" so the
 *  MobileTopBar never reads as blank. */
export function resolveRouteTitle(pathname: string): RouteTitle {
  if (EXACT_ROUTE_TITLES[pathname]) return EXACT_ROUTE_TITLES[pathname];
  for (const { prefix, title } of PREFIX) {
    if (pathname.startsWith(prefix)) return { title };
  }
  return { title: "Edify" };
}
