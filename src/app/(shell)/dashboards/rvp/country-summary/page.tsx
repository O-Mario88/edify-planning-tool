import { redirect } from "next/navigation";
import { PageHeader } from "@/components/ui/PageHeader";
import { AggregatedFieldContextCard } from "@/components/field-intelligence/AggregatedFieldContextCard";
import { DecisionActionsCard } from "@/components/decisions/DecisionActionsCard";
import { getCurrentUser } from "@/lib/auth";
import { rvpCountrySummary, decisionActionsForCreator } from "@/lib/field-intelligence-mock";

// RVP country summary.
//
// RVP works with Country Directors (escalation) and Human Resource. Never
// sees raw daily debriefs. Sees country-level aggregated intelligence plus
// any decisions the RVP has routed to CD or HR.

const ALLOWED = new Set(["RVP", "Admin"]);

export default async function RvpCountrySummaryPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect("/dashboard");

  const ctx = rvpCountrySummary();

  return (
    <>
      {/* Canonical page chrome — title + search + identity cluster.
          PageHeader is a Client Component: pass only strings from this
          server page, never icon components. */}
      <PageHeader
        title="Uganda — Country Weekly Field Intelligence"
        subtitle="Aggregated only. RVP routes decisions to Country Director or HR — never directly to Program Leads or below."
      />

        <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6 space-y-4">
          <AggregatedFieldContextCard
            ctx={ctx}
            title={`${ctx.country} — Country Weekly Field Intelligence`}
            subtitle="Aggregated country-level intelligence for regional oversight."
          />

          <DecisionActionsCard
            title="My escalations"
            subtitle="Decisions you've routed to Country Director or Human Resource."
            actions={decisionActionsForCreator(user.name)}
            emptyMessage="No open RVP escalations this week."
          />
        </div>
      </>
  );
}
