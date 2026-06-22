import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DashboardGreetingHero } from "@/components/dashboards/DashboardGreetingHero";
import { TodayCommandCenter } from "@/components/command/TodayCommandCenter";
import { CommandStack } from "@/components/actions/CommandStack";
import { PartnerDebriefReviewCard } from "@/components/debrief/PartnerDebriefReviewCard";
import { DebriefPromoterCard } from "@/components/debrief/DebriefPromoterCard";
import { CceoKpiStrip } from "@/components/cceo/CceoKpiStrip";
import { CoreServicePackageCard } from "@/components/cceo/CoreServicePackageCard";
import { CoreSsaHeatmapCard } from "@/components/cceo/CoreSsaHeatmapCard";
import { CoreSsaHeatmapLive } from "@/components/cceo/CoreSsaHeatmapLive";
import { isMockAllowed } from "@/lib/mock-policy";
import { CoreSchoolsNeedingAttentionCard } from "@/components/cceo/CoreSchoolsNeedingAttentionCard";
import { VerificationPaymentFunnel } from "@/components/cceo/VerificationPaymentFunnel";
import { CceoSalesforceQueueCard } from "@/components/cceo/CceoSalesforceQueueCard";
import { WeeklyFundRequestCard } from "@/components/budget/WeeklyFundRequestCard";
import { FundApprovalQueueLive } from "@/components/funds/FundApprovalQueueLive";
import { CceoClusterScheduleCard } from "@/components/cceo/CceoClusterScheduleCard";
import { CceoMomentumBanner } from "@/components/cceo/CceoMomentumBanner";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { ResponsiveGrid } from "@/components/ui/ResponsiveGrid";
import { PortfolioSummaryCard } from "@/components/portfolio/PortfolioSummaryCard";
import { ClusterReadinessCard } from "@/components/cluster/ClusterReadinessCard";
import { scopedClusterCounts } from "@/lib/cluster/cluster-scope";
import { getCurrentUser } from "@/lib/auth";
import { fetchTargetsByPeriod } from "@/lib/api/surfaces";
import { BackendTargetsTable } from "@/components/targets/BackendTargetsTable";
import {
  RedAlertSchoolsCard,
  SsaNeededCard,
  RecommendedActionsCard,
} from "@/components/cceo/CoachingRadar";
import { FundSlipStatusCard } from "@/components/cceo/FundSlipStatusCard";
import { PartnerWorkMonitorCard } from "@/components/cceo/PartnerWorkMonitorCard";
import { EvidenceFollowUpCard } from "@/components/cceo/EvidenceFollowUpCard";
import { MyNextActions } from "@/components/next-action/MyNextActions";

