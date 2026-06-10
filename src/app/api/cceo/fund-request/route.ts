// GET /api/cceo/fund-request — the viewer's weekly fund-request pipeline,
// from the same source the /weekly-funds StaffWeeklyView reads
// (findRequestsForStaff + currentWeek). Strictly scoped to the signed-in
// staffId (no demo fallback to another officer — an empty list is the
// truthful API answer). Supports ?week=1..4 to narrow to one week of the
// active month; ?fy=/?month= are ignored (the mock ledger is single-month).

import type { NextRequest } from "next/server";
import { requireCceo, ok, type NextAction } from "../_auth";
import { findRequestsForStaff, currentWeek } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  let requests = findRequestsForStaff(user.staffId);

  const weekParam = Number(req.nextUrl.searchParams.get("week") ?? "");
  if ([1, 2, 3, 4].includes(weekParam)) {
    requests = requests.filter((r) => r.period.weekOfMonth === weekParam);
  }

  const byStatus: Record<string, number> = {};
  for (const r of requests) byStatus[r.status] = (byStatus[r.status] ?? 0) + 1;

  const summary = {
    count: requests.length,
    totalRequestedUgx: requests.reduce((n, r) => n + r.requestedAmount.amount, 0),
    totalDisbursedUgx: requests.reduce((n, r) => n + (r.disbursedAmount?.amount ?? 0), 0),
    byStatus,
  };

  const current = requests.find((r) => r.period.weekOfMonth === currentWeek.weekOfMonth);
  const nextActions: NextAction[] = [];
  const actionable = new Set(["AUTO_GENERATED", "DRAFT", "RETURNED_TO_STAFF", "ACCOUNTABILITY_RETURNED"]);
  if (current && actionable.has(current.status)) {
    nextActions.push({
      label: `Act on Week ${current.period.weekOfMonth} fund request`,
      reason: `${formatMoney(current.requestedAmount)} · status ${current.status} — move it before the week closes (${currentWeek.daysRemaining}d left).`,
      href: "/weekly-funds",
    });
  }

  return ok({ currentWeek, summary, requests }, nextActions);
}
