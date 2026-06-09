"use client";

// My Plan — LIVE. The caller's own scheduled activities from the backend
// (/api/activities?mine=true), with the real row state machine: Complete
// (enter Salesforce ID) and Reschedule both POST to the backend, which enforces
// the SV-/TS- prefix, attendance, and the reschedule slip limit. No mock store.

import { useCallback, useEffect, useState } from "react";
import { CalendarClock, CheckCircle2, RotateCcw, X } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeActivity } from "@/lib/api/surfaces";

const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const OPEN = new Set(["planned", "scheduled", "assigned_to_partner", "partner_scheduled", "in_progress"]);

export function MyPlanLive() {
  const [rows, setRows] = useState<BeActivity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<{ id: string; mode: "complete" | "reschedule" } | null>(null);
  const [field, setField] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    // Active only — completed/closed work lives in the Completed Activities Log.
    fetch("/api/activities?mine=true&statusGroup=active&pageSize=100", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setRows(j.data as BeActivity[]); else setError(j.error || "Could not load your plan"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  const submit = async (a: BeActivity) => {
    if (!editing) return;
    setBusy(true); setError(null);
    try {
      const body = editing.mode === "complete"
        ? { salesforceId: field.trim() }
        : { scheduledDate: field, reason: "Rescheduled from My Plan" };
      const res = await fetch(`/api/activities/${a.id}/${editing.mode}`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const j = await res.json();
      if (j.live) { setEditing(null); setField(""); load(); }
      else setError(j.error || "The action was rejected");
    } catch { setError("Could not reach the server"); }
    setBusy(false);
  };

  const open = rows?.filter((r) => OPEN.has(r.status)) ?? [];
  const rest = rows?.filter((r) => !OPEN.has(r.status)) ?? [];

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><CalendarClock size={14} /> My Plan · scheduled work</h2>
        <a href="/completed-activities" className="text-[10.5px] font-bold text-[var(--color-edify-primary)] hover:underline">View Completed Log →</a>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error && !rows ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !rows || rows.length === 0 ? (
        <EmptyState compact title="Nothing scheduled" message="Activities you schedule appear here with their next action." />
      ) : (
        <>
          {error && <div className="mb-2 text-[11px] text-rose-600 font-semibold">{error}</div>}
          <p className="text-[11.5px] muted mb-2">{open.length} to do · {rest.length} waiting on me</p>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {[...open, ...rest].map((a) => (
              <li key={a.id} className="py-2 text-[12px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0">
                    <span className="font-bold">{titleCase(a.activityType)}</span>
                    <span className={cn("ml-1.5 px-1 py-px rounded text-[8.5px] font-bold uppercase", OPEN.has(a.status) ? "bg-sky-100 text-sky-700" : "bg-slate-100 text-slate-500")}>{titleCase(a.status)}</span>
                    <span className="block muted truncate">{a.school?.name ?? "cluster"}{a.scheduledDate ? ` · ${new Date(a.scheduledDate).toLocaleDateString()}` : ""}</span>
                  </span>
                  {OPEN.has(a.status) && (
                    <span className="inline-flex items-center gap-1 shrink-0">
                      <button onClick={() => { setEditing({ id: a.id, mode: "complete" }); setField(""); }} className="inline-flex items-center gap-1 h-7 px-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-[10.5px] font-bold"><CheckCircle2 size={11} /> Complete</button>
                      <button onClick={() => { setEditing({ id: a.id, mode: "reschedule" }); setField(""); }} className="inline-flex items-center gap-1 h-7 px-2 rounded-lg border border-[var(--color-edify-border)] hover:bg-[var(--surface-3)] text-[10.5px] font-bold"><RotateCcw size={11} /></button>
                    </span>
                  )}
                </div>
                {editing?.id === a.id && (
                  <div className="mt-2 flex items-center gap-1.5">
                    <input
                      autoFocus
                      type={editing.mode === "reschedule" ? "date" : "text"}
                      value={field}
                      onChange={(e) => setField(e.target.value)}
                      placeholder={editing.mode === "complete" ? "Salesforce ID (SV- or TS-)" : ""}
                      className="flex-1 px-2 py-1 rounded border border-[var(--color-edify-border)] text-[11px]"
                    />
                    <button disabled={busy || !field.trim()} onClick={() => submit(a)} className="h-7 px-2.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[10.5px] font-bold disabled:opacity-50">Save</button>
                    <button onClick={() => { setEditing(null); setField(""); }} className="h-7 w-7 grid place-items-center rounded-lg border border-[var(--color-edify-border)]"><X size={12} /></button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
