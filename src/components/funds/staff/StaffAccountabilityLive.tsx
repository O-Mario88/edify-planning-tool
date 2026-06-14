"use client";

// Fund Accountability (owner close-out) — LIVE. After the accountant disburses a
// fund request, the requester accounts for it: enter the NetSuite Expense ID +
// what was spent, and the balance is returned. Posts to the real backend
// (/api/fund-requests/:id/account); the backend re-checks owner + disbursed +
// the NetSuite-ID lock (an approved accountability is frozen). No mock.

import { useCallback, useEffect, useState } from "react";
import { Receipt, Loader2, CheckCircle2, Lock } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { isValidId, ID_FORMATS } from "@/lib/intake/id-formats";
import type { BeFundRequest } from "@/lib/api/surfaces";

const ugx = (n: number) => `UGX ${Math.round(n || 0).toLocaleString()}`;
const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const periodLabel = (key: string) => {
  const m = key.match(/-M(\d+)$/); if (m) return `${MONTHS[Number(m[1])]} ${key.slice(0, 4)}`;
  const q = key.match(/-(Q\d)$/); if (q) return `${q[1]} ${key.slice(0, 4)}`;
  return key;
};

function AccountabilityCard({ r, onDone }: { r: BeFundRequest; onDone: () => void }) {
  const disbursed = r.disbursedAmount ?? r.totalAmount ?? 0;
  const [netsuiteId, setNetsuiteId] = useState(r.accountabilityNetsuiteId ?? "");
  const [spent, setSpent] = useState<string>(String(r.accountedAmount ?? disbursed));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const status = r.accountabilityStatus ?? "none";
  const locked = status === "approved";
  const pending = status === "submitted";
  const spentNum = Number(spent);
  const returned = Math.max(0, disbursed - (Number.isFinite(spentNum) ? spentNum : 0));
  const idOk = isValidId("expense", netsuiteId);
  const canSubmit = idOk && Number.isFinite(spentNum) && spentNum > 0 && !busy;

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const res = await fetch(`/api/fund-requests/${r.id}/account`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ netsuiteId: netsuiteId.trim(), amountSpent: spentNum, amountReturned: returned }),
      });
      const j = await res.json();
      if (j.live) onDone();
      else setErr(j.error || "The accountability was rejected.");
    } catch { setErr("Could not reach the server."); }
    setBusy(false);
  };

  return (
    <li className="rounded-lg border border-[var(--color-edify-border)] overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2.5 bg-[var(--color-edify-soft)]/20">
        <Receipt size={14} className="shrink-0 muted" />
        <span className="min-w-0 flex-1">
          <span className="block text-[12.5px] font-bold truncate">{periodLabel(r.periodKey)} · {r.scope}</span>
          <span className="block text-[10.5px] muted truncate">Disbursed {ugx(disbursed)}{r.disburseReference ? ` · ref ${r.disburseReference}` : ""}</span>
        </span>
        {locked && <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 shrink-0"><Lock size={11} /> Closed</span>}
        {pending && <span className="text-[10px] font-bold text-amber-700 shrink-0">Pending review</span>}
      </div>

      {locked ? (
        <p className="px-3 py-2.5 text-[11px] muted border-t border-[var(--color-edify-divider)]">
          Accounted {ugx(r.accountedAmount ?? 0)} · returned {ugx(r.returnedAmount ?? 0)} · NetSuite {r.accountabilityNetsuiteId}. Approved and locked.
        </p>
      ) : pending ? (
        <p className="px-3 py-2.5 text-[11px] muted border-t border-[var(--color-edify-divider)]">
          Submitted (NetSuite {r.accountabilityNetsuiteId}) — awaiting your supervisor&apos;s approval.
        </p>
      ) : (
        <div className="px-3 py-2.5 border-t border-[var(--color-edify-divider)] space-y-2">
          {status === "returned" && <p className="text-[10.5px] text-sky-700 font-semibold">Returned for correction — resubmit below.</p>}
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="block text-[10px] font-bold uppercase tracking-wide muted mb-0.5">NetSuite Expense ID</span>
              <input
                value={netsuiteId} onChange={(e) => setNetsuiteId(e.target.value)}
                placeholder={ID_FORMATS.expense.example} inputMode="numeric"
                className="w-full h-9 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[12px] font-semibold"
              />
              {netsuiteId && !idOk && <span className="block text-[9.5px] text-rose-600 mt-0.5">{ID_FORMATS.expense.hint}</span>}
            </label>
            <label className="block">
              <span className="block text-[10px] font-bold uppercase tracking-wide muted mb-0.5">Amount spent (UGX)</span>
              <input
                value={spent} onChange={(e) => setSpent(e.target.value.replace(/[^\d]/g, ""))}
                inputMode="numeric"
                className="w-full h-9 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[12px] font-semibold tabular"
              />
            </label>
          </div>
          <p className="text-[10.5px] muted">Returned to treasury: <span className="font-bold tabular">{ugx(returned)}</span></p>
          {err && <p className="text-[11px] text-rose-600 font-semibold">{err}</p>}
          <button
            disabled={!canSubmit} onClick={submit}
            className="w-full inline-flex items-center justify-center gap-1 h-9 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11.5px] font-bold disabled:opacity-50"
          >
            {busy ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />} Submit accountability
          </button>
        </div>
      )}
    </li>
  );
}

export function StaffAccountabilityLive() {
  const [rows, setRows] = useState<BeFundRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    fetch("/api/fund-requests", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (j.live) setRows((j.requests as BeFundRequest[]).filter((r) => r.status === "disbursed" && (r.isOwn ?? true)));
        else setError(j.error || "Could not load your disbursed funds");
      })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Receipt size={14} /> Account for Disbursed Funds</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live</span>
      </header>
      {loading ? <LoadingState compact />
        : error ? <ErrorState compact message={error} onRetry={load} />
        : !rows || rows.length === 0 ? <EmptyState compact title="Nothing to account for" message="Once the accountant disburses a fund request you submitted, it appears here to close out with a NetSuite Expense ID." />
        : <ul className="space-y-1.5">{rows.map((r) => <AccountabilityCard key={r.id} r={r} onDone={load} />)}</ul>}
    </section>
  );
}
