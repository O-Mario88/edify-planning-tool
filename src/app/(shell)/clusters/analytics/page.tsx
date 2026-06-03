import { TitleRegister } from "@/components/shell/TitleRegister";
import { ClusterAnalyticsView } from "@/components/cluster/ClusterAnalyticsView";

export default async function ClusterAnalyticsPage() {
  return (
    <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 space-y-4">
      <TitleRegister title="Cluster Analytics" dateLabel="Live" />
      <ClusterAnalyticsView />
    </div>
  );
}
