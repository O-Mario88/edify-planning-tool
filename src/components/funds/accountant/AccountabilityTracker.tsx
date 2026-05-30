"use client";

import { CheckCircle2, Clock, FileWarning } from "lucide-react";
import { weeklyFundRequests } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { StatusChip } from "@/components/funds/StatusChip";
import { cn } from "@/lib/utils";

// Accountability Tracker — what's been spent vs. accounted for, per
// week-3 request. Surfaces the next-release gate at a glance.
export function AccountabilityTracker() {
  const inFieldOrAccounting = weeklyFundRequests.filter((r) =>
    ["DISBURSED", "RECEIVED", "IN_USE",
     "ACCOUNTABILITY_SUBMITTED", "ACCOUNTABILITY_RETURNED",
    ].includes(r.status),
  );

  const counts = {
    inField: weeklyFundRequests.filter((r) => ["DISBURSED", "RECEIVED", "IN_USE"].includes(r.status)).length,
    pending: weeklyFundRequests.filter((r) => r.status === "ACCOUNTABILITY_SUBMITTED").length,
    returned: weeklyFundRequests.filter((r) => r.status === "ACCOUNTABILITY_RETURNED").length,
  };

  return (
    <article className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight">Accountability Tracker</h3>
          <p className="text-caption muted font-semibold leading-tight">
            Acquittal pipeline · gate inputs for the next release
          </p>
        </div>
      </header>

      <div className="grid grid-cols-3 gap-2 mb-3">
        <SummaryTile label="In Field" value={counts.inField} Icon={Clock} tone="sky" />
        <SummaryTile label="Pending Review" value={counts.pending} Icon={FileWarning} tone="amber" />
        <SummaryTile label="Returned" value={counts.returned} Icon={CheckCircle2} tone="rose" />
      </div>

      <ul className="flex flex-col gap-1.5">
        {inFieldOrAccounting.map((r, i) => {
          const stagger = `stagger-${(i % 6) + 1}`;
          const accounted = r.accountedAmount?.amount ?? 0;
          const disbursed = r.disbursedAmount?.amount ?? 0;
          const pct = disbursed > 0 ? Math.min(100, (accounted / disbursed) * 100) : 0;
          return (
            <li
              key={r.id}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] bg-white p-2.5 tile-in card-lift",
                stagger,
              )}
            >
              <div className="flex items-center gap-2.5">
                <div className="min-w-0 flex-1">
                  <div className="text-[12px] font-extrabold text-slate-900 truncate">
                    {r.staffName}
                    <span className="text-slate-400 font-medium"> — </span>
                    <span className="text-slate-600 font-semibold">{r.district}</span>
                  </div>
                  <div className="text-[10px] muted font-semibold mt-0.5 truncate">
                    Week {r.period.weekOfMonth} · disbursed {formatMoney(r.disbursedAmount ?? { amount: 0, currency: "UGX" })}
                  </div>
                </div>
                <StatusChip status={r.status} size="xs" withDot={false} />
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
                  <div
                    className={cn(
                      "h-full",
                      pct >= 95
                        ? "bg-gradient-to-r from-emerald-500 to-emerald-600"
                        : pct >= 60
                          ? "bg-gradient-to-r from-amber-400 to-amber-500"
                          : "bg-gradient-to-r from-rose-400 to-rose-500",
                    )}
                    style={{ width: `${pct.toFixed(1)}%` }}
                  />
                </div>
                <span className="text-caption tabular font-extrabold text-slate-700 shrink-0 w-[44px] text-right">
                  {pct.toFixed(0)}%
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

const TONE_BG: Record<string, { bg: string; fg: string }> = {
  sky:   { bg: "bg-sky-100",   fg: "text-sky-700" },
  amber: { bg: "bg-amber-100", fg: "text-amber-700" },
  rose:  { bg: "bg-rose-100",  fg: "text-rose-700" },
};

function SummaryTile({
  label, value, Icon, tone,
}: {
  label: string; value: number; Icon: typeof Clock; tone: keyof typeof TONE_BG;
}) {
  const t = TONE_BG[tone];
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] bg-white p-2.5 flex items-center gap-2 card-lift">
      <span className={cn("w-7 h-7 rounded-lg grid place-items-center", t.bg)}>
        <Icon size={12} className={t.fg} />
      </span>
      <div className="min-w-0">
        <div className="text-[15px] font-extrabold tabular num-hero leading-none">{value}</div>
        <div className="text-[10px] muted font-semibold truncate">{label}</div>
      </div>
    </div>
  );
}
