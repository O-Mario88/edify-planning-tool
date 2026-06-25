import { notFound } from "next/navigation";
import { Network, MapPin, User } from "lucide-react";
import { EntityDetail, DetailFacts } from "@/components/shell/EntityDetail";
import { clustersMock } from "@/lib/schools-mock";
import { orgStaff } from "@/lib/org/supervision";
import { PageHeader } from "@/components/ui/PageHeader";
import { ClusterProfileView } from "@/components/cluster/ClusterProfileView";
import { ClusterMemberSchoolsLive } from "@/components/cluster/ClusterMemberSchoolsLive";
import { ClusterIntelligencePanel } from "@/components/cluster/ClusterIntelligencePanel";
import { clusterProfile, clusterById, activeClusters, CLUSTER_MEETING_LABEL, feedbackForCluster, CLUSTER_FEEDBACK_LABEL, meetingsForCluster, schoolsInCluster } from "@/lib/cluster/cluster-core";
import { getCurrentUser } from "@/lib/auth";
import { isBackendEnabled } from "@/lib/api/backend";
import { fetchClusters } from "@/lib/api/surfaces";
import { getCurrentPartner } from "@/lib/partner/partner-identity";
import { NextActionCard } from "@/components/next-action/NextActionCard";
import { nextActionForCluster } from "@/lib/next-action/next-action";
import { unifiedActivitiesForCluster } from "@/lib/activity/unified-activity-source";
import { historyFor } from "@/lib/planning/ssa-performance-mock";
import { computeClusterIntelligence, type ClusterIntelActivity, type ClusterIntelSchool } from "@/lib/cluster/cluster-intelligence";
import type { SsaInterventionArea } from "@/lib/planning/planning-gaps-mock";

