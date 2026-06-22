"use client";

// CD oversight view of the payment pipeline — read-only. The Country Director
// monitors verified work and disbursement status; only the Accountant clears payments.

import { useCallback, useEffect, useState } from "react";
import { Wallet, Lock, CheckCircle2 } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BePaymentQueueRow } from "@/lib/api/surfaces";

const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function AccountantOversightLive() {
  const [rows, setRows] = useState<BePaymentQueueRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    fetch("/api/activities/payment-queue", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setRows(j.rows as BePaymentQueueRow[]); else setError(j.error || "Could not load payment pipeline"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, []);

  const ready = rows?.filter((r) => r.ready) ?? [];
  const blocked = rows?.filter((r) => !r.ready) ?? [];

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Wallet size={14} /> Payment pipeline (oversight)</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · read-only</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !rows || rows.length === 0 ? (
        <EmptyState compact title="No payments in pipeline" message="Partner payments appear here once work is scheduled and verified." />
      ) : (
        <>
          <p className="text-[11.5px] muted mb-2.5">
            {ready.length} ready for accountant clearance · {blocked.length} blocked by IA / evidence / Salesforce ID
          </p>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {[...ready, ...blocked].slice(0, 12).map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-2 py-2 text-[12px]">
                <span className="min-w-0">
                  <span className="font-bold">{titleCase(a.activityType)}</span>
                  <span className="block muted truncate">{a.school?.name ?? "—"} · {a.assignedPartner?.name ?? "partner"}</span>
                </span>
                {a.ready ? (
                  <span className="inline-flex items-center gap-1 text-[10.5px] font-bold text-emerald-700">
                    <CheckCircle2 size={11} /> Ready to pay
                  </span>
                ) : (
                  <span className={cn("inline-flex items-center gap-1 text-[10.5px] font-bold text-amber-700")}>
                    <Lock size={11} /> Awaiting verification
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
