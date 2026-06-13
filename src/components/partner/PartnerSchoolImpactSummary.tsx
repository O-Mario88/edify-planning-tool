// PartnerSchoolImpactSummary — answers the "how is our work helping
// schools?" question. Sits below the operational sections so it
// rewards the partner without distracting from today's work.
//
// Five numbers, all from one source so they always add up:
//   • schoolsSupported  → schoolsCceoConfirmed  → schoolsMeVerified
//   • schoolsShowingImprovement  → schoolsMovedBandUp

import { TrendingUp, ArrowUp } from "lucide-react";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { schoolImpactMetrics } from "@/lib/partner/partner-evidence-mock";

export function PartnerSchoolImpactSummary() {
  const m = schoolImpactMetrics;
  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="text-[15px] font-extrabold tracking-tight">School Improvement Contribution</h3>
          <p className="text-[12px] muted mt-1">
            {m.windowLabel} — your work is changing what schools can do for their pupils.
          </p>
        </div>
      </header>

      {/* Funnel reading — supported → confirmed → verified */}
      <MetricStrip
        bare
        columns="grid-cols-1 sm:grid-cols-3"
        metrics={[
          { key: "supported", label: "Schools supported", value: m.schoolsSupported, caption: "this period" },
          { key: "cceo", label: "CCEO confirmed", value: m.schoolsCceoConfirmed, caption: `${pct(m.schoolsCceoConfirmed, m.schoolsSupported)}% of supported` },
          { key: "mne", label: "M&E verified", value: m.schoolsMeVerified, caption: `${pct(m.schoolsMeVerified, m.schoolsSupported)}% of supported`, tone: "good" },
        ]}
      />

      {/* Outcome callout — band changes are the strongest signal */}
      <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-3 flex items-start gap-3">
        <span className="grid place-items-center h-9 w-9 rounded-xl bg-emerald-100 text-emerald-700 shrink-0">
          <ArrowUp size={15} />
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-[12px] font-extrabold text-emerald-900">
            {m.schoolsMovedBandUp} schools moved up a performance band this period
          </div>
          <p className="text-[11.5px] text-emerald-800 leading-snug mt-0.5">
            {m.schoolsShowingImprovement} schools showing measurable improvement after your partner support.
          </p>
        </div>
        <span className="inline-flex items-center gap-1 text-caption font-bold text-emerald-700 whitespace-nowrap">
          <TrendingUp size={11} />
          Trend up
        </span>
      </div>
    </section>
  );
}

function pct(n: number, total: number): number {
  if (total === 0) return 0;
  return Math.round((n / total) * 100);
}
