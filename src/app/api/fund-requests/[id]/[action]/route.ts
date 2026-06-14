import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendFundAction } from "@/lib/api/surfaces";
import { enforceCsrf } from "@/lib/csrf";

// Fund-request lifecycle actions (backend role-gated):
//   review:  approve | return | reject       (BUDGET_APPROVE)
//   money:   disburse                          (PAYMENT_ACT)
//   account: account | account-approve | account-return
export const dynamic = "force-dynamic";
const ACTIONS = new Set(["approve", "return", "reject", "disburse", "account", "account-approve", "account-return"]);

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string; action: string }> }) {
  const csrf = enforceCsrf(req); if (csrf) return csrf;
  const { id, action } = await ctx.params;
  if (!ACTIONS.has(action)) return NextResponse.json({ live: false, error: `Unknown action: ${action}` }, { status: 400 });
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const r = await backendFundAction(user, id, action, body);
  return r.live
    ? NextResponse.json({ live: true, request: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
