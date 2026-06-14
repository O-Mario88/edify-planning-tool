"use client";

// Fund Approval Queue — LIVE expandable list. Each submitted request is a row
// that expands in place to reveal the per-activity cost breakdown (every line
// priced from the plan + CD cost catalogue) and the approve / return / reject
// actions. Approval is supervision-scoped by the backend: a CCEO approves their
// staff, a PL approves their CCEOs, and no one approves their own request. The
// CD does NOT appear here — they own the rate card, not the approval. No mock.

import { useCallback, useEffect, useState } from "react";
import { Wallet, CheckCircle2, RotateCcw, XCircle, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeFundRequest } from "@/lib/api/surfaces";

const ugx = (n: number) => `UGX ${Math.round(n).toLocaleString()}`;
const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const periodLabel = (p: string, key: string) => {
  const m = key.match(/-M(\d+)$/); if (m) return `${MONTHS[Number(m[1])]} ${key.slice(0, 4)}`;
  const q = key.match(/-(Q\d)$/); if (q) return `${q[1]} ${key.slice(0, 4)}`;
  return p === "weekly" ? `Weekly · ${key.slice(0, 4)}` : key;
};
const statusTone: Record<string, string> = {
  submitted: "bg-amber-100 text-amber-700", approved: "bg-emerald-100 text-emerald-700",
  returned: "bg-sky-100 text-sky-700", rejected: "bg-rose-100 text-rose-700", disbursed: "bg-violet-100 text-violet-700",
};

