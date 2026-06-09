import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { fetchPaymentQueue } from "@/lib/api/surfaces";

// Accountant payment queue — partner work IA-confirmed and ready to pay. No mock.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  const r = await fetchPaymentQueue(user);
  return r.live
    ? NextResponse.json({ live: true, rows: r.data })
    : NextResponse.json({ live: false, error: r.error }, { status: r.error ? 502 : 200 });
}
