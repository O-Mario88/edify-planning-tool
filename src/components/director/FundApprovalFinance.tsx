"use client";

import { useState } from "react";
import Link from "next/link";
import { DollarSign, AlertCircle, Loader2 } from "lucide-react";
import { SectionCard, StatusBadge, TableEmptyRow } from "@/components/ui/primitives";
import { pendingFundRequests as seedPending, fundedNotCompleted } from "@/lib/director-mock";
import { useDemoStore } from "@/components/demo/DemoStore";

type PendingRow = {
  id: string;
  region: string;
  amountLabel: string;
  activitiesCovered: number;
  stage: string;
};

export function FundApprovalFinanceSnapshot({
  pendingFundRequests = seedPending,
  live = false,
}: { pendingFundRequests?: PendingRow[]; live?: boolean } = {}) {
  const { pushToast } = useDemoStore();
  const [busyId, setBusyId] = useState<string | null>(null);

  function handleReview(id: string, region: string, amount: string) {
    if (live) return;
    setBusyId(id);
    window.setTimeout(() => {
      setBusyId(null);
      pushToast({
        tone: "info",
        title: "Opened fund request review",
        body: `${region} · ${amount} — review note logged in audit trail.`,
      });
    }, 400);
  }

  return (
    <SectionCard
      icon={<DollarSign size={13} />}
      title="Fund Approval & Finance Snapshot"
    >
      <div className="text-[12px] font-bold mb-2">Pending Fund Requests (Need Your Approval)</div>
      <div className="overflow-x-auto scrollbar -mx-1 px-1">
      <table className="w-full dtable">
        <thead>
          <tr>
            <th scope="col" className="text-left">Region / Team</th>
            <th scope="col" className="text-right">Amount Requested</th>
            <th scope="col" className="text-right">Activities Covered</th>
            <th scope="col" className="text-left">Stage</th>
            <th scope="col" className="text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          {pendingFundRequests.map((r) => (
            <tr key={r.id}>
              <td className="text-body font-semibold whitespace-nowrap">{r.region}</td>
              <td className="text-right tabular text-body font-semibold">{r.amountLabel}</td>
              <td className="text-right tabular text-body">
                {r.activitiesCovered.toLocaleString()}
              </td>
              <td>
                <StatusBadge tone="amber">{r.stage}</StatusBadge>
              </td>
              <td className="text-right">
                {live ? (
                  <Link
                    href="/approvals"
                    className="btn btn-sm btn-primary inline-flex items-center gap-1"
                  >
                    Review
                  </Link>
                ) : (
                  <button
                    type="button"
                    onClick={() => handleReview(r.id, r.region, r.amountLabel)}
                    disabled={busyId === r.id}
                    className="btn btn-sm btn-primary disabled:opacity-55 inline-flex items-center gap-1"
                    aria-label={`Review fund request for ${r.region}`}
                  >
                    {busyId === r.id ? <Loader2 size={11} className="animate-spin" /> : null}
                    Review
                  </button>
                )}
              </td>
            </tr>
          ))}
          {pendingFundRequests.length === 0 && (
            <TableEmptyRow
              colSpan={5}
              title="No fund requests awaiting your approval"
              body="Once the Program Accountant has reviewed monthly budgets they appear here for Country Director approval."
            />
          )}
        </tbody>
      </table>
      </div>
      <div className="mt-2 text-right">
        <Link
          href="/fund-requests"
          className="text-[12px] font-semibold text-[var(--color-edify-primary)]"
        >
          View All {pendingFundRequests.length}+ pending requests →
        </Link>
      </div>
      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11px] muted">
        Country Director approves fund requests after Program Accountant review. Plan approval is a
        separate flow handled by the Country Program Lead.
      </div>
    </SectionCard>
  );
}

export function FundedNotCompletedCard() {
  return (
    <FundedNotCompletedLive
      openCount={fundedNotCompleted.overdue}
      totalLabel={fundedNotCompleted.totalLabel}
      activityCount={fundedNotCompleted.activities}
      partial={fundedNotCompleted.partial}
      notStarted={fundedNotCompleted.notStarted}
    />
  );
}

export function FundedNotCompletedLive({
  openCount,
  totalLabel,
  activityCount,
  partial = 0,
  notStarted = 0,
}: {
  openCount: number;
  totalLabel: string;
  activityCount: number;
  partial?: number;
  notStarted?: number;
}) {
  return (
    <SectionCard icon={<AlertCircle size={13} />} title="Disbursed — Accountability Open">
      <div className="text-[26px] font-extrabold tabular leading-none">
        {totalLabel}
      </div>
      <div className="text-[12px] muted mt-1">
        Across {activityCount.toLocaleString()} activities · {openCount} without accountability filed
      </div>

      {(partial > 0 || notStarted > 0) && (
        <div className="mt-4 space-y-2.5">
          {partial > 0 && <Row label="Partially Completed" value={partial} tone="text-[var(--color-edify-orange)]" />}
          {notStarted > 0 && <Row label="Not Started" value={notStarted} tone="text-[var(--color-edify-muted)]" />}
        </div>
      )}

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-right">
        <Link
          href="/disbursements"
          className="text-[12px] font-semibold text-[var(--color-edify-primary)]"
        >
          Open payments &amp; accountability →
        </Link>
      </div>
    </SectionCard>
  );
}

function Row({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="flex items-center justify-between text-body">
      <div className="font-semibold">{label}</div>
      <div className={`font-extrabold tabular ${tone}`}>{value.toLocaleString()}</div>
    </div>
  );
}
