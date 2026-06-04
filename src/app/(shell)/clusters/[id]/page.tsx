import Link from "next/link";
import { notFound } from "next/navigation";
import {
  Network,
  MapPin,
  Building2,
  User,
  Calendar,
  School,
  ChevronRight,
} from "lucide-react";
import { EntityDetail, DetailKpi, DetailFacts } from "@/components/shell/EntityDetail";
import { clustersMock, schoolsMock } from "@/lib/schools-mock";
import { orgStaff } from "@/lib/org/supervision";
import { TitleRegister } from "@/components/shell/TitleRegister";
import { ClusterProfileView } from "@/components/cluster/ClusterProfileView";
import { clusterProfile, clusterById, activeClusters, CLUSTER_MEETING_LABEL, feedbackForCluster, CLUSTER_FEEDBACK_LABEL } from "@/lib/cluster/cluster-core";
import { getCurrentUser } from "@/lib/auth";
import { getCurrentPartner } from "@/lib/partner/partner-identity";

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

  const schools = cluster.schoolIds
    .map((sid) => schoolsMock.find((s) => s.schoolId === sid))
    .filter((s): s is NonNullable<typeof s> => Boolean(s));
  const avgSsa = schools.length
    ? Math.round((schools.reduce((a, s) => a + s.ssaScore, 0) / schools.length) * 10) / 10
    : 0;
  const verified = schools.filter((s) => s.ssaStatus === "Completed").length;

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
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DetailKpi label="Member Schools" value={String(schools.length)} caption="In this cluster" Icon={School}   tone="edify"  />
        <DetailKpi label="Avg SSA"        value={`${avgSsa}%`}            caption="Across members" Icon={Calendar} tone={avgSsa >= 70 ? "green" : avgSsa >= 50 ? "amber" : "rose"} />
        <DetailKpi label="SSA Completed"  value={`${verified}/${schools.length}`} caption="Verified"   Icon={Building2} tone="violet" />
        <DetailKpi label="Owner"           value={ownerName} caption="Assigned CCEO" Icon={User} tone="edify" />
      </section>

      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        <div className="col-span-12 md:col-span-5">
          <DetailFacts
            rows={[
              { label: "Cluster ID",        value: cluster.id },
              { label: "Region",            value: cluster.region ?? "—" },
              { label: "District",          value: cluster.district ?? "—" },
              { label: "Shipping Address",  value: <span className="inline-flex items-center gap-1.5"><MapPin size={12} />{cluster.shippingAddress ?? "—"}</span> },
              { label: "Created",           value: cluster.createdAt },
            ]}
          />
        </div>
        <div className="col-span-12 md:col-span-7 card rounded-2xl overflow-hidden">
          <header className="px-4 pt-3.5 pb-2 flex items-baseline justify-between">
            <h3 className="text-[13px] font-extrabold tracking-tight">Member Schools</h3>
            <Link href="/schools" className="text-[11px] font-semibold text-[var(--color-edify-primary)]">View All schools →</Link>
          </header>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {schools.map((s) => (
              <li key={s.schoolId}>
                <Link
                  href={`/schools/${s.schoolId}`}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--color-edify-soft)]/40"
                >
                  <span className="h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                    <Building2 size={14} />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-body font-extrabold tracking-tight truncate">{s.schoolName}</div>
                    <div className="text-caption muted truncate">{s.district} · {s.region} · SSA {s.ssaScore}%</div>
                  </div>
                  <span className={`px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap ${s.ssaStatus === "Completed" ? "bg-emerald-100 text-emerald-700" : s.ssaStatus === "Overdue" ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-700"}`}>
                    {s.ssaStatus}
                  </span>
                  <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>
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
      <TitleRegister title={profile.cluster.name} dateLabel="Cluster" />
      <ClusterProfileView profile={vm} flags={flags} reassignTargets={reassignTargets} canReassign={staffRole} />
    </>
  );
}
