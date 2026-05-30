import Link from "next/link";
import { StubPage } from "@/components/shell/StubPage";
import { monthlyFundingPlans, calculateBudgetVariance } from "@/lib/budget-mock";
import { formatUgxBig } from "@/lib/cost-settings-mock";
import { cn } from "@/lib/utils";

// Short, hand-curated variance reasons — production wires this to the Field
// Intelligence Engine so each spike can be drilled into.
const VARIANCE_REASONS: Record<string, string> = {
  Oct: "Gateway clusters ran with 8% fewer participants than budgeted.",
  Nov: "12 activities moved into Dec due to school closures + route conflicts.",
};

export default function BudgetVarianceReviewPage() {
  const v = calculateBudgetVariance();
  // Months past + current carry variance data; future months still show 0
  const monthsWithSpend = monthlyFundingPlans.filter((m) => m.spent > 0);

  return (
    <StubPage
      title="Budget Variance Review"
      subtitle="At month-end, compare budgeted vs disbursed vs spent vs verified. Variance must connect to Field Intelligence — finance is not separate from field reality."
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Budgeted"  value={formatUgxBig(v.budgeted)} />
        <Stat label="Disbursed" value={formatUgxBig(v.disbursed)} tone="green" />
        <Stat label="Spent"     value={formatUgxBig(v.spent)} tone="amber" />
        <Stat label="Variance"  value={formatUgxBig(v.variance)} tone={v.variance >= 0 ? "green" : "rose"} sub={`${v.pctSpent}% spent`} />
      </section>

      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight">Monthly variance</h2>
          <Link href="/field-intelligence" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
            Open Field Intelligence →
          </Link>
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {monthlyFundingPlans.map((m) => {
            const pct = m.budgeted === 0 ? 0 : Math.round((m.spent / m.budgeted) * 100);
            const tone = pct >= 95 ? "text-emerald-700" : pct >= 70 ? "text-amber-700" : "text-rose-700";
            const reason = VARIANCE_REASONS[m.month];
            const isFuture = m.spent === 0;
            return (
              <li key={m.month} className="py-2.5 flex items-center gap-3">
                <span className="w-12 font-extrabold tracking-tight shrink-0">{m.month}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 text-[11.5px] muted">
                    <span>Budgeted {formatUgxBig(m.budgeted)}</span>
                    <span>·</span>
                    <span>Disbursed {formatUgxBig(m.disbursed)}</span>
                    <span>·</span>
                    <span className="text-[var(--color-edify-text)]">Spent <span className="font-extrabold">{formatUgxBig(m.spent)}</span></span>
                  </div>
                  {!isFuture && (
                    <div className="text-caption muted mt-0.5">{reason ?? "On-track within tolerance."}</div>
                  )}
                </div>
                {!isFuture && (
                  <span className={cn("text-[12px] font-extrabold tabular shrink-0", tone)}>
                    {pct}%
                  </span>
                )}
                {isFuture && <span className="text-caption muted shrink-0">Upcoming</span>}
              </li>
            );
          })}
        </ul>
        <div className="mt-3 text-caption muted">{monthsWithSpend.length} months with spend · {monthlyFundingPlans.length - monthsWithSpend.length} upcoming.</div>
      </section>
    </StubPage>
  );
}

function Stat({ label, value, sub, tone = "edify" }: { label: string; value: string; sub?: string; tone?: "edify" | "green" | "amber" | "rose" }) {
  const TONE = {
    edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
    rose:  "bg-rose-100    text-rose-700",
  } as const;
  return (
    <div className="card p-3.5">
      <div className={cn("text-[11.5px] font-semibold inline-flex items-center px-2 py-[2px] rounded-md", TONE[tone])}>{label}</div>
      <div className="text-[22px] font-extrabold tabular leading-none mt-2">{value}</div>
      {sub && <div className="text-caption muted mt-1">{sub}</div>}
    </div>
  );
}
