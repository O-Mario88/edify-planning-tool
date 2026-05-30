import Link from "next/link";
import {
  Wallet,
  Calculator,
  Layers,
  CalendarDays,
  ListChecks,
  TrendingUp,
  ChevronRight,
  AlertTriangle,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import {
  annualBudgetLines,
  annualBudgetTotal,
  breakAnnualBudgetIntoQuarterlyBudget,
  calculateBudgetVariance,
} from "@/lib/budget-mock";
import { validateCountryCostSettings, formatUgxBig } from "@/lib/cost-settings-mock";
import { activeFinancialYear } from "@/lib/fy-engine";
import { cn } from "@/lib/utils";

export default function AnnualBudgetBuilderPage() {
  const fy        = activeFinancialYear();
  const q         = breakAnnualBudgetIntoQuarterlyBudget();
  const v         = calculateBudgetVariance();
  const costCheck = validateCountryCostSettings();
  const blocked   = !costCheck.ready;

  // Group lines by budgetCategory for the overview.
  const byCategory = new Map<string, { quantity: number; total: number }>();
  for (const l of annualBudgetLines) {
    const cur = byCategory.get(l.budgetCategory) ?? { quantity: 0, total: 0 };
    byCategory.set(l.budgetCategory, { quantity: cur.quantity + l.quantity, total: cur.total + l.totalCost });
  }

  return (
    <StubPage
      title="Annual Budget Builder"
      subtitle={`Generated from active-FY school counts, service rules, and Country Cost Settings. ${fy.label}. Staff do not type budgets — the system calculates them.`}
    >
      {/* Blocked banner */}
      {blocked && (
        <section className="card p-3.5 border-rose-200 bg-rose-50/60">
          <div className="flex items-start gap-3">
            <span className="h-9 w-9 rounded-md bg-rose-100 text-rose-700 grid place-items-center shrink-0"><AlertTriangle size={16} /></span>
            <div className="flex-1 min-w-0">
              <h2 className="text-[13px] font-extrabold tracking-tight">Final approval BLOCKED</h2>
              <p className="text-[11.5px] muted">
                {costCheck.missing.length} required cost settings are still in Draft. Country Director must
                activate them before this budget can be approved.
              </p>
              <Link href="/cost-settings" className="text-[11.5px] font-semibold text-rose-700 hover:underline mt-1 inline-block">
                Open Country Cost Settings →
              </Link>
            </div>
          </div>
        </section>
      )}

      {/* Headline KPIs */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Annual budget"  value={formatUgxBig(annualBudgetTotal)} sub={`${annualBudgetLines.length} budget lines`} />
        <Kpi label="Q1 plan"        value={formatUgxBig(q.Q1)}             sub="Gateway-heavy"   tone="amber" />
        <Kpi label="Disbursed YTD"  value={formatUgxBig(v.disbursed)}      sub="across active months" tone="green" />
        <Kpi label="Spent YTD"      value={formatUgxBig(v.spent)}          sub={`${v.pctSpent}% of budget`} tone={v.pctSpent > 80 ? "amber" : "green"} />
      </section>

      {/* Category breakdown */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Budget by category</h2>
        <ul className="space-y-1.5">
          {Array.from(byCategory.entries()).map(([cat, agg]) => {
            const pct = annualBudgetTotal === 0 ? 0 : Math.round((agg.total / annualBudgetTotal) * 100);
            return (
              <li key={cat} className="grid grid-cols-[minmax(0,1fr)_auto_auto] sm:grid-cols-[200px_minmax(0,1fr)_110px_60px] items-center gap-x-3 gap-y-1 text-[12px]">
                <span className="font-extrabold tracking-tight truncate col-span-3 sm:col-span-1">{cat}</span>
                <div className="h-1.5 rounded-full bg-[#eef2f4] overflow-hidden col-span-3 sm:col-span-1 order-3 sm:order-none">
                  <div className="h-full rounded-full bg-[var(--color-edify-primary)]" style={{ width: `${pct}%` }} />
                </div>
                <span className="text-right font-extrabold tabular whitespace-nowrap">{formatUgxBig(agg.total)}</span>
                <span className="text-right muted tabular whitespace-nowrap">{pct}%</span>
              </li>
            );
          })}
        </ul>
      </section>

      {/* Section nav */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <Tile href="/budget/breakdown"  Icon={Layers}       title="Annual Budget Breakdown"    body="Every line with quantity, unit cost, formula, source." />
        <Tile href="/budget/scenarios"  Icon={Calculator}   title="Budget Scenario Planner"    body="Compare 7 scenarios side-by-side." />
        <Tile href="/budget/monthly"    Icon={CalendarDays} title="Monthly Funding Plan"       body="Quarterly → monthly with funded vs spent." />
        <Tile href="/approvals"  Icon={ListChecks}   title="Approvals" body="Role-aware queue. PLs review CCEO plans, CDs review PLs with funds matching, RVPs final-approve. Audit lives under /budget/approvals/amendments." />
        <Tile href="/budget/variance"   Icon={TrendingUp}   title="Budget Variance Review"     body="Budgeted vs disbursed vs spent, with reasons." />
        <Tile href="/cost-settings"     Icon={Wallet}       title="Country Cost Settings"      body="CD-controlled prices that drive every line." />
      </section>

      {/* Approval workflow contract */}
      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Workflow contract: </span>
        Country Director sets cost settings → system generates annual budget → Program Accountant reviews →
        Country Director approves country budget → RVP approves where required → budget becomes Active → broken
        into quarterly + monthly funding plans → approved monthly plans generate fund requests → disbursement →
        variance review. <span className="font-extrabold text-[var(--color-edify-text)]">Program Leads approve plans only — never funds.</span>
      </section>
    </StubPage>
  );
}

function Kpi({ label, value, sub, tone = "edify" }: { label: string; value: string; sub: string; tone?: "edify" | "green" | "amber" | "rose" }) {
  const TONE = {
    edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
    rose:  "bg-rose-100    text-rose-700",
  } as const;
  return (
    <div className="card p-3.5">
      <div className={cn("text-[11.5px] font-semibold inline-flex items-center px-2 py-[2px] rounded-md", TONE[tone])}>{label}</div>
      <div className="text-[24px] font-extrabold tabular leading-none mt-2">{value}</div>
      <div className="text-caption muted mt-1">{sub}</div>
    </div>
  );
}

function Tile({ href, Icon, title, body }: { href: string; Icon: typeof Wallet; title: string; body: string }) {
  return (
    <Link href={href} className="card p-3.5 flex items-start gap-3 hover:bg-[var(--color-edify-soft)]/40 transition-colors">
      <span className="h-10 w-10 rounded-xl bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
        <Icon size={18} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[13.5px] font-extrabold tracking-tight">{title}</h3>
          <ChevronRight size={13} className="text-[var(--color-edify-muted)]" />
        </div>
        <p className="text-[11.5px] muted leading-snug mt-0.5">{body}</p>
      </div>
    </Link>
  );
}
