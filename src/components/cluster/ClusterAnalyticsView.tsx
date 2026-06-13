// Cluster Analytics — read-only truth surface over the cluster engine.
// Server component: reads the engine directly, no props, no client state.

import {
  MapPin,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import {
  activeClusters,
  clusterAnalytics,
  clusterHealthChecks,
  schoolsInCluster,
  staffVsPartnerClusterComparison,
} from "@/lib/cluster/cluster-core";
import { clusterAcquisitionMetrics } from "@/lib/cluster/cluster-join-source";
import { ClusterSsaHeatmapCard } from "./ClusterSsaHeatmapCard";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { cn } from "@/lib/utils";

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
  const acq = clusterAcquisitionMetrics();

  return (
    <div className="space-y-4">
      {/* KPI tiles */}
      <MetricStrip
        columns="grid-cols-2 md:grid-cols-3 lg:grid-cols-6"
        metrics={[
          { key: "total", label: "Total clusters", value: a.totalClusters },
          { key: "clustered", label: "Schools clustered", value: a.schoolsClustered },
          { key: "unclustered", label: "Schools unclustered", value: a.schoolsUnclustered, tone: a.schoolsUnclustered > 0 ? "alert" : "default" },
          { key: "client", label: "Client clustered", value: a.clientClustered },
          { key: "core", label: "Core clustered", value: a.coreClustered },
          { key: "avg", label: "Avg schools / cluster", value: a.avgSchoolsPerCluster },
        ]}
      />

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

      {/* New schools joined through cluster */}
      <section className="card rounded-2xl p-4">
        <h2 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
          New schools joined through cluster
        </h2>
        <p className="muted text-[12px] mt-0.5">Schools acquired via cluster onboarding/referral. Partner-facilitated clusters count as partner-influenced (ownership stays with staff).</p>
        <div className="mt-3">
          <MetricStrip
            bare
            columns="grid-cols-2 md:grid-cols-5"
            metrics={[
              { key: "joined", label: "Schools joined", value: acq.schoolsJoined },
              { key: "client", label: "Client", value: acq.clientJoined },
              { key: "core", label: "Core", value: acq.coreJoined },
              { key: "learners", label: "Learners added", value: acq.learnersAdded },
              { key: "partner", label: "Partner-influenced", value: acq.partnerInfluenced },
            ]}
          />
        </div>
      </section>

      {/* SSA performance heatmap by cluster */}
      <ClusterSsaHeatmapCard />

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
