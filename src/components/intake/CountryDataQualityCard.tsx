// Country Data Quality surface (spec layer #10). Server component — the headline
// confidence score (master-data + workflow completeness) with a plain-English
// risk summary and per-dimension bars. For CD / IA / RVP.

import { countryDataQuality, type CountryDataQualityBand } from "@/lib/intake/country-data-quality";
import { cn } from "@/lib/utils";

const BAND: Record<CountryDataQualityBand, { text: string; bar: string; chip: string }> = {
  "Excellent": { text: "text-emerald-600", bar: "bg-emerald-500", chip: "bg-emerald-100 text-emerald-700" },
  "Good": { text: "text-emerald-600", bar: "bg-emerald-500", chip: "bg-emerald-100 text-emerald-700" },
  "Fair": { text: "text-amber-600", bar: "bg-amber-500", chip: "bg-amber-100 text-amber-700" },
  "Needs work": { text: "text-rose-600", bar: "bg-rose-500", chip: "bg-rose-100 text-rose-700" },
};

export function CountryDataQualityCard() {
  const r = countryDataQuality();
  const b = BAND[r.band];

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-[15px] font-extrabold tracking-tight">Country Data Quality</h2>
          <p className="text-[11.5px] muted">
            Confidence across school master data and the full workflow — evidence, Salesforce IDs, IA verification, the 10% QA sample, and fund-cost match.
          </p>
          <p className="mt-1.5 text-[12px] font-semibold text-slate-600 dark:text-slate-300">{r.riskSummary}</p>
        </div>
        <div className="text-right shrink-0">
          <div className={cn("text-[28px] font-extrabold tabular leading-none", b.text)}>{r.score}%</div>
          <span className={cn("mt-1 inline-block rounded-md px-1.5 py-[2px] text-[10px] font-extrabold", b.chip)}>{r.band}</span>
        </div>
      </header>

      <ul className="mt-3 grid grid-cols-1 gap-x-5 gap-y-2 sm:grid-cols-2">
        {r.dimensions.map((d) => (
          <li key={d.key}>
            <div className="flex items-baseline justify-between gap-2 text-[11.5px]">
              <span className={cn("truncate", d.risk ? "font-semibold text-slate-700 dark:text-slate-200" : "muted")}>{d.label}</span>
              <span className="tabular shrink-0 text-[11px] muted">{d.detail}</span>
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className={cn("h-full rounded-full", d.risk ? "bg-amber-500" : "bg-emerald-500")}
                style={{ width: `${d.score}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
