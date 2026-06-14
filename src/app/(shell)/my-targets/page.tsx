import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { CplTargetsView } from "@/components/mobile/views/CplTargetsView";
import { CplTargetsDesktopView } from "@/components/mobile/desktop-variants/CplTargetsDesktopView";
import { CommandStack } from "@/components/actions/CommandStack";
import { StaffPartnerMonitoring } from "@/components/partner/StaffPartnerMonitoring";
import { TargetsLive } from "@/components/targets/TargetsLive";
import { PageHeader } from "@/components/ui/PageHeader";
import { getCurrentUser } from "@/lib/auth";

// /my-targets — personal command center.
//
//   • CCEO and CountryProgramLead → live target progress (TargetsLive,
//     fed by real backend target data) + action queue (CommandStack) +
//     partner-activity monitoring, under the canonical PageHeader.
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
          <TargetsLive title="My target progress" />
          {/* Partner activity monitoring — the staff's window into
              every partner activity they assigned, from schedule
              through evidence to payment. Solves the "lose sight of
              partner work" problem from the workflow spec. */}
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
