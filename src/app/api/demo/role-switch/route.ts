import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { DEMO_USERS, type EdifyRole } from "@/lib/auth-public";
import { requireCsrf } from "@/lib/csrf";

// POST /api/demo/role-switch
//
// Demo-mode helper: switches the active session to a different demo user
// by setting the `edify-email`, `edify-role`, `edify-name` cookies.
//
// SECURITY GATE:
//   • In production (NODE_ENV === "production") this endpoint is
//     disabled unless the caller is already an authenticated Admin.
//   • In dev / preview builds it is unrestricted so demos can hop
//     between roles freely.
//
// This is the OPPOSITE of the previous behavior, where any anonymous
// POST could elevate a session to Admin in two clicks.

const FALLBACK_BY_ROLE: Record<EdifyRole, string> = {
  CCEO:                "paul.chinyama@edify.org",
  CountryProgramLead:  "daniel.mwangi@edify.org",
  CountryDirector:     "sarah.okello@edify.org",
  RVP:                 "esther.wanjiru@edify.org",
  ProgramAccountant:   "moses.tindi@edify.org",
  ImpactAssessment:    "grace.alimo@edify.org",
  HumanResource:       "anne.wairimu@edify.org",
  Admin:               "demo@edify.org",
  // Partner default flips to BFEP — the org showcased in the
  // partner Command Center mock data. The LTU accounts still exist
  // (sarah.kanyi@ltu.org, abel.opio@ltu.org, donor@ltu-funder.org)
  // and can still be reached by passing `email` explicitly.
  PartnerAdmin:        "daniel.mwangi@brightfuture.org",
  PartnerFieldOfficer: "ruth.kabuye@brightfuture.org",
  PartnerViewer:       "sarah.nanyongo@edify.org",
};

function setSession(res: NextResponse, email: string, role: EdifyRole, name: string) {
  const opts = {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
    secure: process.env.NODE_ENV === "production",
  };
  res.cookies.set("edify-email", email, opts);
  res.cookies.set("edify-role",  role,  opts);
  res.cookies.set("edify-name",  name,  opts);
  return res;
}

export async function POST(req: Request) {
  const csrf = requireCsrf(req);
  if (csrf) return csrf;

  // In production, only an authenticated Admin may switch roles.
  if (process.env.NODE_ENV === "production") {
    const jar = await cookies();
    const callerRole = jar.get("edify-role")?.value;
    if (callerRole !== "Admin") {
      return NextResponse.json({ ok: false, error: "Forbidden" }, { status: 403 });
    }
  }

  const body = (await req.json().catch(() => null)) as { role?: EdifyRole; email?: string } | null;
  if (!body?.role && !body?.email) {
    return NextResponse.json({ ok: false, error: "Missing role or email" }, { status: 400 });
  }

  // Resolve target user — prefer explicit email, fall back to role-default.
  const email = body.email?.toLowerCase() ?? FALLBACK_BY_ROLE[body.role!];
  const user  = email ? DEMO_USERS[email] : undefined;
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unknown demo user" }, { status: 404 });
  }

  const res = NextResponse.json({ ok: true, user: { email: user.email, role: user.role, name: user.name } });
  return setSession(res, user.email, user.role, user.name);
}
