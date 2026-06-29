"use client";

import { useCallback, useEffect, useState } from "react";
import { Wallet, CheckCircle2, RotateCcw, XCircle, ChevronDown, ChevronRight, Loader2, Coins, UserCheck } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import { csrfHeaders } from "@/lib/csrf-client";

const ugx = (n: number) => `UGX ${Math.round(n).toLocaleString()}`;
const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const statusTone: Record<string, string> = {
  pending_responsible_confirmation: "bg-amber-100 text-amber-700",
  confirmed_for_advance: "bg-blue-100 text-blue-700",
  self_funded: "bg-indigo-100 text-indigo-700",
  not_requested: "bg-gray-100 text-gray-700",
  disbursed: "bg-emerald-100 text-emerald-700",
};

const statusLabel: Record<string, string> = {
  pending_responsible_confirmation: "Pending Confirmation",
  confirmed_for_advance: "Ready for Disbursement",
  self_funded: "Self Funded",
  not_requested: "Not Requested",
  disbursed: "Disbursed",
};

export function FundApprovalQueueLive({ canDisburse = false, canSubmit = false }: { canDisburse?: boolean; canSubmit?: boolean } = {}) {
  const [currentUser, setCurrentUser] = useState<{ id: string; role: string } | null>(null);
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, any>>({});
  const [detailBusy, setDetailBusy] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [disburseForm, setDisburseForm] = useState<{ id: string; method: string; reference: string; amount: number } | null>(null);

  useEffect(() => {
    fetch("/api/auth/me", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (j.id) setCurrentUser({ id: j.id, role: j.role || j.activeRole });
      })
      .catch(() => undefined);
  }, []);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    fetch("/api/fund-requests/weekly", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (Array.isArray(j)) setRows(j);
        else setError("Could not load weekly fund requests");
      })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  const toggle = async (r: any) => {
    setActionErr(null);
    setDisburseForm(null);
    if (openId === r.id) { setOpenId(null); return; }
    setOpenId(r.id);
    if (!detail[r.id]) {
      setDetailBusy(r.id);
      try {
        const res = await fetch(`/api/fund-requests/weekly/${r.id}`, { credentials: "include" });
        const j = await res.json();
        if (j.id) setDetail((d) => ({ ...d, [r.id]: j }));
      } catch { /* silent fallback */ }
      setDetailBusy(null);
    }
  };

  const act = async (r: any, action: "request-advance" | "self-funded" | "not-requested") => {
    setActionBusy(true); setActionErr(null);
    try {
      const res = await fetch(`/api/fund-requests/${r.id}/${action}`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json", ...csrfHeaders() }, body: JSON.stringify({}),
      });
      const j = await res.json();
      if (res.status === 200 || j.id) {
        setDetail((d) => { const n = { ...d }; delete n[r.id]; return n; });
        load();
      } else {
        setActionErr(j.error || j.message || "The action was rejected");
      }
    } catch { setActionErr("Could not reach the server"); }
    setActionBusy(false);
  };

  const submitDisburse = async () => {
    if (!disburseForm) return;
    setActionBusy(true); setActionErr(null);
    try {
      const res = await fetch(`/api/fund-requests/${disburseForm.id}/disburse`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          amount: disburseForm.amount,
          method: disburseForm.method,
          reference: disburseForm.reference,
        }),
      });
      const j = await res.json();
      if (res.status === 200 || j.id) {
        setDetail((d) => { const n = { ...d }; delete n[disburseForm.id]; return n; });
        setDisburseForm(null);
        load();
      } else {
        setActionErr(j.error || j.message || "The disbursement was rejected");
      }
    } catch { setActionErr("Could not reach the server"); }
    setActionBusy(false);
  };

  const isOwner = (r: any) => currentUser?.id === r.responsibleUser;

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Wallet size={14} /> Weekly Fund Requests Queue</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · actual schedule</span>
      </header>

      {loading ? <LoadingState compact />
        : error ? <ErrorState compact message={error} onRetry={load} />
        : !rows || rows.length === 0 ? <EmptyState compact title="No weekly requests found" message="Requests appear automatically when activities are scheduled. The CD Cost Catalogue is fetched to price each activity accurately." />
        : (
        <ul className="space-y-1.5">
          {rows.map((r) => {
            const open = openId === r.id;
            const d = detail[r.id];
            const isMyRequest = isOwner(r);
            return (
              <li key={r.id} className="rounded-lg border border-[var(--color-edify-border)] overflow-hidden">
                <button
                  onClick={() => toggle(r)}
                  className="w-full text-left flex items-center gap-2 px-3 py-2.5 hover:bg-[var(--surface-3)] transition-colors"
                >
                  {open ? <ChevronDown size={14} className="shrink-0 muted" /> : <ChevronRight size={14} className="shrink-0 muted" />}
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span className="text-[12.5px] font-bold truncate">{r.responsibleUserName}</span>
                      <span className={cn("px-1.5 py-0.5 rounded text-[8.5px] font-bold uppercase shrink-0", statusTone[r.status])}>
                        {statusLabel[r.status] || r.status}
                      </span>
                    </span>
                    <span className="block text-[10.5px] muted truncate">
                      Week Start: {r.weekStartDate} · FY {r.fy} {isMyRequest && "· (My Request)"}
                    </span>
                  </span>
                  <span className="text-[13px] font-extrabold tabular shrink-0">{ugx(r.totalAmount)}</span>
                </button>

                {open && (
                  <div className="border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/20 px-3 py-2.5">
                    {detailBusy === r.id && !d ? (
                      <div className="py-3"><LoadingState compact /></div>
                    ) : (
                      <>
                        <div className="text-[9.5px] font-bold uppercase tracking-wide muted mb-1.5">Itemized cost catalogue breakdown</div>
                        {d?.lines && d.lines.length > 0 ? (
                          <ul className="space-y-1.5 mb-2.5">
                            {d.lines.map((l: any) => (
                              <li key={l.id} className="rounded-md border border-[var(--color-edify-border)] bg-[var(--surface-1)] px-2.5 py-1.5 flex items-center justify-between gap-2 text-[11.5px]">
                                <span className="min-w-0">
                                  <span className="font-bold">{l.description}</span>
                                  <span className="muted"> · {titleCase(l.lineItemType)} (Qty: {l.quantity})</span>
                                </span>
                                <span className="font-extrabold tabular shrink-0">{ugx(l.totalCost)}</span>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-[11px] muted mb-2.5">No itemized lines available.</p>
                        )}

                        <div className="flex items-center justify-between text-[12.5px] font-extrabold border-t border-[var(--color-edify-divider)] pt-1.5">
                          <span>Total Requested</span><span className="tabular">{ugx(r.totalAmount)}</span>
                        </div>

                        {actionErr && <p className="mt-2 text-[11px] text-rose-600 font-semibold">{actionErr}</p>}

                        {isMyRequest && r.status === "pending_responsible_confirmation" && (
                          <div className="flex flex-col gap-1.5 mt-2.5">
                            <div className="text-[10px] font-bold text-amber-600 inline-flex items-center gap-1">
                              <UserCheck size={11} /> Confirm funding option for this week's plan:
                            </div>
                            <div className="flex gap-1.5">
                              <button disabled={actionBusy} onClick={() => act(r, "request-advance")} className="flex-1 inline-flex items-center justify-center gap-1 h-9 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11px] font-bold disabled:opacity-50">
                                {actionBusy ? <Loader2 size={12} className="animate-spin" /> : <Coins size={12} />} Request Advance
                              </button>
                              <button disabled={actionBusy} onClick={() => act(r, "self-funded")} className="flex-1 inline-flex items-center justify-center gap-1 h-9 rounded-lg border border-indigo-300 text-indigo-700 hover:bg-indigo-50 text-[11px] font-bold disabled:opacity-50">
                                Own Funds / Claim Later
                              </button>
                              <button disabled={actionBusy} onClick={() => act(r, "not-requested")} className="inline-flex items-center justify-center gap-1 h-9 px-3 rounded-lg border border-rose-300 text-rose-700 hover:bg-rose-50 text-[11px] font-bold disabled:opacity-50">
                                Do Not Request
                              </button>
                            </div>
                          </div>
                        )}

                        {canDisburse && r.status === "confirmed_for_advance" && !disburseForm && (
                          <button onClick={() => setDisburseForm({ id: r.id, method: "Mobile Money", reference: "", amount: r.totalAmount })} className="mt-2.5 w-full inline-flex items-center justify-center gap-1 h-9 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-[11.5px] font-bold">
                            Disburse funds
                          </button>
                        )}

                        {disburseForm && disburseForm.id === r.id && (
                          <div className="mt-2.5 p-3 rounded-lg border border-violet-200 bg-violet-50/50 space-y-2">
                            <div className="text-[11px] font-bold text-violet-800">Record Disbursement Details</div>
                            <div className="grid grid-cols-2 gap-2">
                              <label className="block text-[10px] font-bold text-violet-700">
                                Method
                                <select value={disburseForm.method} onChange={(e) => setDisburseForm({ ...disburseForm, method: e.target.value })} className="w-full h-8 px-1.5 rounded border border-violet-200 bg-white text-[11px] font-normal">
                                  <option value="Mobile Money">Mobile Money</option>
                                  <option value="Bank Transfer">Bank Transfer</option>
                                  <option value="Cash">Cash</option>
                                </select>
                              </label>
                              <label className="block text-[10px] font-bold text-violet-700">
                                Reference / TXN ID
                                <input type="text" placeholder="e.g. TXN-1234" value={disburseForm.reference} onChange={(e) => setDisburseForm({ ...disburseForm, reference: e.target.value })} className="w-full h-8 px-2 rounded border border-violet-200 bg-white text-[11px] font-normal" />
                              </label>
                            </div>
                            <div className="flex gap-2 pt-1">
                              <button disabled={actionBusy || !disburseForm.reference} onClick={submitDisburse} className="flex-1 h-8 rounded bg-violet-600 text-white text-[11px] font-bold disabled:opacity-50">
                                {actionBusy ? <Loader2 size={11} className="animate-spin inline" /> : "Confirm & Send"}
                              </button>
                              <button onClick={() => setDisburseForm(null)} className="px-3 h-8 rounded border border-gray-300 bg-white text-[11px] font-semibold text-gray-700">
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
