import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { LeaderboardMobileView } from "@/components/mobile/views/LeaderboardMobileView";
import { ExecutiveHeader } from "@/components/director/ExecutiveHeader";
import { LeaderboardSummaryCards } from "@/components/leaderboard/LeaderboardSummaryCards";
import { CategoryLeaderboardTabs } from "@/components/leaderboard/CategoryLeaderboardTabs";
import { ProgramLeadLeaderboardCard } from "@/components/leaderboard/ProgramLeadLeaderboardCard";
import { FairnessContextPanel } from "@/components/leaderboard/FairnessContextPanel";

// Verified Impact Leaderboard — single page housing all role views.
// Calculations live in lib/leaderboard-mock.ts so callouts on the CCEO,
// CPL, and Director dashboards read from the same engine.
export default function LeaderboardPage() {
  return (
    <ResponsiveDashboard mobile={<LeaderboardMobileView />} desktop={
    <>
      <ExecutiveHeader
        title="Verified Impact Leaderboard"
        subtitle="Verified results only — celebrate consistent, high-quality work across every target category."
        breadcrumb={["Home", "Leaderboard"]}
      />
        <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
          <LeaderboardSummaryCards />

          <CategoryLeaderboardTabs initialCategory="Overall" />

          <ProgramLeadLeaderboardCard />

          <FairnessContextPanel />
        </div>
      </>
    } />
  );
}
