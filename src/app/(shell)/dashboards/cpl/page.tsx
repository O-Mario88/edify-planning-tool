import { CommandStack } from "@/components/actions/CommandStack";
import { RecruitmentIntelligenceCard } from "@/components/analytics/RecruitmentIntelligenceCard";
import { DecisionEngineEmbed } from "@/components/leadership/DecisionEngineEmbed";
import { ProjectWorkCard } from "@/components/special-projects/ProjectWorkCard";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DashboardGreetingHero } from "@/components/dashboards/DashboardGreetingHero";
import { TodayCommandCenter } from "@/components/command/TodayCommandCenter";
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
import { ScheduleBudgetCard } from "@/components/budget/ScheduleBudgetCard";
import { WeeklyFundRequestCard } from "@/components/budget/WeeklyFundRequestCard";
import { FundApprovalQueueLive } from "@/components/funds/FundApprovalQueueLive";
import { TargetsLive } from "@/components/targets/TargetsLive";
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
import { TeamPlanBoard } from "@/components/cpl/TeamPlanBoard";
import { buildTeamPlan } from "@/lib/cpl/team-plan-engine";
import { ClusterMeetingRecommendationsCard } from "@/components/cpl/ClusterMeetingRecommendations";
import { clusterMeetingRecommendations } from "@/lib/cluster/cluster-meeting-recommendations";
import { PartnerOversightCard } from "@/components/cpl/PartnerOversightCard";
import { TeamDebriefComplianceCard } from "@/components/cpl/TeamDebriefComplianceCard";

