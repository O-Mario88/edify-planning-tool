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
import { LeadershipKpiStrip } from "@/components/director/LeadershipKpiStrip";
import { fetchLeadershipSummary } from "@/lib/api/surfaces";
import { selectionFromSearchParams, geoParamsFromSelection } from "@/lib/filters/apply-filters";
import { ExecutiveAlerts } from "@/components/director/ExecutiveAlerts";
import { CdRiskSummaryCard } from "@/components/escalation/CdRiskSummaryCard";
import { FlagToPlCard } from "@/components/director/FlagToPlCard";
import { MissionSnapshotStrip } from "@/components/director/MissionSnapshotStrip";
import { StaffPerformanceSummary } from "@/components/director/StaffPerformanceSummary";
import { PartnerPerformanceSummary } from "@/components/director/PartnerPerformanceSummary";
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
import { DecisionEngineEmbed } from "@/components/leadership/DecisionEngineEmbed";
import { BudgetIntelligenceEmbed } from "@/components/budget/BudgetIntelligenceEmbed";

// Country Director Dashboard — Country Mission Control.
//
// The CD is the senior country executive: mission, strategy, money,
// people, partners, risk, and impact. This page is ordered as an
// executive decision flow, not an operational feed:
//   A. Today's Executive Alerts — what needs a CD decision, with the
//      why and a recommended action on every row
//   B. Country Mission Snapshot — are we achieving the mission?
//   C. Budget & Fund Request Health — is money matching approved plans?
//   D. Program Execution — is the program on track? (analytics only)
//   E. SSA & Intervention Improvement — are schools improving?
//   F. Staff & Partner Performance — are people delivering / overloaded?
//   G. Recruitment Recommendation — expand or focus?
//   H. Donor-Ready Impact — what can we report confidently?
//   I. Risk & Data Quality — what could undermine all of the above?
//
// The CD never does field-level planning from here: every card is a
// summary with a controlled drilldown, no operational action buttons.
export default async function CountryDirectorDashboard({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  // Defense-in-depth: middleware already gates /dashboards/director,
  // but the page re-checks so a guard gap can't expose this cockpit.
  const user = await getCurrentUser();
  if (!["CountryDirector", "Admin"].includes(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  // Geography filter from the header bar — narrows the WHOLE cockpit (KPI strip,
  // program snapshot, pipeline) server-side, so the numbers track the filter chip.
  const geo = geoParamsFromSelection(selectionFromSearchParams(await searchParams));
  // Live country KPIs from the backend (real counts/aggregates over the CD's scope).
  const leadership = await fetchLeadershipSummary(user, geo);

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
        <CountryAnalyticsLive geo={geo} />

        {/* LEADERSHIP DECISION ENGINE — the executive intelligence layer:
            evidence-backed, human-reviewed recommendations (recruitment, staff,
            partner MOUs, regional investment) computed from live SSA, workload,
            partner & target data. The engine recommends; leadership decides. */}
        <DecisionEngineEmbed />

        {/* BUDGET INTELLIGENCE — the financial brain: cost ↔ verified activity ↔
            SSA impact, low-yield spend + reallocation advisory. */}
        <BudgetIntelligenceEmbed />

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
          {leadership.live ? <LeadershipKpiStrip s={leadership.data} scopeLabel="country" /> : <CountryKpiRow />}
        </section>

        {/* ── STATISTICS FIRST ──────────────────────────────────────────
            Every figure-heavy section sits up top so leadership sees the
            numbers before any work/action content: program execution +
            cluster operations, SSA & impact, donor-ready figures, and the
            risk/data-quality figures. Work, money, people and recruitment
            follow underneath. */}

        {/* PROGRAM EXECUTION — country trend, regional comparison, cluster ops. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Program execution"
            title="Is the program on track?"
            description="Country-wide trend, regional comparison, and cluster operations — monitored through analytics, not field planning."
          />
          <section className="grid grid-cols-12 gap-3 items-stretch [&>div>*]:h-full">
            <div className="col-span-12 lg:col-span-8">
              <CountryPerformanceChart />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <RegionalPerformanceCard />
            </div>
          </section>
          <ClusterOperationsCard scope="country" />
        </section>

        {/* SSA & INTERVENTION IMPROVEMENT — are schools improving? */}
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

        {/* DONOR-READY IMPACT — what can the country report this period? */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Impact"
            title="What can the country report this period?"
            description="Donor-ready reach, training, and improvement figures — deduplicated and scoped to the country. Each tile opens the full report."
          />
          <DonorImpactReachCard snapshot={donorSnapshot} />
        </section>

        {/* RISK & DATA QUALITY — what needs executive protection? */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Risk & data quality"
            title="What needs executive protection?"
            description="Operational backlogs, schools on red alert, and cluster readiness — the data-quality floor under every number above."
          />
          <section className="grid grid-cols-12 gap-3 items-stretch [&>div>*]:h-full" id="operational-risk">
            <div className="col-span-12 lg:col-span-7">
              <OperationalRiskBacklogRow />
            </div>
            <div className="col-span-12 lg:col-span-5" id="priority-schools">
              <PrioritySchoolsUrgentAttentionCard />
            </div>
          </section>
          <ClusterReadinessCard clustered={clusterCounts.clustered} unclustered={clusterCounts.unclustered} needsReview={clusterCounts.needsReview} title="National cluster setup" actionable={false} />
        </section>

        {/* ── WORK & ACTION (below the figures) ────────────────────────── */}

        {/* MAIN WORK — today's queue, then the executive alerts. */}
        <TodayCommandCenter />
        <CommandStack user={user} hideMission />

        {/* TODAY'S EXECUTIVE ALERTS — issue · why · scope · recommended
            action · one button. */}
        <ExecutiveAlerts inputs={{ unclusteredSchools: clusterCounts.unclustered }} />
        <CdRiskSummaryCard />
        {/* The CD's sanctioned action on what they monitor: flag to a PL (who
            plans) — never field-plan directly. Creates a tracked, notified item. */}
        <FlagToPlCard />

        {/* BUDGET & FUND REQUEST HEALTH — financial stewardship. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Money"
            title="Is money matching approved plans?"
            description="Annual budget vs plan, the cost catalogue you control, fund approvals awaiting sign-off, and funds parked without delivery."
          />
          <section className="grid grid-cols-12 gap-3 items-stretch [&>div>*]:h-full" id="country-budget">
            <div className="col-span-12 lg:col-span-7"><ScheduleBudgetCard /></div>
            <div className="col-span-12 lg:col-span-5"><CostSettingsCard /></div>
          </section>
          <section className="grid grid-cols-12 gap-3 items-stretch [&>div>*]:h-full" id="fund-approvals">
            <div className="col-span-12 lg:col-span-8">
              <FundApprovalFinanceSnapshot pendingFundRequests={cdPendingFundRequests()} />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <FundedNotCompletedCard />
            </div>
          </section>
        </section>

        {/* STAFF & PARTNER PERFORMANCE — leadership visibility. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="People & partners"
            title="Are teams and partners delivering?"
            description="PL performance, staff pace with context flags, partner delivery and certification, debriefs routed up to you, and the 10% verification quota."
          />
          {/* Country-lead performance gets its own full row — the table needs the
              width. The staff-pace summary (a 6-metric strip) was cramped at
              col-span-5; it reads better full width, so it moves to its own row
              above partner performance. */}
          <div id="program-leads">
            <ProgramLeadsPerformanceTable />
          </div>
          <StaffPerformanceSummary />
          <PartnerPerformanceSummary />
          <DebriefReviewInbox user={user} audience="cd" />
          <ClientVerificationCard />
        </section>

        {/* RECRUITMENT RECOMMENDATION — expand or focus? */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Recruitment"
            title="Recruit more schools or focus on current schools?"
            description="Capacity, SSA readiness, partner coverage, and impact rolled into one recommendation — with district-level continue/pause calls."
          />
          <RecruitmentIntelligenceCard />
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
