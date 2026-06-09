"use client";

// Cluster planning — LIVE. Real clusters from the backend (/api/clusters), each
// with a live "Schedule meeting" that writes a cluster_meeting / cluster_training
// to the DB via ScheduleActivityLive (cost from the CD rate card). This is the
// honest live cluster-scheduling path: real clusters, real writes. (The legacy
// SIT/1st/2nd/3rd-meeting SLOT model isn't represented in the backend yet, so
// the per-slot board stays mock until a cluster-meeting-slot endpoint exists.)

import { useEffect, useState } from "react";
import { Network, CalendarPlus } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { ScheduleActivityLive } from "./ScheduleActivityLive";
import type { BeCluster } from "@/lib/api/surfaces";

export function ClusterPlanningLive() {
  const [clusters, setClusters] = useState<BeCluster[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [scheduling, setScheduling] = useState<{ id: string; name: string } | null>(null);

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/clusters", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        const rows = Array.isArray(j) ? j : j.clusters ?? j.data ?? [];
        if (j.live === false) setError(j.error || "Could not load clusters");
        else setClusters(rows as BeCluster[]);
      })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Network size={14} /> Cluster planning</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · scoped</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !clusters || clusters.length === 0 ? (
        <EmptyState compact title="No clusters in scope" message="Create clusters in the Cluster Dashboard, then schedule their meetings here." />
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {clusters.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-2 py-2 text-[12px]">
              <span className="min-w-0">
                <span className="font-semibold">{c.name}</span>
                <span className="block text-[10.5px] muted truncate">
                  {c.district?.name ?? c.subCountyName ?? ""}{c._count?.schools != null ? ` · ${c._count.schools} schools` : ""}
                </span>
              </span>
              <button
                onClick={() => setScheduling({ id: c.id, name: c.name })}
                className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-[10.5px] font-bold whitespace-nowrap shrink-0"
              >
                <CalendarPlus size={11} /> Schedule meeting
              </button>
            </li>
          ))}
        </ul>
      )}

      {scheduling && (
        <ScheduleActivityLive
          clusterId={scheduling.id}
          clusterName={scheduling.name}
          onClose={() => setScheduling(null)}
          onScheduled={load}
        />
      )}
    </section>
  );
}
