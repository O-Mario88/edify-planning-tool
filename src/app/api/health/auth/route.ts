import { NextResponse } from "next/server";
import { sessionSigningActive } from "@/lib/session-sig";

// Auth/session config probe. Returns booleans + lengths only — never secret
// values. Surfaces the two prod login blockers we hit: missing session secret,
// and a super-admin password that isn't a usable literal.
export const dynamic = "force-dynamic";

export function GET() {
  const superPw = process.env.SUPER_ADMIN_PASSWORD ?? "";
  const signing = sessionSigningActive();
  return NextResponse.json({
    ok: signing,
    sessionSigningActive: signing, // EDIFY_SESSION_SECRET present? (login 503s if false in prod)
    superAdminConfigured: superPw.length > 0, // a value is set
    superAdminPasswordLength: superPw.length, // spot a stray/templated value (e.g. an unexpected length)
    demoLoginPasswordSet: !!process.env.DEMO_LOGIN_PASSWORD,
    demoAdminEnabled: process.env.ENABLE_DEMO_ADMIN === "true",
    note: !signing
      ? "EDIFY_SESSION_SECRET is not set — login returns 503 in production."
      : superPw.length === 0
        ? "SUPER_ADMIN_PASSWORD is not set — domario@edify.org cannot log in."
        : undefined,
    time: new Date().toISOString(),
  });
}
