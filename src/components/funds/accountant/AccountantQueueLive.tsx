"use client";

// Accountant payment queue — LIVE. Partner-delivered work that is IA-confirmed
// and ready to pay, from /api/activities/payment-queue. Clearing posts
// /api/activities/:id/clear-payment, which the backend gates: evidence accepted
// AND Salesforce ID AND IA confirmed — payment can never bypass verification.

import { useCallback, useEffect, useState } from "react";
import { Wallet, CheckCircle2, Lock } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BePaymentQueueRow } from "@/lib/api/surfaces";

const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function AccountantQueueLive() {
  const [rows, setRows] = useState<BePaymentQueueRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    fetch("/api/activities/payment-queue", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setRows(j.rows as BePaymentQueueRow[]); else setError(j.error || "Could not load the payment queue"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  const clear = async (id: string) => {
    setBusy(id);
    try {
      const res = await fetch(`/api/activities/${id}/clear-payment`, { method: "POST", credentials: "include" });
      const j = await res.json();
      if (j.live) setRows((prev) => prev?.filter((r) => r.id !== id) ?? null);
      else setError(j.error || "Payment was rejected (verification incomplete)");
    } catch { setError("Could not reach the server"); }
    setBusy(null);
  };

  const ready = rows?.filter((r) => r.ready) ?? [];
  const blocked = rows?.filter((r) => !r.ready) ?? [];

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Wallet size={14} /> Verified work ready for payment</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · IA-gated</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !rows || rows.length === 0 ? (
        <EmptyState compact title="Nothing to pay" message="No partner payments are in the pipeline. IA-confirmed work appears here automatically." />
      ) : (
        <>
          <p className="text-[11.5px] muted mb-2.5">{ready.length} ready to clear{blocked.length > 0 ? `, ${blocked.length} still blocked by verification` : ""}.</p>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {[...ready, ...blocked].map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-2 py-2 text-[12px]">
                <span className="min-w-0">
                  <span className="font-bold">{titleCase(a.activityType)}</span>
                  <span className="block muted truncate">{a.school?.name ?? "—"} · {a.assignedPartner?.name ?? "partner"} · <span className="font-mono">{a.salesforceActivityId ?? "no SF id"}</span></span>
                </span>
                {a.ready ? (
                  <button
                    disabled={busy === a.id}
                    onClick={() => clear(a.id)}
                    className="inline-flex items-center gap-1 h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11.5px] font-bold whitespace-nowrap shrink-0 disabled:opacity-50"
                  >
                    <CheckCircle2 size={12} /> Clear payment
                  </button>
                ) : (
                  <span className={cn("inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-amber-200 bg-amber-50 text-amber-700 text-[10.5px] font-bold whitespace-nowrap shrink-0")} title="Awaiting evidence / Salesforce ID / IA confirmation">
                    <Lock size={11} /> Not verified
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
