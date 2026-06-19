// Client-safe view of the auth module.
//
// `lib/auth.ts` is `server-only` (uses next/headers cookies()). This file
// exposes the parts that *must* run on the client too — the login form's
// password validator, the role list, and the role → route map. Keep this
// file free of any server-only imports.

export type EdifyRole =
  | "CCEO"
  | "CountryProgramLead"
  | "CountryDirector"
  | "RVP"
  | "ProgramAccountant"
  | "ImpactAssessment"
  | "HumanResource"
  // Project Coordinator — owns special projects & targeted interventions
  // (maps initiatives to SSA interventions, assigns schools, monitors impact).
  | "ProjectCoordinator"
  | "Admin"
  // Partner Operating Layer — three permission-distinct user types
  // inside a partner organisation. All three land on the same
  // /dashboards/partner page; the page reads the user's PartnerUser
  // record (userType) to decide what's editable vs read-only.
  | "PartnerAdmin"
  | "PartnerFieldOfficer"
  | "PartnerViewer";

export const ROLE_REDIRECT: Record<EdifyRole, string> = {
  // CCEOs land on /my-targets — their personal command center (route map
  // for this week, todo list, target progress, supervisor signals).
  CCEO:               "/my-targets",
  CountryProgramLead: "/dashboards/cpl",
  CountryDirector:    "/dashboards/director",
  RVP:                "/dashboards/rvp",
  ProgramAccountant:  "/dashboards/accountant",
  ImpactAssessment:   "/dashboards/impact",
  // HR lands on their own console — fairness context, support watchlist,
  // recognition board. /team-targets is one tab in their menu but no
  // longer the primary landing page.
  HumanResource:      "/dashboards/hr",
  ProjectCoordinator: "/dashboards/project-coordinator",
  Admin:              "/dashboards/director",
  // Partners land on Today first — a calm to-do, not a dashboard
  // full of analytics. Overview stays reachable from the sidebar
  // for when the partner wants the wider picture.
  PartnerAdmin:        "/partner/today",
  PartnerFieldOfficer: "/partner/today",
  PartnerViewer:       "/partner/today",
};

export type ClientDemoUser = {
  email: string;
  password: string;
  name: string;
  role: EdifyRole;
};

// The named super-admin account. Unlike the generic demo `admin@edify.org`
// (disabled in production unless ENABLE_DEMO_ADMIN=true), this account is a
// real onboarding super-admin that is ALWAYS enabled — including production —
// so the platform owner can sign in to manage users/roles on the live host.
// Its password is NOT the shared demo password: it's seeded server-side in
// lib/auth-runtime-store.ts from SUPER_ADMIN_PASSWORD (so the real secret never
// ships to the browser bundle). The `password` field below is a placeholder
// only — the login route validates against the server-side runtime store.
export const SUPER_ADMIN_EMAIL = "domario@edify.org";

// Demo accounts. Production swaps this for a real auth provider; the
// shape is otherwise unchanged.
// Online-test roster — 10 accounts (password "edify"), aligned 1:1 with the backend.
export const DEMO_USERS: Record<string, ClientDemoUser> = {
  "cceo@edify.org":       { email: "cceo@edify.org",       password: "edify", role: "CCEO",               name: "Paul Chinyama" },
  "pl1@edify.org":        { email: "pl1@edify.org",        password: "edify", role: "CountryProgramLead", name: "Daniel Mwangi" },
  "pl2@edify.org":        { email: "pl2@edify.org",        password: "edify", role: "CountryProgramLead", name: "Aisha Dar" },
  "pl3@edify.org":        { email: "pl3@edify.org",        password: "edify", role: "CountryProgramLead", name: "Samuel Kato" },
  "pl4@edify.org":        { email: "pl4@edify.org",        password: "edify", role: "CountryProgramLead", name: "Rachel Apio" },
  "cd@edify.org":         { email: "cd@edify.org",         password: "edify", role: "CountryDirector",    name: "Sarah Okello" },
  "rvp@edify.org":        { email: "rvp@edify.org",        password: "edify", role: "RVP",                name: "Robert Vance" },
  "ia@edify.org":         { email: "ia@edify.org",         password: "edify", role: "ImpactAssessment",   name: "Grace Alimo" },
  "accountant@edify.org": { email: "accountant@edify.org", password: "edify", role: "ProgramAccountant",  name: "Moses Tindi" },
  "admin@edify.org":      { email: "admin@edify.org",      password: "edify", role: "Admin",              name: "Edify Admin" },
  // Named onboarding super-admin — always enabled (see SUPER_ADMIN_EMAIL above).
  // The `password` here is an unused placeholder; the real credential is seeded
  // server-side from SUPER_ADMIN_PASSWORD and validated by the login route.
  "domario@edify.org":    { email: "domario@edify.org",    password: "edify", role: "Admin",              name: "Omario Edwin" },
};
