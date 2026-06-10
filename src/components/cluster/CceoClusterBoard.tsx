// CceoClusterBoard — the CCEO's cluster / parish-fellowship view (spec §11).
//
// Scope: only clusters containing the viewer's assigned schools (portfolio via
// directoryRecords → school.clusterId). Per cluster the card answers the three
// fellowship questions in one glance — who is in it (schools, SSA coverage),
// what to discuss next (two weakest cluster interventions + recommended topics
// from the SSA-averages topic engine), and when we meet (next scheduled cluster
// meeting, or a schedule action into the cluster profile's meeting scheduler).
//
// Spiritual-transformation integration (spec §14) comes free from the engine:
// when Christlike Behaviour / Exposure to the Word of God are the weakest
// interventions, CLUSTER_DISCUSSION_TOPICS words the topic as discipleship /
// spiritual-life facilitation.
//
// The member-school list is detail-heavy, so it folds behind a native
// <details> (server-rendered, zero client JS) per the CollapsibleCard rule:
// collapse the detail list, never the summary card itself.

import Link from "next/link";
import {
  CalendarPlus,
  ChevronDown,
  HeartHandshake,
  MapPin,
  Phone,
  UserRound,
} from "lucide-react";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Pill, type PillTone } from "@/components/ui/Pill";
import type { EdifyRole } from "@/lib/auth";
import { directoryRecords } from "@/lib/school-directory/directory";
import {
  clusterMeetingRecommendationsForSchools,
  type ClusterMeetingRecommendation,
} from "@/lib/cluster/cluster-meeting-recommendations";
import { schoolsInCluster, clusterStatusOf } from "@/lib/cluster/cluster-core";
import {
  recommendInterventionsForSchool,
  type Severity,
} from "@/lib/planning/intervention-recommendation";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { cn } from "@/lib/utils";

const SEVERITY_PILL: Record<Severity, PillTone> = {
  Critical: "danger",
  "Needs Support": "warning",
  Good: "success",
  Strong: "violet",
};

function avgTone(avg: number | null): string {
  if (avg == null) return "text-slate-500";
  if (avg < 5) return "text-rose-600";
  if (avg < 7) return "text-amber-600";
  return "text-emerald-600";
}

export function CceoClusterBoard({
  staffId,
  role,
}: {
  staffId: string;
  role: EdifyRole;
}) {
  const portfolio = directoryRecords(staffId, role);
  const recs = clusterMeetingRecommendationsForSchools(portfolio);

  return (
    <section aria-label="My clusters" className="space-y-3">
      <SectionHeader
        tier="operational"
        icon={<HeartHandshake size={15} className="text-[var(--color-edify-primary)]" />}
        title="My Clusters — parish fellowships"
        description="Clusters containing your schools. Each card shows SSA coverage, the two weakest interventions, and what to facilitate at the next gathering."
        meta={
          <Pill tone="neutral" size="sm">
            {recs.length} {recs.length === 1 ? "cluster" : "clusters"}
          </Pill>
        }
      />

      {recs.length === 0 ? (
        <div className="card rounded-2xl p-4">
          <p className="text-[12.5px] muted">
            None of your schools belongs to a cluster yet. Assign them from the
            cluster directory below — clustering is the next required setup step.
          </p>
        </div>
      ) : (
        recs.map((c) => <ClusterCard key={c.clusterId} rec={c} viewerStaffId={staffId} />)
      )}
    </section>
  );
}

