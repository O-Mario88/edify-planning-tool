import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { CplTargetsView } from "@/components/mobile/views/CplTargetsView";
import { CplTargetsDesktopView } from "@/components/mobile/desktop-variants/CplTargetsDesktopView";
import { CommandStack } from "@/components/actions/CommandStack";
import { StaffPartnerMonitoring } from "@/components/partner/StaffPartnerMonitoring";
import { TargetsLive } from "@/components/targets/TargetsLive";
import { MyTargetsPerformanceLive } from "@/components/targets/MyTargetsPerformanceLive";
import { PageHeader } from "@/components/ui/PageHeader";
import { getCurrentUser } from "@/lib/auth";

// /my-targets — personal command center.
//
//   • CCEO and CountryProgramLead → live target progress. The PerformanceService
//     cards (backend-driven, every metric) sit above the legacy TargetsLive
//     visit/training strip, so the CCEO sees real achievement across visits,
//     trainings, SSA, evidence, IA — not just two target numbers.
//   • Other roles → CPL-style My Targets view, unchanged.
export default async function MyTargetsPage() {
  const user = await getCurrentUser();

  if (user.role === "CCEO") {
    return (
      <>
        <PageHeader
          title="My Targets"
          subtitle="Your live target progress, action queue, and partner activity."
          noBack
        />
        <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-4">
          <CommandStack user={user} />
          {/* Backend-driven performance cards (every metric, strict achievement
              rules, target status). The central PerformanceService is the source
              of truth — no mock numbers. */}
          <MyTargetsPerformanceLive />
          <TargetsLive title="Visit & training targets" />
          <StaffPartnerMonitoring />
        </div>
      </>
    );
  }

  if (user.role === "CountryProgramLead") {
    return (
      <>
        <PageHeader
          title="My Targets"
          subtitle="Your live team-lead target progress, action queue, and partner activity."
          noBack
        />
        <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-4">
          <CommandStack user={user} />
          <MyTargetsPerformanceLive />
          <TargetsLive title="My team-lead target progress" />
          <StaffPartnerMonitoring />
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
