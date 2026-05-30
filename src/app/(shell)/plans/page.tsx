import { ClipboardList, Plus } from "lucide-react";
import { EntityIndex } from "@/components/shell/EntityIndex";
import { PlansFamilyNav } from "@/components/planning/PlansFamilyNav";
import { PlanIndexAccordion } from "@/components/planning/PlanIndexAccordion";
import { Button } from "@/components/ui/Button";
import { planItems } from "@/lib/mobile-mock";

export default function PlansIndex() {
  return (
    <>
    <PlansFamilyNav current="plans" />
    <EntityIndex
      title="Plans"
      subtitle="Everything you've planned this month: cluster trainings, visits, follow-ups. Tap a row to expand its detail in place."
      Icon={ClipboardList}
      count={planItems.length}
      searchPlaceholder="Search plans"
    >
      <div className="flex justify-end">
        <Button href="/plans/new" Icon={Plus} size="md">
          New Plan
        </Button>
      </div>
      <PlanIndexAccordion items={planItems} />
    </EntityIndex>
    </>
  );
}