function ClusterCard({
  rec: c,
  viewerStaffId,
}: {
  rec: ClusterMeetingRecommendation;
  viewerStaffId: string;
}) {
  const members = schoolsInCluster(c.clusterId);
  const needsReview = members.some((s) => clusterStatusOf(s) === "needs_review");

  return (
    <article className="card rounded-2xl p-4">
      {/* ── Collapsed summary: who · how healthy · what next ── */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <h3 className="text-[14px] font-extrabold tracking-tight">{c.clusterName}</h3>
        <span className="inline-flex items-center gap-1 text-[11.5px] muted">
          <MapPin size={11} aria-hidden />
          {c.district}
          {c.subCounty ? ` · ${c.subCounty}` : ""}
        </span>
        <Pill tone={needsReview ? "warning" : "success"} size="xs" dot>
          {needsReview ? "Needs review" : "Active"}
        </Pill>
        {c.managedByPartnerName && (
          <Pill tone="info" size="xs" subtle>
            Partner: {c.managedByPartnerName}
          </Pill>
        )}
        <span className={cn("ml-auto text-[13px] font-extrabold tabular", avgTone(c.overallAverage))}>
          {c.overallAverage != null ? `${c.overallAverage.toFixed(1)}/10` : "no SSA"}
        </span>
      </div>

      <p className="mt-1 text-[11.5px] muted">
        {c.schools} {c.schools === 1 ? "school" : "schools"} · {c.schoolsWithSsa} with
        current-FY SSA
        {c.schoolsMissingSsa > 0 ? ` · ${c.schoolsMissingSsa} missing SSA` : ""}
      </p>

      {/* ── Two weakest interventions + recommended discussion topics ── */}
      {c.weakest.length === 0 ? (
        <p className="mt-2 text-[12px] muted leading-snug">
          {c.schools === 0
            ? "No schools assigned to this cluster yet — assign schools before planning a fellowship topic."
            : "No scored SSA in this cluster yet — the next cluster action is SSA collection, not a topic meeting."}
        </p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {c.weakest.map((w) => (
            <li key={w.area} className="text-[12px] leading-snug">
              <span className="font-bold">
                {w.area} — {w.average.toFixed(1)}/10
              </span>
              {w.schoolsAffected > 0 && (
                <span className="muted"> · {w.schoolsAffected} schools below Good</span>
              )}
              <span className="block muted">Discuss: “{w.topic}”</span>
            </li>
          ))}
        </ul>
      )}

      {/* ── Next meeting + schedule action (scheduler lives on the profile) ── */}
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Link
          href={`/clusters/${c.clusterId}`}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-edify-border)] px-2.5 py-1 text-[11.5px] font-bold hover:bg-[var(--color-edify-soft)]/40"
        >
          <CalendarPlus size={12} aria-hidden />
          Schedule meeting
        </Link>
        <span className="text-[11px] muted">
          {c.nextMeeting
            ? `Next: ${c.nextMeeting.kind} · ${c.nextMeeting.date}`
            : "Next meeting: None scheduled"}
        </span>
      </div>

      {/* ── Expanded detail: member school rows (detail-heavy → folds) ── */}
      {members.length > 0 && (
        <details className="group mt-3 border-t border-[var(--color-edify-divider)] pt-2.5">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[11.5px] font-bold text-[var(--color-edify-primary)] [&::-webkit-details-marker]:hidden">
            <ChevronDown
              size={13}
              aria-hidden
              className="-rotate-90 transition-transform group-open:rotate-0"
            />
            Member schools ({members.length})
          </summary>
          <ul className="mt-2 divide-y divide-[var(--color-edify-divider)]">
            {members.map((s) => (
              <MemberSchoolRow key={s.schoolId} school={s} viewerStaffId={viewerStaffId} />
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

function MemberSchoolRow({
  school: s,
  viewerStaffId,
}: {
  school: ReturnType<typeof schoolsInCluster>[number];
  viewerStaffId: string;
}) {
  const owner = resolveOwner(s.assignedCceo);
  const mine = owner.status === "matched" && owner.staffId === viewerStaffId;
  const rec = recommendInterventionsForSchool(s.schoolId);
  const weakest = rec.all.slice(0, 2); // ranked weakest → strongest by the engine

  return (
    <li className="py-2.5 first:pt-1 last:pb-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Link
          href={`/schools/${s.schoolId}`}
          className="text-[12.5px] font-bold hover:underline"
        >
          {s.schoolName}
        </Link>
        <Pill tone={s.schoolType === "Core" ? "violet" : "info"} size="xs" subtle>
          {s.schoolType}
        </Pill>
        {mine && (
          <Pill tone="success" size="xs" subtle>
            My school
          </Pill>
        )}
        <span className="ml-auto" />
        <Link
          href={`/schools/${s.schoolId}`}
          className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline"
        >
          Open school →
        </Link>
      </div>

      {/* Location + contact — render only what the record carries. */}
      <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] muted">
        <span className="inline-flex items-center gap-1">
          <MapPin size={10} aria-hidden />
          {s.district}
          {s.subCounty ? ` · ${s.subCounty}` : ""}
          {s.parish ? ` · ${s.parish}` : ""}
        </span>
        {s.primaryContact && (
          <span className="inline-flex items-center gap-1">
            <UserRound size={10} aria-hidden />
            {s.primaryContact}
          </span>
        )}
        {s.phone && (
          <span className="inline-flex items-center gap-1">
            <Phone size={10} aria-hidden />
            {s.phone}
          </span>
        )}
      </p>

      {/* Two weakest interventions + the engine's recommendation. */}
      {rec.hasSsa ? (
        <ul className="mt-1.5 space-y-1">
          {weakest.map((w) => (
            <li key={w.intervention} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px]">
              <Pill tone={SEVERITY_PILL[w.severity]} size="xs" subtle>
                {w.score}/10
              </Pill>
              <span className="font-semibold">{w.intervention}</span>
              <span className="muted">
                → {w.delivery === "partner" ? "Partner" : "Staff"} {w.recommendedActivity}
                {w.partnerType ? ` (${w.partnerType})` : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1.5 text-[11.5px] muted">
          No scored SSA yet — collect the SSA before planning interventions.
        </p>
      )}
    </li>
  );
}
