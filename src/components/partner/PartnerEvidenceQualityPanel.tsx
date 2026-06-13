// PartnerEvidenceQualityPanel — small quality-metrics card showing
// the partner's trailing 30-day evidence performance. Encourages
// quality without overwhelming — 5 simple numbers, one tone per row.

import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { evidenceQualityMetrics } from "@/lib/partner/partner-evidence-mock";

export function PartnerEvidenceQualityPanel() {
  const m = evidenceQualityMetrics;
  const metrics: MetricCell[] = [
    { key: "completion", label: "Completion rate", value: `${m.completionRatePct}%`,      caption: "Required items uploaded", tone: "good" },
    { key: "returned",   label: "Returned rate",   value: `${m.returnedRatePct}%`,        caption: "Of submissions returned", tone: m.returnedRatePct > 10 ? "alert" : "default" },
    { key: "correction", label: "Avg correction",  value: `${m.avgCorrectionDays} days`,  caption: "Median fix turnaround" },
    { key: "mne",        label: "M&E verified",    value: `${m.mneVerificationRatePct}%`, caption: "Of confirmed → counted" },
    { key: "rejected",   label: "Rejected",        value: String(m.rejectedCount),        caption: "Past 30 days", tone: m.rejectedCount > 0 ? "alert" : "good" },
  ];

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-body-lg font-extrabold tracking-tight">Evidence Quality</h3>
          <p className="text-[11.5px] muted mt-0.5">{m.windowLabel}</p>
        </div>
      </header>
      <MetricStrip bare columns="grid-cols-2 lg:grid-cols-5" metrics={metrics} />
    </section>
  );
}
