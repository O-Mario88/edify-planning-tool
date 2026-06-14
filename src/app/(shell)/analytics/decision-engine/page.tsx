import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT, type EdifyRole } from "@/lib/auth-public";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchLeadershipBoards, fetchLeadershipSnapshot } from "@/lib/api/surfaces";
import { DecisionEngineClient } from "@/components/leadership/DecisionEngineClient";

// Leadership Decision Engine — evidence-backed, human-reviewed recommendations
// for recruitment, staffing, partner MOUs, staff/HR, and regional investment.
// The engine RECOMMENDS; leadership DECIDES. Role-gated; the backend re-enforces
// LEADERSHIP_ENGINE_VIEW + role-tailored boards.
const ALLOWED: EdifyRole[] = [
  "CountryDirector", "RVP", "HumanResource", "ImpactAssessment",
  "CountryProgramLead", "ProgramAccountant", "Admin",
];
const CAN_RECOMPUTE: EdifyRole[] = ["CountryDirector", "RVP", "HumanResource", "CountryProgramLead", "Admin"];

export default async function DecisionEnginePage() {
  const user = await getCurrentUser();
  const role = user.role as EdifyRole;
  if (!ALLOWED.includes(role)) redirect(ROLE_REDIRECT[role] ?? "/");

  const bu = { role: user.role, email: user.email };
  const [boardsR, snapR] = await Promise.all([
    fetchLeadershipBoards(bu),
    fetchLeadershipSnapshot(bu),
  ]);

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-5 sm:px-6">
      <PageHeader
        title="Leadership Decision Engine"
        subtitle="Evidence + context + fairness + recommendation — leadership decides."
        titleBadge={<span className="rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-semibold text-white dark:bg-slate-100 dark:text-slate-900">Advisory</span>}
        noBack
      />
      {boardsR.live ? (
        <DecisionEngineClient
          snapshot={snapR.live ? snapR.data : null}
          initialBoards={boardsR.data}
          canRecompute={CAN_RECOMPUTE.includes(role)}
        />
      ) : (
        <BackendOff error={boardsR.error} />
      )}
    </div>
  );
}

function BackendOff({ error }: { error: string | null }) {
  return (
    <div className="mt-6 rounded-xl border border-dashed border-slate-300 p-8 text-center dark:border-slate-700">
      <p className="text-sm font-medium text-[var(--text-primary)]">The Leadership Decision Engine needs the live backend.</p>
      <p className="mt-1 text-xs muted">
        Recommendations are computed from real system data only — no mock figures. Enable the backend
        (EDIFY_USE_BACKEND) and run a recompute to populate insights.
      </p>
      {error && <p className="mt-2 text-[11px] text-rose-500">{error}</p>}
    </div>
  );
}
