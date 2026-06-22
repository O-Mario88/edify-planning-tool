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

export function ClusterDistrictDirectory() {
  const [clusters, setClusters] = useState<BeCluster[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Record<string, SchoolsState>>({});

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/clusters", { cache: "no-store", credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (!j.live) { setError(j.error || "Could not load clusters"); return; }
        const list: BeCluster[] = j.clusters ?? [];
        setClusters(list);
      })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

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

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} onRetry={load} />;
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
      {/* Cluster-wide common weak intervention (shared SSA recommendation). */}
      {common && (
        <div className="mb-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 inline-flex items-start gap-1.5 w-full">
          <Sparkles size={12} className="text-amber-600 mt-0.5 shrink-0" />
          <span className="text-[11.5px] text-amber-800">
            <span className="font-extrabold">Cluster-wide priority:</span>{" "}
            <span className="font-extrabold">{humanizeIntervention(common.area)}</span> is the SSA area the whole cluster is weakest in (avg {common.avgScore}/10) — a good shared cluster-meeting / SIT topic.
          </span>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-[var(--color-edify-divider)] bg-white">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider font-bold muted border-b border-[var(--color-edify-divider)]">
              <th className="px-2.5 py-2">School ID</th>
              <th className="px-2.5 py-2">School Name</th>
              <th className="px-2.5 py-2">Sub-county</th>
              <th className="px-2.5 py-2">Phone</th>
              <th className="px-2.5 py-2">Primary Contact</th>
              <th className="px-2.5 py-2">SSA Recommendation</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {schools.map((s) => (
              <tr key={s.schoolId} className="hover:bg-[var(--color-edify-soft)]/40">
                <td className="px-2.5 py-2 tabular font-semibold whitespace-nowrap">{s.schoolId}</td>
                <td className="px-2.5 py-2 font-extrabold tracking-tight">{s.name}</td>
                <td className="px-2.5 py-2 muted whitespace-nowrap">{s.subCounty ?? "—"}</td>
                <td className="px-2.5 py-2 whitespace-nowrap">
                  {s.phone ? <a href={`tel:${s.phone.replace(/\s+/g, "")}`} className="tabular hover:underline">{s.phone}</a> : <span className="muted">—</span>}
                </td>
                <td className="px-2.5 py-2 whitespace-nowrap">{s.primaryContact ?? <span className="muted">—</span>}</td>
                <td className="px-2.5 py-2">
                  {s.weakestIntervention ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md bg-rose-50 border border-rose-200 text-rose-700 text-[10.5px] font-extrabold whitespace-nowrap">
                      <AlertTriangle size={9} />
                      {humanizeIntervention(s.weakestIntervention.area)} · {s.weakestIntervention.score}/10
                    </span>
                  ) : (
                    <span className="muted text-[10.5px]">No SSA yet</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
