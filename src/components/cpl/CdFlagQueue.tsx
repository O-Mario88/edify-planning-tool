"use client";

import { useCallback, useEffect, useState } from "react";
import { Flag, Check, Eye } from "lucide-react";

// The PL's inbound "Flagged by your Country Director" queue. The CD monitors +
// flags; the PL acts (plans/assigns through the normal planning workflow) and
// acknowledges/resolves here. Backend-driven; renders nothing when none.
type CdFlagItem = {
  id: string; raisedByName?: string | null; category: string; scopeName?: string | null;
  note: string; recommendedAction?: string | null; priority: string; status: string; createdAt: string;
};

const CAT_LABEL: Record<string, string> = {
  ssa: "Weak SSA", target: "Behind target", partner: "Partner", staff: "Staff risk",
  cluster: "Cluster gap", fund: "Fund delay", evidence: "Evidence backlog",
  data_quality: "Data quality", core_package: "Core package", general: "Issue",
};

export function CdFlagQueue() {
  const [flags, setFlags] = useState<CdFlagItem[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    fetch("/api/flags", { credentials: "include" })
      .then((r) => r.json())
      .then((d) => setFlags(d.live && Array.isArray(d.flags) ? d.flags : []))
      .catch(() => setFlags([]));
  }, []);
  useEffect(load, [load]);

  const act = useCallback(async (id: string, action: "acknowledge" | "resolve") => {
    setBusy(id);
    try {
      await fetch(`/api/flags/${id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ action }),
      });
      load();
    } finally { setBusy(null); }
  }, [load]);

  // Nothing to show (backend off or no open flags) → render nothing.
  const open = (flags ?? []).filter((f) => f.status !== "resolved");
  if (!flags || open.length === 0) return null;

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50/40 p-4 dark:border-amber-900/50 dark:bg-amber-950/20">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300">
        <Flag className="h-3.5 w-3.5" /> Flagged by your Country Director · {open.length}
      </div>
      <ul className="mt-2 space-y-2">
        {open.map((f) => (
          <li key={f.id} className="rounded-lg border border-amber-200/70 bg-white p-2.5 dark:border-amber-900/40 dark:bg-slate-900/40">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded-md bg-slate-900 px-1.5 py-px text-[10px] font-semibold text-white dark:bg-slate-100 dark:text-slate-900">{CAT_LABEL[f.category] ?? f.category}</span>
              {f.scopeName && <span className="text-xs font-medium text-[var(--text-primary)]">{f.scopeName}</span>}
              {(f.priority === "high" || f.priority === "urgent") && <span className="text-[10px] font-semibold uppercase text-rose-500">{f.priority}</span>}
              {f.status === "acknowledged" && <span className="text-[10px] uppercase text-sky-600">acknowledged</span>}
            </div>
            <p className="mt-1 text-sm text-[var(--text-primary)]">{f.note}</p>
            {f.recommendedAction && <p className="mt-0.5 text-xs muted">Recommended: {f.recommendedAction}</p>}
            <div className="mt-1.5 flex items-center gap-1.5">
              {f.status === "open" && (
                <button onClick={() => act(f.id, "acknowledge")} disabled={busy === f.id} className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-[11px] font-semibold disabled:opacity-50 dark:border-slate-700">
                  <Eye className="h-3 w-3" /> Acknowledge
                </button>
              )}
              <button onClick={() => act(f.id, "resolve")} disabled={busy === f.id} className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2 py-1 text-[11px] font-semibold text-white disabled:opacity-50">
                <Check className="h-3 w-3" /> Mark resolved
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
