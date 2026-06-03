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

// Demo accounts. Production swaps this for a real auth provider; the
// shape is otherwise unchanged.
export const DEMO_USERS: Record<string, ClientDemoUser> = {
  "paul.chinyama@edify.org":  { email: "paul.chinyama@edify.org",  password: "edify", role: "CCEO",               name: "Paul Chinyama"  },
  "daniel.mwangi@edify.org":  { email: "daniel.mwangi@edify.org",  password: "edify", role: "CountryProgramLead", name: "Daniel Mwangi"  },
  "aisha.dar@edify.org":      { email: "aisha.dar@edify.org",      password: "edify", role: "CountryProgramLead", name: "Aisha Dar"      },
  "sarah.okello@edify.org":   { email: "sarah.okello@edify.org",   password: "edify", role: "CountryDirector",    name: "Sarah Okello"   },
  "esther.wanjiru@edify.org": { email: "esther.wanjiru@edify.org", password: "edify", role: "RVP",                name: "Esther Wanjiru" },
  "anne.wairimu@edify.org":   { email: "anne.wairimu@edify.org",   password: "edify", role: "HumanResource",      name: "Anne Wairimu"   },
  "moses.tindi@edify.org":    { email: "moses.tindi@edify.org",    password: "edify", role: "ProgramAccountant",  name: "Moses Tindi"    },
  "grace.alimo@edify.org":    { email: "grace.alimo@edify.org",    password: "edify", role: "ImpactAssessment",   name: "Grace Alimo"    },
  "admin@edify.org":          { email: "admin@edify.org",          password: "edify", role: "Admin",              name: "Edify Admin"    },
  "rachel.apio@edify.org":    { email: "rachel.apio@edify.org",    password: "edify", role: "ProjectCoordinator", name: "Rachel Apio"    },
  "demo@edify.org":           { email: "demo@edify.org",           password: "demo",  role: "CountryDirector",    name: "Edify Demo"     },
  // ─── Partner demo accounts ───
  // PartnerAdmin — Sarah Kanyi at Literacy Training Uganda. Sees all
  // LTU activities, can submit plans, can respond to corrections.
  "sarah.kanyi@ltu.org":      { email: "sarah.kanyi@ltu.org",      password: "edify", role: "PartnerAdmin",         name: "Sarah Kanyi"    },
  // PartnerFieldOfficer — Abel Opio, an LTU trainer. Sees assigned
  // schools, can upload evidence, can't approve.
  "abel.opio@ltu.org":        { email: "abel.opio@ltu.org",        password: "edify", role: "PartnerFieldOfficer",  name: "Abel Opio"      },
  // PartnerViewer — donor / advisor with read-only access to verified
  // partner work for the contract they support.
  "donor@ltu-funder.org":     { email: "donor@ltu-funder.org",     password: "edify", role: "PartnerViewer",        name: "LTU Donor"      },
  // ─── Bright Future Education Partners (BFEP) ───
  // Demo accounts aligned with the Partner Dashboard reference build
  // (/dashboards/partner). BFEP is the org used throughout
  // partner-dashboard-mock.ts — 24 schools across Mukono + Kayunga,
  // contract BFEP-UG-012. PartnerAdmin lands on the full dashboard;
  // the FieldOfficer / Viewer accounts share the same landing with
  // role-scoped affordances.
  "daniel.mwangi@brightfuture.org": { email: "daniel.mwangi@brightfuture.org", password: "edify", role: "PartnerAdmin",        name: "Daniel Mwangi"  },
  "ruth.kabuye@brightfuture.org":   { email: "ruth.kabuye@brightfuture.org",   password: "edify", role: "PartnerFieldOfficer", name: "Ruth Kabuye"    },
  "sarah.nanyongo@edify.org":       { email: "sarah.nanyongo@edify.org",       password: "edify", role: "PartnerViewer",       name: "Sarah Nanyongo" },
};
