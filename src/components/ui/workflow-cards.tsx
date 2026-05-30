"use client";

import { useState } from "react";
import { Wallet, CheckCircle2, RotateCcw, Banknote, Building2 } from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import {
  fundRequests,
  fundRequestTotal,
  formatUgx,
  type FundRequest,
} from "@/lib/workflow-mock";
import {
  approveFundRequest,
  returnFundRequest,
  markFundRequestDisbursed,
  fundRequestSummary,
} from "@/lib/workflow-actions";
import { shortStatusLabel, fullStatusLabel } from "@/lib/status-labels";
import { useDemoStore } from "@/components/demo/DemoStore";
import { cn } from "@/lib/utils";

// Fund request review table — used by the Program Accountant dashboard.
// `showAccountantActions` toggles inline approve/return buttons; the rest
// of the panel is read-only.

const STATUS_TONE: Record<FundRequest["status"], "amber" | "edify" | "violet" | "green"> = {
  "Pending Accountant": "amber",
  "Pending Director":   "edify",
  "Pending RVP":        "violet",
  "Disbursed":          "green",
};

export function FundRequestCard({
  rows = fundRequests,
  showAccountantActions = false,
}: {
  rows?: FundRequest[];
  showAccountantActions?: boolean;
}) {
  // Local copy of the rows so we can reflect approve / return actions
  // immediately. The underlying module-level array is also mutated by
  // `transitionFundRequest`, which keeps cross-component views (e.g. the
  // accountant disbursement list) in sync within the session.
  const [localRows, setLocalRows] = useState<FundRequest[]>(rows);
  const { pushToast } = useDemoStore();

  function handleApprove(fr: FundRequest) {
    const res = approveFundRequest(fr.id);
    if (!res.ok) {
      pushToast({ tone: "warning", title: "Could not approve", body: `Status is ${fr.status}; expected Pending Accountant.` });
      return;
    }
    setLocalRows((prev) => prev.map((r) => (r.id === fr.id ? res.request : r)));
    pushToast({
      tone: "success",
      title: "Fund request approved",
      body: `${fundRequestSummary(res.request)} — forwarded to Country Director.`,
    });
  }

  function handleReturn(fr: FundRequest) {
    const res = returnFundRequest(fr.id);
    if (!res.ok) {
      pushToast({ tone: "warning", title: "Could not return", body: `Status is ${fr.status}; expected Pending Accountant.` });
      return;
    }
    setLocalRows((prev) => prev.map((r) => (r.id === fr.id ? res.request : r)));
    pushToast({
      tone: "warning",
      title: "Fund request returned",
      body: `${fundRequestSummary(res.request)} — sent back for rework.`,
    });
  }

  return (
    <SectionCard
      icon={<Wallet size={13} />}
      title="Fund requests"
      subtitle={`${localRows.length} requests in flight. Approve, return, or disburse from this queue.`}
    >
      <table className="w-full dtable">
        <thead>
          <tr>
            <th scope="col" className="text-left">ID</th>
            <th scope="col" className="text-left">District</th>
            <th scope="col" className="text-left">Staff</th>
            <th scope="col" className="text-left">Month</th>
            <th scope="col" className="text-right">Total</th>
            <th scope="col" className="text-left">Status</th>
            {showAccountantActions && <th scope="col" className="text-right">Action</th>}
          </tr>
        </thead>
        <tbody>
          {localRows.map((fr) => (
            <tr key={fr.id}>
              <td className="font-mono text-[11px]">{fr.id.toUpperCase()}</td>
              <td className="text-[12px] font-semibold">{fr.district}</td>
              <td className="text-[12px]">{fr.staff}</td>
              <td className="text-[12px]">{fr.month}</td>
              <td className="text-right font-extrabold tabular text-body">
                {formatUgx(fundRequestTotal(fr))}
              </td>
              <td>
                <span title={fullStatusLabel(fr.status)}>
                  <StatusBadge tone={STATUS_TONE[fr.status]}>{shortStatusLabel(fr.status)}</StatusBadge>
                </span>
                {fr.returnedAt && (
                  <div className="text-[10px] muted mt-0.5">(Returned to Accountant)</div>
                )}
              </td>
              {showAccountantActions && (
                <td className="text-right">
                  <div className="inline-flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => handleApprove(fr)}
                      disabled={fr.status !== "Pending Accountant"}
                      className={cn(
                        "h-7 px-2 rounded-md inline-flex items-center gap-1 text-[11px] font-semibold",
                        fr.status === "Pending Accountant"
                          ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-200"
                          : "bg-[var(--color-edify-soft)]/40 text-[var(--color-edify-muted)] cursor-not-allowed",
                      )}
                    >
                      <CheckCircle2 size={11} />
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => handleReturn(fr)}
                      disabled={fr.status !== "Pending Accountant"}
                      className={cn(
                        "h-7 px-2 rounded-md inline-flex items-center gap-1 text-[11px] font-semibold",
                        fr.status === "Pending Accountant"
                          ? "bg-amber-100 text-amber-700 hover:bg-amber-200"
                          : "bg-[var(--color-edify-soft)]/40 text-[var(--color-edify-muted)] cursor-not-allowed",
                      )}
                    >
                      <RotateCcw size={11} />
                      Return
                    </button>
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </SectionCard>
  );
}

// Accountant Disbursement Status list — client island. Owns its own copy
// of the fund request rows so the "Mark Disbursed" button can flip the
// row to "Disbursed" without a full page reload. The underlying module
// array is also mutated (see `markFundRequestDisbursed`) so other panels
// observe the change on next mount.
export function DisbursementList({ initialRows = fundRequests }: { initialRows?: FundRequest[] }) {
  const [rows, setRows] = useState<FundRequest[]>(initialRows);
  const { pushToast } = useDemoStore();

  function handleDisburse(fr: FundRequest) {
    const res = markFundRequestDisbursed(fr.id);
    if (!res.ok) {
      pushToast({
        tone: "warning",
        title: "Cannot disburse",
        body: `Request is already Disbursed or in an unexpected state (${fr.status}).`,
      });
      return;
    }
    setRows((prev) => prev.map((r) => (r.id === fr.id ? res.request : r)));
    pushToast({
      tone: "success",
      title: "Funds marked disbursed",
      body: `${fundRequestSummary(res.request)} — audit entry recorded.`,
    });
  }

  return (
    <SectionCard
      icon={<Banknote size={13} />}
      title="Disbursement Status"
      subtitle="Mark requests as disbursed once paid through finance."
    >
      <div className="space-y-2">
        {rows.map((fr) => (
          <div
            key={fr.id}
            className="rounded-lg border border-[var(--color-edify-border)] px-3 py-2 flex items-center gap-3"
          >
            <span className="icon-tile icon-tile-sm">
              <Building2 size={11} />
            </span>
            <div className="leading-tight flex-1 min-w-0">
              <div className="text-body font-semibold truncate">
                {fr.district} · {fr.month}
              </div>
              <div className="text-[11px] muted truncate">{fr.staff}</div>
            </div>
            <div className="text-[12px] tabular font-semibold">
              {formatUgx(fundRequestTotal(fr))}
            </div>
            <StatusBadge
              tone={
                fr.status === "Disbursed"
                  ? "green"
                  : fr.status === "Pending Director"
                    ? "amber"
                    : "blue"
              }
            >
              {fr.status === "Pending Director" ? "Pending Director" : fr.status}
            </StatusBadge>
            {fr.status !== "Disbursed" && (
              <button
                type="button"
                onClick={() => handleDisburse(fr)}
                className="btn btn-sm btn-primary"
              >
                Mark Disbursed
              </button>
            )}
          </div>
        ))}
      </div>
    </SectionCard>
  );
}
