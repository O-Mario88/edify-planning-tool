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
import { sessionSigningActive, verifySession, SESSION_SIG_COOKIE } from "@/lib/session-sig";

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
import { SUPER_ADMIN_EMAIL } from "@/lib/auth-public";

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

// Online-test roster — exactly 10 accounts (password "edify"), aligned 1:1 with the
// backend edify_pm user table so login + getCurrentUser + the email-keyed FE↔BE
// bridge all resolve. (Earlier named/partner demo accounts were trimmed for Phase 1.)
export const DEMO_USERS: Record<string, DemoUser> = {
  "cceo@edify.org":       { email: "cceo@edify.org",       password: "edify", staffId: "STF-PC-001", salesforceOwnerId: "0050X000009ABCC", name: "Paul Chinyama", initials: "PC", role: "CCEO",               appRole: "CCEO",               scope: "Core Schools Officer" },
  "pl1@edify.org":        { email: "pl1@edify.org",        password: "edify", staffId: "STF-DM-014", salesforceOwnerId: "0050X000009ABCD", name: "Daniel Mwangi", initials: "DM", role: "CountryProgramLead", appRole: "CountryProgramLead", scope: "Program Lead" },
  "pl2@edify.org":        { email: "pl2@edify.org",        password: "edify", staffId: "STF-AD-021", salesforceOwnerId: "0050X000009ABCE", name: "Aisha Dar",     initials: "AD", role: "CountryProgramLead", appRole: "CountryProgramLead", scope: "Program Lead" },
  "pl3@edify.org":        { email: "pl3@edify.org",        password: "edify", staffId: "STF-SK-022", salesforceOwnerId: "0050X000009ABCN", name: "Samuel Kato",   initials: "SK", role: "CountryProgramLead", appRole: "CountryProgramLead", scope: "Program Lead" },
  "pl4@edify.org":        { email: "pl4@edify.org",        password: "edify", staffId: "STF-RA-051", salesforceOwnerId: "0050X000009ABCM", name: "Rachel Apio",   initials: "RA", role: "CountryProgramLead", appRole: "CountryProgramLead", scope: "Program Lead" },
  "cd@edify.org":         { email: "cd@edify.org",         password: "edify", staffId: "STF-SO-007", salesforceOwnerId: "0050X000009ABCF", name: "Sarah Okello",  initials: "SO", role: "CountryDirector",    appRole: "CountryDirector",    scope: "Country Director" },
  "rvp@edify.org":        { email: "rvp@edify.org",        password: "edify", staffId: "STF-RV-003", salesforceOwnerId: "0050X000009ABCG", name: "Robert Vance",  initials: "RV", role: "RVP",                appRole: "RVP",                scope: "Regional VP" },
  "ia@edify.org":         { email: "ia@edify.org",         password: "edify", staffId: "STF-GA-042", salesforceOwnerId: "0050X000009ABCK", name: "Grace Alimo",   initials: "GA", role: "ImpactAssessment",   appRole: "ImpactAssessment",   scope: "M&E / Impact" },
  "accountant@edify.org": { email: "accountant@edify.org", password: "edify", staffId: "STF-MT-031", salesforceOwnerId: "0050X000009ABCJ", name: "Moses Tindi",   initials: "MT", role: "ProgramAccountant",  appRole: "ProgramAccountant",  scope: "Finance Console" },
  "admin@edify.org":      { email: "admin@edify.org",      password: "edify", staffId: "STF-AD-001", salesforceOwnerId: "0050X000009ABCL", name: "Edify Admin",   initials: "EA", role: "Admin",              appRole: "Admin",              scope: "Admin Console" },
  // Named onboarding super-admin — always enabled, including production (see
  // gateAdmin below). Password is seeded server-side from SUPER_ADMIN_PASSWORD
  // (auth-runtime-store.ts); the field here is unused for validation.
  "domario@edify.org":    { email: "domario@edify.org",    password: "edify", staffId: "STF-SA-001", salesforceOwnerId: "0050X000009ABDA", name: "Omario Edwin",  initials: "OE", role: "Admin",              appRole: "Admin",              scope: "Admin Console" },
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
const ANONYMOUS_FALLBACK: DemoUser = DEMO_USERS["pl1@edify.org"];
const IS_PRODUCTION = process.env.NODE_ENV === "production";

// The privileged admin identity is disabled in production unless explicitly
// enabled (mirrors the FE login store + backend seed). This gates IDENTITY
// RESOLUTION, not just password seeding — so even a forged/leaked
// `edify-email=admin@edify.org` cookie can't resolve as Admin on the (ungated)
// /api/* proxies. NOTE: session cookies are unsigned; a host-level gate remains
// the primary control against role-forgery in general.
const ADMIN_ENABLED = process.env.ENABLE_DEMO_ADMIN === "true" || !IS_PRODUCTION;
function gateAdmin(u: DemoUser | null): DemoUser | null {
  if (!u) return u;
  // The named onboarding super-admin is ALWAYS enabled — it's the platform
  // owner's real account, not the generic demo admin, so it bypasses the
  // production admin gate.
  if (u.email.toLowerCase() === SUPER_ADMIN_EMAIL) return u;
  if (!ADMIN_ENABLED && (u.email.toLowerCase() === "admin@edify.org" || u.role === "Admin")) return null;
  return u;
}

// ────────── Server-side resolvers ──────────────────────────────────────

// Reads the session cookie and returns the active user, or null if no
// valid session cookie is present. Use this when the page handles the
// unauthenticated case itself (e.g. /login, /signup).
//
// Django is the single source of truth for identity + role. A signed-in user
// may not be in the static DEMO_USERS map (Django has more accounts than the FE
// roster); in that case we synthesize a DemoUser from the (signed) cookie so the
// rest of the app keeps working. The cookie signature is verified when signing
// is active, so the synthesized identity can't be forged.
export async function getCurrentUserOrNull(): Promise<DemoUser | null> {
  const jar = await cookies();
  const rawEmail = jar.get("edify-email")?.value;
  const rawRole = jar.get("edify-role")?.value;
  const sig = jar.get(SESSION_SIG_COOKIE)?.value;
  // Reject a tampered / forged identity when signing is active (production with
  // EDIFY_SESSION_SECRET set). Without a valid HMAC over (email, role) the
  // session is treated as unauthenticated — closes the role-forge into /api/*.
  if (sessionSigningActive()) {
    if (!rawEmail || !rawRole || !(await verifySession(rawEmail, rawRole, sig))) return null;
  }
  const email = rawEmail?.toLowerCase();
  if (email && DEMO_USERS[email]) return gateAdmin(DEMO_USERS[email]);
  // Legacy: some early sessions only set `edify-role` + `edify-name`.
  const role = rawRole as EdifyRole | undefined;
  const name = jar.get("edify-name")?.value;
  if (role) {
    const match = Object.values(DEMO_USERS).find(
      (u) => u.role === role && (!name || decodeURIComponent(name) === u.name),
    );
    if (match) return gateAdmin(match);
  }
  // Django-sourced identity not in the static FE roster: synthesize a DemoUser
  // from the signed cookie. Email + role are trusted (signature-verified above
  // when signing is active); the staffId/salesforce fields are placeholders the
  // proxy layer doesn't use (the real identity comes from the Django JWT).
  if (email && role) {
    return gateAdmin({
      email,
      password: "", // never used for FE-side validation now (Django is authoritative)
      staffId: "",
      salesforceOwnerId: "",
      name: name ? decodeURIComponent(name) : email,
      initials: (name ? decodeURIComponent(name) : email).slice(0, 2).toUpperCase(),
      role,
      appRole: role as AppRole,
      scope: role,
    });
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
