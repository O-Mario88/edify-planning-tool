import { StubPage } from "@/components/shell/StubPage";
import { generateWhatChangedFromLastYear, previousFinancialYear, activeFinancialYear } from "@/lib/fy-engine";

export default function WhatsChangedPage() {
  const c = generateWhatChangedFromLastYear();
  const prev = previousFinancialYear();
  const curr = activeFinancialYear();

  const rows: { area: string; metric: string; delta: number; tone: "up" | "down" | "flat"; note?: string }[] = [
    { area: "School register",  metric: "Schools added",       delta: c.schoolsAdded,        tone: "up",   note: "Most are Client schools in Northern + Eastern regions." },
    { area: "School register",  metric: "Schools removed",     delta: c.schoolsRemoved,      tone: "down", note: "Closed or merged with another school." },
    { area: "School register",  metric: "Schools inactive",    delta: c.schoolsInactive,     tone: "flat", note: "Active in register but flagged inactive this FY." },
    { area: "Segments",         metric: "Client → Core",       delta: c.clientToCore,        tone: "up",   note: "Earned Core status from sustained verified SSA ≥ 7.5." },
    { area: "Segments",         metric: "Champion candidates", delta: c.championCandidates,  tone: "up",   note: "Verified SSA ≥ 7.5 across all 8 interventions for 2 consecutive FYs." },
    { area: "Performance",      metric: "Districts improving", delta: c.districtsImproving,  tone: "up" },
    { area: "Performance",      metric: "Districts declining", delta: c.districtsDeclining,  tone: "down" },
    { area: "Cost settings",    metric: "Cost lines changed",  delta: c.costChanges,         tone: "flat", note: "CD-approved unit cost updates." },
    { area: "Targets",          metric: "Target rules changed",delta: c.targetChanges,       tone: "flat" },
    { area: "Budget",           metric: "Budget lines changed",delta: c.budgetChanges,       tone: "flat", note: "Driven by school count + cost setting changes." },
  ];

  return (
    <StubPage
      title="What changed from last FY?"
      subtitle={`Year-over-year deltas across schools, segments, performance, cost settings, targets, and budgets. Comparison: ${prev?.label} → ${curr.label}.`}
    >
      <section className="card p-3.5">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
              <th scope="col" className="py-2 pr-2">Area</th>
              <th scope="col" className="py-2 px-2">Metric</th>
              <th scope="col" className="py-2 px-2 text-right">Delta</th>
              <th scope="col" className="py-2 pl-2">Note</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="py-2 pr-2 font-extrabold">{r.area}</td>
                <td className="py-2 px-2">{r.metric}</td>
                <td className="py-2 px-2 text-right tabular font-extrabold">
                  {r.tone === "down" ? `-${r.delta}` : `+${r.delta}`}
                </td>
                <td className="py-2 pl-2 muted">{r.note ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </StubPage>
  );
}
