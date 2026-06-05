import { redirect } from "next/navigation";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CoreDeliveryView, CoreDeliverySummaryCards } from "@/components/core/CoreDeliveryView";
import { coreDeliveryRows, coreDeliverySummary } from "@/lib/core/core-delivery";
import { getCurrentUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Accountant core payments — partner-delivered core activities tied to payment /
// accountability. Gated to finance + oversight roles.
const ALLOWED = ["ProgramAccountant", "CountryDirector", "CountryProgramLead", "Admin"];

export default async function CorePaymentsPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.includes(user.role)) redirect("/core-schools");
  const rows = coreDeliveryRows(user.staffId, user.role);
  const summary = coreDeliverySummary(rows);

  const body = (
    <>
      <CorePageHeader icon="analytics" title="Core Payments & Accountability" subtitle="Partner-delivered core activities — IA-verified work awaiting payment, and cleared payments. Accountant confirms after IA verification." />
      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 pt-3 space-y-3">
        <CoreDeliverySummaryCards summary={summary} mode="accountant" />
        <CoreDeliveryView rows={rows} mode="accountant" />
      </div>
      <RoleBottomNav />
    </>
  );
  return body;
}
