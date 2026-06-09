"use client";

// Completed Activities Log — LIVE. Historical/closed work pulled from the backend
// (/api/activities?statusGroup=completed), kept OUT of the active Planning and
// My Plan views but never deleted. Filterable by activity type + status.

import { useEffect, useMemo, useState } from "react";
import { History } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeActivity } from "@/lib/api/surfaces";

const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const TYPE_GROUPS = [
  { key: "all", label: "All" }, { key: "visit", label: "Visits", match: (t: string) => /visit|in_school_support/.test(t) },
  { key: "training", label: "Trainings", match: (t: string) => /training|school_improvement/.test(t) },
  { key: "cluster", label: "Cluster", match: (t: string) => /cluster/.test(t) },
  { key: "partner", label: "Partner / project", match: (t: string) => /partner|project/.test(t) },
];
const statusTone = (s: string) =>
  /ia_verified|accountant_confirmed|completed/.test(s) ? "bg-emerald-100 text-emerald-700"
  : /cancelled|rejected/.test(s) ? "bg-rose-100 text-rose-700" : "bg-slate-100 text-slate-600";

export function CompletedActivitiesLive() {
  const [rows, setRows] = useState<BeActivity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [group, setGroup] = useState("all");

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/activities?statusGroup=completed&pageSize=300", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setRows(j.data as BeActivity[]); else setError(j.error || "Could not load the activity log"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const filtered = useMemo(() => {
    if (!rows) return [];
    const g = TYPE_GROUPS.find((x) => x.key === group);
    return g?.match ? rows.filter((r) => g.match!(r.activityType)) : rows;
  }, [rows, group]);

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><History size={14} /> Completed Activities Log</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · history</span>
      </header>

      {loading ? <LoadingState compact />
        : error ? <ErrorState compact message={error} onRetry={load} />
        : !rows || rows.length === 0 ? <EmptyState compact title="No completed activities yet" message="Verified, paid, and closed work moves here automatically — out of your active task views." />
        : (
        <>
          <div className="flex items-center gap-1.5 mb-2.5 flex-wrap">
            {TYPE_GROUPS.map((g) => (
              <button key={g.key} onClick={() => setGroup(g.key)} className={cn("px-2 py-0.5 rounded-full text-[11px] font-bold border", group === g.key ? "bg-[var(--color-edify-primary)] text-white border-transparent" : "muted border-[var(--color-edify-border)]")}>{g.label}</button>
            ))}
            <span className="ml-auto text-[11px] muted">{filtered.length} of {rows.length}</span>
          </div>
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-[11.5px] px-1">
              <thead>
                <tr className="text-left muted uppercase text-[9.5px] tracking-wide border-b border-[var(--color-edify-border)]">
                  <th className="py-1.5 pr-2">Activity</th><th className="py-1.5 px-1">School / cluster</th>
                  <th className="py-1.5 px-1">District</th><th className="py-1.5 px-1">Date</th>
                  <th className="py-1.5 px-1">SF ID</th><th className="py-1.5 px-1 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-edify-divider)]">
                {filtered.slice(0, 200).map((a) => (
                  <tr key={a.id}>
                    <td className="py-1.5 pr-2 font-semibold whitespace-nowrap">{titleCase(a.activityType)}</td>
                    <td className="py-1.5 px-1 truncate max-w-[150px]">{a.school?.name ?? "cluster"}</td>
                    <td className="py-1.5 px-1 muted">{a.school?.district?.name ?? "—"}</td>
                    <td className="py-1.5 px-1 muted whitespace-nowrap">{a.scheduledDate ? new Date(a.scheduledDate).toLocaleDateString() : `${a.fy ?? ""} ${a.quarter ?? ""}`}</td>
                    <td className="py-1.5 px-1 font-mono text-[10px] muted">{a.salesforceActivityId ?? "—"}</td>
                    <td className="py-1.5 px-1 text-right"><span className={cn("px-1.5 py-0.5 rounded text-[9.5px] font-bold whitespace-nowrap", statusTone(a.status))}>{titleCase(a.status)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
