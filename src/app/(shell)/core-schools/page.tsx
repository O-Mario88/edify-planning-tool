import Link from "next/link";
import { GraduationCap, Trophy, TrendingUp, ArrowRight } from "lucide-react";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { PageHeader } from "@/components/ui/PageHeader";
import { coreBoardData, coreBoardSummary } from "@/lib/core/core-board";
import { getCurrentUser } from "@/lib/auth";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

// Core School Directory — a filtered view of the School Directory + the unified
// CoreSchoolProfile / CorePlan (schoolType = Core). One identity, one model.
export default async function CoreSchoolDashboard() {
  const user = await getCurrentUser();
  const cards = coreBoardData(user.staffId, user.role);
  const summary = coreBoardSummary(cards);

  const body = (
    <>
      <PageHeader
        title="Core Schools"
        subtitle="Schools onboarded as Core — each tracked through its 4 visits + 4 trainings package, follow-up SSA, measured impact, and the champion pipeline. Filtered from the School Directory by core status."
        Icon={GraduationCap}
        searchPlaceholder="Search core schools"
      />
      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 space-y-3 lg:space-y-4 pt-3">
        <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
          <Kpi label="Core schools" value={summary.plans} />
          <Kpi label="Active plans" value={summary.active} />
          <Kpi label="Awaiting Follow-Up SSA" value={summary.pendingFollowUp} />
          <Kpi label="Impact measured" value={summary.impactMeasured} />
          <Kpi label="Champions" value={summary.champions} tone="text-amber-700" />
          <Kpi label="Visits · Trainings" value={`${summary.visitsDone} · ${summary.trainingsDone}`} />
        </section>

        <section className="card p-3.5">
          <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
            <h2 className="text-[13px] font-extrabold tracking-tight">Core School Directory</h2>
            <Link href="/planning/core-schools" className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)]">
              Planning Console <ArrowRight size={12} />
            </Link>
          </div>
          {cards.length === 0 ? (
            <p className="py-8 text-center text-[12px] muted italic">No core schools in your scope yet — onboard a verified candidate to populate this directory.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                    <th className="py-2 pr-2">School</th>
                    <th className="py-2 px-2">District · Cluster</th>
                    <th className="py-2 px-2">Owner</th>
                    <th className="py-2 px-2 text-right">Baseline</th>
                    <th className="py-2 px-2">Package</th>
                    <th className="py-2 px-2">Status</th>
                    <th className="py-2 px-2">Impact</th>
                    <th className="py-2 px-2">Champion</th>
                    <th className="py-2 pl-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-edify-divider)]">
                  {cards.map((c) => (
                    <tr key={c.plan.id} className="hover:bg-[var(--color-edify-soft)]/30 align-top">
                      <td className="py-2.5 pr-2">
                        <Link href={`/schools/${c.plan.schoolId}`} className="font-extrabold hover:underline">{c.schoolName}</Link>
                        <div className="text-[10px] muted tabular">ID {c.plan.schoolId}</div>
                      </td>
                      <td className="py-2.5 px-2 muted">{c.district}{c.cluster ? ` · ${c.cluster}` : ""}</td>
                      <td className="py-2.5 px-2 muted">{c.owner ?? "—"}</td>
                      <td className="py-2.5 px-2 text-right tabular font-bold">{c.baselineAverage.toFixed(1)}</td>
                      <td className="py-2.5 px-2">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-16 rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
                            <div className="h-full rounded-full bg-[var(--color-edify-primary)]" style={{ width: `${c.progress.packageCompletionPercent}%` }} />
                          </div>
                          <span className="text-[10.5px] muted tabular">{c.progress.visitsCompleted}V·{c.progress.trainingsCompleted}T</span>
                        </div>
                      </td>
                      <td className="py-2.5 px-2"><span className="text-[10.5px] font-semibold">{c.plan.status}</span></td>
                      <td className="py-2.5 px-2">
                        {c.impact ? (
                          <span className={cn("inline-flex items-center gap-1 font-bold tabular text-[11px]", c.impact.averageChange >= 0 ? "text-emerald-700" : "text-rose-700")}>
                            <TrendingUp size={11} /> {c.impact.averageChange >= 0 ? "+" : ""}{c.impact.averageChange}
                          </span>
                        ) : <span className="text-[11px] muted">—</span>}
                      </td>
                      <td className="py-2.5 px-2">
                        {c.championStatus !== "Not Eligible" ? (
                          <span className="inline-flex items-center gap-1 text-[10.5px] font-bold text-amber-700"><Trophy size={11} /> {c.championStatus}</span>
                        ) : <span className="text-[11px] muted">—</span>}
                      </td>
                      <td className="py-2.5 pl-2 text-right">
                        <Link href="/planning/core-schools" className="text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline">Plan →</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
      <RoleBottomNav />
    </>
  );

  return <ResponsiveDashboard mobile={body} desktop={body} />;
}

function Kpi({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="card px-3 py-2.5">
      <div className="text-[10px] font-semibold muted leading-tight">{label}</div>
      <div className={cn("text-[18px] font-extrabold tabular leading-none mt-1", tone)}>{value}</div>
    </div>
  );
}
