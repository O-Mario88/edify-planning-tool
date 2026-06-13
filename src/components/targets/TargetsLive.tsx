"use client";

// TargetsLive — backend-driven target progress by period. Self-fetches
// /api/targets (→ /targets/time-period): per-period target vs achieved for
// staff + partner + total, with a status and gap. No mock.

import { useEffect, useState } from "react";
import { Target } from "lucide-react";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeTargets } from "@/lib/api/surfaces";

const STATUS_TONE: Record<string, string> = {
  "On Track": "bg-emerald-50 text-emerald-700",
  "Ahead": "bg-emerald-50 text-emerald-700",
  "Slightly Behind": "bg-amber-50 text-amber-700",
  "Behind": "bg-rose-50 text-rose-700",
  "Critical": "bg-rose-50 text-rose-700",
};

export function TargetsLive({ title = "Target progress", staffId }: { title?: string; staffId?: string }) {
  const [data, setData] = useState<BeTargets | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true); setError(null);
    fetch(`/api/targets${staffId ? `?staffId=${encodeURIComponent(staffId)}` : ""}`, { credentials: "include" })
      .then((r) => r.json())
      // A role with no target profile returns non-live — degrade to an empty
      // state rather than a scary error (keeps dashboards clean).
      .then((j) => { setData(j.live ? (j as BeTargets) : null); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, [staffId]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data || data.rows.length === 0) return <EmptyState title="No targets set" message="Targets appear once they're configured for this FY." />;

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Target size={14} /> {title} <span className="muted font-semibold">· FY {data.fy}</span></h3>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>
      <p className="text-[11px] muted mb-2">Portfolio: <span className="font-extrabold text-[var(--color-edify-text)]">{data.totalPortfolio}</span> schools</p>
      <div className="overflow-x-auto rounded-lg border border-[var(--color-edify-divider)]">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider font-bold muted border-b border-[var(--color-edify-divider)]">
              <th className="px-2.5 py-2">Period</th>
              <th className="px-2.5 py-2">Target</th>
              <th className="px-2.5 py-2">Achieved</th>
              <th className="px-2.5 py-2">%</th>
              <th className="px-2.5 py-2">Gap</th>
              <th className="px-2.5 py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {data.rows.map((r) => (
              <tr key={r.period} className="hover:bg-[var(--color-edify-soft)]/40">
                <td className="px-2.5 py-2 font-extrabold">{r.period}</td>
                <td className="px-2.5 py-2 tabular">{r.total.target}</td>
                <td className="px-2.5 py-2 tabular font-semibold">{r.total.achieved}</td>
                <td className="px-2.5 py-2 tabular">{r.total.pct == null ? "—" : `${r.total.pct}%`}</td>
                <td className={cn("px-2.5 py-2 tabular font-extrabold", r.gap > 0 ? "text-rose-600" : "text-emerald-600")}>{r.gap > 0 ? r.gap : 0}</td>
                <td className="px-2.5 py-2"><span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-bold", STATUS_TONE[r.status] ?? "bg-slate-100 text-slate-600")}>{r.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.dataQuality && data.dataQuality.length > 0 && (
        <p className="text-[10.5px] text-amber-600 mt-2">⚠ {data.dataQuality.join(" · ")}</p>
      )}
    </section>
  );
}
