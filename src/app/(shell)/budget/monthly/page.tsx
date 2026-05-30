import { StubPage } from "@/components/shell/StubPage";
import { monthlyFundingPlans, calculateBudgetVariance } from "@/lib/budget-mock";
import { formatUgxBig } from "@/lib/cost-settings-mock";
import { activeFinancialYear } from "@/lib/fy-engine";
import { cn } from "@/lib/utils";

const QTONE = {
  Q1: "bg-emerald-100 text-emerald-700",
  Q2: "bg-sky-100     text-sky-700",
  Q3: "bg-violet-100  text-violet-700",
  Q4: "bg-amber-100   text-amber-700",
} as const;

export default function MonthlyFundingPlanPage() {
  const fy = activeFinancialYear();
  const v  = calculateBudgetVariance();

  return (
    <StubPage
      title="Monthly Funding Plan"
      subtitle={`Annual → Quarterly → Monthly. ${fy.label}. Only approved planned activities + active cost settings generate funding. Unscheduled, vague, or unapproved activities are excluded.`}
    >
      {/* Variance summary */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Budgeted"  value={formatUgxBig(v.budgeted)} />
        <Kpi label="Disbursed" value={formatUgxBig(v.disbursed)} tone="green" />
        <Kpi label="Spent"     value={formatUgxBig(v.spent)} tone="amber" />
        <Kpi label="Variance"  value={formatUgxBig(v.variance)} sub={`${v.pctSpent}% spent`} tone={v.variance >= 0 ? "green" : "rose"} />
      </section>

      {/* Monthly table */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight">Monthly funding plan</h2>
          <span className="text-caption muted">FY months Oct → Sep</span>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">Month</th>
                <th scope="col" className="py-2 px-2">Quarter</th>
                <th scope="col" className="py-2 px-2 text-right">Budgeted</th>
                <th scope="col" className="py-2 px-2 text-right">Funded</th>
                <th scope="col" className="py-2 px-2 text-right">Disbursed</th>
                <th scope="col" className="py-2 px-2 text-right">Spent</th>
                <th scope="col" className="py-2 pl-2 text-right">Variance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {monthlyFundingPlans.map((m) => {
                const variancePct = m.budgeted === 0 ? 0 : Math.round((m.variance / m.budgeted) * 100);
                return (
                  <tr key={m.month}>
                    <td className="py-2 pr-2 font-extrabold">{m.month}</td>
                    <td className="py-2 px-2">
                      <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold", QTONE[m.quarter])}>
                        {m.quarter}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-right tabular">{formatUgxBig(m.budgeted)}</td>
                    <td className="py-2 px-2 text-right tabular">{formatUgxBig(m.funded)}</td>
                    <td className="py-2 px-2 text-right tabular">{formatUgxBig(m.disbursed)}</td>
                    <td className="py-2 px-2 text-right tabular font-extrabold">{formatUgxBig(m.spent)}</td>
                    <td className="py-2 pl-2 text-right tabular font-extrabold">
                      <span className={m.variance >= 0 ? "text-emerald-700" : "text-rose-700"}>
                        {formatUgxBig(m.variance)}
                        <span className="muted font-medium ml-1">({variancePct}%)</span>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Flow contract */}
      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Flow: </span>
        Annual Budget → Quarterly Budget → Monthly Funding Plan → Approved Plan Activities → Fund Requests →
        Disbursement → Funded vs Completed. Monthly funding is generated only from approved planned activities,
        active cost settings, and confirmed cluster dates where required.
      </section>
    </StubPage>
  );
}

function Kpi({ label, value, sub, tone = "edify" }: { label: string; value: string; sub?: string; tone?: "edify" | "green" | "amber" | "rose" }) {
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
