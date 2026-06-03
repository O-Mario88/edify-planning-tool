// Cluster Analytics — read-only truth surface over the cluster engine.
// Server component: reads the engine directly, no props, no client state.

import {
  Boxes,
  CheckCircle2,
  CircleSlash,
  Layers,
  Users,
  GraduationCap,
  MapPin,
  ShieldAlert,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import {
  activeClusters,
  clusterAnalytics,
  clusterHealthChecks,
  schoolsInCluster,
  staffVsPartnerClusterComparison,
} from "@/lib/cluster/cluster-core";
import { cn } from "@/lib/utils";

type Kpi = { label: string; value: number; Icon: LucideIcon };

type DistrictRollup = {
  district: string;
  clusters: number;
  schools: number;
};

function districtRollups(): DistrictRollup[] {
  const map = new Map<string, DistrictRollup>();
  for (const c of activeClusters()) {
    const key = c.district || "—";
    const row =
      map.get(key) ?? { district: key, clusters: 0, schools: 0 };
    row.clusters += 1;
    row.schools += schoolsInCluster(c.id).length;
    map.set(key, row);
  }
  return [...map.values()].sort((a, b) => b.clusters - a.clusters);
}

export function ClusterAnalyticsView() {
  const a = clusterAnalytics();
  const health = clusterHealthChecks();
  const rollups = districtRollups();
  const cmp = staffVsPartnerClusterComparison();

  const kpis: Kpi[] = [
    { label: "Total clusters", value: a.totalClusters, Icon: Boxes },
    { label: "Schools clustered", value: a.schoolsClustered, Icon: CheckCircle2 },
    { label: "Schools unclustered", value: a.schoolsUnclustered, Icon: CircleSlash },
    { label: "Client clustered", value: a.clientClustered, Icon: Users },
    { label: "Core clustered", value: a.coreClustered, Icon: GraduationCap },
    { label: "Avg schools / cluster", value: a.avgSchoolsPerCluster, Icon: Layers },
  ];

  return (
    <div className="space-y-4">
      {/* KPI tiles */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {kpis.map((k) => (
          <div key={k.label} className="card rounded-2xl p-4">
            <div className="flex items-center justify-between">
              <span className="text-[24px] font-extrabold tracking-tight tabular text-[var(--color-edify-text)]">
                {k.value}
              </span>
              <k.Icon
                className="size-4 text-[var(--color-edify-primary)]"
                aria-hidden
              />
            </div>
            <div className="muted mt-1 text-[12px]">{k.label}</div>
          </div>
        ))}
      </div>

      {/* Clusters by district */}
      <section className="card rounded-2xl p-4">
        <h2 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
          Clusters by district
        </h2>
        <div className="mt-3 space-y-2">
          {rollups.length === 0 ? (
            <p className="muted text-[12.5px]">No active clusters yet.</p>
          ) : (
            rollups.map((r) => (
              <div
                key={r.district}
                className="flex items-center justify-between rounded-xl border border-[var(--color-edify-border)] px-3 py-2"
              >
                <span className="flex items-center gap-2 text-[12.5px] text-[var(--color-edify-text)]">
                  <MapPin
                    className="size-3.5 text-[var(--color-edify-primary)]"
                    aria-hidden
                  />
                  {r.district}
                </span>
                <span className="muted text-[12px] tabular">
                  {r.clusters} cluster{r.clusters === 1 ? "" : "s"} ·{" "}
                  {r.schools} school{r.schools === 1 ? "" : "s"}
                </span>
              </div>
            ))
          )}
        </div>
      </section>

      {/* Staff vs partner cluster management */}
      <section className="card rounded-2xl p-4">
        <h2 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
          Staff vs partner cluster management
        </h2>
        <p className="muted text-[12px] mt-0.5">How staff-managed and partner-managed clusters compare on delivery, attendance, and SSA.</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="text-left muted border-b border-[var(--color-edify-divider)]">
                <th className="py-1.5 pr-3 font-semibold">Metric</th>
                <th className="py-1.5 px-3 font-semibold text-sky-700">Staff-managed</th>
                <th className="py-1.5 px-3 font-semibold text-violet-700">Partner-managed</th>
              </tr>
            </thead>
            <tbody className="tabular">
              {[
                ["Clusters", cmp.staff.clusters, cmp.partner.clusters],
                ["Meetings scheduled", cmp.staff.meetingsScheduled, cmp.partner.meetingsScheduled],
                ["Meetings IA-confirmed", cmp.staff.meetingsConfirmed, cmp.partner.meetingsConfirmed],
                ["Attendance total", cmp.staff.attendanceTotal, cmp.partner.attendanceTotal],
                ["Teachers reached", cmp.staff.teachersReached, cmp.partner.teachersReached],
                ["School leaders reached", cmp.staff.schoolLeadersReached, cmp.partner.schoolLeadersReached],
                ["Avg SSA completion", `${cmp.staff.avgSsaCompletion}%`, `${cmp.partner.avgSsaCompletion}%`],
              ].map(([label, s, p]) => (
                <tr key={String(label)} className="border-b border-[var(--color-edify-divider)] last:border-0">
                  <td className="py-1.5 pr-3 text-[var(--color-edify-text)]">{label}</td>
                  <td className="py-1.5 px-3 font-extrabold">{s}</td>
                  <td className="py-1.5 px-3 font-extrabold">{p}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* System health */}
      <section className="card rounded-2xl p-4">
        <h2 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
          System health
        </h2>
        <div className="mt-3 space-y-2">
          {health.length === 0 ? (
            <div className="flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-[12.5px] text-emerald-600 dark:text-emerald-400">
              <ShieldCheck className="size-4" aria-hidden />
              All clear — no cluster integrity issues.
            </div>
          ) : (
            health.map((issue) => (
              <div
                key={issue.kind}
                className={cn(
                  "flex items-center justify-between rounded-xl border px-3 py-2 text-[12.5px]",
                  issue.count > 0
                    ? "border-rose-500/40 bg-rose-500/10 text-rose-600 dark:text-rose-400"
                    : "border-[var(--color-edify-border)] text-[var(--color-edify-text)]"
                )}
              >
                <span className="flex items-center gap-2">
                  <ShieldAlert className="size-4" aria-hidden />
                  {issue.label}
                </span>
                <span className="font-extrabold tabular">{issue.count}</span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
