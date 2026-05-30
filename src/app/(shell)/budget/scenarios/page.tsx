import { StubPage } from "@/components/shell/StubPage";
import { budgetScenarios } from "@/lib/budget-mock";
import { formatUgxBig } from "@/lib/cost-settings-mock";
import { activeFinancialYear } from "@/lib/fy-engine";
import { cn } from "@/lib/utils";

export default function BudgetScenarioPlannerPage() {
  const fy = activeFinancialYear();

  return (
    <StubPage
      title="Budget Scenario Planner"
      subtitle={`Compare 7 budget scenarios side-by-side. ${fy.label}. CD + RVP use this to decide between minimum coverage, standard, full Core support, accelerated catch-up, partner-led delivery, reduced funding, or expansion.`}
    >
      <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {budgetScenarios.map((s) => (
          <article key={s.key} className="card p-3.5 flex flex-col gap-3">
            <header>
              <h2 className="text-[14.5px] font-extrabold tracking-tight">{s.label}</h2>
              <p className="text-[11.5px] muted leading-snug mt-0.5">{s.description}</p>
            </header>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-center">
              <Stat label="Total"          value={formatUgxBig(s.totalCost)} />
              <Stat label="Schools"        value={String(s.schoolsCovered)} />
              <Stat label="Funding gap"    value={s.fundingGap === 0 ? "—" : formatUgxBig(s.fundingGap)} />
            </div>

            <div className="flex items-center gap-2 text-caption">
              <span className="muted">Target risk:</span>
              <span className={cn(
                "inline-flex items-center px-1.5 py-[2px] rounded-md font-extrabold whitespace-nowrap",
                s.targetRisk === "Low"    && "bg-emerald-100 text-emerald-700",
                s.targetRisk === "Medium" && "bg-amber-100   text-amber-700",
                s.targetRisk === "High"   && "bg-rose-100    text-rose-700",
              )}>
                {s.targetRisk}
              </span>
            </div>

            <div className="text-[11.5px]">
              <div className="text-caption font-extrabold uppercase tracking-wide muted">Includes</div>
              <div className="muted">{s.activitiesIncluded.join(" · ")}</div>
            </div>

            {s.activitiesExcluded.length > 0 && (
              <div className="text-[11.5px]">
                <div className="text-caption font-extrabold uppercase tracking-wide muted">Excludes</div>
                <div className="muted">{s.activitiesExcluded.join(" · ")}</div>
              </div>
            )}

            <div className="rounded-lg bg-[var(--color-edify-soft)]/60 px-2.5 py-2 text-[11.5px]">
              <span className="font-extrabold">Expected impact: </span>
              <span>{s.expectedImpact}</span>
            </div>
          </article>
        ))}
      </section>
    </StubPage>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-2">
      <div className="text-[9.5px] muted font-extrabold uppercase tracking-wide">{label}</div>
      <div className="text-[13.5px] font-extrabold tabular leading-none mt-1">{value}</div>
    </div>
  );
}
