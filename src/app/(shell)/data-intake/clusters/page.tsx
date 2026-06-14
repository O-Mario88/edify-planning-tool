import { PageHeader } from "@/components/ui/PageHeader";
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
import { getCurrentUser } from "@/lib/auth";
import { isBackendEnabled } from "@/lib/api/backend";
import { fetchActivities, type BeActivity } from "@/lib/api/surfaces";

// Readable label for a backend cluster activity (activityType is the raw enum).
function backendClusterLabel(a: BeActivity): string {
  if (a.activityType === "cluster_meeting") return "Cluster Meeting";
  if (a.activityType === "cluster_training") return "Cluster Training";
  return a.activityType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Map backend awaiting-IA cluster activities into the confirmation VM. Counts /
// minutes / file flags aren't surfaced on the activity row (they live on the
// evidence records), so they default — the IA confirm action only needs the id
// + Salesforce ID, both of which are present.
function fromBackend(rows: BeActivity[]): IaClusterConfirmationVM[] {
  return rows
    .filter((a) => a.cluster != null)
    .map((a) => ({
      id: a.id,
      label: backendClusterLabel(a),
      clusterName: a.cluster?.name ?? "Cluster",
      district: a.school?.district?.name ?? "—",
      date: a.scheduledDate ?? "",
      organizer: a.deliveryType === "partner" ? "partner" : "edify",
      managedByPartnerName: a.assignedPartner?.name,
      completedBy: undefined,
      salesforceTrainingId: a.salesforceActivityId ?? "",
      salesforceIdValid: isValidTsId(a.salesforceActivityId ?? ""),
      teachers: 0,
      leaders: 0,
      other: 0,
      total: 0,
      hasMinutes: false,
      hasResolutions: false,
      attendanceFileName: undefined,
      nextMeetingDate: undefined,
    }));
}

function fromMock(): IaClusterConfirmationVM[] {
  return clusterActivitiesAwaitingIa().map((m) => {
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
  });
}

export default async function ClusterQualityPage() {
  // Backend-first: read the awaiting-IA cluster activities from Postgres so the
  // queue reflects backend-completed cluster meetings (the in-memory store only
  // holds mock-id activities, so the IA never saw real cluster work to confirm).
  let confirmations: IaClusterConfirmationVM[];
  if (isBackendEnabled()) {
    const user = await getCurrentUser();
    const r = await fetchActivities(
      { email: user.email, role: user.role },
      "?status=awaiting_ia_verification&pageSize=200",
    );
    confirmations = r.live ? fromBackend(r.data.data) : fromMock();
  } else {
    confirmations = fromMock();
  }

  return (
    <>
      <PageHeader
        title="Cluster Quality"
        subtitle="IA confirmation queue for completed cluster meetings, plus data-quality checks across the cluster register."
        dateLabel="IA"
        backFallbackHref="/data-intake"
      />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 space-y-4">
        <IaClusterConfirmationQueue items={confirmations} />
        <IaClusterQualityQueue />
      </div>
    </>
  );
}
