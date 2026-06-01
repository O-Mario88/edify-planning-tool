import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { CommandStack } from "@/components/actions/CommandStack";
import { DebriefPromoterCard } from "@/components/debrief/DebriefPromoterCard";
import { CceoSixKpiRow } from "@/components/cceo/CceoSixKpiRow";
import { CceoKpiStrip } from "@/components/cceo/CceoKpiStrip";
import { CoreServicePackageCard } from "@/components/cceo/CoreServicePackageCard";
import { RiskBottleneckBoard } from "@/components/cceo/RiskBottleneckBoard";
import { CoreSsaHeatmapCard } from "@/components/cceo/CoreSsaHeatmapCard";
import { SsaQualityCard } from "@/components/cceo/SsaQualityCard";
import { CoreSchoolsNeedingAttentionCard } from "@/components/cceo/CoreSchoolsNeedingAttentionCard";
import { VerificationPaymentFunnel } from "@/components/cceo/VerificationPaymentFunnel";
import { CceoMonthPlannerCard } from "@/components/cceo/CceoMonthPlannerCard";
import { CceoMonthlyActivityBreakdownCard } from "@/components/cceo/CceoMonthlyActivityBreakdownCard";
import { CceoSalesforceQueueCard } from "@/components/cceo/CceoSalesforceQueueCard";
import { CceoRouteOpportunitiesCard } from "@/components/cceo/CceoRouteOpportunitiesCard";
import { CceoClusterScheduleCard } from "@/components/cceo/CceoClusterScheduleCard";
import { CceoNextPrioritySchoolStrip } from "@/components/cceo/CceoNextPrioritySchoolStrip";
import { CceoQuickActionsRow } from "@/components/cceo/CceoQuickActionsRow";
import { CceoMomentumBanner } from "@/components/cceo/CceoMomentumBanner";
import { CollapsibleCard } from "@/components/ui/CollapsibleCard";
import { getCurrentUser } from "@/lib/auth";

