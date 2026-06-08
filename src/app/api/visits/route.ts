import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendFetch, isBackendEnabled } from "@/lib/api/backend";
import type { BeActivity, BePaginated } from "@/lib/api/surfaces";

// Backend-backed Visits index. Visits are scoped activities whose type is one of
// the visit kinds (school_visit, follow_up_visit, coaching_visit, core_visit).
// The /activities endpoint filters by a single activityType, so we pull the
// scoped page and keep the visit kinds here. No mock fallback — empty array
// when the database has no visits, error surfaced to the client.
export const dynamic = "force-dynamic";

const VISIT_TYPES = new Set(["school_visit", "follow_up_visit", "coaching_visit", "core_visit"]);

const TYPE_LABEL: Record<string, string> = {
  school_visit: "Visit",
  coaching_visit: "Visit",
  core_visit: "Visit",
  follow_up_visit: "Follow-Up Visit",
};

// Backend ActivityStatus → the display labels the page renders.
const STATUS_LABEL: Record<string, string> = {
  ia_verified: "Verified",
  accountant_confirmed: "Verified",
  completed: "Verified",
  salesforce_id_required: "Awaiting SF ID",
  awaiting_ia_verification: "Awaiting SF ID",
  in_progress: "In Progress",
  evidence_uploaded: "In Progress",
  evidence_accepted: "In Progress",
};

export type VisitRow = {
  id: string;
  type: string;
  status: string;
  context: string; // school name
  date: string;
};

export async function GET() {
  const user = await getCurrentUser();
  if (!isBackendEnabled()) {
    return NextResponse.json({ live: false, error: null });
  }
  const r = await backendFetch<BePaginated<BeActivity>>(`/activities?pageSize=200`, user);
  if (!r.ok) {
    return NextResponse.json({ live: false, error: r.error }, { status: 502 });
  }

  const visits: VisitRow[] = r.data.data
    .filter((a) => VISIT_TYPES.has(a.activityType))
    .map((a) => ({
      id: a.id,
      type: TYPE_LABEL[a.activityType] ?? "Visit",
      status: STATUS_LABEL[a.status] ?? "Planned",
      context: a.school?.name ?? "Unassigned school",
      date: a.scheduledDate ? new Date(a.scheduledDate).toLocaleDateString() : "Unscheduled",
    }));

  return NextResponse.json({ live: true, visits });
}
