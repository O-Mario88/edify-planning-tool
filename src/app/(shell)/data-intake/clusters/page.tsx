import { TitleRegister } from "@/components/shell/TitleRegister";
import IaClusterQualityQueue from "@/components/cluster/IaClusterQualityQueue";

export default async function ClusterQualityPage() {
  return (
    <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 space-y-4">
      <TitleRegister title="Cluster Quality" dateLabel="IA" />
      <IaClusterQualityQueue />
    </div>
  );
}
