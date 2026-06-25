import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PageHeader } from "@/components/ui/PageHeader";
import { MockLeakageCard } from "@/components/system-health/MockLeakageCard";
import { ContractHealthCard } from "@/components/system-health/ContractHealthCard";
import { OnlineTestReadinessCard } from "@/components/system-health/OnlineTestReadinessCard";
import { WorkflowHealthCard } from "@/components/system-health/WorkflowHealthCard";
import { DemoReadinessCard } from "@/components/system-health/DemoReadinessCard";
import { SourceOfTruthCard } from "@/components/system-health/SourceOfTruthCard";
import { EscalationLadderCard } from "@/components/escalation/EscalationLadderCard";

// System Health — production-safety + mock-data-leakage status (spec §18).
// Admin-only.
export default async function SystemHealthPage() {
  const user = await getCurrentUser();
  if (user.role !== "Admin") redirect(ROLE_REDIRECT[user.role] ?? "/");

  return (
    <>
      <PageHeader
        title="System Health"
        subtitle="Production safety & mock-data status — tracks the backend-only migration: which frontend pages and components still import mock data, and whether the app is configured to never render fake data in production."
      />
      <div className="px-4 sm:px-6 pt-2 pb-24 space-y-4">
        <OnlineTestReadinessCard />
        <ContractHealthCard />
        <DemoReadinessCard />
        <WorkflowHealthCard />
        <EscalationLadderCard />
        <SourceOfTruthCard />
        <MockLeakageCard />
      </div>
    </>
  );
}
