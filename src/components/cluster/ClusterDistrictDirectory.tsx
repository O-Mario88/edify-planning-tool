"use client";

// Cluster directory grouped by DISTRICT — the cluster dashboard.
//
// Backend-driven (no mock): self-fetches /api/clusters, groups the live clusters
// by district, and renders each cluster as an expandable card. Expanding a
// cluster lazy-fetches /api/clusters/:id/schools and shows the roster with the
// per-school weakest SSA intervention plus the cluster-wide common weak area.

import { useEffect, useMemo, useState } from "react";
import {
  Network, MapPin, Users, UserCheck, Phone, ChevronRight, AlertTriangle, Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeCluster, BeClusterSchool } from "@/lib/api/surfaces";
import { CLUSTERS_UPDATED } from "@/lib/cluster/cluster-events";

type SchoolsState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; schools: BeClusterSchool[]; common: { area: string; avgScore: number } | null };

// Backend intervention key → readable label, e.g. "teaching_and_learning" →
// "Teaching & Learning".
function humanizeIntervention(key: string): string {
  return key
    .split("_")
    .map((w) => (w === "and" ? "&" : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

function districtOf(c: BeCluster): string {
  return c.district?.name ?? "Unassigned district";
}
function subCountiesOf(c: BeCluster): string[] {
  if (c.subCounties && c.subCounties.length) return c.subCounties;
  const one = c.subCountyName ?? c.subCounty?.name;
  return one ? [one] : [];
}
function schoolCountOf(c: BeCluster): number {
  return c.schoolCount ?? c._count?.schools ?? 0;
}

type Props = {
  /** Server-rendered list so production shows clusters on first paint (not after client fetch). */
  initialClusters?: BeCluster[] | null;
  initialError?: string | null;
};

export function ClusterDistrictDirectory({ initialClusters = null, initialError = null }: Props) {
  const [clusters, setClusters] = useState<BeCluster[] | null>(initialClusters);
  const [error, setError] = useState<string | null>(initialError);
  const [loading, setLoading] = useState(initialClusters === null && !initialError);
  const [expanded, setExpanded] = useState<Record<string, SchoolsState>>({});

  const load = (opts?: { silent?: boolean }) => {
    if (!opts?.silent) { setLoading(true); setError(null); }
    fetch("/api/clusters", { cache: "no-store", credentials: "include" })
      .then(async (r) => {
        const j = await r.json().catch(() => null);
        if (!j || typeof j !== "object") {
          setError(`Could not load clusters (HTTP ${r.status})`);
          return;
        }
        if (!j.live) {
          setError(j.error || "Could not load clusters");
          if (!initialClusters?.length) setClusters(null);
          return;
        }
        const list: BeCluster[] = j.clusters ?? [];
        setClusters(list);
        setError(null);
      })
      .catch(() => setError("Could not reach the server — check you are signed in."))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    // Server already prefetched clusters — don't clobber good SSR data on mount.
    if (initialClusters === null && !initialError) load();
    const onUpdated = () => load();
    window.addEventListener(CLUSTERS_UPDATED, onUpdated);
    return () => window.removeEventListener(CLUSTERS_UPDATED, onUpdated);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount + event wiring only
  }, []);

  function toggle(clusterId: string) {
    setExpanded((prev) => {
      // Collapse if already open.
      if (prev[clusterId] && prev[clusterId].kind !== "idle") {
        const next = { ...prev };
        delete next[clusterId];
        return next;
      }
      return { ...prev, [clusterId]: { kind: "loading" } };
    });
    // Lazy-fetch the roster on first open.
    if (!expanded[clusterId]) {
      fetch(`/api/clusters/${encodeURIComponent(clusterId)}/schools`, { cache: "no-store", credentials: "include" })
        .then((r) => r.json())
        .then((j) => {
          if (j.live) {
            setExpanded((prev) => ({ ...prev, [clusterId]: { kind: "ready", schools: j.schools ?? [], common: j.commonWeakIntervention ?? null } }));
          } else {
            setExpanded((prev) => ({ ...prev, [clusterId]: { kind: "error", message: j.error ?? "Could not load schools" } }));
          }
        })
        .catch(() => setExpanded((prev) => ({ ...prev, [clusterId]: { kind: "error", message: "Network error" } })));
    }
  }

  // Group clusters by district, district names sorted A→Z.
  const byDistrict = useMemo(() => {
    const map = new Map<string, BeCluster[]>();
    for (const c of clusters ?? []) {
      const d = districtOf(c);
      const arr = map.get(d) ?? [];
      arr.push(c);
      map.set(d, arr);
    }
    return [...map.entries()]
      .map(([district, list]) => ({ district, list: list.sort((a, b) => a.name.localeCompare(b.name)) }))
      .sort((a, b) => a.district.localeCompare(b.district));
  }, [clusters]);

  if (loading && clusters === null && !error) return <LoadingState />;
  if (error && (!clusters || clusters.length === 0)) return <ErrorState message={error} onRetry={() => load()} />;
  if (!clusters || clusters.length === 0) {
    return <EmptyState title="No clusters yet" message="Create a cluster, then assign schools to it from the School Directory." />;
  }

  return (
    <div className="space-y-5">
      {byDistrict.map(({ district, list }) => (
        <section key={district}>
          {/* District group header */}
          <div className="flex items-center gap-2 mb-2 px-0.5">
            <MapPin size={14} className="text-[var(--color-edify-primary)]" />
            <h3 className="text-[13px] font-extrabold tracking-tight">{district}</h3>
            <span className="inline-flex items-center px-1.5 py-[2px] rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] text-[10px] font-extrabold tabular">
              {list.length} cluster{list.length === 1 ? "" : "s"}
            </span>
          </div>

          <div className="space-y-2">
            {list.map((c) => {
              const st = expanded[c.id];
              const isOpen = !!st && st.kind !== "idle";
              const subs = subCountiesOf(c);
              return (
                <div key={c.id} className="rounded-xl border border-[var(--color-edify-divider)] bg-white overflow-hidden">
                  {/* Cluster header — click to expand */}
                  <button
                    type="button"
                    onClick={() => toggle(c.id)}
                    aria-expanded={isOpen}
                    className="w-full flex items-start gap-3 p-3.5 text-left hover:bg-[var(--color-edify-soft)]/40 transition-colors"
                  >
                    <span className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                      <Network size={15} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h4 className="text-[13px] font-extrabold tracking-tight truncate">{c.name}</h4>
                        <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] text-[10px] font-bold tabular">
                          <Users size={9} /> {schoolCountOf(c)} school{schoolCountOf(c) === 1 ? "" : "s"}
                        </span>
                      </div>
                      {/* Location — district · sub-counties */}
                      <p className="text-[11px] muted leading-tight inline-flex items-center gap-1 mt-0.5">
                        <MapPin size={9} className="text-[var(--color-edify-primary)] shrink-0" />
                        {district}{subs.length ? ` · ${subs.join(", ")}` : ""}
                      </p>
                      {/* Leader + phone */}
                      <div className="flex items-center gap-3 flex-wrap mt-1 text-[11px]">
                        <span className="inline-flex items-center gap-1 muted">
                          <UserCheck size={10} className="text-[var(--color-edify-primary)]" />
                          {c.clusterLeaderName ? <span className="font-semibold text-[var(--color-edify-text)]">{c.clusterLeaderName}</span> : <span className="italic">No leader set</span>}
                        </span>
                        {c.clusterLeaderPhone && (
                          <a href={`tel:${c.clusterLeaderPhone.replace(/\s+/g, "")}`} onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-1 tabular hover:underline">
                            <Phone size={9} className="text-[var(--color-edify-primary)]" />
                            {c.clusterLeaderPhone}
                          </a>
                        )}
                      </div>
                    </div>
                    <ChevronRight size={15} className={cn("text-[var(--color-edify-muted)] shrink-0 mt-1 transition-transform", isOpen && "rotate-90")} />
                  </button>

                  {/* Expanded roster */}
                  {isOpen && (
                    <div className="border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/20 p-3">
                      {st.kind === "loading" && <LoadingState compact />}
                      {st.kind === "error" && <ErrorState compact message={st.message} onRetry={() => toggle(c.id)} />}
                      {st.kind === "ready" && (
                        st.schools.length === 0 ? (
                          <EmptyState compact title="No schools yet" message="Assign schools to this cluster from the School Directory." />
                        ) : (
                          <ClusterSchoolTable schools={st.schools} common={st.common} />
                        )
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function ClusterSchoolTable({ schools, common }: { schools: BeClusterSchool[]; common: { area: string; avgScore: number } | null }) {
  return (
    <div>
      {common && (
        <div className="mb-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 inline-flex items-start gap-1.5 w-full">
          <Sparkles size={12} className="text-amber-600 mt-0.5 shrink-0" />
          <span className="text-[11.5px] text-amber-800 font-semibold">
            Cluster-wide priority: <span className="font-extrabold text-amber-900">{humanizeIntervention(common.area)}</span> is the SSA area the whole cluster is weakest in (avg {common.avgScore.toFixed(1)}/10).
          </span>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-[var(--color-edify-divider)] bg-white shadow-sm">
        <table className="w-full text-[11.5px] min-w-[1000px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider font-bold muted bg-slate-50 border-b border-[var(--color-edify-divider)]">
              <th className="px-3 py-2.5">School ID</th>
              <th className="px-3 py-2.5">School Name</th>
              <th className="px-3 py-2.5">Geography</th>
              <th className="px-3 py-2.5">Type</th>
              <th className="px-3 py-2.5">Assigned Staff</th>
              <th className="px-3 py-2.5 text-center">SSA Avg</th>
              <th className="px-3 py-2.5">Weakest Intervention</th>
              <th className="px-3 py-2.5">Struggling Areas</th>
              <th className="px-3 py-2.5">Last Visit</th>
              <th className="px-3 py-2.5">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {schools.map((s) => (
              <tr key={s.schoolId} className="hover:bg-slate-50/80 transition-colors">
                <td className="px-3 py-2.5 tabular font-bold text-slate-700 whitespace-nowrap">{s.schoolId}</td>
                <td className="px-3 py-2.5 font-extrabold text-slate-900">
                  <a href={`/schools/${s.schoolId}`} className="hover:text-[var(--color-edify-primary)] hover:underline">
                    {s.name}
                  </a>
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <div className="font-medium text-slate-700">{s.district ?? "—"}</div>
                  <div className="text-[10px] text-slate-500">
                    {s.subCounty ? s.subCounty : ""}
                    {s.parish ? ` · ${s.parish}` : ""}
                  </div>
                </td>
                <td className="px-3 py-2.5 capitalize font-semibold text-slate-700">{s.schoolType}</td>
                <td className="px-3 py-2.5 text-slate-700 font-semibold">{s.assignedStaff}</td>
                <td className="px-3 py-2.5 text-center tabular font-extrabold text-slate-800">
                  {s.currentSsaAverage != null ? `${s.currentSsaAverage.toFixed(1)}/10` : "—"}
                </td>
                <td className="px-3 py-2.5">
                  {s.ssaStatus === "done" ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded bg-rose-50 border border-rose-100 text-rose-700 text-[10.5px] font-extrabold">
                      {s.weakestSsaIntervention}
                    </span>
                  ) : (
                    <span className="text-amber-600 font-bold text-[10.5px] inline-flex items-center gap-0.5">
                      <AlertTriangle size={10} /> Pending SSA
                    </span>
                  )}
                </td>
                <td className="px-3 py-2.5 max-w-[200px] truncate text-[11px] font-medium text-slate-600">
                  {s.topStrugglingInterventions.length > 0 ? s.topStrugglingInterventions.join(", ") : "—"}
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap text-slate-700 font-medium">{s.lastVisitDate}</td>
                <td className="px-3 py-2.5 text-[11px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap">
                  {s.recommendedAction}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
