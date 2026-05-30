"use client";

import Link from "next/link";
import { ArrowUpRight, Bell, Wallet } from "lucide-react";
import { findRequestsForStaff, currentWeek } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { StatusChip } from "@/components/funds/StatusChip";
import { cn } from "@/lib/utils";

// "My Weekly Fund Request" — a dashboard-friendly card that sits on
// the CCEO landing page. Shows this week's request + a quick CTA into
// the full /weekly-funds page.
export function MyWeeklyFundCard({ staffId }: { staffId: string }) {
  const requests = findRequestsForStaff(staffId);
  const fallback = requests.length > 0 ? requests : findRequestsForStaff("STF-PC-001");
  const thisWeek = fallback.find((r) => r.period.weekOfMonth === currentWeek.weekOfMonth);

  if (!thisWeek) {
    return (
      <article className="card p-3.5">
        <h3 className="text-[13px] font-extrabold tracking-tight mb-1.5">My Weekly Fund Request</h3>
        <p className="text-[11.5px] muted">No request generated for this week yet.</p>
      </article>
    );
  }

  return (
    <article className="card p-3.5 flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-2">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight">My Weekly Fund Request</h3>
          <p className="text-caption muted font-semibold leading-tight">
            Week {thisWeek.period.weekOfMonth} · {currentWeek.monthLabel}
          </p>
        </div>
        <Link
          href="/weekly-funds"
          className="inline-flex items-center gap-1 text-[11px] font-extrabold text-[var(--color-edify-primary)]"
        >
          Open
          <ArrowUpRight size={10} />
        </Link>
      </header>

      <div className="flex items-end justify-between gap-2 mt-1">
        <div className="text-[20px] font-extrabold tabular num-hero glow-emerald text-slate-900 leading-none">
          {formatMoney(thisWeek.requestedAmount)}
        </div>
        <StatusChip status={thisWeek.status} />
      </div>

      <div className="mt-2 text-caption muted font-semibold">
        {thisWeek.activities.length} activities · planned {formatMoney(thisWeek.plannedAmount)}
      </div>

      {/* Notification strip — surfaces returns / pending receipts */}
      {(thisWeek.status === "RETURNED_TO_STAFF" || thisWeek.status === "ACCOUNTABILITY_RETURNED") && (
        <div className={cn(
          "mt-2 rounded-lg border border-rose-200 bg-rose-50 px-2 py-1.5 flex items-center gap-2",
        )}>
          <Bell size={12} className="text-rose-600 shrink-0" />
          <span className="text-caption font-extrabold text-rose-700 truncate">
            Your Lead returned this week — open to fix and resubmit.
          </span>
        </div>
      )}
      {thisWeek.status === "DISBURSED" && (
        <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1.5 flex items-center gap-2">
          <Wallet size={12} className="text-emerald-600 shrink-0" />
          <span className="text-caption font-extrabold text-emerald-700 truncate">
            Funds sent. Open to confirm you&apos;ve received them.
          </span>
        </div>
      )}
    </article>
  );
}
