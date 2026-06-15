import { NextResponse } from "next/server";
import { requireCsrf } from "@/lib/csrf";
import { SESSION_SIG_COOKIE } from "@/lib/session-sig";

// POST /api/auth/logout
//
// Clears the three session cookies set by /api/auth/login
// (edify-email, edify-role, edify-name) plus the legacy
// `edify_session` cookie. The SignOutButton calls this and then
// redirects the client to /login.
function clearSession(res: NextResponse) {
  const opts = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
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
  return clearSession(NextResponse.json({ ok: true, redirect: "/login" }));
}

// GET is supported so a plain anchor with `href="/api/auth/logout"` works
// as a fallback if JS is disabled.
export async function GET(request: Request) {
  return clearSession(
    NextResponse.redirect(new URL("/login", request.url), { status: 302 }),
  );
}
