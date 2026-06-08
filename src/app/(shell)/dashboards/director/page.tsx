import { CommandStack } from "@/components/actions/CommandStack";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DonorImpactReachCard } from "@/components/director/DonorImpactReachCard";
import { getDonorMetricSnapshot } from "@/lib/donor-metrics";
import { DebriefReviewInbox } from "@/components/messages/DebriefReviewInbox";
import { CountryKpiRow } from "@/components/director/CountryKpiRow";
import { LeadershipAttentionRow } from "@/components/director/LeadershipAttentionRow";
import { TrainingCoverageCard } from "@/components/director/TrainingCoverageCard";
import { allClusterTrainingPlans } from "@/lib/plan-builder-engine";
import { PlanScheduleByWeek } from "@/components/planning/PlanScheduleByWeek";
import { planItems, cceoPlanItems } from "@/lib/mobile-mock";
import {
  CountryPerformanceChart,
  RegionalPerformanceCard,
} from "@/components/ui/lazy-charts";
import { ProgramLeadsPerformanceTable } from "@/components/director/ProgramLeadsTable";
import {
  FundApprovalFinanceSnapshot,
  FundedNotCompletedCard,
} from "@/components/director/FundApprovalFinance";
import { OperationalRiskBacklogRow } from "@/components/director/OperationalRiskRow";
import { SchoolSsaIntelligenceCard } from "@/components/director/SchoolSsaIntelligenceCard";
import { PrioritySchoolsUrgentAttentionCard } from "@/components/director/PrioritySchoolsAttention";
import { QuickLeadershipActions } from "@/components/director/QuickLeadershipActions";
import { ClientVerificationCard } from "@/components/ssa/ClientVerificationCard";
import { ClusterReadinessCard } from "@/components/cluster/ClusterReadinessCard";
import { ClusterOperationsCard } from "@/components/cluster/ClusterOperationsCard";
import { scopedClusterCounts } from "@/lib/cluster/cluster-scope";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { SsaPerformanceGrid } from "@/components/ssa/SsaPerformanceGrid";
import { InterventionImprovementGrid } from "@/components/ssa/InterventionImprovementGrid";
import { SupportImprovementCard } from "@/components/analytics/SupportImprovementCard";

