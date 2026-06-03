import { Banknote } from "lucide-react";
import { TitleRegister } from "@/components/shell/TitleRegister";
import PartnerClusterPaymentsQueue, {
  type PartnerClusterPaymentVM,
} from "@/components/cluster/PartnerClusterPaymentsQueue";
import {
  CLUSTER_MEETING_LABEL,
  clusterById,
  partnerClusterPaymentsReady,
} from "@/lib/cluster/cluster-core";

export default async function PartnerClusterPaymentsPage() {
  const items: PartnerClusterPaymentVM[] = partnerClusterPaymentsReady().map((m) => {
    const cluster = clusterById(m.clusterId);
    return {
      id: m.id,
      partner: cluster?.managedByPartnerName ?? m.organizer,
      clusterName: cluster?.name ?? "Unknown cluster",
      district: cluster?.district ?? "—",
      label: CLUSTER_MEETING_LABEL[m.kind],
      date: m.date,
      salesforceTrainingId: m.salesforceTrainingId,
      total: m.totalParticipants ?? 0,
      iaConfirmedAt: m.iaConfirmedAt,
    };
  });

  return (
    <div className="px-4 sm:px-5 md:px-6 pt-4 pb-12 space-y-4">
      <TitleRegister title="Partner Cluster Payments" dateLabel="Finance" />

      <div className="flex items-center gap-2">
        <span className="text-[var(--color-edify-primary)]">
          <Banknote className="h-4 w-4" />
        </span>
        <h1 className="text-[18px] font-extrabold tracking-tight">
          Partner Cluster Payments
        </h1>
      </div>

      <section className="card rounded-2xl p-4 space-y-3">
        <p className="muted text-[12px]">
          The accountant can only clear a partner cluster payment after IA has
          confirmed the activity. Every item below is already IA-confirmed and
          awaiting finance clearance.
        </p>
        <PartnerClusterPaymentsQueue items={items} />
      </section>
    </div>
  );
}
