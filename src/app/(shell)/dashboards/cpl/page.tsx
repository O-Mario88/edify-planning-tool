import { CommandStack } from "@/components/actions/CommandStack";
import { ProjectWorkCard } from "@/components/special-projects/ProjectWorkCard";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DebriefPromoterCard } from "@/components/debrief/DebriefPromoterCard";
import { PlCommandLanes } from "@/components/cpl/PlCommandLanes";
import { CplFieldWorkCard } from "@/components/cpl/CplFieldWorkCard";
import { TeamKpiRow } from "@/components/cpl/TeamKpiRow";
import { CplLeadershipAttentionRow } from "@/components/cpl/CplLeadershipAttentionRow";
import { TeamPerformanceOverviewChart } from "@/components/ui/lazy-charts";
import { PersonalTargetsCard } from "@/components/cpl/PersonalTargetsCard";
import { CceoPerformanceTable } from "@/components/cpl/CceoPerformanceTable";
import { ApprovalQueueCard } from "@/components/cpl/ApprovalQueueCard";
import { PlPartnerPaymentsQueue } from "@/components/partner/PlPartnerPaymentsQueue";
import { TeamBacklogSnapshotCard } from "@/components/cpl/TeamBacklogSnapshotCard";
import {
  InterventionPerformanceByClusterCard,
  SchoolsNeedingUrgentAttentionCard,
} from "@/components/cpl/SchoolSsaIntelligenceCard";
import { SmartRouteCapacityCard } from "@/components/cpl/SmartRouteCapacityCard";
import { FundingExecutionCard } from "@/components/cpl/FundingExecutionCard";
import { QuickActionsRow } from "@/components/cpl/QuickActionsRow";
import { MyPlanCard } from "@/components/planning/MyPlanCard";
import { ClientVerificationCard } from "@/components/ssa/ClientVerificationCard";
import { ClusterReadinessCard } from "@/components/cluster/ClusterReadinessCard";
import { ClusterOperationsCard } from "@/components/cluster/ClusterOperationsCard";
import { scopedClusterCounts } from "@/lib/cluster/cluster-scope";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { TeamCapacityCard } from "@/components/cpl/TeamCapacityCard";
import { ROLE_REDIRECT } from "@/lib/auth-public";

