import { CommandStack } from "@/components/actions/CommandStack";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DonorImpactReachCard } from "@/components/director/DonorImpactReachCard";
import { getDonorMetricSnapshot } from "@/lib/donor-metrics";
import { ImpactKpiRow } from "@/components/impact/ImpactKpiRow";
import { ProgramOverviewCard } from "@/components/impact/ProgramOverviewCard";
import { DataVerificationFunnelCard } from "@/components/impact/DataVerificationFunnelCard";
import { DataQualityTrendChart } from "@/components/ui/lazy-charts";
import { QualityCheckStatusCard } from "@/components/ui/lazy-charts";
import { TopIssuesCard } from "@/components/impact/TopIssuesCard";
import { RecentDataUploadsCard } from "@/components/impact/RecentDataUploadsCard";
import { PartnerPerformanceCard } from "@/components/impact/PartnerPerformanceCard";
import { TrainingDataQualityCard } from "@/components/impact/TrainingDataQualityCard";
import { ImpactQuickActionsRow } from "@/components/impact/ImpactQuickActionsRow";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { QueueView } from "@/components/mobile/views/QueueView";
import { InsightStrip } from "@/components/insights/InsightCard";
import { IaPlanCard } from "@/components/planning/PlanCascadeCards";
import { ClusterReadinessCard } from "@/components/cluster/ClusterReadinessCard";
import { scopedClusterCounts } from "@/lib/cluster/cluster-scope";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { insightsForImpactAssessment } from "@/lib/insights";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { SsaPerformanceGrid } from "@/components/ssa/SsaPerformanceGrid";
import { InterventionImprovementGrid } from "@/components/ssa/InterventionImprovementGrid";

export default async function ImpactDashboard() {
  // Defense-in-depth: middleware already gates /dashboards/impact, but
  // the page re-checks so a guard gap can't expose this console.
  const user = await getCurrentUser();
  if (!["ImpactAssessment", "Admin"].includes(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }

  // The verification-first donor cut: which reach/training/impact figures
  // are donor-ready vs still pending M&E verification. Same builder as
  // /donor-reporting so IA's count and the published report never diverge.
  const donorSnapshot = getDonorMetricSnapshot({
    role: "ImpactAssessment",
    userName: user.name,
    generatedBy: user.name,
  });
  const clusterCounts = scopedClusterCounts(user.staffId, user.role);

  return (
    <ResponsiveDashboard
      mobile={
        <>
          <DashboardPageHeader role="ImpactAssessment" />
          <QueueView />
        </>
      }
      desktop={
        <>
          <DashboardPageHeader role="ImpactAssessment" />
          <div className="px-6 pb-24 md:pb-6 pt-4 space-y-5">
            {/* Section 1 — Today.  The unified action surface. */}
            <CommandStack user={user} hideMission />

            {/* SSA truth layer (IA scope) — performance + impact, backend-driven. */}
            <SsaPerformanceGrid />
            <InterventionImprovementGrid />

            {/* Section 2 — Vital signs.  Five KPIs + system insights. */}
            <section className="space-y-3">
              <SectionHeader
                tier="strategic"
                eyebrow="This Period"
                title="Vital Signs"
                description="The five numbers leadership reads first, plus what the system is noticing right now."
              />
              <ImpactKpiRow />
              <ClusterReadinessCard clustered={clusterCounts.clustered} unclustered={clusterCounts.unclustered} needsReview={clusterCounts.needsReview} title="Cluster setup quality" hrefAll="/data-intake/clusters" />
              <InsightStrip insights={insightsForImpactAssessment()} />
            </section>

            {/* Section 3 — Verification.  The strategic #2.
                Plan card (what's expected) + Program Overview (counts
                by program) + Verification Funnel (terminal states). */}
            <section className="space-y-3">
              <SectionHeader
                tier="strategic"
                eyebrow="Verification"
                title="What's Flowing Through the Pipe"
                description="From plan to upload to verification — where every record sits today."
              />
              <IaPlanCard />
              <div className="grid grid-cols-12 gap-4 items-stretch">
                {/* `flex flex-col` (not `flex` alone) is critical at tablet:
                    when the wrapper is `col-span-12`, row-direction flex
                    shrinks the article to its content min-width, leaving
                    a half-empty row. Column direction stretches it. */}
                <div className="col-span-12 lg:col-span-8 flex flex-col">
                  <ProgramOverviewCard />
                </div>
                <div className="col-span-12 lg:col-span-4 flex flex-col">
                  <DataVerificationFunnelCard />
                </div>
              </div>
            </section>

            {/* Section 3b — Donor-ready counts.  The verified output of
                the pipeline above: what M&E can sign off for donors. */}
            <section className="space-y-3">
              <SectionHeader
                tier="strategic"
                eyebrow="Donor-ready"
                title="What's Cleared for Donor Reporting"
                description="The reach, training, and improvement figures verification has signed off — pending records stay flagged and out of the headline totals. Each tile opens the full report."
              />
              <DonorImpactReachCard snapshot={donorSnapshot} />
            </section>

            {/* Section 4 — Quality & partners.  Operational rhythm.
                Columns rebalanced to eliminate the ~660px gap that the
                old layout left under the left rail:
                  • LEFT  (8 cols): Trend → Uploads → Partner Performance
                  • RIGHT (4 cols): Quality issues → Training → Top issues
                Heights now match within ~30px so the section reads as
                two parallel rails of equivalent weight. */}
            <section className="space-y-3">
              <SectionHeader
                tier="strategic"
                eyebrow="Quality & Partners"
                title="Where Attention Is Needed"
                description="Data-quality drift, partner performance, and the training evidence backing every reported metric."
              />
              <div className="grid grid-cols-12 gap-4 items-start">
                <div className="col-span-12 lg:col-span-8 space-y-4">
                  <DataQualityTrendChart />
                  <RecentDataUploadsCard />
                  <PartnerPerformanceCard />
                </div>
                <div className="col-span-12 lg:col-span-4 space-y-4">
                  <QualityCheckStatusCard />
                  <TrainingDataQualityCard />
                  <TopIssuesCard />
                </div>
              </div>
            </section>

            {/* Section 5 — Page tools.  Demoted utility footer. */}
            <ImpactQuickActionsRow />
          </div>
        </>
      }
    />
  );
}
