// Auth + role resolution — the single source of truth for the demo session.
//
// In production this module would call a real /api/auth/session endpoint
// (HTTP-only cookie + JWT). Today we mock it: the LoginPanel writes a
// non-HTTP-only cookie pair (`edify-email` + `edify-role` + `edify-name`)
// and every server component reads from here.
//
// One module owns:
//   • ROLE_REDIRECT       — role → landing route (used by login + /dashboard)
//   • DEMO_USERS          — email → user record (used by login validator)
//   • getCurrentUser()    — server-side resolver. Reads cookies and falls
//                           back to a deterministic default so storybook /
//                           tests / unauth views don't crash.

import "server-only";
import { cookies } from "next/headers";
import type { CurrentUser, AppRole } from "@/lib/schools-mock";

// ────────── Roles ──────────────────────────────────────────────────────

export type EdifyRole =
  | "CCEO"
  | "CountryProgramLead"
  | "CountryDirector"
  | "RVP"
  | "ProgramAccountant"
  | "ImpactAssessment"
  | "HumanResource"
  | "ProjectCoordinator"
  | "Admin"
  | "PartnerAdmin"
  | "PartnerFieldOfficer"
  | "PartnerViewer";

// Role → landing route. The canonical map lives in auth-public.ts (client
// safe). We re-export it here so server callers don't need a second import.
export { ROLE_REDIRECT } from "@/lib/auth-public";

// Sidebar subtitle per role.
export const SUBTITLE_BY_ROLE: Record<EdifyRole, string> = {
  CCEO:                "Field Operations Console",
  CountryProgramLead:  "Country Program Lead Console",
  CountryDirector:     "Country Director Console",
  RVP:                 "Regional VP Console",
  ProgramAccountant:   "Finance Console",
  ImpactAssessment:    "M&E / Impact Console",
  HumanResource:       "People & Performance",
  ProjectCoordinator:  "Special Projects Console",
  Admin:               "Admin Console",
  PartnerAdmin:        "Partner Command Center",
  PartnerFieldOfficer: "Partner Command Center",
  PartnerViewer:       "Partner Command Center",
};

// ────────── Demo user store ────────────────────────────────────────────
//
// In production this is a database. Here it's a static map by email so
// the LoginPanel and getCurrentUser() share one identity per account.
// The intent: log in as paul.chinyama@edify.org → every server component
// downstream resolves `currentUser` to Paul Chinyama with role=CCEO.

export type DemoUser = {
  email: string;
  password: string;
  staffId: string;
  salesforceOwnerId: string;
  name: string;
  initials: string;
  role: EdifyRole;
  appRole: AppRole;          // mirrors the older AppRole type used by mocks
  scope: string;
  /**
   * Staff's home / primary district. Drives the cost-engine's
   * district-type derivation: any school in this district is Primary
   * for cost purposes (no accommodation, lower transport rate), all
   * other districts are Secondary. Optional in the demo — falls back
   * to a role-appropriate default at the call site.
   */
  district?: string;
};