// Country Director Dashboard — Executive cockpit replica.
//
// Reading order (post-rebalance — every row now pairs cards by
// content weight, so no row leaves dead vertical space):
//   1. Executive Header — breadcrumb + title + subtitle + filters + profile
//   2. 8 KPI tiles
//   3. Leadership Attention — 3 alert banners
//   4. Country Performance Overview + Regional Performance
//   5. Program Leads Performance + Priority Schools Needing Urgent Attention
//   6. Operational Risk & Backlog + School & SSA Intelligence
//   7. Fund Approval & Finance Snapshot + Funded Not Completed
//   8. Quick Leadership Actions — 6 shortcuts
//
// All the auxiliary callouts that previously stacked above the fold
// (decision routing, leave impact, leaderboard, weekly debriefs, top
// performers, team targets, SSA refresh, training follow-ups) have been
// stripped because none of them appear in the reference. The director
// view is a glanceable status read-out, not a feed of personal queues —
// those live on the Director's "Today" and per-domain pages.
export default async function CountryDirectorDashboard() {
  // Defense-in-depth: middleware already gates /dashboards/director,
  // but the page re-checks so a guard gap can't expose this cockpit.
  const user = await getCurrentUser();
  if (!["CountryDirector", "Admin"].includes(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }

  // National donor-reporting rollup — same builder as /donor-reporting,
  // so the dashboard snapshot and the full report never disagree.
  const donorSnapshot = getDonorMetricSnapshot({
    role: "CountryDirector",
    userName: user.name,
    generatedBy: user.name,
  });
  const clusterCounts = scopedClusterCounts(user.staffId, user.role);

  const body = (
    <>
      <DashboardPageHeader role="CountryDirector" />
      <div className="px-3 sm:px-4 md:px-5 pb-24 md:pb-5 pt-3 md:pt-4 space-y-4 md:space-y-5">
        {/* TODAY — CommandStack carries its own header. */}
        <CommandStack user={user} hideMission />

        {/* Three-layer truth: ① SSA performance (status) ② intervention
            improvement (FY change) ③ support→improvement (what worked before SSA). */}
        <SsaPerformanceGrid />
        <InterventionImprovementGrid />
        <SupportImprovementCard />

        {/* COUNTRY HEALTH — KPIs, attention banners, debrief routing,
            training coverage. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Country health"
            title="The state of the country this period"
            description="Eight headline KPIs, leadership-attention alerts, debriefs routed up to you, and training-coverage against SSA gaps."
          />
          <CountryKpiRow />
          <ClusterReadinessCard clustered={clusterCounts.clustered} unclustered={clusterCounts.unclustered} needsReview={clusterCounts.needsReview} title="National cluster setup" />
          <ClusterOperationsCard scope="country" />
          <LeadershipAttentionRow />
          <DebriefReviewInbox user={user} audience="cd" />
          <TrainingCoverageCard audience="cd" clusterPlans={allClusterTrainingPlans()} />
        </section>

        {/* PERFORMANCE — country chart, regional rail, PL table,
            priority schools, recognition. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Performance"
            title="How regions and program leads are tracking"
            description="Country-wide trend, regional comparison, PL performance, schools needing attention, and the period's top performers."
          />
          <section className="grid grid-cols-12 gap-3 items-stretch">
            <div className="col-span-12 lg:col-span-8">
              <CountryPerformanceChart />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <RegionalPerformanceCard />
            </div>
          </section>
          <section className="grid grid-cols-12 gap-3 items-stretch" id="program-leads">
            <div className="col-span-12 lg:col-span-7">
              <ProgramLeadsPerformanceTable />
            </div>
            <div className="col-span-12 lg:col-span-5" id="priority-schools">
              <PrioritySchoolsUrgentAttentionCard />
            </div>
          </section>
          {/* Portfolio self-verification — country rollup of the 10% quota. */}
          <ClientVerificationCard />
        </section>

        {/* OPERATIONS & PLAN — risk backlog, SSA intelligence, plan
            horizon. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Operations & plan"
            title="Where execution is at risk"
            description="Operational risk + SSA intelligence today, then the 30-day plan horizon for what's coming."
          />
          <section className="grid grid-cols-12 gap-3 items-stretch" id="operational-risk">
            <div className="col-span-12 lg:col-span-5">
              <OperationalRiskBacklogRow />
            </div>
            <div className="col-span-12 lg:col-span-7" id="ssa-intelligence">
              <SchoolSsaIntelligenceCard />
            </div>
          </section>
          <PlanScheduleByWeek
            items={[...planItems, ...cceoPlanItems]}
            audience="leadership"
            title="30-day plan horizon — country"
            initialExpanded="first"
          />
        </section>

        {/* FINANCE — fund approvals + funded-not-completed. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Finance"
            title="What's in approval and where money is parked"
            description="Fund approvals awaiting your sign-off and disbursements that haven't yet converted to delivery."
          />
          <section className="grid grid-cols-12 gap-3 items-stretch" id="fund-approvals">
            <div className="col-span-12 lg:col-span-8">
              <FundApprovalFinanceSnapshot />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <FundedNotCompletedCard />
            </div>
          </section>
        </section>

        {/* IMPACT & DONOR REPORTING — what the country can report up to
            donors this period, straight from verified workflow data. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Impact"
            title="What the country can report this period"
            description="Donor-ready reach, training, and improvement figures — deduplicated and scoped to the country. Each tile opens the full report."
          />
          <DonorImpactReachCard snapshot={donorSnapshot} />
        </section>

        {/* Quick Leadership Actions — closing utility surface. */}
        <QuickLeadershipActions />
      </div>
    </>
  );

  // Same content tree for mobile + desktop. Each component below the
  // hero uses responsive Tailwind classes (grid-cols-1 → md:grid-cols-2
  // → lg:grid-cols-X) and tables overflow inside their own cards on
  // phones rather than blowing out the page width.
  return <ResponsiveDashboard mobile={body} desktop={body} />;
}
