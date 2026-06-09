"use client";

// Fund Approval Queue — LIVE master-detail. Clicking a queue item updates the
// detail panel dynamically (selectedFundRequestId) — the previous bug was a
// static panel. Backend-driven (/api/fund-requests), role-scoped; approve /
// return / reject act on the SELECTED request only.

import { useCallback, useEffect, useState } from "react";
import { Wallet, CheckCircle2, RotateCcw, XCircle, Inbox } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeFundRequest } from "@/lib/api/surfaces";

const ugx = (n: number) => `UGX ${Math.round(n).toLocaleString()}`;
const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const periodLabel = (p: string, key: string) => {
  const m = key.match(/-M(\d+)$/); if (m) return `${MONTHS[Number(m[1])]} ${key.slice(0, 4)}`;
  const q = key.match(/-(Q\d)$/); if (q) return `${q[1]} ${key.slice(0, 4)}`;
  return p === "weekly" ? `Weekly · ${key.slice(0, 4)}` : key;
};
const statusTone: Record<string, string> = {
  submitted: "bg-amber-100 text-amber-700", approved: "bg-emerald-100 text-emerald-700",
  returned: "bg-sky-100 text-sky-700", rejected: "bg-rose-100 text-rose-700", disbursed: "bg-violet-100 text-violet-700",
};

export function FundApprovalQueueLive() {
  const [rows, setRows] = useState<BeFundRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    fetch("/api/fund-requests", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (j.live) { setRows(j.requests as BeFundRequest[]); }
        else setError(j.error || "Could not load fund requests");
      })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  const selected = rows?.find((r) => r.id === selectedId) ?? null;

  const act = async (action: "approve" | "return" | "reject") => {
    if (!selected) return;
    setBusy(true); setActionErr(null);
    try {
      const res = await fetch(`/api/fund-requests/${selected.id}/${action}`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
      });
      const j = await res.json();
      if (j.live) load();
      else setActionErr(j.error || "The action was rejected");
    } catch { setActionErr("Could not reach the server"); }
    setBusy(false);
  };

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Wallet size={14} /> Fund Approval Queue</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · scoped</span>
      </header>

      {loading ? <LoadingState compact />
        : error ? <ErrorState compact message={error} onRetry={load} />
        : !rows || rows.length === 0 ? <EmptyState compact title="No fund requests in your queue" message="Submitted fund requests awaiting review appear here." />
        : (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.2fr] gap-3">
          {/* Queue */}
          <ul className="space-y-1 max-h-[22rem] overflow-y-auto pr-0.5">
            {rows.map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => { setSelectedId(r.id); setActionErr(null); }}
                  className={cn("w-full text-left rounded-lg border p-2.5 transition-colors",
                    selectedId === r.id ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-soft)]/40" : "border-[var(--color-edify-border)] hover:bg-[var(--surface-3)]")}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12px] font-bold truncate">{r.submittedBy}</span>
                    <span className={cn("px-1.5 py-0.5 rounded text-[8.5px] font-bold uppercase shrink-0", statusTone[r.status])}>{r.status}</span>
                  </div>
                  <div className="flex items-center justify-between gap-2 mt-0.5">
                    <span className="text-[10.5px] muted">{r.submittedByRole} · {periodLabel(r.period, r.periodKey)}</span>
                    <span className="text-[11.5px] font-extrabold tabular">{ugx(r.totalAmount)}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>

          {/* Detail */}
          <div className="rounded-lg border border-[var(--color-edify-border)] p-3 bg-[var(--color-edify-soft)]/20 min-h-[14rem]">
            {!selected ? (
              <div className="h-full grid place-items-center text-center py-8">
                <div className="text-[12px] muted inline-flex flex-col items-center gap-1.5"><Inbox size={20} className="text-slate-300" /> Select a fund request to view details.</div>
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between gap-2 mb-1">
                  <h3 className="text-[14px] font-extrabold">{selected.submittedBy}</h3>
                  <span className={cn("px-2 py-0.5 rounded-full text-[9.5px] font-bold uppercase", statusTone[selected.status])}>{selected.status}</span>
                </div>
                <div className="text-[24px] font-extrabold tabular leading-none mb-2.5">{ugx(selected.totalAmount)}</div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11.5px]">
                  <Row k="Role" v={selected.submittedByRole} />
                  <Row k="Scope" v={selected.scope} />
                  <Row k="Period" v={periodLabel(selected.period, selected.periodKey)} />
                  <Row k="FY" v={selected.fy} />
                  <Row k="Activities" v={`${selected.activityCount} costed`} />
                  <Row k="Submitted" v={new Date(selected.createdAt).toLocaleDateString()} />
                </dl>
                {selected.reviewNote && <p className="mt-2 text-[10.5px] muted italic">Note: {selected.reviewNote}</p>}
                {actionErr && <p className="mt-2 text-[11px] text-rose-600 font-semibold">{actionErr}</p>}
                {selected.status === "submitted" && (
                  <div className="flex gap-1.5 mt-3">
                    <button disabled={busy} onClick={() => act("approve")} className="flex-1 inline-flex items-center justify-center gap-1 h-9 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11.5px] font-bold disabled:opacity-50"><CheckCircle2 size={13} /> Approve</button>
                    <button disabled={busy} onClick={() => act("return")} className="inline-flex items-center justify-center gap-1 h-9 px-3 rounded-lg border border-sky-300 text-sky-700 hover:bg-sky-50 text-[11.5px] font-bold disabled:opacity-50"><RotateCcw size={13} /> Return</button>
                    <button disabled={busy} onClick={() => act("reject")} className="inline-flex items-center justify-center gap-1 h-9 px-3 rounded-lg border border-rose-300 text-rose-700 hover:bg-rose-50 text-[11.5px] font-bold disabled:opacity-50"><XCircle size={13} /> Reject</button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-[9px] uppercase tracking-wide muted font-semibold">{k}</dt>
      <dd className="font-semibold capitalize">{v}</dd>
    </div>
  );
}
