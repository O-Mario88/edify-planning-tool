import { notFound } from "next/navigation";
import { Network, MapPin, User } from "lucide-react";
import { EntityDetail, DetailFacts } from "@/components/shell/EntityDetail";
import { clustersMock } from "@/lib/schools-mock";
import { orgStaff } from "@/lib/org/supervision";
import { PageHeader } from "@/components/ui/PageHeader";
import { ClusterProfileView } from "@/components/cluster/ClusterProfileView";
import { ClusterMemberSchoolsLive } from "@/components/cluster/ClusterMemberSchoolsLive";
import { clusterProfile, clusterById, activeClusters, CLUSTER_MEETING_LABEL, feedbackForCluster, CLUSTER_FEEDBACK_LABEL } from "@/lib/cluster/cluster-core";
import { getCurrentUser } from "@/lib/auth";
import { getCurrentPartner } from "@/lib/partner/partner-identity";
import { NextActionCard } from "@/components/next-action/NextActionCard";
import { nextActionForCluster } from "@/lib/next-action/next-action";
import { unifiedActivitiesForCluster } from "@/lib/activity/unified-activity-source";

export default async function ClusterDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  // Engine cluster (CLU-*) → the real, performance-computed profile. Falls
  // through to the legacy clustersMock detail for old saved-group ids.
  if (clusterById(id)) {
    return <EngineClusterProfile clusterId={id} />;
  }

  const cluster = clustersMock.find((c) => c.id === id);
  if (!cluster) return notFound();

  // Account owner is a CCEO — show the name, not the raw staffId. Falls back
  // to the stored value if the id isn't on the roster.
  const ownerName = orgStaff(cluster.ownerCceoId)?.name ?? cluster.ownerCceoId;

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",     href: "/dashboard" },
        { label: "Clusters", href: "/clusters" },
        { label: cluster.name },
      ]}
      title={cluster.name}
      subtitle={cluster.description ?? "Cluster of schools for grouped planning + delivery."}
      Icon={Network}
    >
      <DetailFacts
        rows={[
          { label: "Cluster ID",        value: cluster.id },
          { label: "Owner",             value: <span className="inline-flex items-center gap-1.5"><User size={12} />{ownerName}</span> },
          { label: "Region",            value: cluster.region ?? "—" },
          { label: "District",          value: cluster.district ?? "—" },
          { label: "Shipping Address",  value: <span className="inline-flex items-center gap-1.5"><MapPin size={12} />{cluster.shippingAddress ?? "—"}</span> },
          { label: "Created",           value: cluster.createdAt },
        ]}
      />

      <ClusterMemberSchoolsLive clusterId={cluster.id} />
    </EntityDetail>
  );
}

// ── Engine cluster profile (the location-based school group) ────────
async function EngineClusterProfile({ clusterId }: { clusterId: string }) {
  const profile = clusterProfile(clusterId);
  if (!profile) return notFound();
  const user = await getCurrentUser();
  const partner = await getCurrentPartner();

  const staffRole = ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"].includes(user.role);
  const isManagingPartner = !!partner && profile.cluster.managedByPartnerId === partner.id;
  const flags = {
    canRecord: staffRole || isManagingPartner,
    canIa: ["ImpactAssessment", "Admin"].includes(user.role),
    canPay: ["ProgramAccountant", "Admin"].includes(user.role),
    canReturn: staffRole,
  };

  const vm = {
    id: profile.cluster.id,
    name: profile.cluster.name,
    district: profile.cluster.district,
    subCounties: profile.cluster.subCounties ?? [],
    region: profile.cluster.region,
    managementType: profile.managementType,
    partnerName: profile.cluster.managedByPartnerName,
    leaderName: profile.cluster.clusterLeaderName,
    leaderPhone: profile.cluster.clusterLeaderPhone,
    clientCount: profile.clientCount,
    coreCount: profile.coreCount,
    schoolCount: profile.schools.length,
    ssaDone: profile.ssaDone,
    ssaMissing: profile.ssaMissing,
    ssaCompletionRate: profile.ssaCompletionRate,
    meetingsCompleted: profile.meetingsCompleted,
    meetingsScheduled: profile.meetingsScheduled,
    attendanceTotal: profile.attendanceTotal,
    teachersReached: profile.teachersReached,
    schoolLeadersReached: profile.schoolLeadersReached,
    paymentsReady: profile.paymentsReady,
    paymentsPaid: profile.paymentsPaid,
    schools: profile.schools.map((s) => ({ schoolId: s.schoolId, schoolName: s.schoolName, schoolType: s.schoolType, ssaStatus: s.ssaStatus })),
    activities: profile.activities.map((a) => ({
      id: a.id, kind: a.kind, label: CLUSTER_MEETING_LABEL[a.kind], date: a.date,
      organizer: a.organizer, status: a.status, salesforceTrainingId: a.salesforceTrainingId,
      teachers: a.teachersCount, leaders: a.schoolLeadersCount, total: a.totalParticipants,
      iaConfirmedAt: a.iaConfirmedAt, paidAt: a.accountantPaidAt, returnedReason: a.returnedReason,
      nextMeetingDate: a.nextMeetingDate, minutesText: a.minutesText, resolutionsText: a.resolutionsText,
      netsuiteExpenseId: a.netsuiteExpenseId,
    })),
    feedback: feedbackForCluster(profile.cluster.id).map((f) => ({
      id: f.id,
      label: CLUSTER_FEEDBACK_LABEL[f.feedbackType],
      by: `${f.submittedBy} (${f.submittedByRole})`,
      date: f.createdAt,
      whatWentWell: f.whatWentWell,
      challenges: f.challenges,
      recommendations: f.recommendations,
      rating: f.rating,
    })),
  };

  // Reassignment targets: every other active cluster. CCEO/PL own cluster
  // assignment; IA/CD/Admin may correct it.
  const reassignTargets = activeClusters()
    .filter((c) => c.id !== clusterId)
    .map((c) => ({ id: c.id, name: c.name, district: c.district }));

  return (
    <>
      <PageHeader
        title={profile.cluster.name}
        dateLabel="Cluster"
        backFallbackHref="/clusters"
        breadcrumbTrailingLabel={profile.cluster.name}
      />
      <div className="px-4 sm:px-5 lg:px-6 pt-3">
        <NextActionCard
          action={nextActionForCluster(
            { hasSchools: profile.schools.length > 0, hasScheduledCycle: profile.meetingsScheduled > 0 },
            unifiedActivitiesForCluster(clusterId),
          )}
          title="Cluster next action"
        />
      </div>
      <ClusterProfileView profile={vm} flags={flags} reassignTargets={reassignTargets} canReassign={staffRole} />
    </>
  );
}
