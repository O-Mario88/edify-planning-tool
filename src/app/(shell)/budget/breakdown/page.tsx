import { StubPage } from "@/components/shell/StubPage";
import {
  annualBudgetLines,
  annualBudgetTotal,
  calculateBudgetToPlanTraceability,
} from "@/lib/budget-mock";
import { formatUgxBig } from "@/lib/cost-settings-mock";
import { activeFinancialYear } from "@/lib/fy-engine";
import { cn } from "@/lib/utils";

export default function AnnualBudgetBreakdownPage() {
  const fy = activeFinancialYear();

  return (
    <StubPage
      title="Annual Budget Breakdown"
      subtitle={`Every line traces back to the plan. Total: ${formatUgxBig(annualBudgetTotal)} for ${fy.label}. Each row shows formula + source + the monthly funding curve.`}
    >
      {/* Phone (<md): row-detail card list — every field is a label:value
          pair stacked under the category title. Avoids horizontal-scroll
          tables that force a one-thumb user to drag sideways. */}
      <section className="md:hidden space-y-2">
        {annualBudgetLines.map((l) => {
          const t = calculateBudgetToPlanTraceability(l);
          return (
            <article key={l.id} className="card p-3.5">
              <header className="flex items-start justify-between gap-3 mb-2">
                <h3 className="text-[13px] font-extrabold leading-tight">{l.budgetCategory}</h3>
                <span className={cn(
                  "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0",
                  l.status === "Active" && "bg-emerald-100 text-emerald-700",
                )}>{l.status}</span>
              </header>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11.5px]">
                <div>
                  <dt className="muted text-[10px] uppercase tracking-wide font-semibold">Quantity</dt>
                  <dd className="tabular font-semibold">{l.quantity.toLocaleString()}</dd>
                </div>
                <div className="text-right">
                  <dt className="muted text-[10px] uppercase tracking-wide font-semibold">Unit cost</dt>
                  <dd className="tabular font-semibold">{formatUgxBig(l.unitCost)}</dd>
                </div>
                <div className="col-span-2 flex items-center justify-between border-t border-[var(--color-edify-border)] pt-1.5 mt-0.5">
                  <dt className="muted text-[10px] uppercase tracking-wide font-semibold">Total</dt>
                  <dd className="tabular font-extrabold text-[13px]">{formatUgxBig(l.totalCost)}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="muted text-[10px] uppercase tracking-wide font-semibold">Formula</dt>
                  <dd className="muted leading-snug">{l.formula}</dd>
                </div>
                <div>
                  <dt className="muted text-[10px] uppercase tracking-wide font-semibold">Source</dt>
                  <dd>
                    <span className="inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]">
                      {l.source}
                    </span>
                  </dd>
                </div>
                <div className="text-right">
                  <dt className="muted text-[10px] uppercase tracking-wide font-semibold">Owner</dt>
                  <dd className="muted">{t.ownerType}</dd>
                </div>
              </dl>
            </article>
          );
        })}
        <article className="card p-3.5 bg-[var(--color-edify-soft)]/40 flex items-center justify-between">
          <span className="text-[12px] font-extrabold">Total annual budget</span>
          <span className="tabular font-extrabold text-body-lg">{formatUgxBig(annualBudgetTotal)}</span>
        </article>
      </section>

      {/* Tablet + desktop (≥md): the full traceability table — formula,
          source, owner, status all visible at once. */}
      <section className="hidden md:block card p-3.5">
        <div className="overflow-x-auto">
          <table className="w-full text-[12px] min-w-[820px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">Category</th>
                <th scope="col" className="py-2 px-2 text-right">Quantity</th>
                <th scope="col" className="py-2 px-2 text-right">Unit cost</th>
                <th scope="col" className="py-2 px-2 text-right">Total</th>
                <th scope="col" className="py-2 px-2">Formula</th>
                <th scope="col" className="py-2 px-2">Source</th>
                <th scope="col" className="py-2 px-2">Owner</th>
                <th scope="col" className="py-2 pl-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {annualBudgetLines.map((l) => {
                const t = calculateBudgetToPlanTraceability(l);
                return (
                  <tr key={l.id} className="hover:bg-[var(--color-edify-soft)]/30 align-top">
                    <td className="py-2.5 pr-2 font-extrabold">{l.budgetCategory}</td>
                    <td className="py-2.5 px-2 text-right tabular">{l.quantity.toLocaleString()}</td>
                    <td className="py-2.5 px-2 text-right tabular">{formatUgxBig(l.unitCost)}</td>
                    <td className="py-2.5 px-2 text-right tabular font-extrabold">{formatUgxBig(l.totalCost)}</td>
                    <td className="py-2.5 px-2 muted leading-snug max-w-[260px]">{l.formula}</td>
                    <td className="py-2.5 px-2">
                      <span className="inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]">
                        {l.source}
                      </span>
                    </td>
                    <td className="py-2.5 px-2 muted">{t.ownerType}</td>
                    <td className="py-2.5 pl-2">
                      <span className={cn(
                        "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                        l.status === "Active" && "bg-emerald-100 text-emerald-700",
                      )}>{l.status}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-[var(--color-edify-border)]">
                <td colSpan={3} className="py-2 pr-2 text-right font-extrabold">Total annual budget</td>
                <td className="py-2 px-2 text-right font-extrabold tabular">{formatUgxBig(annualBudgetTotal)}</td>
                <td colSpan={4} />
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Traceability contract: </span>
        Every line above must trace back to a plan, service rule, Core package rule, or approved assumption.
        No vague lines. No manually-typed totals. The system regenerates this whenever cost settings or school
        counts change.
      </section>
    </StubPage>
  );
}
