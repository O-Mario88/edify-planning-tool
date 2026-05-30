import Link from "next/link";
import { GraduationCap, ChevronRight, CheckCircle2, Clock, AlertCircle, Users, XCircle } from "lucide-react";
import { SectionCard, KpiCard } from "@/components/ui/primitives";
import {
  countryTrainingStats,
  regionTrainingStats,
  trainingByIntervention,
} from "@/lib/training-stats";
import type { ClusterTrainingPlan } from "@/lib/plan-builder-engine";

// Training coverage card — surfaces school + cluster training delivery
// alongside the SSA gaps each training is meant to close. Built once,
// rendered in CD / RVP / IA dashboards with `audience` controlling
// the scope label (country vs region) and the breakdown depth.
//
// SSA-driven by construction: every row in the intervention table is
// keyed by an SSA intervention area, so the CD/RVP can see at a glance
// whether the trainings being delivered match the weakest interventions
// the SSA flagged. A high-coverage row paired with a low-SSA
// intervention = misalignment worth interrogating.
//
// When `clusterPlans` is provided, a third section surfaces the
// SSA-driven cluster fit — which clusters have a scheduled training,
// the topic chosen, the % of schools it actually fits, and how many
// schools are deferred to school-level support this period. Skipped
// clusters bubble to the top so the CD/RVP can spot them in one glance.

export function TrainingCoverageCard({
  audience,
  clusterPlans,
}: {
  /** Controls the scope label and lower-section depth. */
  audience: "cd" | "rvp" | "ia";
  /**
   * Per-cluster scheduling plans from `allClusterTrainingPlans()`.
   * Optional — the card degrades gracefully if omitted (e.g. early
   * in build-out, or for audiences where cluster detail is noise).
   */
  clusterPlans?: ClusterTrainingPlan[];
}) {
  const stats = audience === "rvp" ? regionTrainingStats() : countryTrainingStats();
  const breakdown = trainingByIntervention();
  const scopeLabel =
    audience === "rvp" ? "Region"
    : audience === "cd" ? "Country"
    : "Programme-wide";

  return (
    <SectionCard
      icon={<GraduationCap size={13} />}
      title={`Trainings · ${scopeLabel}`}
      subtitle="SSA-driven cluster cohorts. Every row is an SSA intervention area — coverage shows whether the gap is being closed."
      actions={
        <Link
          href="/trainings"
          className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-1"
        >
          Open trainings
          <ChevronRight size={12} />
        </Link>
      }
    >
      {/* Status strip — 4 KPIs */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
        <KpiCard
          label="Scheduled"
          value={stats.scheduled.toString()}
          caption="Confirmed cohorts ahead"
          icon={<Clock size={16} />}
          iconTone="edify"
        />
        <KpiCard
          label="In progress"
          value={stats.inProgress.toString()}
          caption="Delivery underway"
          icon={<Clock size={16} />}
          iconTone="amber"
        />
        <KpiCard
          label="Completed"
          value={stats.completed.toString()}
          caption="Delivered + closed"
          icon={<CheckCircle2 size={16} />}
          iconTone="green"
        />
        <KpiCard
          label="Completion rate"
          value={`${stats.completionRate}%`}
          caption="Of closed cohorts"
          icon={<AlertCircle size={16} />}
          iconTone={stats.completionRate >= 90 ? "green" : stats.completionRate >= 75 ? "amber" : "edify"}
        />
      </section>

      {/* Intervention breakdown — the SSA-coverage signal */}
      <div>
        <header className="flex items-baseline justify-between mb-2">
          <h3 className="text-body font-extrabold tracking-tight">Coverage by SSA intervention</h3>
          <span className="text-caption muted">
            Worst-covered first
          </span>
        </header>
        <table className="w-full dtable">
          <thead>
            <tr>
              <th scope="col" className="text-left">Intervention</th>
              <th scope="col" className="text-right">Cohorts</th>
              <th scope="col" className="text-right">Completed</th>
              <th scope="col" className="text-right">Coverage</th>
            </tr>
          </thead>
          <tbody>
            {breakdown.map((row) => {
              const tone =
                row.coveragePct >= 80 ? "text-emerald-700"
                : row.coveragePct >= 50 ? "text-amber-700"
                : "text-rose-700";
              return (
                <tr key={row.intervention}>
                  <td className="text-body font-semibold">{row.intervention}</td>
                  <td className="text-right tabular text-[12px]">{row.total}</td>
                  <td className="text-right tabular text-[12px]">{row.completed}</td>
                  <td className={`text-right tabular text-body font-extrabold ${tone}`}>
                    {row.coveragePct}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Cluster scheduling — the SSA-driven fit signal. Worst fit (and
          Skipped clusters) sort to the top so escalations are visible
          before scrolling. */}
      {clusterPlans && clusterPlans.length > 0 && (
        <div className="mt-4 pt-4 border-t border-[var(--color-edify-divider)]">
          <header className="flex items-baseline justify-between mb-2">
            <h3 className="text-body font-extrabold tracking-tight">Cluster scheduling — SSA fit</h3>
            <span className="text-caption muted">Worst fit first · Skipped at top</span>
          </header>
          <table className="w-full dtable">
            <thead>
              <tr>
                <th scope="col" className="text-left">Cluster</th>
                <th scope="col" className="text-left">Topic this period</th>
                <th scope="col" className="text-right">Schools</th>
                <th scope="col" className="text-right">Attending</th>
                <th scope="col" className="text-right">Deferred</th>
                <th scope="col" className="text-right">Fit</th>
              </tr>
            </thead>
            <tbody>
              {clusterPlans.map((p) => {
                const skipped = p.topic === "Skipped";
                const fitTone =
                  skipped              ? "text-rose-700"
                  : p.fitRate >= 70    ? "text-emerald-700"
                  : p.fitRate >= 50    ? "text-amber-700"
                  :                       "text-rose-700";
                return (
                  <tr key={p.clusterId}>
                    <td className="text-body font-semibold">{p.clusterName}</td>
                    <td className="text-[12px]">
                      {skipped ? (
                        <span className="inline-flex items-center gap-1 text-rose-700 font-semibold">
                          <XCircle size={11} />
                          Skipped — visits instead
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1">
                          <Users size={11} className="text-[var(--color-edify-muted)]" />
                          {p.topic}
                        </span>
                      )}
                    </td>
                    <td className="text-right tabular text-[12px]">{p.totalSchools}</td>
                    <td className="text-right tabular text-[12px]">{p.attending}</td>
                    <td className="text-right tabular text-[12px] text-amber-700 font-semibold">{p.deferred}</td>
                    <td className={`text-right tabular text-body font-extrabold ${fitTone}`}>
                      {skipped ? "—" : `${p.fitRate}%`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="text-caption muted mt-2 leading-snug">
            Topic is selected by SSA distribution: the intervention shared by the most schools in the cluster, when ≥6 schools cross the cohort threshold. Otherwise the session is skipped and those schools get a visit this period — their training need queues for the next cycle.
          </p>
        </div>
      )}
    </SectionCard>
  );
}
