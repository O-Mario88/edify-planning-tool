// Edge middleware — authoritative route gate for the Edify shell.
//
// Responsibilities:
//   1. Block anonymous access to any authenticated route under (shell)
//      or under the role-specific paths (/dashboards, /budget, /admin,
//      /cost-settings, /data-intake, /debriefs, /schools, /plans, etc.).
//      → redirect to /login with ?next=<original> for post-login bounce.
//
//   2. Block wrong-role access to role-restricted dashboards. For each
//      restricted prefix, only listed roles may pass; any other signed-in
//      user is redirected to their own role's landing page.
//
// Public routes (login, signup, forgot/reset password, legal pages, API
// auth endpoints, static assets) are always allowed.
//
// We deliberately keep the cookie read minimal and stateless — middleware
// runs on every request, so it must not depend on any server-only or
// node-only module. The Edify session is three cookies set by
// /api/auth/login: edify-email, edify-role, edify-name.

import { NextResponse, type NextRequest } from "next/server";
import { DEMO_USERS, ROLE_REDIRECT, type EdifyRole } from "@/lib/auth-public";
import { CSRF_COOKIE_NAME, generateCsrfToken } from "@/lib/csrf";

// Dev-only `?as=<Role>` impersonation. Production: hard no-op.
//
// Lets a developer preview any role by appending `?as=PartnerAdmin`
// (or any EdifyRole value) to a URL. The middleware:
//   1. Resolves the role to its canonical demo user via DEMO_USERS
//   2. Sets the three session cookies (edify-email/-role/-name)
//   3. Strips the query and redirects so the URL stays clean
//
// Security: gated behind `NODE_ENV !== "production"`. In prod, a
// stray `?as=Admin` is ignored — the middleware reads cookies as
// usual and the request is treated as anonymous if those are absent.
const KNOWN_ROLES = new Set<EdifyRole>([
  "CCEO", "CountryProgramLead", "CountryDirector", "RVP",
  "ProgramAccountant", "ImpactAssessment", "HumanResource", "ProjectCoordinator", "Admin",
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer",
]);

const DEMO_USER_BY_ROLE: Partial<Record<EdifyRole, string>> = (() => {
  const map: Partial<Record<EdifyRole, string>> = {};
  for (const u of Object.values(DEMO_USERS)) {
    if (!map[u.role]) map[u.role] = u.email;
  }
  return map;
})();

// ──────────────────────────────────────────────────────────────────────
// Public routes — never gated. Anything not in this list AND not under
// PROTECTED_PREFIXES is allowed (e.g. /api/auth/*, static assets).
// ──────────────────────────────────────────────────────────────────────

const PUBLIC_PATHS = new Set<string>([
  "/login",
  "/signup",
  "/forgot-password",
  "/reset-password",
  "/legal/privacy",
  "/legal/terms",
]);

// Routes that REQUIRE an authenticated session. Everything else is
// allowed by default (auth API routes, _next assets, favicon, etc.).
const PROTECTED_PREFIXES = [
  "/dashboards",
  "/dashboard",
  "/activities",
  "/access-restricted",
  "/school-directory",
  "/recruitment",
  "/system-health",
  "/my-targets",
  "/my-plan",
  "/my-team",
  "/team-targets",
  "/plans",
  "/planning",
  "/schools",
  "/staff",
  "/partners",
  "/route",
  "/visits",
  "/today",
  "/trainings",
  "/completed-activities",
  "/team-plan",
  "/notifications",
  "/messages",
  "/budget",
  "/cost-settings",
  "/data-intake",
  "/data-verification",
  "/debriefs",
  "/field-intelligence",
  "/program-lead",
  "/quality-checks",
  "/queue",
  "/reports",
  "/resources",
  "/special-projects",
  "/projects",
  "/ssa",
  "/core-schools",
  "/map",
  "/search",
  "/settings",
  "/profile",
  "/more",
  "/leave",
  "/onboarding",
  "/coverage",
  "/admin",
  "/focus",
  "/partner",
  // Field-coach + finance surfaces (previously missing — these were
  // reachable without a session because protection is allowlist-based).
  "/evidence",
  "/clusters",
  "/weekly-funds",
  "/disbursements",
  "/fund-requests",
  "/analytics",
  "/approvals",
  "/monthly-fund-request",
  // Audit round 3 — these data/management surfaces were absent from the
  // allowlist, so they bypassed the login wall entirely (the shell
  // layout uses getCurrentUserOrNull and never redirects).
  "/capacity",
  "/calendar",
  "/fy",
  "/exam-scores",
  "/discipleship-clubs",
  "/donor-reporting",
];

