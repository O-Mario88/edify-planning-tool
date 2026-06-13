import { CommandStack } from "@/components/actions/CommandStack";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DashboardGreetingHero } from "@/components/dashboards/DashboardGreetingHero";
import { CountryAnalyticsLive } from "@/components/analytics/CountryAnalyticsLive";
import { TodayCommandCenter } from "@/components/command/TodayCommandCenter";
import { DonorImpactReachCard } from "@/components/director/DonorImpactReachCard";
import { ScheduleBudgetCard } from "@/components/budget/ScheduleBudgetCard";
import { CostSettingsCard } from "@/components/budget/CostSettingsCard";
import { getDonorMetricSnapshot } from "@/lib/donor-metrics";
import { DebriefReviewInbox } from "@/components/messages/DebriefReviewInbox";
import { CountryKpiRow } from "@/components/director/CountryKpiRow";
import { ExecutiveAlerts } from "@/components/director/ExecutiveAlerts";
import { CdRiskSummaryCard } from "@/components/escalation/CdRiskSummaryCard";
import { MissionSnapshotStrip } from "@/components/director/MissionSnapshotStrip";
import { StaffPerformanceSummary } from "@/components/director/StaffPerformanceSummary";
import { PartnerPerformanceSummary } from "@/components/director/PartnerPerformanceSummary";
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
import { fundRequests as fundRequestsStore } from "@/lib/actions/store";
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
import { RecruitmentIntelligenceCard } from "@/components/analytics/RecruitmentIntelligenceCard";

