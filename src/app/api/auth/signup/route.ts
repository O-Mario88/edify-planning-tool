// Signup endpoint. Persists a new user record into the runtime store
// (lib/auth-runtime-store.ts), hashes the password through the
// hash-ready placeholder, and immediately sets the same HTTP-only
// session cookies that /api/auth/login produces so the new user lands
// straight on their role's dashboard.
//
// SECURITY: open signup is locked to role=CCEO. Privileged roles
// (Admin, Country Director, RVP, Program Accountant, Impact Assessment,
// HR, Country Program Lead) can ONLY be created by an authenticated
// Admin through a separate provisioning endpoint (not exposed in this
// build). Any `role` field on the request body is ignored.
//
// Wire shape:
//   POST { email, name, password } → { ok, redirect } | { ok: false, message }

import { NextResponse } from "next/server";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { createUser } from "@/lib/auth-runtime-store";
import { requireCsrf } from "@/lib/csrf";
import { signSession, sessionSigningActive, SESSION_SIG_COOKIE } from "@/lib/session-sig";
import { ipFromRequest, rateLimit, rateLimitResponse } from "@/lib/rate-limit";

export const dynamic = "force-dynamic";

type SignupBody = {
  email?: string;
  name?: string;
  password?: string;
};

const SAFE_ERROR = "We couldn't create your account. Please check your details and try again.";

// 5 signup attempts per IP per hour. Tight because there's no legit
// reason a real user signs up six times — it's almost always abuse.
const SIGNUP_RATE = { max: 5, windowMs: 60 * 60 * 1000 } as const;

export async function POST(request: Request) {
  const csrf = requireCsrf(request);
  if (csrf) return csrf;

  const ip = ipFromRequest(request);
  const rl = await rateLimit(`signup:${ip}`, SIGNUP_RATE);
  if (!rl.ok) {
    return rateLimitResponse(rl, "Too many signup attempts. Please wait and try again.");
  }

  let body: SignupBody;
  try {
    body = (await request.json()) as SignupBody;
  } catch {
    return NextResponse.json({ ok: false, message: SAFE_ERROR }, { status: 400 });
  }

  // Open signup always creates a CCEO account. The `role` field is
  // intentionally NOT read from the request body — it is hardcoded
  // here. An authenticated Admin uses a separate provisioning flow
  // to assign elevated roles.
  const result = createUser({
    email: body.email ?? "",
    name: body.name ?? "",
    password: body.password ?? "",
    role: "CCEO",
  });

  if (!result.ok) {
    // Map internal reasons to safe, copy-aware messages.
    const message =
      result.reason === "EMAIL_EXISTS"
        ? "An account with this email already exists."
        : result.reason === "WEAK_PASSWORD"
          ? "Password must be at least 6 characters."
          : result.reason === "INVALID_EMAIL"
            ? "Please enter a valid email address."
            : result.reason === "INVALID_NAME"
              ? "Please enter your full name."
              : SAFE_ERROR;
    return NextResponse.json({ ok: false, message }, { status: 400 });
  }

  const { user } = result;
  const isProd = process.env.NODE_ENV === "production";
  const maxAge = 60 * 60 * 24 * 30; // 30 days for a fresh signup

  const res = NextResponse.json({
    ok: true as const,
    role: user.role,
    name: user.name,
    redirect: ROLE_REDIRECT[user.role],
  });
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
  if (sessionSigningActive()) {
    res.cookies.set(SESSION_SIG_COOKIE, await signSession(user.email, user.role), cookieOpts);
  }
  return res;
}