// Country Program Lead Dashboard — Team Field Command Center.
//
// The PL is a player-coach: Team Coach + Quality Controller + Cluster
// Strategist + Field Execution Manager. Reading order = the PL's day:
//   A. Today's Required Actions — debrief, command stack, attention alerts
//   B. My Field Work — the PL's own plan, schools, and targets
//   C. Team Execution — per-CCEO Team Plan board, KPIs, capacity,
//      CCEO performance, plan approvals, routes
//   D. Schools & Clusters at Risk — urgent schools + SSA-guided cluster
//      meeting recommendations (two weakest interventions → topics)
//   E. Partner Work Needing Attention — oversight + payment gate
//   F. Budget & Fund Readiness — does money match the planned work?
//   G. Impact & Quality — intervention heatmap, verification quota,
//      evidence/Salesforce backlog, team debrief compliance
//
// Not here by design: CD-level strategy (cost catalogue editing, country
// rollups) and accountant-level payment controls.
export default async function CountryProgramLeadDashboard() {
  // Defense-in-depth: middleware already gates /dashboards/cpl, but the
  // page re-checks so a guard gap can't expose another role's cockpit.
  const user = await getCurrentUser();
  if (!["CountryProgramLead", "Admin"].includes(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  const clusterCounts = scopedClusterCounts(user.staffId, user.role);
  const teamPlan = buildTeamPlan(user.staffId);
  const clusterRecs = clusterMeetingRecommendations(user.staffId);

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
        {/* GREETING HERO — system-wide layout rule: header → hero →
            stats → work. Orients the PL before any numbers or queues. */}
        <DashboardGreetingHero user={user} />
        <TargetsLive title="Team target progress" />

        {/* Leadership Decision Engine — supervised-team staff & staffing advisory. */}
        <DecisionEngineEmbed board="staff_hr" heading="Team & Staff Decisions" />

        {/* TEAM SNAPSHOT — the program statistics band, directly below
            the hero: eight team KPIs before any work content. */}
        <TeamKpiRow />

        {/* A. TODAY'S REQUIRED ACTIONS — file the debrief first, then the
            command stack and the leadership-attention alerts. */}
        <DebriefPromoterCard submitterRole="CountryProgramLead" />
        <TodayCommandCenter />
        <CommandStack user={user} hideMission />
        <CplLeadershipAttentionRow />

        {/* B. MY FIELD WORK — the player half of the player-coach split:
            the PL's own schools, plan, and personal targets. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="My field work"
            title="What you must personally do this week"
            description="Your own visits, trainings, cluster meetings, and targets — separate from the team's work."
          />
          <PlCommandLanes />
          <div id="my-field-work">
            <CplFieldWorkCard />
          </div>
          <section className="grid grid-cols-12 gap-3 md:gap-4 items-stretch">
            <div className="col-span-12 lg:col-span-8" id="my-plan">
              <MyPlanCard role="cpl" />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <PersonalTargetsCard />
            </div>
          </section>
          <ProjectWorkCard user={user} />
        </section>

        {/* C. TEAM EXECUTION — the coach half: per-CCEO supervision board,
            team KPIs, capacity, CCEO table + plan approvals, routes. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Team execution"
            title="What your CCEOs are doing"
            description="Per-CCEO status with the why behind it, team KPIs, workload capacity, plan approvals, and route quality — without opening every CCEO page."
          />
          <TeamPlanBoard rows={teamPlan.rows} summary={teamPlan.summary} />
          <TeamCapacityCard plStaffId={user.staffId} />
          <section className="grid grid-cols-12 gap-3 md:gap-4 items-stretch" id="cceo-performance">
            <div className="col-span-12 lg:col-span-7">
              <CceoPerformanceTable />
            </div>
            <div className="col-span-12 lg:col-span-5" id="approvals">
              <ApprovalQueueCard />
            </div>
          </section>
          <section className="grid grid-cols-12 gap-3 md:gap-4 items-stretch">
            <div className="col-span-12 lg:col-span-8" id="team-performance">
              <TeamPerformanceOverviewChart />
            </div>
            <div className="col-span-12 lg:col-span-4" id="smart-route">
              <SmartRouteCapacityCard />
            </div>
          </section>
        </section>

        {/* D. SCHOOLS & CLUSTERS AT RISK — where support is needed next:
            urgent schools, then SSA-guided cluster meeting topics. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Schools & clusters"
            title="Which schools and clusters need support"
            description="Red-alert schools, cluster setup, cluster operations, and SSA-guided meeting recommendations — the two weakest interventions per cluster with a ready discussion topic."
          />
          <div id="urgent-schools">
            <SchoolsNeedingUrgentAttentionCard />
          </div>
          <ClusterMeetingRecommendationsCard recommendations={clusterRecs} />
          <ClusterReadinessCard clustered={clusterCounts.clustered} unclustered={clusterCounts.unclustered} needsReview={clusterCounts.needsReview} title="Team cluster setup" />
          <ClusterOperationsCard scope="team" />
          <RecruitmentIntelligenceCard />
        </section>

        {/* E. PARTNER WORK NEEDING ATTENTION — monitor + intervene;
            onboarding stays with the CD. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Partners"
            title="Partner work needing attention"
            description="Payments awaiting your approval, evidence status, and partners at delivery risk — escalate to the CD when quality doesn't recover."
          />
          <PartnerOversightCard />
          <div id="partner-payments">
            <PlPartnerPaymentsQueue />
          </div>
        </section>

        {/* F. BUDGET & FUND READINESS — does money match planned work? */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Budget & funds"
            title="Are funds matching the planned work?"
            description="The schedule auto-costed from the CD rate card, the weekly envelope, and the monthly fund requests rolled up from your CCEOs."
          />
          <section className="grid grid-cols-12 gap-3 md:gap-4 items-stretch" id="team-budget">
            <div className="col-span-12 lg:col-span-7"><ScheduleBudgetCard /></div>
            <div className="col-span-12 lg:col-span-5"><WeeklyFundRequestCard /></div>
          </section>
          {/* PL approves the monthly fund requests + plans rolled up from the
              CCEOs they supervise. Expandable rows; every cost from the
              catalogue. Backend scopes this to the supervision chain. */}
          <div id="fund-approvals">
            <FundApprovalQueueLive />
          </div>
        </section>

        {/* G. IMPACT & QUALITY — is support improving schools, and is the
            data chain (evidence → Salesforce → IA) keeping up? */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Impact & quality"
            title="Are schools improving — and is the data keeping up?"
            description="Intervention performance by cluster, funding execution, the 10% verification quota, the evidence/Salesforce backlog, and team debrief compliance."
          />
          <section className="grid grid-cols-12 gap-3 md:gap-4 items-stretch">
            <div className="col-span-12 lg:col-span-8" id="ssa-intelligence">
              <InterventionPerformanceByClusterCard />
            </div>
            <div className="col-span-12 lg:col-span-4" id="finance">
              <FundingExecutionCard />
            </div>
          </section>
          <ClientVerificationCard highlightStaffId={user.staffId} />
          <div id="backlog-snapshot">
            <TeamBacklogSnapshotCard />
          </div>
          <TeamDebriefComplianceCard plStaffId={user.staffId} />
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
