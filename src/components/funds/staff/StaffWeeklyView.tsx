"use client";

import { useMemo, useState } from "react";
import { ArrowUpRight, CalendarRange, Wallet } from "lucide-react";
import { findRequestsForStaff, currentWeek } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { StatusChip } from "@/components/funds/StatusChip";
import { StaffWeeklyRequestCard } from "./StaffWeeklyRequestCard";
import { FundAccountabilityCenter } from "./FundAccountabilityCenter";
import { ReimbursementClaimModal } from "./ReimbursementClaimModal";
import { PageHeader } from "@/components/ui/PageHeader";
import { cn } from "@/lib/utils";

// Staff view of the weekly fund pipeline.
//
// Layout:
//   1. Header     — title + month label + outstanding chip
//   2. Week tabs  — 4 tabs (W1..W4) with status pill on each
//   3. Detail     — full request card (activities, money trail,
//                   status-driven action set)
export function StaffWeeklyView({
  staffId,
  staffName,
}: {
  staffId: string;
  staffName: string;
}) {
  const requests = useMemo(() => {
    // If the signed-in staff has no requests in our mock set, fall back
    // to Paul Chinyama so the page is never empty in the demo.
    const own = findRequestsForStaff(staffId);
    return own.length > 0 ? own : findRequestsForStaff("STF-PC-001");
  }, [staffId]);

  const [activeWeek, setActiveWeek] = useState<1 | 2 | 3 | 4>(
    (currentWeek.weekOfMonth as 1 | 2 | 3 | 4) ?? 3,
  );
  const [reimbursementOpen, setReimbursementOpen] = useState(false);
  const active = requests.find((r) => r.period.weekOfMonth === activeWeek);

  return (
    <>
      <PageHeader
        title="My Weekly Fund Requests"
        subtitle={`${staffName} · ${currentWeek.monthLabel} · Auto-generated from your approved monthly plan`}
        actions={
          <>
            <span className="inline-flex items-center gap-1 h-10 px-2.5 rounded-xl border border-emerald-200 bg-emerald-50 text-[12px] font-extrabold text-emerald-700">
              <CalendarRange size={11} />
              Week {currentWeek.weekOfMonth} · {currentWeek.daysRemaining}d left
            </span>
            <a
              href="#balance"
              className="inline-flex items-center gap-1 h-10 px-2.5 rounded-xl border border-[var(--color-edify-border)] bg-white text-[12px] font-extrabold text-slate-700"
            >
              <Wallet size={11} />
              My balance
              <ArrowUpRight size={11} className="text-slate-400" />
            </a>
          </>
        }
      />

      {/* Week tab strip */}
      <section className="px-3 sm:px-4 lg:px-6 pb-3">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          {requests.map((r, i) => {
            const isActive = r.period.weekOfMonth === activeWeek;
            const stagger = `stagger-${i + 1}`;
            return (
              <button
                key={r.id}
                type="button"
                onClick={() => setActiveWeek(r.period.weekOfMonth)}
                className={cn(
                  "card card-lift tile-in p-3 text-left transition-colors",
                  isActive
                    ? "ring-2 ring-[var(--color-edify-primary)] border-[var(--color-edify-primary)]"
                    : "",
                  stagger,
                )}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] muted font-bold uppercase tracking-wide">
                    Week {r.period.weekOfMonth}
                  </span>
                  <StatusChip status={r.status} size="xs" withDot={false} />
                </div>
                <div className="text-[16px] font-extrabold tabular num-hero text-slate-900 leading-none">
                  {formatMoney(r.requestedAmount)}
                </div>
                <div className="text-[10px] muted font-semibold mt-1 truncate">
                  {r.period.weekStartIso} → {r.period.weekEndIso}
                </div>
                <div className="text-[10px] muted font-semibold mt-0.5">
                  {r.activities.length} activities
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* Detail */}
      <div className="px-3 sm:px-4 lg:px-6 pb-3 space-y-3 lg:space-y-4">
        {active ? (
          <>
            <StaffWeeklyRequestCard request={active} />
            <FundAccountabilityCenter
              request={active}
              onConfirmReceipt={() => {
                // Wired to engine.confirmReceipt in real flow.
              }}
              onSubmitAccountability={() => {
                // Wired to engine.submitAccountability in real flow.
              }}
              onOpenReimbursement={() => setReimbursementOpen(true)}
            />
          </>
        ) : (
          <article className="card p-6 grid place-items-center text-[12px] muted italic min-h-[200px]">
            No request for this week yet.
          </article>
        )}
      </div>

      <ReimbursementClaimModal
        open={reimbursementOpen}
        onClose={() => setReimbursementOpen(false)}
        defaults={
          active
            ? {
                activityTitle: active.activities[0]?.title,
                weeklyPlanId: active.weeklyPlanId,
                fundRequestId: active.id,
                amountPreviouslyDisbursedUgx: active.disbursedAmount?.amount ?? 0,
              }
            : undefined
        }
        onSubmit={() => {
          setReimbursementOpen(false);
          // Wired to engine.submitReimbursementClaim in real flow.
        }}
      />
    </>
  );
}
