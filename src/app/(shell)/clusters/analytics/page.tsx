import { PageHeader } from "@/components/ui/PageHeader";
import { ClusterAnalyticsView } from "@/components/cluster/ClusterAnalyticsView";

export default async function ClusterAnalyticsPage() {
  return (
    <>
      <PageHeader
        title="Cluster Analytics"
        subtitle="Live truth surface over the cluster engine — coverage, SSA completion, staff vs partner delivery, district rollups."
        dateLabel="Live"
        backFallbackHref="/clusters"
      />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 space-y-4">
        <ClusterAnalyticsView />
      </div>
    </>
  );
}
