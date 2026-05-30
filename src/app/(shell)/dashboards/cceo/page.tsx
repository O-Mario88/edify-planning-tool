import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DebriefPromoterCard } from "@/components/debrief/DebriefPromoterCard";
import { CceoSixKpiRow } from "@/components/cceo/CceoSixKpiRow";
import { CceoKpiStrip } from "@/components/cceo/CceoKpiStrip";
import { CoreServicePackageCard } from "@/components/cceo/CoreServicePackageCard";
import { SsaQualityCard } from "@/components/cceo/SsaQualityCard";
import { CoreSchoolsNeedingAttentionCard } from "@/components/cceo/CoreSchoolsNeedingAttentionCard";
import { CceoMonthPlannerCard } from "@/components/cceo/CceoMonthPlannerCard";
import { CceoMonthlyActivityBreakdownCard } from "@/components/cceo/CceoMonthlyActivityBreakdownCard";
import { CceoSalesforceQueueCard } from "@/components/cceo/CceoSalesforceQueueCard";
import { CceoRouteOpportunitiesCard } from "@/components/cceo/CceoRouteOpportunitiesCard";
import { CceoClusterScheduleCard } from "@/components/cceo/CceoClusterScheduleCard";
import { CceoNextPrioritySchoolStrip } from "@/components/cceo/CceoNextPrioritySchoolStrip";
import { CceoQuickActionsRow } from "@/components/cceo/CceoQuickActionsRow";
import { CceoMomentumBanner } from "@/components/cceo/CceoMomentumBanner";
import { SectionHeader } from "@/components/ui/SectionHeader";

// CCEO Operating View Dashboard.
//
// Narrative spine — five strategic chapters that give the page a story
// instead of a stack of cards:
//
//   1. (no header) DebriefPromoter — the day's status nudge
//   2. THIS WEEK    — KPIs + health funnel + Service Package
//   3. AT RISK      — Schools needing a CCEO this week (full width)
//   4. OPERATIONS   — Quality, Salesforce queue, cluster schedule
//   5. SCHEDULE     — Month planner, activity breakdown, route ops
//   6. PRIORITY     — Next priority school spotlight
//   7. (no header) Quick Actions + Momentum Banner
//
// Long-content cards (Best Performing, Needing Attention, Salesforce
// Queue, Route Opportunities, Cluster Schedule) scroll *inside* the
// card so they never distort row heights.

export default async function CceoDashboardPage() {
  // DashboardHeroServer retired per global hero removal pass.
  const mobile = (
    <div className="min-h-screen bg-[var(--color-page)] flex flex-col">
      <DashboardPageHeader role="CCEO" />
      <main className="flex-1 px-3 sm:px-4 pt-3 pb-28 space-y-3">
        <DebriefPromoterCard submitterRole="CCEO" />
        <CceoSixKpiRow />
        <CceoKpiStrip />
        <CoreServicePackageCard />
        <SsaQualityCard />
        <CoreSchoolsNeedingAttentionCard />
        <CceoMonthPlannerCard />
        <CceoMonthlyActivityBreakdownCard />
        <CceoSalesforceQueueCard />
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
        <DebriefPromoterCard submitterRole="CCEO" />

        {/* THIS WEEK — vital signs.  KPI tiles + health funnel + service. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="This Week"
            title="Where you are"
            description="Headline KPIs, school-health distribution, and your service-package progress at a glance."
          />
          <CceoSixKpiRow />
          <CceoKpiStrip />
          <CoreServicePackageCard />
        </section>

        {/* AT RISK — schools that need a CCEO visit / call. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="At risk"
            title="Schools that need a CCEO this week"
            description="Ranked by health-score drop, missed visits, and overdue SSA."
          />
          <CoreSchoolsNeedingAttentionCard />
        </section>

        {/* OPERATIONS — quality, Salesforce queue, cluster schedule. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Operations"
            title="Quality, queues, and clusters"
            description="SSA quality drift, what's waiting in Salesforce, and the cluster timetable."
          />
          <div className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
            <div className="col-span-12 lg:col-span-4">
              <SsaQualityCard />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <CceoSalesforceQueueCard />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <CceoClusterScheduleCard />
            </div>
          </div>
        </section>

        {/* SCHEDULE — month planner + activity breakdown + routes. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Schedule"
            title="What's planned across the month"
            description="Visit cadence, activity mix, and route opportunities for the days ahead."
          />
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
        </section>

        {/* PRIORITY — next priority school spotlight. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Priority"
            title="Next priority school"
            description="The school the system thinks unlocks the most downstream this week."
          />
          <CceoNextPrioritySchoolStrip />
        </section>

        {/* Quick Actions + Momentum banner — closing surfaces, no
            chapter header (each is its own self-contained surface). */}
        <CceoQuickActionsRow />
        <CceoMomentumBanner />
      </div>
    </>
  );

  return <ResponsiveDashboard mobile={mobile} desktop={desktop} />;
}
