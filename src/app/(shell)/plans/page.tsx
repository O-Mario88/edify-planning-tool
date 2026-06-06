import { ClipboardList, Plus } from "lucide-react";
import { EntityIndex } from "@/components/shell/EntityIndex";
import { PlansFamilyNav } from "@/components/planning/PlansFamilyNav";
import { PlanIndexAccordion } from "@/components/planning/PlanIndexAccordion";
import { MyPlanList, type MyPlanRow } from "@/components/planning/MyPlanList";
import { Button } from "@/components/ui/Button";
import { planItems } from "@/lib/mobile-mock";
import { getCurrentUser } from "@/lib/auth";
import { activities } from "@/lib/actions/store";

export const dynamic = "force-dynamic";

export default async function PlansIndex() {
  const user = await getCurrentUser();
  // The live plan-as-list: activities the current user has scheduled (from a
  // school/cluster). Each row carries the Reschedule/Reassign/Cancel-Defer/
  // Complete actions. Falls back to nothing until the user schedules something.
  const myRows: MyPlanRow[] = activities()
    .filter((a) => a.assigneeId === user.staffId)
    .sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1))
    .map((a) => ({
      id: a.id, title: a.title, schoolId: a.schoolId, schoolName: a.schoolName,
      kind: a.kind, scheduledDate: a.scheduledDate, status: a.status,
      deliveryType: a.deliveryType, partnerName: a.partnerName,
      rescheduleCount: a.rescheduleCount, lastReason: a.lastReason,
    }));

  return (
    <>
    <PlansFamilyNav current="plans" />
    <EntityIndex
      title="Plans"
      subtitle="Everything you've planned: scheduled from a school or cluster. Reschedule, reassign, defer, cancel, or complete each row in place."
      Icon={ClipboardList}
      count={myRows.length + planItems.length}
      searchPlaceholder="Search plans"
    >
      <div className="flex justify-end">
        <Button href="/plans/new" Icon={Plus} size="md">
          New Plan
        </Button>
      </div>

      {/* Live My Plan — scheduled from schools/clusters, with row actions. */}
      <section className="space-y-2">
        <h2 className="text-[12px] font-extrabold uppercase tracking-wide muted">My Plan · scheduled activities</h2>
        <MyPlanList rows={myRows} />
      </section>

      <PlanIndexAccordion items={planItems} />
    </EntityIndex>
    </>
  );
}
