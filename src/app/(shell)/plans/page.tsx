import { ClipboardList, Plus } from "lucide-react";
import { EntityIndex } from "@/components/shell/EntityIndex";
import { PlansFamilyNav } from "@/components/planning/PlansFamilyNav";
import { MyPlanList, type MyPlanRow } from "@/components/planning/MyPlanList";
import { Button } from "@/components/ui/Button";
import { getCurrentUser } from "@/lib/auth";
import { activities } from "@/lib/actions/store";
import { fetchMyPlanActivities, type BeActivity } from "@/lib/api/surfaces";
import { activeFinancialYear } from "@/lib/fy-engine";

export const dynamic = "force-dynamic";

const ACT_TITLE: Record<string, string> = {
  school_visit: "School visit", follow_up_visit: "Follow-up visit", coaching_visit: "Coaching visit",
  in_school_support: "In-school support", training: "Training", school_improvement_training: "Improvement training",
  cluster_meeting: "Cluster meeting", cluster_training: "Cluster training", ssa_activity: "SSA activity",
  project_activity: "Project activity", core_visit: "Core visit", core_training: "Core training",
};

// Backend ActivityStatus → My Plan display status (Completed/Cancelled are terminal).
function mapStatus(s: string): string {
  if (["completed", "ia_verified", "accountant_confirmed", "evidence_accepted", "awaiting_ia_verification", "salesforce_id_required"].includes(s)) return "Completed";
  if (s === "cancelled") return "Cancelled";
  if (s === "deferred") return "Deferred";
  if (s === "rescheduled") return "Rescheduled";
  return "Planned";
}

function beToRow(a: BeActivity, source: "backend" | "store"): MyPlanRow {
  return {
    id: a.id,
    title: `${ACT_TITLE[a.activityType] ?? "Activity"}${a.school?.name ? ` — ${a.school.name}` : ""}`,
    schoolId: a.school?.schoolId ?? undefined,
    schoolName: a.school?.name ?? undefined,
    kind: a.activityType,
    scheduledDate: a.scheduledDate ?? undefined,
    status: mapStatus(a.status),
    deliveryType: a.deliveryType as "staff" | "partner",
    rescheduleCount: a.rescheduleCount ?? 0,
    lastReason: a.lastReason ?? undefined,
    source,
  };
}

export default async function PlansIndex() {
  const user = await getCurrentUser();

  // Write-path migration: when the backend is enabled, My Plan is the backend's
  // authoritative, enforced activity list. Falls back to the in-memory store
  // (mock-id-school scheduling) when the backend is off or unreachable.
  const fy = activeFinancialYear().id;
  const be = await fetchMyPlanActivities(user, fy);
  const source: "backend" | "store" = be.live ? "backend" : "store";
  const myRows: MyPlanRow[] = be.live
    ? be.data.data.map((a) => beToRow(a, "backend"))
    : activities()
        .filter((a) => a.assigneeId === user.staffId)
        .sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1))
        .map((a) => ({
          id: a.id, title: a.title, schoolId: a.schoolId, schoolName: a.schoolName,
          kind: a.kind, scheduledDate: a.scheduledDate, status: a.status,
          deliveryType: a.deliveryType, partnerName: a.partnerName,
          rescheduleCount: a.rescheduleCount, lastReason: a.lastReason,
          source: "store" as const,
        }));

  return (
    <>
    <PlansFamilyNav current="plans" />
    <EntityIndex
      title="Plans"
      subtitle="Everything you've planned: scheduled from a school or cluster. Reschedule, reassign, defer, cancel, or complete each row in place."
      Icon={ClipboardList}
      count={myRows.length}
      searchPlaceholder="Search plans"
    >
      <div className="flex justify-end">
        <Button href="/plans/new" Icon={Plus} size="md">
          New Plan
        </Button>
      </div>

      {/* Live My Plan — scheduled from schools/clusters, with row actions. */}
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <h2 className="text-[12px] font-extrabold uppercase tracking-wide muted">My Plan · scheduled activities</h2>
          {source === "backend" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · backend</span>
          )}
        </div>
        <MyPlanList rows={myRows} />
      </section>
    </EntityIndex>
    </>
  );
}