// Country Director Dashboard — Country Mission Control.
//
// The CD is the senior country executive: mission, strategy, money,
// people, partners, risk, and impact. This page is ordered as an
// executive decision flow, not an operational feed:
//   A. Today's Executive Alerts — what needs a CD decision, with the
//      why and a recommended action on every row
//   B. Country Mission Snapshot — are we achieving the mission?
//   C. Budget & Fund Request Health — is money matching approved plans?
//   D. Program Execution — are teams executing the plan?
//   E. SSA & Intervention Improvement — are schools improving?
//   F. Staff & Partner Performance — are people delivering / overloaded?
//   G. Recruitment Recommendation — expand or focus?
//   H. Donor-Ready Impact — what can we report confidently?
//   I. Risk & Data Quality — what could undermine all of the above?
//
// The CD never does field-level planning from here: every card is a
// summary with a controlled drilldown, no operational action buttons.
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
        {/* GREETING HERO — system-wide layout rule: header → hero →
            stats → work. "Good morning, [CD]. Here is the country
            execution, budget, and impact picture for today." */}
        <DashboardGreetingHero user={user} />

        {/* Live program snapshot (backend analytics) — real KPIs + activity pipeline. */}
        <CountryAnalyticsLive />

        {/* COUNTRY MISSION SNAPSHOT + KPI ROW — the program statistics
            band, directly below the hero and before any work content. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Mission"
            title="Are we achieving the country mission?"
            description="Reach, training, improvement, and coverage — from the same builder as the donor report — plus the country's headline KPIs."
          />
          <MissionSnapshotStrip snapshot={donorSnapshot} />
          <CountryKpiRow />
        </section>

        {/* MAIN WORK — today's queue, then the executive alerts. */}
        <TodayCommandCenter />
        <CommandStack user={user} hideMission />

        {/* TODAY'S EXECUTIVE ALERTS — issue · why · scope · recommended
            action · one button. Supersedes the old attention banners. */}
        <ExecutiveAlerts inputs={{ unclusteredSchools: clusterCounts.unclustered }} />
        <CdRiskSummaryCard />

        {/* C. BUDGET & FUND REQUEST HEALTH — financial stewardship. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Money"
            title="Is money matching approved plans?"
            description="Annual budget vs plan, the cost catalogue you control, fund approvals awaiting sign-off, and funds parked without delivery."
          />
          <section className="grid grid-cols-12 gap-3 items-stretch" id="country-budget">
            <div className="col-span-12 lg:col-span-7"><ScheduleBudgetCard /></div>
            <div className="col-span-12 lg:col-span-5"><CostSettingsCard /></div>
          </section>
          <section className="grid grid-cols-12 gap-3 items-stretch" id="fund-approvals">
            <div className="col-span-12 lg:col-span-8">
              <FundApprovalFinanceSnapshot pendingFundRequests={cdPendingFundRequests()} />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <FundedNotCompletedCard />
            </div>
          </section>
        </section>

        {/* D. PROGRAM EXECUTION — are teams executing the plan? */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Program execution"
            title="Are teams executing the plan?"
            description="Country-wide trend, regional comparison, cluster operations, training coverage against SSA gaps, and the 30-day plan horizon."
          />
          <section className="grid grid-cols-12 gap-3 items-stretch">
            <div className="col-span-12 lg:col-span-8">
              <CountryPerformanceChart />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <RegionalPerformanceCard />
            </div>
          </section>
          <ClusterOperationsCard scope="country" />
          <TrainingCoverageCard audience="cd" clusterPlans={allClusterTrainingPlans()} />
          <PlanScheduleByWeek
            items={[...planItems, ...cceoPlanItems]}
            audience="leadership"
            title="30-day plan horizon — country"
            initialExpanded="first"
          />
        </section>

        {/* E. SSA & INTERVENTION IMPROVEMENT — are schools improving?
            Three-layer truth: ① SSA performance (status) ② intervention
            improvement (FY change) ③ support→improvement (what worked). */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="SSA & impact"
            title="Are schools improving?"
            description="All 8 interventions: current FY performance, FY-to-FY change, and which support is associated with improvement."
          />
          <SsaPerformanceGrid />
          <InterventionImprovementGrid />
          <SupportImprovementCard />
          <SchoolSsaIntelligenceCard />
        </section>

        {/* F. STAFF & PARTNER PERFORMANCE — leadership visibility,
            not HR detail or partner raw operations. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="People & partners"
            title="Are teams and partners delivering?"
            description="PL performance, staff pace with context flags, partner delivery and certification, debriefs routed up to you, and the 10% verification quota."
          />
          <section className="grid grid-cols-12 gap-3 items-stretch" id="program-leads">
            <div className="col-span-12 lg:col-span-7">
              <ProgramLeadsPerformanceTable />
            </div>
            <div className="col-span-12 lg:col-span-5">
              <StaffPerformanceSummary />
            </div>
          </section>
          <PartnerPerformanceSummary />
          <DebriefReviewInbox user={user} audience="cd" />
          <ClientVerificationCard />
        </section>

        {/* G. RECRUITMENT RECOMMENDATION — expand or focus? The CD's
            directory replacement: country + per-district recommendation. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Recruitment"
            title="Recruit more schools or focus on current schools?"
            description="Capacity, SSA readiness, partner coverage, and impact rolled into one recommendation — with district-level continue/pause calls."
          />
          <RecruitmentIntelligenceCard />
        </section>

        {/* H. DONOR-READY IMPACT — what can we report confidently? */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Impact"
            title="What can the country report this period?"
            description="Donor-ready reach, training, and improvement figures — deduplicated and scoped to the country. Each tile opens the full report."
          />
          <DonorImpactReachCard snapshot={donorSnapshot} />
        </section>

        {/* I. RISK & DATA QUALITY — what could undermine the above. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Risk & data quality"
            title="What needs executive protection?"
            description="Operational backlogs, schools on red alert, and cluster readiness — the data-quality floor under every number above."
          />
          <section className="grid grid-cols-12 gap-3 items-stretch" id="operational-risk">
            <div className="col-span-12 lg:col-span-7">
              <OperationalRiskBacklogRow />
            </div>
            <div className="col-span-12 lg:col-span-5" id="priority-schools">
              <PrioritySchoolsUrgentAttentionCard />
            </div>
          </section>
          <ClusterReadinessCard clustered={clusterCounts.clustered} unclustered={clusterCounts.unclustered} needsReview={clusterCounts.needsReview} title="National cluster setup" actionable={false} />
        </section>

        {/* Quick Leadership Actions — closing utility surface. */}
        <QuickLeadershipActions />
      </div>
    </>
  );

  // Same content tree for mobile + desktop. Each content tree uses
  // responsive Tailwind classes (grid-cols-1 → md:grid-cols-2 → lg…)
  // and tables overflow inside their own cards on phones rather than
  // blowing out the page width.
  return <ResponsiveDashboard mobile={body} desktop={body} />;
}

// Live "pending fund requests" rows for the CD finance snapshot —
// folds the fundRequestsStore() SUBMITTED + APPROVED rows into the
// region-grouped shape FundApprovalFinanceSnapshot expects.
function cdPendingFundRequests() {
  const PENDING_STATUSES = new Set(["SUBMITTED", "APPROVED", "READY_TO_DISBURSE"]);
  const byRegion = new Map<string, { id: string; region: string; amount: number; activities: number; stages: Set<string> }>();
  for (const r of fundRequestsStore()) {
    if (!PENDING_STATUSES.has(r.status)) continue;
    const key = r.district || r.countryId || "—";
    const acc = byRegion.get(key) ?? { id: `fr-${key}`, region: key, amount: 0, activities: 0, stages: new Set<string>() };
    acc.amount += r.requestedAmount.amount;
    acc.activities += r.activities.length;
    acc.stages.add(r.status === "SUBMITTED" ? "Review" : "Approved");
    byRegion.set(key, acc);
  }
  const fmt = (n: number) =>
    n >= 1_000_000_000 ? `UGX ${(n / 1_000_000_000).toFixed(2)}B`
    : n >= 1_000_000     ? `UGX ${(n / 1_000_000).toFixed(1)}M`
    :                       `UGX ${n.toLocaleString()}`;
  return Array.from(byRegion.values()).map((r) => ({
    id: r.id,
    region: r.region,
    amountLabel: fmt(r.amount),
    activitiesCovered: r.activities,
    stage: r.stages.has("Review") ? "Review" : "Approved",
  }));
}