// Role-restricted prefixes. Map prefix → roles allowed. Anyone else with
// a valid session gets bounced to their own role homepage.
const ROLE_RESTRICTED: Array<{ prefix: string; allow: EdifyRole[] }> = [
  { prefix: "/dashboards/director",   allow: ["CountryDirector", "Admin"] },
  { prefix: "/dashboards/cpl",        allow: ["CountryProgramLead", "Admin"] },
  { prefix: "/dashboards/rvp",        allow: ["RVP", "Admin"] },
  { prefix: "/dashboards/hr",         allow: ["HumanResource", "Admin"] },
  { prefix: "/dashboards/accountant", allow: ["ProgramAccountant", "Admin"] },
  { prefix: "/dashboards/impact",     allow: ["ImpactAssessment", "Admin"] },
  { prefix: "/dashboards/project-coordinator", allow: ["ProjectCoordinator", "Admin"] },
  // Partner Operating Layer — partner users land here; Admin can also
  // view for support purposes. Edify staff are NOT allowed in (the
  // page enforces partner-scoped reads, which would surface nothing
  // useful to a staff role).
  { prefix: "/dashboards/partner",    allow: ["PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin"] },
  // Partner workflow sub-pages (assignments, schedule, today, evidence,
  // corrections, payments, schools, support-journey, reports, messages,
  // profile, help) — same access model as /dashboards/partner.
  { prefix: "/partner",               allow: ["PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin"] },
  { prefix: "/admin",                 allow: ["Admin"] },
  { prefix: "/system-health",         allow: ["Admin"] },
  { prefix: "/cost-settings",         allow: ["CountryDirector", "Admin", "ProgramAccountant"] },
  { prefix: "/budget/approvals",      allow: ["CountryProgramLead", "CountryDirector", "RVP", "ProgramAccountant", "Admin"] },
  // Fund Approvals — financial sign-off surface. Restricted to the
  // four roles that actually have an approval / disbursement role in
  // the fund flow:
  //   • CountryProgramLead — approves team CCEO fund requests
  //   • CountryDirector    — approves country-level requests
  //   • RVP                — regional cross-country oversight
  //   • ProgramAccountant  — clears disbursement, treasury intake
  // Admin retains access for support. Everyone else (including IA +
  // CCEO + HR + Partner) is bounced to their role's home.
  { prefix: "/approvals",             allow: ["CountryProgramLead", "CountryDirector", "RVP", "ProgramAccountant", "Admin"] },
  // Monthly Fund Request — country-level monthly envelope auto-generated
  // from approved monthly plans. Same role gate as /approvals: PL
  // reviews, CD reviews + approves, RVP sees only after CD approval,
  // Accountant prepares disbursement after RVP approval.
  { prefix: "/monthly-fund-request",  allow: ["CountryProgramLead", "CountryDirector", "RVP", "ProgramAccountant", "Admin"] },
  { prefix: "/program-lead",          allow: ["CountryProgramLead", "Admin"] },
  // Data intake (Add School / Upload SSA / templates / queue / readiness)
  // is IA + Admin only — "CD does cost, not data" and the accountant's
  // intake is treasury (weekly-funds), not school data. Previously also
  // allowed ProgramAccountant + CountryDirector, who could then VIEW the
  // ungated Upload Center subpages.
  { prefix: "/data-intake",           allow: ["ImpactAssessment", "Admin"] },
  // Plan Builder workspace — same field-planning roles as /planning +
  // /my-plan. Was auth-only with no role gate, so any session (Accountant,
  // IA, RVP, HR) could open the full builder.
  { prefix: "/plans",                 allow: ["CCEO", "CountryProgramLead", "Admin"] },
  // Capacity dashboards — CCEO (own) + PL (team) view; CD/IA set the
  // per-staff support limits. Excludes RVP/HR/Accountant/Partner.
  { prefix: "/capacity",              allow: ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"] },
  // Analytics — portfolio/country intelligence for the program roles.
  // HR (people ops) and partner users have no analytics surface.
  { prefix: "/analytics",             allow: ["CCEO", "CountryProgramLead", "CountryDirector", "RVP", "ImpactAssessment", "ProjectCoordinator", "Admin"] },
  // Leadership Decision Engine — executive advisory layer. Broader than the
  // rest of analytics: HR (staff/HR board) and the Accountant (finance-implication
  // view) are included; CCEO/ProjectCoordinator are not leadership-decision roles.
  // Longest-prefix-wins, so this overrides the /analytics rule above.
  { prefix: "/analytics/decision-engine", allow: ["CountryDirector", "RVP", "HumanResource", "ImpactAssessment", "CountryProgramLead", "ProgramAccountant", "Admin"] },
  // Fund requests carry money amounts — visible to the fund-flow roles
  // only. HR + IA + partners are bounced.
  { prefix: "/fund-requests",         allow: ["CCEO", "CountryProgramLead", "CountryDirector", "RVP", "ProgramAccountant", "Admin"] },
  // School Directory — operational working surface. Only the roles that
  // actually work schools (CCEO, PL, IA) + the project coordinator who
  // assigns project schools. CD/RVP/HR/Accountant/Partner are bounced to an
  // Access Restricted page (they lead through analytics, not the directory).
  { prefix: "/schools",               allow: ["CCEO", "CountryProgramLead", "ImpactAssessment", "ProjectCoordinator", "Admin"] },
  { prefix: "/school-directory",      allow: ["CCEO", "CountryProgramLead", "ImpactAssessment", "ProjectCoordinator", "Admin"] },
  // Field planning surfaces — operational working pages for the roles that
  // plan and execute school activities (CCEO plans their portfolio, PL plans
  // for themselves + their team). The Country Director leads through the
  // executive dashboard, analytics, and approvals — never row-level field
  // planning — so the CD (and every non-field role) is bounced to the
  // Access Restricted page that explains the executive view instead.
  { prefix: "/planning",              allow: ["CCEO", "CountryProgramLead", "Admin"] },
  { prefix: "/my-plan",               allow: ["CCEO", "CountryProgramLead", "Admin"] },
  { prefix: "/completed-activities",  allow: ["CCEO", "CountryProgramLead", "Admin"] },
  // Team Plan — the PL's per-CCEO supervision workspace. Scoped to the
  // supervision chain, so only the PL (and Admin) can open it.
  { prefix: "/team-plan",             allow: ["CountryProgramLead", "Admin"] },
  // Evidence & Accountability — the field officer's own proof queues
  // (evidence, Salesforce ID, IA returns, accountability). Personal to
  // the field roles; leadership reads the same truth through analytics.
  { prefix: "/evidence",              allow: ["CCEO", "CountryProgramLead", "Admin"] },
  // Disbursement console — accountant payment controls. CCEOs track
  // payment STATUS through weekly funds + partner monitoring, never the
  // pay-out controls themselves (spec: CCEO must not see accountant
  // payment controls).
  { prefix: "/disbursements",         allow: ["ProgramAccountant", "CountryDirector", "Admin"] },
];

// Prefixes whose wrong-role bounce should land on the explicit Access
// Restricted page (not a silent redirect to the role's home).
const SHOW_ACCESS_RESTRICTED = [
  "/schools",
  "/school-directory",
  "/planning",
  "/my-plan",
  "/completed-activities",
];

function isProtected(pathname: string): boolean {
  if (PUBLIC_PATHS.has(pathname)) return false;
  return PROTECTED_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(p + "/"),
  );
}

