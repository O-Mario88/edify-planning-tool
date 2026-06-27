import { NextResponse } from "next/server";
import { requireCsrf } from "@/lib/csrf";
import { cookieSecure } from "@/lib/cookie-security";
import { SESSION_SIG_COOKIE } from "@/lib/session-sig";
import { clearCredentials } from "@/lib/api/session-credentials";

// POST /api/auth/logout
//
// Clears the three session cookies set by /api/auth/login
// (edify-email, edify-role, edify-name) plus the legacy
// `edify_session` cookie, AND drops the in-memory backend credentials so the
// proxy can no longer authenticate as that user. The SignOutButton calls this
// and then redirects the client to /login.
function clearSession(req: Request, res: NextResponse) {
  // Drop the per-user backend credentials recorded at login.
  const email = req.headers.get("cookie")?.match(/edify-email=([^;]+)/)?.[1];
  if (email) clearCredentials(decodeURIComponent(email));
  const opts = {
    httpOnly: true,
    sameSite: "lax" as const,
    // Match how the cookies were set (Secure by request protocol) so the
    // deletion reliably clears them over http://localhost too.
    secure: cookieSecure(req),
    path: "/",
    maxAge: 0,
  };
  res.cookies.set("edify-email", "", opts);
  res.cookies.set("edify-role", "", opts);
  res.cookies.set("edify-name", "", opts);
  res.cookies.set(SESSION_SIG_COOKIE, "", opts);
  // Plus the legacy single-cookie session so old sessions log out cleanly.
  res.cookies.set("edify_session", "", opts);
  return res;
}

export async function POST(request: Request) {
  const csrf = requireCsrf(request);
  if (csrf) return csrf;
  return clearSession(request, NextResponse.json({ ok: true, redirect: "/login" }));
}

// GET is supported so a plain anchor with `href="/api/auth/logout"` works
// as a fallback if JS is disabled.
export async function GET(request: Request) {
  return clearSession(
    request,
    NextResponse.redirect(new URL("/login", request.url), { status: 302 }),
  );
}
