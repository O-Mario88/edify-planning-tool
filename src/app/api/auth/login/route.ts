// Server-side login endpoint.
//
// Replaces the previous client-side cookie write in LoginPanel. The client
// now POSTs credentials here; the server validates against DEMO_USERS,
// sets HTTP-only cookies (so JS can't read them), and returns the
// role-redirect URL the client should route to.
//
// This is still a demo identity store — production swaps DEMO_USERS for a
// real DB lookup and hashed-password comparison. The wire shape stays:
//   POST { email, password, remember? } → { ok, role, redirect } | { ok: false, message }

import { NextResponse } from "next/server";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { authenticateRuntime } from "@/lib/auth-runtime-store";
import { requireCsrf } from "@/lib/csrf";
import { ipFromRequest, rateLimit, rateLimitResponse } from "@/lib/rate-limit";
import { log, telemetry } from "@/lib/log";

export const dynamic = "force-dynamic";

type LoginBody = {
  email?: string;
  password?: string;
  remember?: boolean;
};

const SAFE_ERROR = "Invalid email or password.";

// 8 login attempts per IP per 10 minutes. Tuned so a real human
// fumbling their password three times in a row never hits the limit,
// while a credential-stuffing script bouncing through 50 emails gets
// stopped at the 9th attempt with a Retry-After.
const LOGIN_RATE = { max: 8, windowMs: 10 * 60 * 1000 } as const;

export async function POST(request: Request) {
  const csrf = requireCsrf(request);
  if (csrf) return csrf;

  const ip = ipFromRequest(request);
  const rl = await rateLimit(`login:${ip}`, LOGIN_RATE);
  if (!rl.ok) {
    return rateLimitResponse(rl, "Too many login attempts. Please wait and try again.");
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

  // Generic validation — never reveal which factor failed.
  if (!email || !password) {
    return NextResponse.json({ ok: false, message: SAFE_ERROR }, { status: 401 });
  }

  // Verify against the runtime user store (seeded with DEMO_USERS at
  // module init, then extended by /api/auth/signup new accounts).
  const user = authenticateRuntime(email, password);
  if (!user) {
    // Constant-ish delay so timing attacks can't tell the difference.
    await new Promise((r) => setTimeout(r, 80));
    // Log the *attempt*, not the password. `email` is fine in logs;
    // the credential isn't.
    log.warn("auth.login.failed", { ip, email });
    return NextResponse.json({ ok: false, message: SAFE_ERROR }, { status: 401 });
  }

  log.info("auth.login.ok", { ip, email: user.email, role: user.role });
  telemetry.track({ name: "auth.login", userId: user.email, props: { role: user.role } });

  const maxAge = remember ? 60 * 60 * 24 * 30 : 60 * 60 * 12;
  const isProd = process.env.NODE_ENV === "production";

  const res = NextResponse.json({
    ok: true as const,
    role: user.role,
    name: user.name,
    redirect: ROLE_REDIRECT[user.role],
  });

  // HTTP-only session cookies — JS cannot read these. The server-side
  // resolver in lib/auth.ts (getCurrentUser) reads them server-side.
  const cookieOpts = {
    path: "/",
    maxAge,
    httpOnly: true,
    sameSite: "lax" as const,
    secure: isProd,
  };
  res.cookies.set("edify-email", user.email, cookieOpts);
  res.cookies.set("edify-role", user.role, cookieOpts);
  res.cookies.set("edify-name", user.name, cookieOpts);

  return res;
}
