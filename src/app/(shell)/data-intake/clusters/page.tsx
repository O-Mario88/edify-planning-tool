import { TitleRegister } from "@/components/shell/TitleRegister";
import IaClusterQualityQueue from "@/components/cluster/IaClusterQualityQueue";
import IaClusterConfirmationQueue, {
  type IaClusterConfirmationVM,
} from "@/components/cluster/IaClusterConfirmationQueue";
import {
  CLUSTER_MEETING_LABEL,
  clusterActivitiesAwaitingIa,
  clusterById,
  isValidTsId,
} from "@/lib/cluster/cluster-core";

export default async function ClusterQualityPage() {
  const confirmations: IaClusterConfirmationVM[] = clusterActivitiesAwaitingIa().map(
    (m) => {
      const cluster = clusterById(m.clusterId);
      return {
        id: m.id,
        label: CLUSTER_MEETING_LABEL[m.kind],
        clusterName: cluster?.name ?? "Unknown cluster",
        district: cluster?.district ?? "—",
        date: m.date,
        organizer: m.organizer,
        managedByPartnerName: cluster?.managedByPartnerName,
        completedBy: m.completedBy,
        salesforceTrainingId: m.salesforceTrainingId,
        salesforceIdValid: isValidTsId(m.salesforceTrainingId),
        teachers: m.teachersCount ?? 0,
        leaders: m.schoolLeadersCount ?? 0,
        other: m.otherCount ?? 0,
        total: m.totalParticipants ?? 0,
        hasMinutes: Boolean(m.minutesText && m.minutesText.trim()),
        hasResolutions: Boolean(m.resolutionsText && m.resolutionsText.trim()),
        attendanceFileName: m.attendanceFileName,
        nextMeetingDate: m.nextMeetingDate,
      };
    },
  );

  return (
    <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 space-y-4">
      <TitleRegister title="Cluster Quality" dateLabel="IA" />
      <IaClusterConfirmationQueue items={confirmations} />
      <IaClusterQualityQueue />
    </div>
  );
}
