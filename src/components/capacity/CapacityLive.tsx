"use client";

// CapacityLive — backend-driven direct-support capacity. Self-fetches
// /api/staff-capacity (→ /assignment/capacity): the staff's max schools, used,
// and remaining for direct support, with at/near-limit flags. No mock.

import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeStaffCapacity } from "@/lib/api/surfaces";

export function CapacityLive({ staffId }: { staffId?: string }) {
  const [cap, setCap] = useState<BeStaffCapacity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true); setError(null);
    fetch(`/api/staff-capacity${staffId ? `?staffId=${encodeURIComponent(staffId)}` : ""}`, { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setCap(j as BeStaffCapacity); else setError(j.error || "Could not load capacity"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, [staffId]);

  if (loading) return <LoadingState compact />;
  if (error) return <ErrorState compact message={error} onRetry={load} />;
  if (!cap) return <EmptyState compact title="No capacity record" message="Direct-support capacity appears once schools are assigned." />;

  const pct = cap.max ? Math.min(100, Math.round((cap.used / cap.max) * 100)) : 0;
  const tone = cap.atLimit ? "rose" : cap.nearLimit ? "amber" : "emerald";

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5">
        <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Users size={14} /> Direct-support capacity <span className="muted font-semibold">· FY {cap.fy}</span></h3>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>
      <div className="flex items-end gap-3 mb-2">
        <div className="text-[28px] font-extrabold tabular leading-none">{cap.used}<span className="text-[16px] muted">/{cap.max}</span></div>
        <div className="text-[12px] muted pb-1">schools in direct support · <span className="font-extrabold text-[var(--color-edify-text)]">{cap.remaining}</span> remaining</div>
      </div>
      <div className="h-2.5 rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
        <div className={cn("h-full rounded-full transition-all",
          tone === "rose" ? "bg-rose-500" : tone === "amber" ? "bg-amber-500" : "bg-emerald-500")} style={{ width: `${pct}%` }} />
      </div>
      {cap.atLimit && <p className="text-[11px] text-rose-600 font-semibold mt-2">At limit — route new school support to a partner.</p>}
      {!cap.atLimit && cap.nearLimit && <p className="text-[11px] text-amber-600 font-semibold mt-2">Near limit ({pct}%) — plan partner delivery for new schools.</p>}
    </section>
  );
}
