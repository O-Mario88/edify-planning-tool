// GET /api/cceo/my-plan — the viewer's already-scheduled activity list,
// sectioned by urgency exactly like the /my-plan page: backend-first
// (fetchMyPlanActivities) with the in-memory action store as fallback,
// then sectionMyPlan (Due Today · This Week · This Month · Waiting on Me ·
// Needs Attention). Supports ?fy= (passed to the backend read); ?week=/
// ?month= are ignored (sections already encode the period).

import type { NextRequest } from "next/server";
import { requireCceo, ok, type NextAction } from "../_auth";
import { activities, fundRequests } from "@/lib/actions/store";
import { fetchMyPlanActivities } from "@/lib/api/surfaces";
import { activeFinancialYear } from "@/lib/fy-engine";
import {
  buildFundingByActivity,
  fromBeActivity,
  fromStoreActivity,
  sectionMyPlan,
  type MyPlanItem,
} from "@/lib/planning/my-plan-sections";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  const fy = req.nextUrl.searchParams.get("fy") ?? activeFinancialYear().id;
  const today = new Date();
  const todayIso = today.toISOString().slice(0, 10);

  const be = await fetchMyPlanActivities(user, fy);
  let items: MyPlanItem[];
  if (be.live) {
    items = be.data.data
      .map((a) => fromBeActivity(a, todayIso))
      .filter((i): i is MyPlanItem => i !== null);
  } else {
    const funding = buildFundingByActivity(fundRequests());
    items = activities()
      .filter((a) => a.assigneeId === user.staffId)
      .map((a) => fromStoreActivity(a, funding, todayIso))
      .filter((i): i is MyPlanItem => i !== null);
  }

  const sections = sectionMyPlan(items, today);

  const dueToday = sections.find((s) => s.key === "dueToday");
  const waiting = sections.find((s) => s.key === "waitingOnMe");
  const nextActions: NextAction[] = [];
  if (dueToday && dueToday.items.length > 0) {
    nextActions.push({
      label: `Run today's ${dueToday.items.length} scheduled ${dueToday.items.length === 1 ? "activity" : "activities"}`,
      reason: `${dueToday.items[0].typeLabel} at ${dueToday.items[0].entityName}${dueToday.items.length > 1 ? " and more" : ""}.`,
      href: "/my-plan",
    });
  }
  if (waiting && waiting.items.length > 0) {
    nextActions.push({
      label: `Clear ${waiting.items.length} item${waiting.items.length === 1 ? "" : "s"} waiting on you`,
      reason: "Evidence or Salesforce IDs are blocking completed work from verification.",
      href: "/my-plan",
    });
  }

  return ok({ fy, live: be.live, itemCount: items.length, sections }, nextActions);
}
