import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { TeamTargetsMobileView } from "@/components/mobile/views/TeamTargetsMobileView";
import { TeamTargetsHeader } from "@/components/team-targets/TeamTargetsHeader";
import { StaffTargetTable } from "@/components/team-targets/StaffTargetTable";
import { PartnerTargetTable } from "@/components/team-targets/PartnerTargetTable";
import { AttentionStrip } from "@/components/team-targets/AttentionStrip";
import { TargetRecoveryFocusTable } from "@/components/team-targets/TargetRecoveryFocusTable";
import { TeamTargetsTabs, type TeamTargetsTab } from "@/components/team-targets/TeamTargetsTabs";
import { OperatingTargetsView } from "@/components/operating-targets/OperatingTargetsView";
import { TargetsLive } from "@/components/targets/TargetsLive";
import { cceoOperatingTargets, teamOperatingTargets } from "@/lib/operating-targets-mock";
import { filterStaffForUser } from "@/lib/team-targets-mock";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { FairMatrixPlot } from "@/components/performance/FairMatrixPlot";
import { RebalanceRecommendationsCard } from "@/components/performance/RebalanceRecommendationsCard";
import { buildFairMatrix, generateRebalanceSuggestions } from "@/lib/performance/fwi-engine";
import { fairMatrixInputsForTeam, rebalanceInputsForTeam } from "@/lib/performance/fwi-mock";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Team Targets Dashboard with tabbed navigation.
//
//   • Default tab per role:
//       CCEO                 → My Targets   (personal command center)
//       CountryProgramLead   → Team Targets (the original page body)
//       CountryDirector / RVP → Team Targets (treated as country / regional)
//   • Engine in lib/team-targets-mock.ts is still the single source of truth.
//   • Mid-year below-40 escalation remains gated by SupportReviewDrawer.

function defaultTabForRole(role: string): TeamTargetsTab {
  if (role === "CCEO") return "my";
  if (role === "CountryDirector" || role === "RVP") return "team";
  return "team";
}

export default async function TeamTargetsDashboard() {
  const user = await getCurrentUser();
  // Per-CCEO + partner target rows and the Fair Workload Index are fabricated
  // (named non-existent staff). Never expose performance/PIP bands from mock data.
  if (!isMockAllowed()) return <InsufficientData surface="team targets" />;
  const currentUser = toCurrentUser(user);
  const visible = filterStaffForUser(currentUser);
  const defaultTab = defaultTabForRole(user.role);

  // My Targets — CCEOs see their own OperatingTargetsView inline so
  // the cockpit reads the same on the team-targets tab as on the
  // dedicated /my-targets page. Non-CCEO roles get a pointer card.
  const myTargetsSlot = user.role === "CCEO"
    ? (
        <>
          <div className="flex justify-end">
            <Link
              href="/my-targets"
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-white border border-[var(--color-edify-border)] text-[11.5px] font-bold text-[var(--color-edify-primary)] hover:bg-[var(--color-edify-soft)]/40 transition-colors"
            >
              Open full My Targets
              <ExternalLink size={11} />
            </Link>
          </div>
          <OperatingTargetsView data={cceoOperatingTargets} />
        </>
      )
    : (
        <section className="card p-3.5">
          <h2 className="text-body-lg font-extrabold tracking-tight mb-1">My Targets</h2>
          <p className="text-body muted">
            For Program Leads and senior roles, personal targets live on the dedicated My Targets page.
          </p>
          <Link
            href="/my-targets"
            className="mt-2 inline-flex items-center gap-1.5 h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-extrabold"
          >
            Open My Targets <ExternalLink size={12} />
          </Link>
        </section>
      );

  // Team Targets — for PL / CD / HR / IA / RVP we render the new
  // OperatingTargetsView wired to a team aggregation derived from every
  // CCEO's My Targets data (see lib/operating-targets-mock →
  // teamOperatingTargets). The legacy per-staff + per-partner tables
  // stay below so PLs can still drill into per-CCEO rows.
  const teamAudienceLabel: Record<string, string> = {
    CountryProgramLead: "Country Program Lead",
    CountryDirector:    "Country Director",
    HumanResource:      "People & Performance",
    ImpactAssessment:   "M&E / Impact Assessment",
    RVP:                "Regional VP",
  };
  const teamData = teamOperatingTargets({
    scope:    "My Team Targets",
    audience: teamAudienceLabel[user.role] ?? "Team",
  });
  // ──── Fair Workload Index — Performance in Context ────
  //
  // Computed server-side from the FWI mock layer. In production this
  // reads pre-computed PortfolioComplexity + StaffTargetRow joins.
  const fairMatrixRows = buildFairMatrix(fairMatrixInputsForTeam());
  const complexityByStaff: Record<string, number> = Object.fromEntries(
    fairMatrixRows.map((r) => [r.staffId, r.complexityScore]),
  );
  // medianMultiplierHigh is tuned slightly lower than the engine's
  // default (1.5) so small teams (≤6 staff) still surface suggestions
  // when one staff is meaningfully overloaded. Production reverts to
  // the 1.5 default once the staff list crosses ~10.
  const rebalanceRecs = generateRebalanceSuggestions(
    rebalanceInputsForTeam(complexityByStaff),
    { medianMultiplierHigh: 1.3, medianMultiplierLow: 0.5 },
  );

  const teamTargetsSlot = (
    <>
      <TargetsLive title="Team target progress" />
      <OperatingTargetsView data={teamData} />

      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 lg:col-span-7 space-y-4">
          <FairMatrixPlot rows={fairMatrixRows} />
        </div>
        <div className="col-span-12 lg:col-span-5">
          <RebalanceRecommendationsCard recs={rebalanceRecs} />
        </div>
      </section>

      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 space-y-4">
          <StaffTargetTable rows={visible} />
          <PartnerTargetTable />
        </div>
      </section>
    </>
  );


  const supportNeededSlot = (
    <>
      <AttentionStrip />
      <TargetRecoveryFocusTable />
    </>
  );

  const targetRecoverySlot = <TargetRecoveryFocusTable />;

  return (
    <ResponsiveDashboard mobile={<TeamTargetsMobileView />} desktop={
    <>
      <TeamTargetsHeader />
        <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
          <TeamTargetsTabs
            defaultTab={defaultTab}
            myTargets={myTargetsSlot}
            teamTargets={teamTargetsSlot}
            supportNeeded={supportNeededSlot}
            targetRecovery={targetRecoverySlot}
          />
        </div>
      </>
    } />
  );
}