export default async function ClusterDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  // Engine cluster (CLU-*) → the real, performance-computed profile. Falls
  // through to the legacy clustersMock detail for old saved-group ids.
  if (clusterById(id)) {
    return <EngineClusterProfile clusterId={id} />;
  }

  // Backend cuid: the live planning-gap "Schedule" links point at real Postgres
  // cluster cuids that neither the engine store nor clustersMock resolve — the
  // page used to 404 on every real cluster. Resolve it from the live clusters
  // list (no dedicated /clusters/:id header endpoint yet) + show live schools.
  if (isBackendEnabled()) {
    const user = await getCurrentUser();
    const r = await fetchClusters({ email: user.email, role: user.role });
    const be = r.live ? r.data.find((c) => c.id === id) : undefined;
    if (be) {
      return (
        <EntityDetail
          breadcrumbs={[
            { label: "Home", href: "/dashboard" },
            { label: "Clusters", href: "/clusters" },
            { label: be.name },
          ]}
          title={be.name}
          subtitle="Cluster of schools for grouped planning + delivery."
          Icon={Network}
        >
          <DetailFacts
            rows={[
              { label: "Cluster ID", value: be.id },
              { label: "Type", value: be.clusterType ?? "—" },
              { label: "Status", value: be.status ?? "—" },
              { label: "District", value: be.district?.name ?? "—" },
              { label: "Sub-county", value: be.subCounty?.name ?? be.subCountyName ?? "—" },
              { label: "Leader", value: be.clusterLeaderName ?? "—" },
            ]}
          />
          <ClusterMemberSchoolsLive clusterId={be.id} />
        </EntityDetail>
      );
    }
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

  // Build the cluster intelligence inputs from the in-memory engine
  // store. The same compute function powers `/clusters/:id/intelligence`
  // on the backend, so the math is identical.
  const meetings = meetingsForCluster(clusterId);
  const memberSchools = schoolsInCluster(clusterId);
  const intelSchools: ClusterIntelSchool[] = memberSchools.map((s) => {
    const hist = historyFor(s.schoolId);
    const curr = hist[0];
    const prev = hist[1];
    const currScores: Partial<Record<SsaInterventionArea, number>> | undefined = curr
      ? Object.fromEntries(curr.scores.map((sc) => [sc.intervention, sc.score])) as Partial<Record<SsaInterventionArea, number>>
      : undefined;
    const prevScores: Partial<Record<SsaInterventionArea, number>> | undefined = prev
      ? Object.fromEntries(prev.scores.map((sc) => [sc.intervention, sc.score])) as Partial<Record<SsaInterventionArea, number>>
      : undefined;
    const hasCompletedTraining = meetings.some(
      (m) => (m.kind === "sit" || m.kind === "training" || m.kind === "cluster_training") &&
             (m.status === "IA Confirmed" || m.status === "Paid" || m.status === "Closed"),
    );
    const hasCompletedMeeting = meetings.some(
      (m) => m.kind !== "sit" && m.kind !== "training" && m.kind !== "cluster_training" &&
             (m.status === "IA Confirmed" || m.status === "Paid" || m.status === "Closed"),
    );
    return {
      schoolId: s.schoolId,
      schoolName: s.schoolName,
      schoolType: s.schoolType === "Core" ? "Core" : "Client",
      hasCurrentFySsa: s.ssaStatus === "SSA Done",
      currentSsa: currScores,
      previousSsa: prevScores,
      visitedThisPeriod: hasCompletedMeeting,
      trainedThisPeriod: hasCompletedTraining,
    };
  });
  const intelActivities: ClusterIntelActivity[] = meetings.map((m) => ({
    id: m.id,
    activityType: m.kind === "sit" ? "school_improvement_training"
                : m.kind === "training" || m.kind === "cluster_training" ? "cluster_training"
                : m.kind === "follow_up" ? "follow_up"
                : "cluster_meeting",
    date: m.date,
    status: m.status === "IA Confirmed" || m.status === "Paid" || m.status === "Closed" ? "Completed"
          : m.status === "Scheduled" || m.status === "Awaiting IA" ? "Scheduled"
          : "Other",
    teachersTrained: m.teachersCount,
    schoolLeadersTrained: m.schoolLeadersCount,
  }));
  const intel = computeClusterIntelligence({ schools: intelSchools, activities: intelActivities });

  const intelHistory = profile.activities.map((a) => ({
    id: a.id,
    title: CLUSTER_MEETING_LABEL[a.kind],
    type: (a.kind === "sit" ? "sit"
        : a.kind === "training" || a.kind === "cluster_training" ? "training"
        : a.kind === "follow_up" ? "follow_up"
        : "meeting") as "meeting" | "training" | "sit" | "follow_up" | "project_session",
    date: a.date,
    attendance: a.totalParticipants,
    teachersTrained: a.teachersCount,
    schoolLeadersTrained: a.schoolLeadersCount,
    evidenceStatus: a.evidenceUploaded ? "complete" : undefined,
    activityCode: a.salesforceTrainingId,
    iaStatus: a.iaConfirmedAt ? "verified" : a.status === "Awaiting IA" ? "pending" : undefined,
    resolutions: a.resolutionsText,
    nextActions: a.minutesText,
  }));
  const intelSchoolRows = memberSchools.map((s) => {
    const hist = historyFor(s.schoolId);
    const curr = hist[0];
    return {
      schoolId: s.schoolId,
      schoolName: s.schoolName,
      schoolType: (s.schoolType === "Core" ? "Core" : "Client") as "Client" | "Core" | "Potential Core",
      accountOwner: s.assignedCceo,
      ssaStatus: (s.ssaStatus === "SSA Done" ? "complete" : "missing") as "complete" | "missing" | "pending",
      latestSsa: curr?.averageScore,
      weakestIntervention: curr ? curr.scores.reduce((w, sc) => sc.score < w.score ? sc : w).intervention : undefined,
      visitStatus: ("not_visited") as "visited" | "not_visited",
      trainingStatus: ("not_trained") as "trained" | "not_trained",
    };
  });

  return (
    <>
      <PageHeader
        title={profile.cluster.name}
        dateLabel="Cluster"
        backFallbackHref="/clusters"
        breadcrumbTrailingLabel={profile.cluster.name}
      />
      <div className="px-4 sm:px-5 lg:px-6 pt-3 space-y-3">
        <NextActionCard
          action={nextActionForCluster(
            { hasSchools: profile.schools.length > 0, hasScheduledCycle: profile.meetingsScheduled > 0 },
            unifiedActivitiesForCluster(clusterId),
          )}
          title="Cluster next action"
        />

        <ClusterIntelligencePanel
          header={{
            id: profile.cluster.id,
            name: profile.cluster.name,
            district: profile.cluster.district,
            subCounties: profile.cluster.subCounties ?? [],
            region: profile.cluster.region,
            type: profile.managementType,
            cceoName: profile.cluster.clusterLeaderName,
            partnerName: profile.cluster.managedByPartnerName,
          }}
          intel={intel}
          history={intelHistory}
          schools={intelSchoolRows}
          scheduleHref={`/planning?cluster=${encodeURIComponent(clusterId)}`}
        />
      </div>
      <ClusterProfileView profile={vm} flags={flags} reassignTargets={reassignTargets} canReassign={staffRole} />
    </>
  );
}