// CCEO Role Command Center.
//
// Action-first → performance → improvement intelligence → pipelines →
// schedule → motivation. In ten seconds the CCEO sees what needs action,
// whether they're on pace, what's improving, what's blocking, and what
// to do next.
//
//   1. COMMAND      — Today's command + Next 3 actions (CommandStack)
//   2. THIS WEEK    — pace KPIs + service package
//   3. ATTENTION    — Risk & bottleneck board (owner + action)
//   4. IMPROVEMENT  — SSA intervention heatmap + quality drift
//   5. AT RISK      — schools that need my attention this week
//   6. PIPELINE     — Verification & payment funnel + Salesforce queue
//   7. SCHEDULE     — month planner, activity mix, routes
//   8. PRIORITY     — next priority school
//   9. (no header)  — quick actions + momentum
export default async function CceoDashboardPage() {
  const user = await getCurrentUser();

  const mobile = (
    <div className="min-h-screen bg-[var(--color-page)] flex flex-col">
      <DashboardPageHeader role="CCEO" />
      <main className="flex-1 px-3 sm:px-4 pt-3 pb-28 space-y-3">
        <CommandStack user={user} />
        <DebriefPromoterCard submitterRole="CCEO" />
        <CceoSixKpiRow />
        <CceoKpiStrip />
        <CoreServicePackageCard />
        <RiskBottleneckBoard />
        <CoreSsaHeatmapCard />
        <SsaQualityCard />
        <CoreSchoolsNeedingAttentionCard />
        <VerificationPaymentFunnel />
        <CceoSalesforceQueueCard />
        <CceoMonthPlannerCard />
        <CceoMonthlyActivityBreakdownCard />
        <CceoRouteOpportunitiesCard />
        <CceoClusterScheduleCard />
        <CceoNextPrioritySchoolStrip />
        <CceoQuickActionsRow />
        <CceoMomentumBanner />
      </main>
    </div>
  );

  const desktop = (
    <>
      <DashboardPageHeader role="CCEO" />
      <div className="px-4 sm:px-5 lg:px-6 pb-24 lg:pb-6 pt-3 lg:pt-4 space-y-8 lg:space-y-10">
        {/* COMMAND — actions before everything else. What to do next. */}
        <CommandStack user={user} />

        <DebriefPromoterCard submitterRole="CCEO" />

        {/* THIS WEEK — vital signs.  KPI tiles + health funnel + service. */}
        <CollapsibleCard
          surface="bare"
          bodyClassName="space-y-3"
          id="cceo-this-week"
          tier="strategic"
          eyebrow="This Week"
          title="Where you are"
          description="Headline KPIs, school-health distribution, and your service-package progress at a glance."
        >
          <CceoSixKpiRow />
          <CceoKpiStrip />
          <CoreServicePackageCard />
        </CollapsibleCard>

        {/* ATTENTION — risks grouped by type, each with owner + action. */}
        <CollapsibleCard
          surface="bare"
          bodyClassName="space-y-3"
          id="cceo-attention"
          tier="strategic"
          eyebrow="Attention"
          title="What needs attention"
          description="Planning, execution, verification, partner, and payment risks — each with an owner and the next action."
        >
          <RiskBottleneckBoard />
        </CollapsibleCard>

        {/* IMPROVEMENT — SSA intervention intelligence. */}
        <CollapsibleCard
          surface="bare"
          bodyClassName="space-y-3"
          id="cceo-improvement"
          tier="strategic"
          eyebrow="Improvement"
          title="Where schools are struggling"
          description="SSA performance by intervention, plus quality drift across recent assessments."
        >
          <div className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
            <div className="col-span-12 lg:col-span-8">
              <CoreSsaHeatmapCard />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <SsaQualityCard />
            </div>
          </div>
        </CollapsibleCard>

        {/* AT RISK — schools that need my attention this week. */}
        <CollapsibleCard
          surface="bare"
          bodyClassName="space-y-3"
          id="cceo-at-risk"
          tier="strategic"
          eyebrow="At risk"
          title="Schools That Need My Attention This Week"
          description="Ranked by health-score drop, missed visits, and overdue SSA."
        >
          <CoreSchoolsNeedingAttentionCard />
        </CollapsibleCard>

        {/* PIPELINE — verification & payment, plus the Salesforce queue. */}
        <CollapsibleCard
          surface="bare"
          bodyClassName="space-y-3"
          id="cceo-pipeline"
          tier="strategic"
          eyebrow="Pipeline"
          title="Verification & payment"
          description="Where completed work is stuck on its way from evidence to cleared payment."
        >
          <div className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
            <div className="col-span-12 lg:col-span-7">
              <VerificationPaymentFunnel />
            </div>
            <div className="col-span-12 lg:col-span-5">
              <CceoSalesforceQueueCard />
            </div>
          </div>
        </CollapsibleCard>

        {/* SCHEDULE — month planner + activity breakdown + routes. */}
        <CollapsibleCard
          surface="bare"
          bodyClassName="space-y-3"
          id="cceo-schedule"
          tier="strategic"
          eyebrow="Schedule"
          title="What's planned across the month"
          description="Visit cadence, activity mix, and route opportunities for the days ahead."
        >
          <div className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
            <div className="col-span-12 lg:col-span-4">
              <CceoMonthPlannerCard />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <CceoMonthlyActivityBreakdownCard />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <CceoRouteOpportunitiesCard />
            </div>
          </div>
        </CollapsibleCard>

        {/* PRIORITY — next priority school spotlight. */}
        <CollapsibleCard
          surface="bare"
          bodyClassName="space-y-3"
          id="cceo-priority"
          tier="strategic"
          eyebrow="Priority"
          title="Next priority school"
          description="The school the system thinks unlocks the most downstream this week."
        >
          <CceoNextPrioritySchoolStrip />
        </CollapsibleCard>

        {/* Quick Actions + Momentum banner — closing surfaces. */}
        <CceoQuickActionsRow />
        <CceoMomentumBanner />
      </div>
    </>
  );

  return <ResponsiveDashboard mobile={mobile} desktop={desktop} />;
}
