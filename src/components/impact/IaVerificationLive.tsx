"use client";

// IA verification queue — LIVE. The activities awaiting IA confirmation
// (Salesforce ID entered, evidence accepted), straight from the backend
// (/api/activities?status=awaiting_ia_verification). Confirming posts
// /api/activities/:id/ia-confirm, which the backend gates (IA only) and which
// moves the activity into the accountant's payment queue. No mock.

import { useCallback, useEffect, useState } from "react";
import { ShieldCheck, CheckCircle2, ArrowRight, FileText, Paperclip, Loader2 } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import { csrfHeaders } from "@/lib/csrf-client";
import type { BeActivity } from "@/lib/api/surfaces";

const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

type EvItem = { id: string; kind: string; status: string; originalName: string | null; mimeType: string | null };

export function IaVerificationLive() {
  const [rows, setRows] = useState<BeActivity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Record<string, EvItem[]>>({});
  const [evOpen, setEvOpen] = useState<string | null>(null);
  const [evBusy, setEvBusy] = useState<string | null>(null);

  const toggleEvidence = async (activityId: string) => {
    if (evOpen === activityId) { setEvOpen(null); return; }
    setEvOpen(activityId);
    if (!evidence[activityId]) {
      setEvBusy(activityId);
      try {
        const j = await fetch(`/api/evidence/activity/${activityId}`, { credentials: "include" }).then((r) => r.json());
        setEvidence((m) => ({ ...m, [activityId]: (j.evidence ?? []) as EvItem[] }));
      } catch { setEvidence((m) => ({ ...m, [activityId]: [] })); }
      setEvBusy(null);
    }
  };

  const load = useCallback(() => {
    setLoading(true); setError(null);
    fetch("/api/activities?status=awaiting_ia_verification&pageSize=100", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setRows(j.data as BeActivity[]); else setError(j.error || "Could not load the IA queue"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  const confirm = async (id: string) => {
    setBusy(id);
    try {
      const res = await fetch(`/api/activities/${id}/ia-confirm`, { method: "POST", credentials: "include", headers: { ...csrfHeaders() } });
      const j = await res.json();
      if (j.live) setRows((prev) => prev?.filter((r) => r.id !== id) ?? null);
      else setError(j.error || "Confirm was rejected");
    } catch { setError("Could not reach the server"); }
    setBusy(null);
  };

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><ShieldCheck size={14} /> Work waiting for IA confirmation</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · scoped</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !rows || rows.length === 0 ? (
        <EmptyState compact title="Queue clear" message="No activities are waiting for IA confirmation right now." />
      ) : (
        <>
          <p className="text-[11.5px] muted mb-2.5">{rows.length} activit{rows.length === 1 ? "y" : "ies"} with a Salesforce ID, awaiting your confirmation. Confirming releases the work to the accountant.</p>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {rows.map((a) => (
              <li key={a.id} className="py-2 text-[12px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0">
                    <span className="font-bold">{titleCase(a.activityType)}</span>
                    <span className={cn("ml-1.5 px-1 py-px rounded text-[8.5px] font-bold uppercase", a.deliveryType === "partner" ? "bg-violet-100 text-violet-700" : "bg-sky-100 text-sky-700")}>{a.deliveryType}</span>
                    <span className="block muted truncate">{a.school?.name ?? "—"} · <span className="font-mono">{a.salesforceActivityId ?? "no SF id"}</span></span>
                  </span>
                  <span className="flex items-center gap-1.5 shrink-0">
                    {/* Open the evidence BEFORE confirming — the IA must see the proof. */}
                    <button
                      onClick={() => toggleEvidence(a.id)}
                      className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:bg-[var(--surface-3)] text-[11px] font-bold whitespace-nowrap"
                    >
                      {evBusy === a.id ? <Loader2 size={12} className="animate-spin" /> : <Paperclip size={12} />} Evidence
                    </button>
                    <button
                      disabled={busy === a.id}
                      onClick={() => confirm(a.id)}
                      className="inline-flex items-center gap-1 h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11.5px] font-bold whitespace-nowrap disabled:opacity-50"
                    >
                      <CheckCircle2 size={12} /> Confirm <ArrowRight size={11} />
                    </button>
                  </span>
                </div>
                {evOpen === a.id && (
                  <div className="mt-1.5 ml-1 pl-3 border-l-2 border-[var(--color-edify-divider)]">
                    {evBusy === a.id ? (
                      <p className="text-[11px] muted py-1">Loading evidence…</p>
                    ) : (evidence[a.id]?.length ?? 0) === 0 ? (
                      <p className="text-[11px] text-amber-600 font-semibold py-1">No evidence uploaded — confirm only if this activity needs none.</p>
                    ) : (
                      <ul className="space-y-1 py-1">
                        {evidence[a.id].map((ev) => (
                          <li key={ev.id} className="flex items-center justify-between gap-2">
                            <span className="inline-flex items-center gap-1.5 min-w-0 muted">
                              <FileText size={12} className="shrink-0" />
                              <span className="truncate">{ev.originalName ?? ev.kind}</span>
                              <span className="px-1 py-px rounded bg-[var(--color-edify-soft)] text-[8.5px] font-bold uppercase shrink-0">{ev.status}</span>
                            </span>
                            <a href={`/api/evidence/${ev.id}/file`} target="_blank" rel="noopener noreferrer" className="text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline shrink-0">Open</a>
                          </li>
                        ))}
                      </ul>
                    )}
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
