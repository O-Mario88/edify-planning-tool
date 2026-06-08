import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchPaymentQueue, clearPayment } from "@/lib/api/surfaces";

// Accountant partner-payment pipeline. The backend re-enforces both the
// PAYMENT_ACT permission and the IA-verified + Salesforce-ID + evidence-accepted
// gate — this handler is a thin scoped proxy.
export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchPaymentQueue(user);
  return r.live
    ? NextResponse.json({ rows: r.data, live: true })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}

export async function POST(req: NextRequest) {
  const user = await getCurrentUser();
  const body = await req.json().catch(() => ({}));
  const activityId = typeof body?.activityId === "string" ? body.activityId : "";
  if (!activityId) return NextResponse.json({ error: "activityId required" }, { status: 400 });
  const r = await clearPayment(user, activityId);
  return r.live
    ? NextResponse.json({ ...r.data, live: true })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
