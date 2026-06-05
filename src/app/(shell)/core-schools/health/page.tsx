import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CoreHealthPanel } from "@/components/core/CoreHealthPanel";
import { coreHealthReport } from "@/lib/core/core-health";

export const dynamic = "force-dynamic";

// Core data-integrity / health checks — surfaces the one-schoolId invariants
// (§22–23): plans without baseline / 4 interventions / 8 slots, completed slots
// without Salesforce IDs or IA verification, follow-up not linked, and so on.
export default async function CoreHealthPage() {
  const report = coreHealthReport();
  const body = (
    <>
      <CorePageHeader
        icon="health"
        title="Core Health Checks"
        subtitle="Data-integrity rules across the core lifecycle. Every finding points to the record that breaks the one-schoolId invariant."
      />
      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 pt-3">
        <CoreHealthPanel report={report} />
      </div>
      <RoleBottomNav />
    </>
  );
  return body;
}
