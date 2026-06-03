import { TitleRegister } from "@/components/shell/TitleRegister";
import { ClusterAuditTrailView } from "@/components/cluster/ClusterAuditTrailView";

export default async function ClusterAuditPage() {
  return (
    <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 space-y-4">
      <TitleRegister title="Cluster Audit Trail" dateLabel="Activity" />
      <ClusterAuditTrailView />
    </div>
  );
}
