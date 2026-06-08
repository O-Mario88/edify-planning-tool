import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { scanMockLeakage } from "@/lib/mock-audit/scan";
import { isMockAllowed, isBackendOn, isProductionSafe } from "@/lib/mock-policy";

// System Health — mock-data status (spec §18). Admin-only; surfaces the live
// mock-leakage scan + the production-safety flags.
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getCurrentUser();
  if (user.role !== "Admin") return NextResponse.json({ error: "Access restricted" }, { status: 403 });

  const report = scanMockLeakage();
  return NextResponse.json({
    report,
    policy: {
      mockAllowed: isMockAllowed(),
      backendOn: isBackendOn(),
      productionSafe: isProductionSafe(),
      nodeEnv: process.env.NODE_ENV ?? "development",
    },
  });
}