// Country Program Lead Dashboard — replica of the SIPA reference.
//
// Reading order (post-rebalance — every row is now sized to its
// natural content so no card has dead space and no label truncates):
//   1. Unified DashboardHero (title · filters · greeting · chips · CTAs)
//   2. 8 KPI tiles — single row at xl, 4×2 at lg, 2-up on phone
//   3. Leadership Attention — 3 alert banners
//   4. Team Performance Overview (8) + My Personal Targets (4)
//   5. CCEO Performance (7) + Approval Queue (5)         ← two tables paired
//   6. Team Backlog Snapshot — full-width 6-tile strip   ← promoted from col-3
//   7. SSA Intelligence (8) + Funding & Execution (4)    ← heatmap gets room
//   8. Smart Route & Capacity — full width               ← 4 KPIs + table breathe
//   9. Quick Actions — 6 shortcut tiles
//
// What changed vs the original 5/4/3 + 4/4/4 layout:
//   • The 5/4/3 row crushed Team Backlog's 6 tiles into ~280px each —
//     labels truncated, the card visually starved.
//   • The 4/4/4 row crushed SSA Intelligence (heatmap *and* schools
//     list) into ~390px — both halves shrunk.
// Splitting Team Backlog and Smart Route into their own full-width
// rows lets every card show its full content at a glanceable size.
export default async function CountryProgramLeadDashboard() {
  // Defense-in-depth: middleware already gates /dashboards/cpl, but the
  // page re-checks so a guard gap can't expose another role's cockpit.
  const user = await getCurrentUser();
  if (!["CountryProgramLead", "Admin"].includes(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  const clusterCounts = scopedClusterCounts(user.staffId, user.role);

  const body = (
    <>

      {/* Subtle page wash — two soft radial gradients so the dashboard
          reads as a deliberate surface rather than a wall of cards on
          beige paper. Fixed and behind everything so it doesn't fight
          scrolling. */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          backgroundImage:
            "radial-gradient(1200px 600px at 8% 0%, rgba(82,112,131,0.05) 0%, transparent 55%), radial-gradient(900px 500px at 100% 4%, rgba(16,185,129,0.04) 0%, transparent 50%)",
        }}
      />

      <DashboardPageHeader role="CountryProgramLead" />
      <div className="px-3 sm:px-4 md:px-5 lg:px-6 pb-24 lg:pb-6 pt-3 md:pt-4 space-y-4 md:space-y-5">
        {/* Today's Program Debrief promoter sits above CommandStack so
            the PL is reminded to file before they review queues. */}
        <DebriefPromoterCard submitterRole="CountryProgramLead" />

        {/* TODAY — 10-Second Command Stack carries its own strategic
            header internally; no outer chapter needed. */}
        <CommandStack user={user} hideMission />

        {/* FIELD & TEAM — the player-coach split. Two command lanes
            (My Field Work vs My Team Work) so the PL sees their own
            implementation target AND what the CCEO team needs, before the
            deeper field-work card. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Field & team"
            title="Your two jobs today"
            description="You deliver field work and you lead a CCEO team — here's what each needs from you right now."
          />
          <PlCommandLanes />
          <ClusterReadinessCard clustered={clusterCounts.clustered} unclustered={clusterCounts.unclustered} needsReview={clusterCounts.needsReview} title="Team cluster setup" />
          <ClusterOperationsCard scope="team" />
          <ProjectWorkCard user={user} />
          <div id="my-field-work">
            <CplFieldWorkCard />
          </div>
        </section>

        {/* TEAM PERFORMANCE — KPIs, attention alerts, monthly chart,
            personal targets. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Team performance"
            title="How your team is tracking"
            description="Eight KPIs, leadership-attention alerts, and the monthly performance picture next to your own targets."
          />
          <TeamKpiRow />
          <TeamCapacityCard plStaffId={user.staffId} />
          <CplLeadershipAttentionRow />
          <section className="grid grid-cols-12 gap-3 md:gap-4 items-stretch">
            <div className="col-span-12 lg:col-span-8" id="team-performance">
              <TeamPerformanceOverviewChart />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <PersonalTargetsCard />
            </div>
          </section>
        </section>

        {/* APPROVALS & PEOPLE — CCEO table, approval queue, best
            performers, partner payments, the team plan. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Approvals & people"
            title="What needs your sign-off"
            description="CCEO performance, the approval queue, recognition, partner-payment gate, and the team field plan."
          />
          <section className="grid grid-cols-12 gap-3 md:gap-4 items-stretch" id="cceo-performance">
            <div className="col-span-12 lg:col-span-7">
              <CceoPerformanceTable />
            </div>
            <div className="col-span-12 lg:col-span-5" id="approvals">
              <ApprovalQueueCard />
            </div>
          </section>
          <div id="partner-payments">
            <PlPartnerPaymentsQueue />
          </div>
          <div id="my-plan">
            <MyPlanCard role="cpl" />
          </div>
          {/* Portfolio self-verification — own quota + the whole CCEO team's 10%. */}
          <ClientVerificationCard highlightStaffId={user.staffId} />
        </section>

        {/* OPERATIONS — Team backlog, intervention heatmap, funding,
            urgent schools. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Operations"
            title="Where execution is slipping"
            description="Team backlog, intervention performance by cluster, funding execution, and schools needing urgent attention."
          />
          <div id="backlog-snapshot">
            <TeamBacklogSnapshotCard />
          </div>
          <section className="grid grid-cols-12 gap-3 md:gap-4 items-stretch">
            <div className="col-span-12 lg:col-span-8" id="ssa-intelligence">
              <InterventionPerformanceByClusterCard />
            </div>
            <div className="col-span-12 lg:col-span-4" id="finance">
              <FundingExecutionCard />
            </div>
          </section>
          <div id="urgent-schools">
            <SchoolsNeedingUrgentAttentionCard />
          </div>
        </section>

        {/* ROUTES — Smart routing + capacity. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Routes"
            title="Capacity and route quality"
            description="Where the team can pick up more visits and which routes are degrading."
          />
          <div id="smart-route">
            <SmartRouteCapacityCard />
          </div>
        </section>

        {/* Quick Actions — its own self-contained card, no chapter. */}
        <QuickActionsRow />
      </div>
    </>
  );

  // Same content tree for mobile + desktop — every component handles
  // its own breakpoints (grids collapse to 2-col on phone, tables
  // become card lists where the column count would overflow, charts
  // resize fluidly).
  return <ResponsiveDashboard mobile={body} desktop={body} />;
}
