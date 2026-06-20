// /planning/core-schools — Core School Planning Console.
//
// Backend-first: the gap buckets, their counts, and the schools behind each gap
// all come from /planning/core (scoped to the user server-side). The rich
// in-memory mock workspace is kept ONLY for offline dev (mock opted in); prod
// never renders fabricated core data — it shows a controlled empty state.

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CorePlanningWorkspace } from "@/components/core/CorePlanningWorkspace";
import { CorePlanningBoardLive } from "@/components/core/CorePlanningBoardLive";
import { coreBoardData, coreBoardSummary } from "@/lib/core/core-board";
import { fetchPlanningCore } from "@/lib/api/surfaces";
import { isMockAllowed } from "@/lib/mock-policy";
import { getCurrentUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

function BackLink() {
  return (
    <div className="px-4 sm:px-5 md:px-6 pt-3">
      <Link
        href="/planning"
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]"
      >
        <ArrowLeft size={12} /> Back to Planning Console
      </Link>
    </div>
  );
}

export default async function Page() {
  const user = await getCurrentUser();
  const core = await fetchPlanningCore({ email: user.email, role: user.role });

  // ── Backend-driven (the real path) ──────────────────────────────────
  if (core.live) {
    const buckets = core.data;
    const stat = (k: string) => buckets.find((b) => b.key === k)?.count ?? 0;
    const totalGaps = buckets.reduce((s, b) => s + b.count, 0);
    return (
      <>
        <CorePageHeader
          icon="schools"
          title="Core School Planning Console"
          subtitle="Every core school flows through SSA → 4 priority interventions → 4 visits + 4 trainings → follow-up SSA → impact. Counts and lists are live from the backend."
          filters={[
            { iconKey: "calendar", label: "FY26" },
            { iconKey: "filter", label: `${stat("missingSsa")} awaiting SSA` },
            { iconKey: "map", label: `${stat("ready")} ready to plan` },
            { iconKey: "user", label: `${totalGaps} open gaps` },
          ]}
          searchPlaceholder="Search core schools"
        />
        <BackLink />
        <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 pt-4">
          <CorePlanningBoardLive buckets={buckets} />
        </div>
      </>
    );
  }

  // ── Dev-only mock fallback (backend off + mock opted in) ─────────────
  if (isMockAllowed()) {
    const cards = coreBoardData(user.staffId, user.role);
    const summary = coreBoardSummary(cards);
    const viewer = {
      canAssign: ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"].includes(user.role),
      canExec: ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "Admin"].includes(user.role),
      canIa: ["ImpactAssessment", "Admin"].includes(user.role),
      canPl: ["CountryProgramLead", "Admin"].includes(user.role),
      canAccountant: ["ProgramAccountant", "Admin"].includes(user.role),
    };
    const canChampion = ["ImpactAssessment", "CountryProgramLead", "CountryDirector", "Admin"].includes(user.role);
    return (
      <>
        <CorePageHeader
          icon="schools"
          title="Core School Planning Console"
          subtitle="Development mock data — the backend is unavailable."
          filters={[
            { iconKey: "calendar", label: "FY26" },
            { iconKey: "map", label: `${summary.plans} core plans` },
            { iconKey: "user", label: `${summary.champions} champions` },
          ]}
          searchPlaceholder="Search core schools"
        />
        <BackLink />
        <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 pt-4">
          <CorePlanningWorkspace cards={cards} viewer={viewer} canChampion={canChampion} />
        </div>
      </>
    );
  }

  // ── Backend unavailable, mock not allowed → controlled empty state ───
  return (
    <>
      <CorePageHeader
        icon="schools"
        title="Core School Planning Console"
        subtitle="Every core school flows through SSA → 4 visits + 4 trainings → impact."
        filters={[{ iconKey: "calendar", label: "FY26" }]}
        searchPlaceholder="Search core schools"
      />
      <BackLink />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 pt-10">
        <div className="rounded-xl border border-[var(--color-edify-border)] bg-white p-8 text-center">
          <div className="text-[14px] font-bold">Core planning is temporarily unavailable</div>
          <div className="text-[12px] muted mt-1">The planning service didn’t respond. Refresh, or check back shortly.</div>
        </div>
      </div>
    </>
  );
}
