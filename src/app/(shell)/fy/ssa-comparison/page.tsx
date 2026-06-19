import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { cn } from "@/lib/utils";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";
import { getCurrentUser } from "@/lib/auth";
import { fetchInterventionImprovement } from "@/lib/api/surfaces";

// Module-scope so it isn't re-created on every render (react-hooks/static-components).
function Stat({ label, value, tone }: { label: string; value: number; tone: "up" | "down" | "flat" }) {
  return (
    <div className="card p-3.5">
      <div className="text-caption muted">{label}</div>
      <div className={cn("text-2xl font-extrabold tracking-tight mt-1", tone === "up" ? "text-emerald-600" : tone === "down" ? "text-rose-600" : "text-slate-600")}>
        {value.toLocaleString()}
      </div>
    </div>
  );
}

// Year-over-year SSA movement — LIVE from the backend intervention-improvement
// engine (prev-FY vs current-FY, per district, across the 8 interventions). Only
// schools with BOTH a prior-FY and current-FY SSA are compared; the rest are shown
// as "no baseline" rather than counted as impact.
export default async function YearlyComparisonPage() {
  const user = await getCurrentUser();
  const res = await fetchInterventionImprovement(user, { groupBy: "district" });
  if (!res.live)
    return (
      <ProductiveEmptyState
        Icon={TrendingUp}
        title="Year-over-year SSA comparison isn't connected to live data yet"
        description="Prior-vs-current FY SSA impact is withheld until both years trace to live source records."
        actionLabel="Open Analytics"
        actionHref="/analytics"
        links={[{ label: "Data room", href: "/analytics/data-room" }, { label: "Schools", href: "/schools" }]}
        note="No fabricated comparison figures are shown."
      />
    );
  const { currentFy, prevFy, rows } = res.data;

  const totals = rows.reduce(
    (t, r) => ({
      improved: t.improved + r.schoolsImproved,
      declined: t.declined + r.schoolsDeclined,
      noComp: t.noComp + r.schoolsNoComparison,
    }),
    { improved: 0, declined: 0, noComp: 0 },
  );
  const sorted = [...rows].sort((a, b) => (b.improvementRate ?? -1) - (a.improvementRate ?? -1));

  return (
    <StubPage
      title="Yearly SSA Performance Comparison"
      subtitle={`Year-over-year SSA movement (FY${prevFy} → FY${currentFy}) by district, across all 8 official intervention areas. Only schools with both a prior-FY and current-FY SSA are compared.`}
    >
      <section className="grid grid-cols-3 gap-3">
        <Stat label="Schools improved" value={totals.improved} tone="up" />
        <Stat label="Schools declined" value={totals.declined} tone="down" />
        <Stat label="No prior-FY baseline" value={totals.noComp} tone="flat" />
      </section>

      <section className="card overflow-hidden mt-4">
        <header className="px-4 py-3 border-b border-[var(--color-edify-divider)]">
          <h2 className="text-body-lg font-extrabold tracking-tight">District improvement ({rows.length})</h2>
          <p className="text-[11.5px] muted">Ranked by improvement rate. "Most improved" / "weakest" are the standout interventions per district.</p>
        </header>
        <div className="divide-y divide-[var(--color-edify-divider)]">
          {sorted.map((r) => {
            const rate = r.improvementRate;
            const Icon = rate == null ? Minus : rate >= 60 ? TrendingUp : rate <= 40 ? TrendingDown : Minus;
            const tone = rate == null ? "text-slate-400" : rate >= 60 ? "text-emerald-600" : rate <= 40 ? "text-rose-600" : "text-amber-600";
            return (
              <div key={r.groupId} className="px-4 py-2.5 grid grid-cols-12 gap-2 items-center text-[12px]">
                <div className="col-span-3 font-extrabold tracking-tight truncate">{r.groupName}</div>
                <div className={cn("col-span-2 inline-flex items-center gap-1 font-extrabold", tone)}>
                  <Icon size={12} /> {rate == null ? "—" : `${rate}%`}
                </div>
                <div className="col-span-3 text-secondary">
                  <span className="text-emerald-700 font-semibold">{r.schoolsImproved}↑</span>{" / "}
                  <span className="text-rose-700 font-semibold">{r.schoolsDeclined}↓</span>
                  {r.schoolsNoComparison ? <span className="muted"> · {r.schoolsNoComparison} no baseline</span> : null}
                </div>
                <div className="col-span-2 truncate text-emerald-700">
                  {r.bestIntervention ? `${r.bestIntervention.label} +${r.bestIntervention.change}` : "—"}
                </div>
                <div className="col-span-2 truncate text-rose-700">
                  {r.weakestIntervention ? `${r.weakestIntervention.label} ${r.weakestIntervention.currAvg ?? ""}` : "—"}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </StubPage>
  );
}
