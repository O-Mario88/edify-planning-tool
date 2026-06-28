// Server-side login endpoint.
//
// Authenticates against the Django backend (the single source of truth for
// identity, role, and scope). On success, the user's REAL credentials are
// recorded server-side (lib/api/session-credentials) so the same-origin /api/*
// proxy routes can authenticate as that user against Django with their own JWT —
// no shared demo password, no role-mapped account. HTTP-only cookies carry the
// session identity; the password never reaches the browser.
//
// Wire shape (unchanged for the client):
//   POST { email, password, remember? } → { ok, role, name, redirect } | { ok: false, message }

import { NextResponse } from "next/server";
import { ROLE_REDIRECT, type EdifyRole } from "@/lib/auth-public";
import { recordCredentials } from "@/lib/api/session-credentials";
import { requireCsrf } from "@/lib/csrf";
import { cookieSecure } from "@/lib/cookie-security";
import { ipFromRequest, rateLimit, rateLimitResponse } from "@/lib/rate-limit";
import { log, telemetry } from "@/lib/log";

export const dynamic = "force-dynamic";

const API = process.env.EDIFY_API_URL ?? "http://localhost:4000/api";

type LoginBody = {
  email?: string;
  password?: string;
  remember?: boolean;
};

const SAFE_ERROR = "Invalid email or password.";

// 8 login attempts per IP per 10 minutes (Django enforces its own per-account
// lockout too; this is the IP-level front gate).
const LOGIN_RATE = { max: 8, windowMs: 10 * 60 * 1000 } as const;

// Map the backend's EdifyRole values to the frontend role strings used by
// ROLE_REDIRECT. The backend resolves the real role/scope from its own user
// record; we just translate the label for the FE's routing.
const BACKEND_ROLE_TO_FE: Record<string, EdifyRole> = {
  CCEO: "CCEO",
  CountryProgramLead: "CountryProgramLead",
  CountryDirector: "CountryDirector",
  RegionalVicePresident: "RVP",
  ImpactAssessment: "ImpactAssessment",
  ProgramAccountant: "ProgramAccountant",
  HumanResources: "HumanResource",
  ProjectCoordinator: "ProjectCoordinator",
  Admin: "Admin",
  PartnerAdmin: "PartnerAdmin",
  PartnerFieldOfficer: "PartnerFieldOfficer",
};

export async function POST(request: Request) {
  const csrf = requireCsrf(request);
  if (csrf) return csrf;

  const ip = ipFromRequest(request);
  if (process.env.NODE_ENV !== "development") {
    const rl = await rateLimit(`login:${ip}`, LOGIN_RATE);
    if (!rl.ok) {
      return rateLimitResponse(rl, "Too many login attempts. Please wait and try again.");
    }
  }

  let body: LoginBody;
  try {
    body = (await request.json()) as LoginBody;
  } catch {
    return NextResponse.json({ ok: false, message: SAFE_ERROR }, { status: 400 });
  }

  const email = body.email?.trim().toLowerCase() ?? "";
  const password = body.password ?? "";
  const remember = body.remember === true;

  if (!email || !password) {
    return NextResponse.json({ ok: false, message: SAFE_ERROR }, { status: 401 });
  }

  // Authenticate against the Django backend — the single source of truth.
  type BackendLoginResponse = {
    accessToken?: string;
    refreshToken?: string;
    user?: { id?: string; email?: string; name?: string; roles?: string[]; activeRole?: string };
  };
  let backend: BackendLoginResponse | null = null;
  try {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
    if (!res.ok) {
      // Generic error — never reveal which factor failed (parity with Django).
      await new Promise((r) => setTimeout(r, 80));
      log.warn("auth.login.failed", { ip, email, backendStatus: res.status });
      return NextResponse.json({ ok: false, message: SAFE_ERROR }, { status: 401 });
    }
    backend = (await res.json()) as BackendLoginResponse;
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Network error";
    log.error("auth.login.backend-unreachable", { ip, email, msg });
    return NextResponse.json(
      { ok: false, message: `Cannot reach the data backend (${msg}). It may be starting up — try again shortly.` },
      { status: 502 },
    );
  }

  if (!backend?.accessToken || !backend.user) {
    return NextResponse.json({ ok: false, message: SAFE_ERROR }, { status: 502 });
  }

  const feRole = BACKEND_ROLE_TO_FE[backend.user.activeRole ?? ""] ?? "PartnerFieldOfficer";
  const name = backend.user.name ?? email;

  log.info("auth.login.ok", { ip, email, role: feRole });
  telemetry.track({ name: "auth.login", userId: email, props: { role: feRole } });

  // Record the user's REAL credentials server-side so the /api/* proxy routes
  // authenticate against Django as this user (their own JWT, real scope).
  recordCredentials(email, password);

  const maxAge = remember ? 60 * 60 * 24 * 30 : 60 * 60 * 12;
  const res = NextResponse.json({
    ok: true as const,
    role: feRole,
    name,
    email,
    redirect: ROLE_REDIRECT[feRole],
  });

  // HTTP-only session cookies — JS cannot read these. The server-side resolver
  // (lib/auth.ts) reads them to resolve the current user for rendering.
  const cookieOpts = {
    path: "/",
    maxAge,
    httpOnly: true,
    sameSite: "lax" as const,
    secure: cookieSecure(request),
  };
  res.cookies.set("edify-email", email, cookieOpts);
  res.cookies.set("edify-role", feRole, cookieOpts);
  res.cookies.set("edify-name", name, cookieOpts);
  // HMAC signature over the identity (verified by the resolver + middleware so
  // a forged/edited cookie can't impersonate a role). Inert when no secret set.
  try {
    const { signSession, sessionSigningActive, SESSION_SIG_COOKIE } = await import("@/lib/session-sig");
    if (sessionSigningActive()) {
      res.cookies.set(SESSION_SIG_COOKIE, await signSession(email, feRole), cookieOpts);
    }
  } catch {
    /* session-sig optional */
  }

  return res;
}
