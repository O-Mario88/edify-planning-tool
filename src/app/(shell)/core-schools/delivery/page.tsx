import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CoreDeliveryView, CoreDeliverySummaryCards } from "@/components/core/CoreDeliveryView";
import { corePartnerRows, coreDeliverySummary } from "@/lib/core/core-delivery";
import { getCurrentUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Partner core delivery — the partner's assigned core activities (scoped to
// partner-assigned plans by coreBoardData). Oversight roles see all partner work.
export default async function CoreDeliveryPage() {
  const user = await getCurrentUser();
  const rows = corePartnerRows(user.staffId, user.role);
  const summary = coreDeliverySummary(rows);

  const body = (
    <>
      <CorePageHeader icon="schools" title="Core Delivery (Partner)" subtitle="Assigned core visits + trainings — schedule, deliver, upload evidence, then await staff review and IA verification." />
      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 pt-3 space-y-3">
        <CoreDeliverySummaryCards summary={summary} mode="partner" />
        <CoreDeliveryView rows={rows} mode="partner" />
      </div>
      <RoleBottomNav />
    </>
  );
  return body;
}