function restrictionFor(pathname: string): EdifyRole[] | null {
  // Most specific prefix wins (longest match).
  let best: { prefix: string; allow: EdifyRole[] } | null = null;
  for (const r of ROLE_RESTRICTED) {
    if (pathname === r.prefix || pathname.startsWith(r.prefix + "/")) {
      if (!best || r.prefix.length > best.prefix.length) best = r;
    }
  }
  return best ? best.allow : null;
}

// Attaches the CSRF cookie to a response if the request didn't already
// carry one. Non-HttpOnly by design — client JS reads it and echoes
// the value back as the x-csrf-token header on mutating fetches
// (double-submit pattern; see lib/csrf.ts).
function ensureCsrfCookie(req: NextRequest, res: NextResponse): NextResponse {
  if (req.cookies.get(CSRF_COOKIE_NAME)) return res;
  res.cookies.set(CSRF_COOKIE_NAME, generateCsrfToken(), {
    path: "/",
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    // NOT HttpOnly — client JS needs to read this.
    httpOnly: false,
    maxAge: 60 * 60 * 24 * 365, // 1 year, rotation isn't necessary for double-submit
  });
  return res;
}

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;

  // ─── Dev-only `?as=<Role>` impersonation ───────────────────────────
  // Hard-gated by NODE_ENV so production builds can never trigger this.
  if (process.env.NODE_ENV !== "production") {
    const asParam = req.nextUrl.searchParams.get("as");
    if (asParam && KNOWN_ROLES.has(asParam as EdifyRole)) {
      const role = asParam as EdifyRole;
      const email = DEMO_USER_BY_ROLE[role];
      const user = email ? DEMO_USERS[email] : undefined;
      if (user) {
        // Strip ?as= and redirect to the clean URL with the cookies set.
        const clean = req.nextUrl.clone();
        clean.searchParams.delete("as");
        const res = NextResponse.redirect(clean);
        // Dev cookies are NOT httpOnly so the preview iframe / proxy
        // layers pass them through reliably. In production this
        // branch is unreachable (NODE_ENV gate above), so the lower
        // security bar here doesn't widen the prod attack surface.
        const opts = {
          path: "/",
          maxAge: 60 * 60 * 24 * 30,
          sameSite: "lax" as const,
          httpOnly: false,
          secure: false,
        };
        res.cookies.set("edify-email", user.email, opts);
        res.cookies.set("edify-role", user.role, opts);
        res.cookies.set("edify-name", user.name, opts);
        return ensureCsrfCookie(req, res);
      }
    }
  }

  // Always allow internal Next.js paths + favicon + api routes
  // (api/auth/* gates itself; api/demo/* gates itself in production).
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/assets/") ||
    pathname === "/" ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  if (!isProtected(pathname)) {
    // Public pages (login, signup, etc.) still need a CSRF cookie so
    // the form submits to /api/auth/login carry the token.
    return ensureCsrfCookie(req, NextResponse.next());
  }

  const role = req.cookies.get("edify-role")?.value as EdifyRole | undefined;
  const email = req.cookies.get("edify-email")?.value;

  // Not signed in → bounce to /login with ?next= so the user comes back.
  if (!role || !email) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return ensureCsrfCookie(req, NextResponse.redirect(url));
  }

  // Signed in but wrong role for this restricted prefix → bounce to
  // their own role's landing page.
  const allow = restrictionFor(pathname);
  if (allow && !allow.includes(role)) {
    const url = req.nextUrl.clone();
    const showRestricted = SHOW_ACCESS_RESTRICTED.some(
      (p) => pathname === p || pathname.startsWith(p + "/"),
    );
    if (showRestricted) {
      url.pathname = "/access-restricted";
      url.search = `?from=${encodeURIComponent(pathname)}`;
    } else {
      url.pathname = ROLE_REDIRECT[role] ?? "/login";
      url.search = "";
    }
    return ensureCsrfCookie(req, NextResponse.redirect(url));
  }

  return ensureCsrfCookie(req, NextResponse.next());
}

export const config = {
  // Run on everything except Next internals + static. The handler above
  // does the fine-grained logic.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|assets/).*)",
  ],
};