export function FundApprovalQueueLive({ canDisburse = false, canSubmit = false }: { canDisburse?: boolean; canSubmit?: boolean } = {}) {
  const [submitMsg, setSubmitMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [rows, setRows] = useState<BeFundRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, BeFundRequest>>({});
  const [detailBusy, setDetailBusy] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    fetch("/api/fund-requests", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setRows(j.requests as BeFundRequest[]); else setError(j.error || "Could not load fund requests"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  // Lazy-load the costed breakdown the first time a row is expanded.
  const toggle = async (r: BeFundRequest) => {
    setActionErr(null);
    if (openId === r.id) { setOpenId(null); return; }
    setOpenId(r.id);
    if (!detail[r.id]) {
      setDetailBusy(r.id);
      try {
        const res = await fetch(`/api/fund-requests/${r.id}`, { credentials: "include" });
        const j = await res.json();
        if (j.live) setDetail((d) => ({ ...d, [r.id]: j.request as BeFundRequest }));
      } catch { /* surface nothing; the row still shows summary */ }
      setDetailBusy(null);
    }
  };

  const act = async (r: BeFundRequest, action: "approve" | "return" | "reject" | "disburse" | "account-approve" | "account-return") => {
    setActionBusy(true); setActionErr(null);
    try {
      const res = await fetch(`/api/fund-requests/${r.id}/${action}`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
      });
      const j = await res.json();
      if (j.live) { setDetail((d) => { const n = { ...d }; delete n[r.id]; return n; }); load(); }
      else setActionErr(j.error || "The action was rejected");
    } catch { setActionErr("Could not reach the server"); }
    setActionBusy(false);
  };

  // Generate THIS month's fund request from the caller's scheduled work (derived
  // from the plan + CD cost register; the backend blocks on any missing cost).
  const submitMine = async () => {
    setActionBusy(true); setSubmitMsg(null);
    try {
      const j = await fetch("/api/fund-requests", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ period: "monthly" }),
      }).then((r) => r.json());
      if (j.live) { setSubmitMsg({ ok: true, text: "Monthly fund request submitted to your supervisor." }); load(); }
      else setSubmitMsg({ ok: false, text: j.error || "Could not generate the request." });
    } catch { setSubmitMsg({ ok: false, text: "Could not reach the server." }); }
    setActionBusy(false);
  };

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Wallet size={14} /> Fund Approval Queue</h2>
        <div className="flex items-center gap-2">
          {canSubmit && (
            <button disabled={actionBusy} onClick={submitMine} className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[10.5px] font-bold disabled:opacity-50">
              {actionBusy ? <Loader2 size={12} className="animate-spin" /> : <Wallet size={12} />} Generate my monthly request
            </button>
          )}
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · you supervise</span>
        </div>
      </header>
      {submitMsg && <p className={`mb-2 text-[11px] font-semibold ${submitMsg.ok ? "text-emerald-600" : "text-rose-500"}`}>{submitMsg.text}</p>}

      {loading ? <LoadingState compact />
        : error ? <ErrorState compact message={error} onRetry={load} />
        : !rows || rows.length === 0 ? <EmptyState compact title="No fund requests in your queue" message="Requests from the staff you supervise appear here for approval. Each cost is drawn from the plan and the cost catalogue." />
        : (
        <ul className="space-y-1.5">
          {rows.map((r) => {
            const open = openId === r.id;
            const d = detail[r.id];
            return (
              <li key={r.id} className="rounded-lg border border-[var(--color-edify-border)] overflow-hidden">
                {/* Row header — click to expand */}
                <button
                  onClick={() => toggle(r)}
                  className="w-full text-left flex items-center gap-2 px-3 py-2.5 hover:bg-[var(--surface-3)] transition-colors"
                >
                  {open ? <ChevronDown size={14} className="shrink-0 muted" /> : <ChevronRight size={14} className="shrink-0 muted" />}
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span className="text-[12.5px] font-bold truncate">{r.submittedBy}</span>
                      <span className={cn("px-1.5 py-0.5 rounded text-[8.5px] font-bold uppercase shrink-0", statusTone[r.status])}>{r.status}</span>
                    </span>
                    <span className="block text-[10.5px] muted truncate">{r.submittedByRole} · {periodLabel(r.period, r.periodKey)} · {r.activityCount} costed</span>
                  </span>
                  <span className="text-[13px] font-extrabold tabular shrink-0">{ugx(r.totalAmount)}</span>
                </button>

                {/* Expanded detail — costed breakdown + actions */}
                {open && (
                  <div className="border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/20 px-3 py-2.5">
                    {detailBusy === r.id && !d ? (
                      <div className="py-3"><LoadingState compact /></div>
                    ) : (
                      <>
                        <div className="text-[9.5px] font-bold uppercase tracking-wide muted mb-1.5">Costed activities — every line from the cost catalogue</div>
                        {d?.breakdown && d.breakdown.activities.length > 0 ? (
                          <ul className="space-y-1.5 mb-2.5">
                            {d.breakdown.activities.map((a) => (
                              <li key={a.id} className="rounded-md border border-[var(--color-edify-border)] bg-[var(--surface-1)] px-2.5 py-1.5">
                                <div className="flex items-center justify-between gap-2 text-[11.5px]">
                                  <span className="min-w-0 truncate">
                                    <span className="font-bold">{titleCase(a.activityType)}</span>
                                    <span className="muted"> · {a.target}{a.month ? ` · ${MONTHS[a.month]}` : ""} · {a.deliveryType}</span>
                                  </span>
                                  <span className={cn("font-extrabold tabular shrink-0", a.costMissing ? "text-rose-600" : "")}>{a.costMissing ? "no rate" : ugx(a.amount)}</span>
                                </div>
                                {a.lines.length > 0 && (
                                  <div className="mt-1 pl-2 border-l-2 border-[var(--color-edify-divider)] space-y-0.5">
                                    {a.lines.map((l, i) => (
                                      <div key={i} className="flex items-center justify-between gap-2 text-[10px] muted">
                                        <span>{l.label}{l.qty > 1 ? ` × ${l.qty}` : ""}</span>
                                        <span className={cn("tabular", l.missing ? "text-rose-600 font-bold" : "")}>{l.missing ? "rate missing" : ugx(l.amount)}</span>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-[11px] muted mb-2.5">No itemised activities available for this period.</p>
                        )}

                        <div className="flex items-center justify-between text-[12.5px] font-extrabold border-t border-[var(--color-edify-divider)] pt-1.5">
                          <span>Total requested</span><span className="tabular">{ugx(r.totalAmount)}</span>
                        </div>

                        {r.reviewNote && <p className="mt-2 text-[10.5px] muted italic">Note: {r.reviewNote}</p>}
                        {actionErr && <p className="mt-2 text-[11px] text-rose-600 font-semibold">{actionErr}</p>}

                        {/* Actions only when the backend says you may review this row */}
                        {(d?.canReview ?? r.canReview) ? (
                          <div className="flex gap-1.5 mt-2.5">
                            <button disabled={actionBusy} onClick={() => act(r, "approve")} className="flex-1 inline-flex items-center justify-center gap-1 h-9 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11.5px] font-bold disabled:opacity-50">{actionBusy ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />} Approve</button>
                            <button disabled={actionBusy} onClick={() => act(r, "return")} className="inline-flex items-center justify-center gap-1 h-9 px-3 rounded-lg border border-sky-300 text-sky-700 hover:bg-sky-50 text-[11.5px] font-bold disabled:opacity-50"><RotateCcw size={13} /> Return</button>
                            <button disabled={actionBusy} onClick={() => act(r, "reject")} className="inline-flex items-center justify-center gap-1 h-9 px-3 rounded-lg border border-rose-300 text-rose-700 hover:bg-rose-50 text-[11.5px] font-bold disabled:opacity-50"><XCircle size={13} /> Reject</button>
                          </div>
                        ) : r.status === "submitted" ? (
                          <p className="mt-2.5 text-[10.5px] muted">This is your own request — it routes to your supervisor for approval.</p>
                        ) : null}
                        {/* Accountant disburse — only on backend-APPROVED rows; the
                            backend re-enforces PAYMENT_ACT before money moves. */}
                        {canDisburse && r.status === "approved" && (
                          <button disabled={actionBusy} onClick={() => act(r, "disburse")} className="mt-2.5 w-full inline-flex items-center justify-center gap-1 h-9 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-[11.5px] font-bold disabled:opacity-50">{actionBusy ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />} Disburse funds</button>
                        )}
                        {/* Supervisor accountability review — the close-out leg.
                            Shown when a supervised submitter has filed accountability
                            (NetSuite ID + spent/returned) awaiting your approval. */}
                        {(d?.canAccountReview ?? r.canAccountReview) && (
                          <div className="mt-2.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] p-2.5">
                            <p className="text-[10.5px] font-bold mb-1.5">Accountability filed{r.accountabilityNetsuiteId ? ` · NetSuite ${r.accountabilityNetsuiteId}` : ""}
                              <span className="muted font-normal"> · accounted {ugx(r.accountedAmount ?? 0)} · returned {ugx(r.returnedAmount ?? 0)}</span></p>
                            <div className="flex gap-1.5">
                              <button disabled={actionBusy} onClick={() => act(r, "account-approve")} className="flex-1 inline-flex items-center justify-center gap-1 h-9 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11.5px] font-bold disabled:opacity-50">{actionBusy ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />} Approve accountability</button>
                              <button disabled={actionBusy} onClick={() => act(r, "account-return")} className="inline-flex items-center justify-center gap-1 h-9 px-3 rounded-lg border border-sky-300 text-sky-700 hover:bg-sky-50 text-[11.5px] font-bold disabled:opacity-50"><RotateCcw size={13} /> Return</button>
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