// CCEO — My Field Coaching Assistant (spec: "Today First" field dashboard).
//
// The CCEO is a school coach, trainer, spiritual-transformation
// facilitator, and field reporter — NOT an admin. The dashboard answers,
// in order: what must I do today → which schools need urgent support →
// which need SSA → what should I schedule → which clusters meet → what
// partner work waits on me → what money this week → what proof is
// pending → am I on target → submit the debrief.
//
//   hero  GREETING      — "Good morning, X. Here's what needs your attention."
//   stats SNAPSHOT      — portfolio + pace strip (system layout rule:
//                         header → hero → stats → work)
//   A     TODAY         — Today's required actions (command center + stack)
//   B–D   COACHING RADAR— red alerts · SSA missing · recommended visits/trainings
//   E     CLUSTERS      — parish-fellowship readiness + upcoming meetings
//   F     PARTNER WORK  — assignments, evidence to review, payment status
//   G     THIS WEEK'S MONEY — auto-generated fund slip + cost breakdown
//   H     PROOF         — evidence / Salesforce / IA follow-up
//   I     TARGETS       — period targets + core service package
//   J     DEBRIEF       — daily debrief promoter (drawer)
export default async function CceoDashboardPage() {
  const user = await getCurrentUser();
  const targets = await fetchTargetsByPeriod(user);
  const clusterCounts = scopedClusterCounts(user.staffId, user.role);

  const mobile = (
    <div className="min-h-screen bg-[var(--color-page)] flex flex-col">
      <DashboardPageHeader role="CCEO" />
      <main className="flex-1 px-3 sm:px-4 pt-3 pb-28 space-y-3">
        {/* Layout rule: header → greeting hero → stats → work. */}
        <DashboardGreetingHero user={user} />
        <PortfolioSummaryCard staffId={user.staffId} />
        <CceoKpiStrip />
        {/* A — today's required actions, before everything else. */}
        <MyNextActions assigneeId={user.staffId} />
        {isMockAllowed() ? <CommandStack user={user} hideMission /> : <TodayCommandCenter />}
        {/* B–D — coaching radar. */}
        <RedAlertSchoolsCard staffId={user.staffId} role={user.role} />
        <SsaNeededCard staffId={user.staffId} role={user.role} />
        <RecommendedActionsCard staffId={user.staffId} role={user.role} />
        {/* E — clusters / parish fellowships. */}
        <ClusterReadinessCard clustered={clusterCounts.clustered} unclustered={clusterCounts.unclustered} needsReview={clusterCounts.needsReview} title="Cluster setup readiness" />
        <CceoClusterScheduleCard />
        {/* F — partner work to review. */}
        <PartnerWorkMonitorCard />
        <PartnerDebriefReviewCard />
        {/* G — this week's money. */}
        <FundSlipStatusCard staffId={user.staffId} />
        <WeeklyFundRequestCard />
        {/* H — proof: evidence / Salesforce / IA. */}
        <EvidenceFollowUpCard user={user} />
        <CceoSalesforceQueueCard />
        <VerificationPaymentFunnel />
        {/* I — targets + service package. */}
        {targets.live && <BackendTargetsTable targets={targets.data} title="My targets by time period" />}
        <CoreServicePackageCard />
        {/* J — daily debrief. */}
        <DebriefPromoterCard submitterRole="CCEO" />
        <CceoMomentumBanner />
      </main>
    </div>
  );

  const desktop = (
    <>
      <DashboardPageHeader role="CCEO" />
      <div className="px-4 sm:px-5 lg:px-6 pb-24 lg:pb-6 pt-3 lg:pt-4 space-y-4 lg:space-y-5">
        {/* GREETING HERO — orientation before numbers and queues. */}
        <DashboardGreetingHero user={user} />

        {/* SNAPSHOT — the statistics band under the hero. */}
        <div className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
          <div className="col-span-12 lg:col-span-7">
            <PortfolioSummaryCard staffId={user.staffId} />
          </div>
          <div className="col-span-12 lg:col-span-5">
            <ClusterReadinessCard clustered={clusterCounts.clustered} unclustered={clusterCounts.unclustered} needsReview={clusterCounts.needsReview} title="Cluster setup readiness" />
          </div>
        </div>
        <CceoKpiStrip />

        {/* A — TODAY'S REQUIRED ACTIONS. First section, always. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Today"
            title="Today's required actions"
            description="Visits, trainings, cluster meetings, reviews, and submissions due — each with its reason and one button."
          />
          <MyNextActions assigneeId={user.staffId} />
          {isMockAllowed() ? <CommandStack user={user} hideMission /> : <TodayCommandCenter />}
        </section>

        {/* B–D — COACHING RADAR: which school, why, what next. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Coaching radar"
            title="Which schools need you"
            description="Red alerts, missing SSAs, and the visits & trainings the SSA engine recommends — straight from your portfolio's two weakest interventions."
          />
          {/* Equal-peer cards → ResponsiveGrid auto-fit so they flow 3→2→1 by
              width (the old col-span jumped straight from 1-col to 3-col with no
              tablet state) and a compact card never strands a column. */}
          <ResponsiveGrid min={300} gap={16} className="items-stretch">
            <RedAlertSchoolsCard staffId={user.staffId} role={user.role} />
            <SsaNeededCard staffId={user.staffId} role={user.role} />
            <RecommendedActionsCard staffId={user.staffId} role={user.role} />
          </ResponsiveGrid>
          <div className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch [&>div>*]:h-full">
            <div className="col-span-12 lg:col-span-7"><CoreSchoolsNeedingAttentionCard /></div>
            <div className="col-span-12 lg:col-span-5">{isMockAllowed() ? <CoreSsaHeatmapCard /> : <CoreSsaHeatmapLive />}</div>
          </div>
        </section>

        {/* E — CLUSTER / PARISH FELLOWSHIP ACTIONS. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Clusters"
            title="Parish fellowships & cluster meetings"
            description="Upcoming meetings and the discussion topics your clusters' SSA averages recommend."
          />
          <CceoClusterScheduleCard />
        </section>

        {/* F — PARTNER WORK TO REVIEW. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Partner work"
            title="What partners owe you — and what you owe them"
            description="Unscheduled assignments, evidence waiting on your review, returns, Salesforce hand-offs, and payment status."
          />
          {/* The monitor is a 6-metric strip — it earns full width. The debrief
              review card renders null when there are no partner debriefs, so a
              fixed 5-col beside it stranded a dead void; stack it full-width
              below instead and it simply disappears when empty. */}
          <PartnerWorkMonitorCard />
          <PartnerDebriefReviewCard />
        </section>

        {/* G — THIS WEEK'S MONEY. Auto-generated; the CCEO never adds it up. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="This week's money"
            title="Weekly fund request"
            description="Generated from your scheduled activities at CD-approved catalogue rates — review, submit, account."
          />
          <div className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch [&>div>*]:h-full">
            <div className="col-span-12 lg:col-span-5"><FundSlipStatusCard staffId={user.staffId} /></div>
            <div className="col-span-12 lg:col-span-7"><WeeklyFundRequestCard /></div>
          </div>
          <div id="fund-approvals">
            <FundApprovalQueueLive canSubmit />
          </div>
        </section>

        {/* H — PROOF: evidence / Salesforce / IA follow-up. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Proof"
            title="Evidence, Salesforce & IA follow-up"
            description="Completed work isn't done until evidence is up, the SV-/TS- ID is in, and IA has verified it."
          />
          <div className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch [&>div>*]:h-full">
            <div className="col-span-12 lg:col-span-5"><EvidenceFollowUpCard user={user} /></div>
            <div className="col-span-12 lg:col-span-7"><VerificationPaymentFunnel /></div>
          </div>
          <CceoSalesforceQueueCard />
        </section>

        {/* I — TARGET PROGRESS. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Targets"
            title="Where you stand on your targets"
            description="Monthly progress rolls up to quarterly, mid-year, and FY — with the core service package alongside."
          />
          {targets.live && <BackendTargetsTable targets={targets.data} title="My targets by time period" />}
          <CoreServicePackageCard />
        </section>

        {/* J — DAILY DEBRIEF + closing momentum. */}
        <DebriefPromoterCard submitterRole="CCEO" />
        <CceoMomentumBanner />
      </div>
    </>
  );

  return <ResponsiveDashboard mobile={mobile} desktop={desktop} />;
}
