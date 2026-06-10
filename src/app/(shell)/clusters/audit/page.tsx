import { PageHeader } from "@/components/ui/PageHeader";
import { ClusterAuditTrailView } from "@/components/cluster/ClusterAuditTrailView";

export default async function ClusterAuditPage() {
  return (
    <>
      <PageHeader
        title="Cluster Audit Trail"
        subtitle="Append-only history of every cluster mutation — creations, school moves, IA corrections, partner handoffs."
        dateLabel="Activity"
        backFallbackHref="/clusters"
      />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 space-y-4">
        <ClusterAuditTrailView />
      </div>
    </>
  );
}