export const DEMO_USERS: Record<string, DemoUser> = {
  "paul.chinyama@edify.org":  { email: "paul.chinyama@edify.org",  password: "edify", staffId: "STF-PC-001", salesforceOwnerId: "0050X000009ABCC", name: "Paul Chinyama",  initials: "PC", role: "CCEO",               appRole: "CCEO",               scope: "Core Schools Officer" },
  "daniel.mwangi@edify.org":  { email: "daniel.mwangi@edify.org",  password: "edify", staffId: "STF-DM-014", salesforceOwnerId: "0050X000009ABCD", name: "Daniel Mwangi",  initials: "DM", role: "CountryProgramLead", appRole: "CountryProgramLead", scope: "Planning Officer" },
  "aisha.dar@edify.org":      { email: "aisha.dar@edify.org",      password: "edify", staffId: "STF-AD-021", salesforceOwnerId: "0050X000009ABCE", name: "Aisha Dar",      initials: "AD", role: "CountryProgramLead", appRole: "CountryProgramLead", scope: "Program Manager" },
  "sarah.okello@edify.org":   { email: "sarah.okello@edify.org",   password: "edify", staffId: "STF-SO-007", salesforceOwnerId: "0050X000009ABCF", name: "Sarah Okello",   initials: "SO", role: "CountryDirector",    appRole: "CountryDirector",    scope: "Country Director" },
  "esther.wanjiru@edify.org": { email: "esther.wanjiru@edify.org", password: "edify", staffId: "STF-EW-003", salesforceOwnerId: "0050X000009ABCG", name: "Esther Wanjiru", initials: "EW", role: "RVP",                appRole: "RVP",                scope: "Regional VP" },
  "anne.wairimu@edify.org":   { email: "anne.wairimu@edify.org",   password: "edify", staffId: "STF-AW-019", salesforceOwnerId: "0050X000009ABCH", name: "Anne Wairimu",   initials: "AW", role: "HumanResource",      appRole: "CountryProgramLead", scope: "People & Performance" },
  "moses.tindi@edify.org":    { email: "moses.tindi@edify.org",    password: "edify", staffId: "STF-MT-031", salesforceOwnerId: "0050X000009ABCJ", name: "Moses Tindi",    initials: "MT", role: "ProgramAccountant",  appRole: "ProgramAccountant",  scope: "Finance Console" },
  "grace.alimo@edify.org":    { email: "grace.alimo@edify.org",    password: "edify", staffId: "STF-GA-042", salesforceOwnerId: "0050X000009ABCK", name: "Grace Alimo",    initials: "GA", role: "ImpactAssessment",   appRole: "ImpactAssessment",   scope: "M&E / Impact"      },
  "admin@edify.org":          { email: "admin@edify.org",          password: "edify", staffId: "STF-AD-001", salesforceOwnerId: "0050X000009ABCL", name: "Edify Admin",    initials: "EA", role: "Admin",              appRole: "Admin",              scope: "Admin Console"     },
  // Project Coordinator — owns special projects. appRole stays CountryProgramLead
  // so the AppRole-keyed data layer (getVisibleProjects, etc.) keeps working;
  // the ProjectCoordinator identity lives on the EdifyRole side (auth/sidebar/UI).
  "rachel.apio@edify.org":    { email: "rachel.apio@edify.org",    password: "edify", staffId: "STF-RA-051", salesforceOwnerId: "0050X000009ABCM", name: "Rachel Apio",    initials: "RA", role: "ProjectCoordinator",  appRole: "CountryProgramLead", scope: "Special Projects Coordinator" },
  "demo@edify.org":           { email: "demo@edify.org",           password: "demo",  staffId: "STF-DD-099", salesforceOwnerId: "0050X000009ABCI", name: "Edify Demo",     initials: "ED", role: "CountryDirector",    appRole: "CountryDirector",    scope: "Country Director" },
  // ─── LTU partner demo accounts (Literacy Training Uganda) ───
  "sarah.kanyi@ltu.org":      { email: "sarah.kanyi@ltu.org",      password: "edify", staffId: "PSF-SK-001", salesforceOwnerId: "0050X000009LTU1", name: "Sarah Kanyi",   initials: "SK", role: "PartnerAdmin",        appRole: "CCEO", scope: "Partner Admin"        },
  "abel.opio@ltu.org":        { email: "abel.opio@ltu.org",        password: "edify", staffId: "PSF-AO-002", salesforceOwnerId: "0050X000009LTU2", name: "Abel Opio",     initials: "AO", role: "PartnerFieldOfficer", appRole: "CCEO", scope: "Partner Field Officer" },
  "donor@ltu-funder.org":     { email: "donor@ltu-funder.org",     password: "edify", staffId: "PSF-LD-001", salesforceOwnerId: "0050X000009LTU3", name: "LTU Donor",     initials: "LD", role: "PartnerViewer",       appRole: "CCEO", scope: "Partner Viewer"        },
  // ─── BFEP partner demo accounts (Bright Future Education Partners) ───
  // Aligned with the Partner Dashboard reference build at /dashboards/partner.
  // BFEP is the org used throughout partner-dashboard-mock.ts — 24 schools
  // across Mukono + Kayunga, contract BFEP-UG-012. Daniel Mwangi here is
  // the BFEP focal person (distinct from daniel.mwangi@edify.org who is
  // the country program lead on the Edify staff side).
  "daniel.mwangi@brightfuture.org": { email: "daniel.mwangi@brightfuture.org", password: "edify", staffId: "PSF-DM-BFEP", salesforceOwnerId: "0050X000009BFE1", name: "Daniel Mwangi",  initials: "DM", role: "PartnerAdmin",        appRole: "CCEO", scope: "Partner Admin"         },
  "ruth.kabuye@brightfuture.org":   { email: "ruth.kabuye@brightfuture.org",   password: "edify", staffId: "PSF-RK-BFEP", salesforceOwnerId: "0050X000009BFE2", name: "Ruth Kabuye",    initials: "RK", role: "PartnerFieldOfficer", appRole: "CCEO", scope: "Partner Field Officer" },
  "sarah.nanyongo@edify.org":       { email: "sarah.nanyongo@edify.org",       password: "edify", staffId: "STF-SN-BFEP", salesforceOwnerId: "0050X000009BFE3", name: "Sarah Nanyongo", initials: "SN", role: "PartnerViewer",       appRole: "CCEO", scope: "Edify Focal · BFEP"    },
};

