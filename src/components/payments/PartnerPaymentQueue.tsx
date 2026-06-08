"use client";

// Partner-to-payment queue (accountant).
//
// The terminal gate of the school improvement OS: partner-delivered activities
// that have cleared IA verification. Payment is BLOCKED — and the backend
// re-enforces this — until evidence is accepted, a Salesforce ID is entered,
// and IA has confirmed. Spec §10: "No IA confirmation, no payment."
//
// Salesforce ID convention surfaced here: visits = SV-•••, training / cluster
// meeting / SIT = TS-•••. The accountant clears each row to mark it paid.

import { useEffect, useState, useCallback } from "react";
import { Wallet, CheckCircle2, ShieldCheck, FileCheck2, Hash, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BePaymentQueueRow } from "@/lib/api/surfaces";

function GateChip({ ok, label, Icon }: { ok: boolean; label: string; Icon: typeof ShieldCheck }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9.5px] font-bold border",
        ok ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-slate-100 text-slate-400 border-slate-200",
      )}
      title={label}
    >
      <Icon size={10} /> {label}
    </span>
  );
}

export function PartnerPaymentQueue() {
  const [rows, setRows] = useState<BePaymentQueueRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [off, setOff] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/payments", { credentials: "include" });
      const j = await res.json();
      if (j.live) { setRows(j.rows ?? []); setOff(false); } else { setOff(true); }
    } catch { setOff(true); }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const clear = useCallback(async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      const res = await fetch("/api/payments", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ activityId: id }),
      });
      const j = await res.json();
      if (j.paymentStatus === "paid") {
        setRows((prev) => prev.filter((r) => r.id !== id));
      } else {
        setError(j.error || "Could not clear this payment.");
      }
    } catch {
      setError("Could not reach the payment service.");
    }
    setBusy(null);
  }, []);

  if (off) return null;

  const readyCount = rows.filter((r) => r.ready).length;

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <Wallet size={14} /> Partner payment queue
          {rows.length > 0 && <span className="muted font-semibold">· {readyCount} ready</span>}
        </h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">
          Live · scoped · IA-gated
        </span>
      </header>

      {error && <p className="mb-2 text-[11px] font-semibold text-rose-600 bg-rose-50 border border-rose-200 rounded px-2 py-1">{error}</p>}

      {loading ? (
        <div className="py-8 text-center text-[12px] muted">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="py-8 text-center text-[12px] muted">No partner activities awaiting payment. Cleared payments leave the queue.</div>
      ) : (
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-[11px] px-1 border-separate border-spacing-y-1">
            <thead>
              <tr className="text-left muted font-bold uppercase tracking-wide text-[9.5px]">
                <th className="py-1 pr-2">School</th>
                <th className="py-1 px-2">Partner</th>
                <th className="py-1 px-2">Salesforce ID</th>
                <th className="py-1 px-2">Gates</th>
                <th className="py-1 pl-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const evOk = r.evidenceStatus === "accepted";
                const sfOk = !!r.salesforceActivityId;
                const iaOk = r.iaVerificationStatus === "confirmed";
                return (
                  <tr key={r.id} className="hover:bg-[var(--color-edify-soft)]/30">
                    <td className="py-1.5 pr-2">
                      <div className="font-semibold text-[11px] whitespace-nowrap">{r.school?.name ?? "—"}</div>
                      <div className="muted text-[9.5px] capitalize">{r.activityType?.replace(/_/g, " ")}</div>
                    </td>
                    <td className="py-1.5 px-2 text-[10.5px] whitespace-nowrap">{r.assignedPartner?.name ?? "—"}</td>
                    <td className="py-1.5 px-2">
                      {r.salesforceActivityId
                        ? <span className="inline-flex items-center gap-1 font-mono text-[10px] font-bold text-slate-700"><Hash size={10} />{r.salesforceActivityId}</span>
                        : <span className="muted text-[10px]">— missing —</span>}
                    </td>
                    <td className="py-1.5 px-2">
                      <div className="flex items-center gap-1 flex-wrap">
                        <GateChip ok={evOk} label="Evidence" Icon={FileCheck2} />
                        <GateChip ok={sfOk} label="SF ID" Icon={Hash} />
                        <GateChip ok={iaOk} label="IA" Icon={ShieldCheck} />
                      </div>
                    </td>
                    <td className="py-1.5 pl-2 text-right">
                      <button
                        onClick={() => void clear(r.id)}
                        disabled={!r.ready || busy === r.id}
                        className={cn(
                          "inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[10.5px] font-bold border transition-colors",
                          r.ready
                            ? "bg-emerald-600 text-white border-transparent hover:bg-emerald-700 disabled:opacity-60"
                            : "muted border-[var(--color-edify-border)] cursor-not-allowed",
                        )}
                        title={r.ready ? "Clear this payment" : "Blocked — evidence, Salesforce ID, and IA confirmation all required"}
                      >
                        {busy === r.id ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}
                        {r.ready ? "Clear payment" : "Blocked"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-[10.5px] muted">Payment is released only when evidence is accepted, a Salesforce ID is recorded, and IA has confirmed. Visits use <span className="font-mono">SV-•••</span>; training, cluster meetings, and SITs use <span className="font-mono">TS-•••</span>.</p>
    </section>
  );
}
