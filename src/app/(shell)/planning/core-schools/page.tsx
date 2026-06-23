// /planning/core-schools — Core School Planning Console.
//
// Consumes the unified CorePlan + CoreActivitySlot model (no hardcoded plans).
// Every core school flows through SSA → 4 priority interventions → 4 visits +
// 4 trainings → execution (Salesforce/IA) → follow-up SSA → impact → champion.

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CorePlanningWorkspace } from "@/components/core/CorePlanningWorkspace";
import { coreBoardSummary, resolveCoreBoardData } from "@/lib/core/core-board";
import { getCurrentUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function Page() {
  const user = await getCurrentUser();
  const cards = await resolveCoreBoardData({ email: user.email, role: user.role }, user.staffId, user.role);
  const summary = coreBoardSummary(cards);

  const viewer = {
    canAssign: ["CCEO", "CountryProgramLead", "ImpactAssessment", "Admin"].includes(user.role),
    canExec: ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "Admin"].includes(user.role),
    canIa: ["ImpactAssessment", "Admin"].includes(user.role),
    canPl: ["CountryProgramLead", "Admin"].includes(user.role),
    canAccountant: ["ProgramAccountant", "Admin"].includes(user.role),
  };
  const canChampion = ["ImpactAssessment", "CountryProgramLead", "Admin"].includes(user.role);

  return (
    <>
      <CorePageHeader
        icon="schools"
        title="Core School Planning Console"
        subtitle="Every core school flows through SSA → 4 priority interventions → 4 visits + 4 trainings → follow-up SSA → impact. This board mutates the real core plan."
        filters={[
          { iconKey: "calendar", label: "FY26" },
          { iconKey: "map", label: `${summary.plans} core plans` },
          { iconKey: "user", label: `${summary.champions} champions` },
          { iconKey: "filter", label: `${summary.pendingFollowUp} awaiting SSA` },
        ]}
        searchPlaceholder="Search core schools"
      />
      <div className="px-4 sm:px-5 md:px-6 flex items-center justify-between gap-3 flex-wrap">
        <Link href="/planning" className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]">
          <ArrowLeft size={12} /> Back to Planning Console
        </Link>
        <div className="flex items-center gap-3 text-[11px] muted">
          <span><b className="text-[var(--color-edify-text)] tabular">{summary.visitsDone}</b> visits done</span>
          <span><b className="text-[var(--color-edify-text)] tabular">{summary.trainingsDone}</b> trainings done</span>
          <span><b className="text-[var(--color-edify-text)] tabular">{summary.impactMeasured}</b> impact measured</span>
        </div>
      </div>

      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 pt-4">
        <CorePlanningWorkspace cards={cards} viewer={viewer} canChampion={canChampion} />
      </div>
    </>
  );
}
