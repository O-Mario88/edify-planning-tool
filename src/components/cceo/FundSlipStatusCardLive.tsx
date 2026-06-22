import Link from "next/link";
import { Wallet } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchBudgetWeekly } from "@/lib/api/surfaces";
import { InsufficientData } from "@/components/ui/InsufficientData";

const fmtUgx = (n: number) =>
  n >= 1_000_000
    ? `UGX ${(n / 1_000_000).toFixed(1)}M`
    : n >= 1_000
      ? `UGX ${Math.round(n / 1_000)}K`
      : `UGX ${Math.round(n).toLocaleString()}`;

// Live fund-slip summary for the CCEO dashboard — current week's scheduled
// activities costed from the CD register (/budget/weekly). No mock totals.
export async function FundSlipStatusCardLive() {
  const user = await getCurrentUser();
  const res = await fetchBudgetWeekly(user);
  if (!res.live) return <InsufficientData surface="this week's fund slip" />;

  const b = res.data;
  if (b.count === 0) {
    return (
      <div className="card rounded-2xl p-4">
        <h3 className="text-[16px] font-extrabold tracking-tight flex items-center gap-2">
          <Wallet className="h-4 w-4 text-[var(--color-edify-primary)]" />
          This week&apos;s fund slip
        </h3>
        <p className="muted text-[12px] mt-2">
          No fund requests yet — schedule activities in Planning and the weekly slip
          generates itself from the cost catalogue.
        </p>
      </div>
    );
  }

  const focusWeek = b.weeks[b.weeks.length - 1];
  const weekLabel = focusWeek?.week ? `Week ${focusWeek.week}` : "This week";
  const activityCount = focusWeek?.count ?? b.count;
  const amount = focusWeek?.amount ?? b.total;
  const costMissing = b.costMissingCount > 0;

  return (
    <div className="card rounded-2xl p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[16px] font-extrabold tracking-tight flex items-center gap-2">
          <Wallet className="h-4 w-4 text-[var(--color-edify-primary)]" />
          This week&apos;s fund slip
        </h3>
        <span
          className={`text-[11px] font-bold px-2 py-0.5 rounded-md ${
            costMissing
              ? "bg-amber-100 text-amber-700"
              : "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]"
          }`}
        >
          {costMissing ? "Cost gaps" : "Live"}
        </span>
      </div>

      <div className="rounded-xl border border-[var(--color-edify-border)] px-3 py-2.5">
        <div className="text-[13px] font-bold text-[var(--color-edify-text)]">
          {weekLabel} · {activityCount} planned{" "}
          {activityCount === 1 ? "activity" : "activities"} · {fmtUgx(amount)}
        </div>
        <div className="muted text-[11.5px] mt-0.5">
          {costMissing
            ? `${b.costMissingCount} activities missing a catalogue rate — ask your CD.`
            : "Amount auto-priced from your scheduled activities and the CD cost catalogue."}
        </div>
      </div>

      <Link
        href="/weekly-funds"
        className="inline-flex items-center h-9 px-3.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12.5px] font-bold hover:opacity-90 transition-opacity"
      >
        Review weekly fund request
      </Link>
    </div>
  );
}
