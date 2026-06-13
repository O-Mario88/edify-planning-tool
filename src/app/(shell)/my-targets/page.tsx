import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { CplTargetsView } from "@/components/mobile/views/CplTargetsView";
import { CplTargetsDesktopView } from "@/components/mobile/desktop-variants/CplTargetsDesktopView";
import { OperatingTargetsView, OperatingTargetsPageHeader } from "@/components/operating-targets/OperatingTargetsView";
import { CommandStack } from "@/components/actions/CommandStack";
import { StaffPartnerMonitoring } from "@/components/partner/StaffPartnerMonitoring";
import { cceoOperatingTargets, plOperatingTargets } from "@/lib/operating-targets-mock";
import { TargetsLive } from "@/components/targets/TargetsLive";
import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { WorkloadContextCallout } from "@/components/performance/WorkloadContextCallout";
import { buildFairMatrix, computePortfolioComplexity } from "@/lib/performance/fwi-engine";
import { fairMatrixInputsForTeam } from "@/lib/performance/fwi-mock";

// /my-targets — personal command center.
//
//   • CCEO and CountryProgramLead → new OperatingTargetsView (the
//     multi-period scorecard introduced in the May 2025 design refresh:
//     7 period donut tiles, 6 KPI summary cards, target-by-period
//     matrix, progress trend chart, contribution waterfall, performance
//     distribution, top areas to focus).
//   • Other roles → CPL-style My Targets view, unchanged.
export default async function MyTargetsPage() {
  const user = await getCurrentUser();
  // Role-scoped filter options for the live header filter bar.
  const scope = getFilterScope({ user });

  if (user.role === "CCEO") {
    // Look up this staff member's FWI row from the team matrix so the
    // callout shows raw vs adjusted pace + the top load factors.
    // Falls back to a neutral display when the staff isn't seeded in
    // the mock (which is fine for demo users not in the FWI roster).
    const team = buildFairMatrix(fairMatrixInputsForTeam());
    const me = team.find((r) => r.staffName.toLowerCase().includes(user.name.split(" ")[0].toLowerCase()));
    const meInput = fairMatrixInputsForTeam().find((r) => r.staffId === me?.staffId);
    const contributions = meInput
      ? computePortfolioComplexity(meInput.complexityInputs).contributions
      : null;

    return (
      <>
        {/* Page chrome — single canonical header strip at the top.
            Lives ABOVE the welcome hero so title · period filters ·
            Export · search · message · bell · avatar all sit in one
            row, not a duplicate mid-page strip. */}
        <OperatingTargetsPageHeader data={cceoOperatingTargets} scope={scope} />
        <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-4">
          <CommandStack user={user} />
          <TargetsLive title="My target progress" />
          {me && contributions ? (
            <WorkloadContextCallout
              staffName={user.name}
              rawPacePct={me.rawPacePct}
              adjustedPacePct={me.adjustedPacePct}
              complexityPercentile={me.complexityPercentile}
              contributions={contributions}
            />
          ) : null}
          {/* Partner activity monitoring — the staff's window into
              every partner activity they assigned, from schedule
              through evidence to payment. Solves the "lose sight of
              partner work" problem from the workflow spec. */}
          <StaffPartnerMonitoring />
          <OperatingTargetsView data={cceoOperatingTargets} />
        </div>
      </>
    );
  }

  if (user.role === "CountryProgramLead") {
    return (
      <>
        <OperatingTargetsPageHeader data={plOperatingTargets} scope={scope} />
        <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-4">
          <CommandStack user={user} />
          <TargetsLive title="My team-lead target progress" />
          <StaffPartnerMonitoring />
          <OperatingTargetsView data={plOperatingTargets} />
        </div>
      </>
    );
  }

  return (
    <ResponsiveDashboard
      mobile={<CplTargetsView />}
      desktop={<CplTargetsDesktopView />}
    />
  );
}
