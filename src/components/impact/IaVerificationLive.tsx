"use client";

// IA verification queue — LIVE. The activities awaiting IA confirmation
// (Salesforce ID entered, evidence accepted), straight from the backend
// (/api/activities?status=awaiting_ia_verification). Confirming posts
// /api/activities/:id/ia-confirm, which the backend gates (IA only) and which
// moves the activity into the accountant's payment queue. No mock.

import { useCallback, useEffect, useState } from "react";
import { ShieldCheck, CheckCircle2, ArrowRight } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeActivity } from "@/lib/api/surfaces";

const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function IaVerificationLive() {
  const [rows, setRows] = useState<BeActivity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

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
      const res = await fetch(`/api/activities/${id}/ia-confirm`, { method: "POST", credentials: "include" });
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
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · scoped</span>
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
              <li key={a.id} className="flex items-center justify-between gap-2 py-2 text-[12px]">
                <span className="min-w-0">
                  <span className="font-bold">{titleCase(a.activityType)}</span>
                  <span className={cn("ml-1.5 px-1 py-px rounded text-[8.5px] font-bold uppercase", a.deliveryType === "partner" ? "bg-violet-100 text-violet-700" : "bg-sky-100 text-sky-700")}>{a.deliveryType}</span>
                  <span className="block muted truncate">{a.school?.name ?? "—"} · <span className="font-mono">{a.salesforceActivityId ?? "no SF id"}</span></span>
                </span>
                <button
                  disabled={busy === a.id}
                  onClick={() => confirm(a.id)}
                  className="inline-flex items-center gap-1 h-8 px-3 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-[11.5px] font-bold whitespace-nowrap shrink-0 disabled:opacity-50"
                >
                  <CheckCircle2 size={12} /> Confirm <ArrowRight size={11} />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
