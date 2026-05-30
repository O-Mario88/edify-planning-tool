"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, RotateCcw, Eye, ChevronRight } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  cplApprovalsList,
  cplApprovalCounts,
  type CplApprovalItem,
  type CplApprovalCategory,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<CplApprovalItem["status"], string> = {
  "Awaiting Approval": "bg-amber-100   text-amber-700",
  "Needs Review":      "bg-sky-100     text-sky-700",
  "Ready":             "bg-emerald-100 text-emerald-700",
  "Approved":          "bg-emerald-100 text-emerald-700",
  "Returned":          "bg-rose-100    text-rose-700",
};

const CATS: { key: CplApprovalCategory; label: string }[] = [
  { key: "plans",    label: "Plans" },
  { key: "funds",    label: "Funds" },
  { key: "backlogs", label: "Backlogs" },
];

export function CplApprovalsDesktopView() {
  const [cat, setCat] = useState<CplApprovalCategory>("plans");
  const visible = cplApprovalsList.filter((i) => i.category === cat);

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Plans, funds, and reports awaiting your review. The CPL approves plans + proposed budgets here; fund disbursement still requires CD + RVP sign-off."
      />
      <div className="mx-auto w-full max-w-5xl px-4 sm:px-5 md:px-6 pb-10 md:pb-6">
        <div className="grid grid-cols-12 gap-4 items-start">
          <div className="col-span-12 lg:col-span-8">
            {/* Category tabs */}
      <div className="card rounded-2xl p-2 flex items-center gap-1 mb-3">
        {CATS.map((c) => {
          const active = c.key === cat;
          const count = cplApprovalsList.filter((i) => i.category === c.key).length;
          return (
            <button
              key={c.key}
              type="button"
              onClick={() => setCat(c.key)}
              className={cn(
                "h-9 px-3 rounded-lg text-[12px] font-extrabold tracking-tight inline-flex items-center gap-2",
                active
                  ? "bg-[var(--color-edify-primary)] text-white"
                  : "text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/40",
              )}
            >
              {c.label}
              <span className={cn(
                "inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-md text-[10px] font-extrabold",
                active ? "bg-white/20" : "bg-[var(--color-edify-soft)]/70",
              )}>{count}</span>
            </button>
          );
        })}
      </div>

      {/* Approval cards */}
      <ul className="space-y-2">
        {visible.length === 0 ? (
          <li className="card rounded-2xl p-8 text-center">
            <div className="text-body-lg font-extrabold tracking-tight">Nothing here</div>
            <p className="text-[11.5px] muted mt-1">Switch category to see other items.</p>
          </li>
        ) : (
          visible.map((i) => (
            <li key={i.id} className="card rounded-2xl p-3 flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-[13px] font-extrabold tracking-tight">{i.title}</div>
                  <span className={cn(
                    "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0",
                    STATUS_TONE[i.status],
                  )}>
                    {i.status}
                  </span>
                </div>
                <div className="text-caption muted">
                  {i.owner} · {i.ownerRole} · {i.district} · {i.plannedRange}
                </div>
                <div className="text-[11.5px] mt-1 font-extrabold tabular">{i.cost}</div>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <button type="button" className="h-9 w-9 rounded-md border border-[var(--color-edify-border)] grid place-items-center hover:bg-[var(--color-edify-soft)]/40" aria-label="View">
                  <Eye size={12} className="text-[var(--color-edify-muted)]" />
                </button>
                <button type="button" className="h-9 px-3 rounded-md bg-emerald-500 hover:bg-emerald-600 text-white text-[11px] font-semibold inline-flex items-center gap-1">
                  <CheckCircle2 size={11} />
                  Approve
                </button>
                <button type="button" className="h-9 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] font-semibold inline-flex items-center gap-1">
                  <RotateCcw size={11} />
                  Return
                </button>
              </div>
            </li>
          ))
        )}
            </ul>
          </div>
          <aside className="col-span-12 lg:col-span-4 lg:sticky lg:top-4 space-y-3">
            <div className="card p-3.5">
              <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2">This Month</h3>
              <ul className="space-y-1.5 text-[12px]">
                <Row label="Waiting"        count={cplApprovalCounts.waiting}       tone="amber" />
                <Row label="Returned"       count={cplApprovalCounts.returned}      tone="rose" />
                <Row label="Approved today" count={cplApprovalCounts.approvedToday} tone="green" />
              </ul>
            </div>
            <Link href="/approvals" className="card p-3.5 flex items-center gap-2 hover:bg-[var(--color-edify-soft)]/40">
              <span className="text-body font-extrabold tracking-tight">Approvals</span>
              <ChevronRight size={12} className="ml-auto text-[var(--color-edify-muted)]" />
            </Link>
          </aside>
        </div>
      </div>
    </>
  );
}

function Row({ label, count, tone }: { label: string; count: number; tone: "amber" | "rose" | "green" }) {
  const TONE = { amber: "text-amber-700", rose: "text-rose-700", green: "text-emerald-700" } as const;
  return (
    <li className="flex items-baseline justify-between">
      <span className="muted">{label}</span>
      <span className={cn("font-extrabold tabular", TONE[tone])}>{count}</span>
    </li>
  );
}
