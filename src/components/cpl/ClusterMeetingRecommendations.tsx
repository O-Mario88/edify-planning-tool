import Link from "next/link";
import { ArrowUpRight, CalendarPlus, Network } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import type { ClusterMeetingRecommendation } from "@/lib/cluster/cluster-meeting-recommendations";
import { cn } from "@/lib/utils";

// Cluster meeting recommendations — the PL's cluster-strategy card.
// Each row: the cluster, its SSA coverage, the TWO weakest interventions
// with a recommended discussion topic + reason + schools affected, and a
// schedule action that lands on the cluster profile (where the meeting
// scheduler lives). Weakest cluster first, so reading order = priority.

function scoreTone(avg: number | null): string {
  if (avg == null) return "text-slate-500";
  if (avg < 5) return "text-rose-600";
  if (avg < 7) return "text-amber-600";
  return "text-emerald-600";
}

export function ClusterMeetingRecommendationsCard({
  recommendations,
  limit = 5,
}: {
  recommendations: ClusterMeetingRecommendation[];
  limit?: number;
}) {
  const shown = recommendations.slice(0, limit);
  const hidden = recommendations.length - shown.length;

  return (
    <SectionCard
      icon={<Network size={13} />}
      title="Cluster Meetings — what to discuss next"
      actions={
        <Link href="/clusters" className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline">
          Cluster directory <ArrowUpRight size={12} />
        </Link>
      }
    >
      {shown.length === 0 ? (
        <p className="text-[12.5px] muted py-2">No active clusters in your scope yet.</p>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {shown.map((c) => (
            <li key={c.clusterId} className="py-3 first:pt-1 last:pb-1">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="text-[13px] font-extrabold tracking-tight">{c.clusterName}</span>
                <span className="text-[11px] muted">
                  {c.district}
                  {c.subCounty ? ` · ${c.subCounty}` : ""} · {c.schools} schools · {c.schoolsWithSsa} with SSA
                  {c.schoolsMissingSsa > 0 ? ` · ${c.schoolsMissingSsa} missing` : ""}
                  {c.managedByPartnerName ? ` · partner: ${c.managedByPartnerName}` : ""}
                </span>
                <span className={cn("ml-auto text-[13px] font-extrabold tabular", scoreTone(c.overallAverage))}>
                  {c.overallAverage != null ? `${c.overallAverage.toFixed(1)}/10` : "no SSA"}
                </span>
              </div>

              {c.weakest.length === 0 ? (
                <p className="mt-1 text-[12px] muted leading-snug">
                  {c.schools === 0 ? (
                    <>
                      No schools assigned to this cluster yet — assign schools from the{" "}
                      <Link href="/clusters" className="underline font-semibold">cluster hub</Link>{" "}
                      first.
                    </>
                  ) : (
                    "No scored SSA in this cluster yet — the next cluster action is SIT / SSA collection, not a topic meeting."
                  )}
                </p>
              ) : (
                <ul className="mt-1.5 space-y-1.5">
                  {c.weakest.map((w) => (
                    <li key={w.area} className="text-[12px] leading-snug">
                      <span className="font-bold">
                        {w.area} — {w.average.toFixed(1)}/10
                      </span>
                      {w.schoolsAffected > 0 && (
                        <span className="muted"> · {w.schoolsAffected} schools below Good</span>
                      )}
                      <span className="block muted">“{w.topic}”</span>
                    </li>
                  ))}
                </ul>
              )}

              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Link
                  href={`/clusters/${c.clusterId}`}
                  className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-edify-border)] px-2.5 py-1 text-[11.5px] font-bold hover:bg-[var(--color-edify-soft)]/40"
                >
                  <CalendarPlus size={12} />
                  Schedule cluster meeting
                </Link>
                {c.nextMeeting && (
                  <span className="text-[11px] muted">
                    Next planned: {c.nextMeeting.kind} · {c.nextMeeting.date}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {hidden > 0 && (
        <p className="mt-1.5 text-[11px] muted">
          + {hidden} more clusters in the <Link href="/clusters" className="underline">directory</Link>, strongest last.
        </p>
      )}
    </SectionCard>
  );
}