// Internal fallback identity used ONLY in dev (NODE_ENV !== "production")
// when no cookie is present — so storybook / preview routes / unit tests
// don't crash. Production code paths never reach this because
// `src/middleware.ts` redirects anonymous traffic on protected routes
// before any page renders.
//
// HOSTING-SECURITY: the fallback is hard-gated to non-production below.
// Middleware does NOT gate `/api/*`, so without this gate an anonymous
// caller to a proxy route (e.g. /api/evidence/<id>/file) would resolve to
// this real PL identity and be served scoped data. In production the
// resolver instead throws, so no anonymous caller ever gets an identity.
const ANONYMOUS_FALLBACK: DemoUser = DEMO_USERS["daniel.mwangi@edify.org"];
const IS_PRODUCTION = process.env.NODE_ENV === "production";

// The privileged admin identity is disabled in production unless explicitly
// enabled (mirrors the FE login store + backend seed). This gates IDENTITY
// RESOLUTION, not just password seeding — so even a forged/leaked
// `edify-email=admin@edify.org` cookie can't resolve as Admin on the (ungated)
// /api/* proxies. NOTE: session cookies are unsigned; a host-level gate remains
// the primary control against role-forgery in general.
const ADMIN_ENABLED = process.env.ENABLE_DEMO_ADMIN === "true" || !IS_PRODUCTION;
function gateAdmin(u: DemoUser | null): DemoUser | null {
  if (u && !ADMIN_ENABLED && (u.email.toLowerCase() === "admin@edify.org" || u.role === "Admin")) return null;
  return u;
}

// ────────── Server-side resolvers ──────────────────────────────────────

// Reads the session cookie and returns the active user, or null if no
// valid session cookie is present. Use this when the page handles the
// unauthenticated case itself (e.g. /login, /signup).
export async function getCurrentUserOrNull(): Promise<DemoUser | null> {
  const jar = await cookies();
  const email = jar.get("edify-email")?.value?.toLowerCase();
  if (email && DEMO_USERS[email]) return gateAdmin(DEMO_USERS[email]);
  // Legacy: some early sessions only set `edify-role` + `edify-name`.
  const role = jar.get("edify-role")?.value as EdifyRole | undefined;
  const name = jar.get("edify-name")?.value;
  if (role) {
    const match = Object.values(DEMO_USERS).find(
      (u) => u.role === role && (!name || decodeURIComponent(name) === u.name),
    );
    if (match) return gateAdmin(match);
  }
  return null;
}

// Server-side resolver used by shell pages. Returns the signed-in user
// or, when no session cookie is present (unauthenticated requests to
// unprotected routes that still happen to render server components),
// returns ANONYMOUS_FALLBACK so layout-level chrome doesn't crash.
//
// SECURITY MODEL: route protection lives in `src/middleware.ts`, which
// redirects anonymous traffic on protected routes to /login BEFORE any
// page renders. This resolver therefore must never be the security
// gate — it's a convenience that always yields a DemoUser. Pages that
// need to handle the "no session" case explicitly should use
// `getCurrentUserOrNull()` instead.
export async function getCurrentUser(): Promise<DemoUser> {
  const user = await getCurrentUserOrNull();
  if (user) return user;
  // In production never hand a privileged identity to an anonymous caller.
  // Pages are redirected to /login by middleware before they render; any
  // server context that still reaches here (notably the `/api/*` proxies,
  // which middleware does not gate) is genuinely unauthenticated.
  if (IS_PRODUCTION) throw new Error("UNAUTHENTICATED");
  return ANONYMOUS_FALLBACK;
}

// Read just the role — handy when a server component only needs to pick a
// dashboard layout / sidebar variant.
export async function getCurrentRole(): Promise<EdifyRole> {
  return (await getCurrentUser()).role;
}

// Translate a `DemoUser` into the older `CurrentUser` shape used by the
// mock layer. Keeps existing `getVisibleX(currentUser)` filters working
// without us refactoring every mock.
export function toCurrentUser(u: DemoUser): CurrentUser {
  return {
    staffId:           u.staffId,
    salesforceOwnerId: u.salesforceOwnerId,
    email:             u.email,
    name:              u.name,
    initials:          u.initials,
    role:              u.appRole,
    country:           "Uganda",
    scope:             u.scope as CurrentUser["scope"],
  };
}
