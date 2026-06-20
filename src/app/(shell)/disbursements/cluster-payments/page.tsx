import { Banknote } from "lucide-react";
import { TitleRegister } from "@/components/shell/TitleRegister";
import PartnerClusterPaymentsQueue, {
  type PartnerClusterPaymentVM,
} from "@/components/cluster/PartnerClusterPaymentsQueue";
import {
  StaffClusterAccountabilityQueue,
  type StaffAccountabilityVM,
} from "@/components/cluster/StaffClusterAccountabilityQueue";
import {
  CLUSTER_MEETING_LABEL,
  clusterById,
  partnerClusterPaymentsReady,
  staffClusterAccountabilityPending,
} from "@/lib/cluster/cluster-core";
import { isMockAllowed } from "@/lib/mock-policy";

export default async function PartnerClusterPaymentsPage() {
  // These finance queues derive from the in-memory cluster-meeting fixtures
  // (no backend cluster-payments endpoint yet). Outside dev they resolve to
  // empty so the accountant never sees fabricated payments — the queues render
  // their own "nothing awaiting clearance" empty state.
  const mockOk = isMockAllowed();
  const items: PartnerClusterPaymentVM[] = (mockOk ? partnerClusterPaymentsReady() : []).map((m) => {
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

  const staffItems: StaffAccountabilityVM[] = (mockOk ? staffClusterAccountabilityPending() : []).map((m) => {
    const cluster = clusterById(m.clusterId);
    return {
      id: m.id,
      clusterName: cluster?.name ?? "Unknown cluster",
      district: cluster?.district ?? "—",
      label: CLUSTER_MEETING_LABEL[m.kind],
      date: m.date,
      salesforceTrainingId: m.salesforceTrainingId,
      total: m.totalParticipants ?? 0,
      responsible: m.completedBy ?? m.scheduledBy,
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
        <h2 className="text-[14px] font-extrabold tracking-tight">Partner payments</h2>
        <p className="muted text-[12px]">
          The accountant can only clear a partner cluster payment after IA has
          confirmed the activity. Every item below is already IA-confirmed and
          awaiting finance clearance.
        </p>
        <PartnerClusterPaymentsQueue items={items} />
      </section>

      <section className="card rounded-2xl p-4 space-y-3">
        <h2 className="text-[14px] font-extrabold tracking-tight">Staff Netsuite accountability</h2>
        <p className="muted text-[12px]">
          Staff-managed cluster activities that are IA-confirmed and awaiting
          Netsuite accountability. Record the Netsuite Expense ID to close each.
        </p>
        <StaffClusterAccountabilityQueue items={staffItems} />
      </section>
    </div>
  );
}
