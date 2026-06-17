import { getCurrentUser } from "@/lib/auth";
import { getDonorMetricSnapshot } from "@/lib/donor-metrics";
import { buildLiveDonorSnapshot } from "@/lib/donor-metrics-live";
import { isMockAllowed } from "@/lib/mock-policy";
import {
  METRIC_GROUP_LABELS,
  METRIC_STATUS_LABELS,
  type DonorMetric,
  type DonorRoleScope,
  type MetricSource,
} from "@/lib/donor-metrics-types";

// /donor-reporting/print — a print-styled donor reporting summary.
//
// This route deliberately lives outside the (shell) group so the
// sidebar / mobile nav / dashboard chrome don't bleed into the
// printed page. The user clicks "Donor Summary PDF" on the analytics
// surface → this route opens in a new tab → user prints / Save as PDF.
// Output is one self-contained A4 document; CSS prints clean without
// any extra tooling.

export const dynamic = "force-dynamic";

function roleToScope(role: string): DonorRoleScope {
  switch (role) {
    case "CCEO":               return "CCEO";
    case "CountryProgramLead": return "ProgramLead";
    case "ImpactAssessment":   return "ImpactAssessment";
    case "CountryDirector":    return "CountryDirector";
    case "RVP":                return "RVP";
    default:                   return "ProgramLead";
  }
}

function fmt(value: number | null, unit?: string): string {
  if (value === null) return "—";
  if (unit === "UGX") {
    if (value >= 1_000_000_000) return `UGX ${(value / 1_000_000_000).toFixed(2)} bn`;
    if (value >= 1_000_000) return `UGX ${(value / 1_000_000).toFixed(1)} M`;
    if (value >= 1_000) return `UGX ${(value / 1_000).toFixed(0)} k`;
    return `UGX ${value.toLocaleString()}`;
  }
  return value.toLocaleString();
}

function sourceLabel(source: MetricSource): string {
  switch (source) {
    case "derived":        return "Live · derived from records";
    case "estimated":      return "Estimated · awaiting taxonomy";
    case "pending_schema": return "Awaiting schema";
  }
}

export default async function DonorReportingPrintPage() {
  const user = await getCurrentUser();
  // Production: only REAL, verified, backend-derived donor metrics may leave the
  // system as a PDF. The mock snapshot renders for dev/design reference only.
  const live = !isMockAllowed() ? await buildLiveDonorSnapshot(user) : null;
  if (!isMockAllowed() && !live) {
    return (
      <main className="print-doc">
        <PrintStyles />
        <header className="print-header">
          <div className="print-eyebrow">Donor Reporting Impact</div>
          <h1>Donor report is not ready</h1>
          <p className="print-subtitle">
            Complete and verify activities to generate donor metrics. Every figure on
            this report is derived from IA-verified, source-backed records — none are
            estimated or fabricated.
          </p>
        </header>
      </main>
    );
  }
  const snapshot =
    live ??
    getDonorMetricSnapshot({
      role: roleToScope(user.role),
      userName: user.name,
      generatedBy: user.name,
    });

  return (
    <main className="print-doc">
      <PrintStyles />
      <header className="print-header">
        <div className="print-eyebrow">Donor Reporting Impact · {snapshot.roleScope}</div>
        <h1>{snapshot.scopeLabel}</h1>
        <p className="print-subtitle">
          Evidence-backed reach, training, geography & school improvement —
          {" "}{snapshot.filters.operationalCycleLabel}
          {" · "}{snapshot.filters.dateRangeStart} → {snapshot.filters.dateRangeEnd}
        </p>
        <div className="print-meta">
          <span>
            Generated {new Date(snapshot.generatedAt).toLocaleString()} by {snapshot.generatedBy}.
          </span>
          <span className="print-readiness">
            Donor Reporting Readiness · <b>{snapshot.readiness.score}%</b> ·
            {" "}{snapshot.readiness.summary}
          </span>
        </div>
        {/* Cmd/Ctrl + P is the canonical "Save as PDF" path; this is
            a hint, not a handler. Hidden in the printed output. */}
        <div className="print-action no-print">
          Press Cmd/Ctrl + P to save this report as a PDF
        </div>
      </header>

      <section>
        <h2>Donor-Ready Numbers</h2>
        <table className="kpi-table">
          <thead>
            <tr>
              <th>Group</th>
              <th>Metric</th>
              <th className="num">Donor-ready</th>
              <th className="num">Confirmed</th>
              <th className="num">Pending</th>
              <th className="num">Excluded</th>
              <th>Status</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.metrics.map((m) => (
              <MetricRow key={m.key} m={m} />
            ))}
          </tbody>
        </table>
      </section>

      <section className="page-break">
        <h2>Readiness Breakdown</h2>
        <table className="readiness-table">
          <thead>
            <tr>
              <th>Component</th>
              <th className="num">Score</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.readiness.components.map((c) => (
              <tr key={c.key}>
                <td>{c.label}</td>
                <td className="num">{c.pct}%</td>
                <td>{c.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Student Impact Coverage</h2>
        <table className="kv-table">
          <tbody>
            <tr><td>Schools reached</td><td className="num">{snapshot.enrollmentCoverage.schoolsReached.toLocaleString()}</td></tr>
            <tr><td>Schools with enrollment on file</td><td className="num">{snapshot.enrollmentCoverage.schoolsWithEnrollment.toLocaleString()}</td></tr>
            <tr><td>Schools missing enrollment</td><td className="num">{snapshot.enrollmentCoverage.schoolsMissingEnrollment.toLocaleString()}</td></tr>
            <tr><td>Caveat</td><td>{snapshot.enrollmentCoverage.note}</td></tr>
          </tbody>
        </table>
      </section>

      <section className="page-break">
        <h2>By Intervention</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>Intervention</th>
              <th className="num">Trainings</th>
              <th className="num">Teachers</th>
              <th className="num">Leaders</th>
              <th className="num">Schools</th>
              <th className="num">Students</th>
              <th className="num">Improved</th>
              <th className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.interventions.map((r) => (
              <tr key={r.area}>
                <td>{r.area}</td>
                <td className="num">{r.trainings.toLocaleString()}</td>
                <td className="num">{r.teachersTrained.toLocaleString()}</td>
                <td className="num">{r.schoolLeadersTrained.toLocaleString()}</td>
                <td className="num">{r.schoolsReached.toLocaleString()}</td>
                <td className="num">{r.studentsImpacted?.toLocaleString() ?? "—"}</td>
                <td className="num">{r.schoolsImproved?.toLocaleString() ?? "—"}</td>
                <td className="num">{fmt(r.costUgx, "UGX")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>By District</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>District</th>
              <th className="num">Schools</th>
              <th className="num">Teachers</th>
              <th className="num">Leaders</th>
              <th className="num">Students</th>
              <th className="num">Trainings</th>
              <th className="num">Visits</th>
              <th className="num">Improved</th>
              <th className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.districts.map((d) => (
              <tr key={d.district}>
                <td>{d.district}</td>
                <td className="num">{d.schoolsReached.toLocaleString()}</td>
                <td className="num">{d.teachersTrained.toLocaleString()}</td>
                <td className="num">{d.schoolLeadersTrained.toLocaleString()}</td>
                <td className="num">{d.studentsImpacted?.toLocaleString() ?? "—"}</td>
                <td className="num">{d.trainings.toLocaleString()}</td>
                <td className="num">{d.visits.toLocaleString()}</td>
                <td className="num">{d.schoolsImproved?.toLocaleString() ?? "—"}</td>
                <td className="num">{fmt(d.costUgx, "UGX")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {snapshot.warnings.length > 0 && (
        <section className="page-break">
          <h2>Data Quality &amp; Caveats</h2>
          <ul className="warnings">
            {snapshot.warnings.map((w, i) => (
              <li key={i} className={`warning-${w.severity}`}>
                <div className="warning-title">
                  <span className={`warning-badge warning-badge-${w.severity}`}>
                    {w.severity}
                  </span>
                  {w.title}
                </div>
                <p>{w.detail}</p>
                {w.affectedMetricKeys.length > 0 && (
                  <p className="warning-affected">
                    Affects: {w.affectedMetricKeys.join(", ")}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2>Metric Definitions</h2>
        <dl className="defs">
          {snapshot.metrics.map((m) => (
            <div key={m.key} className="def">
              <dt>{m.label}</dt>
              <dd>{m.definition}</dd>
            </div>
          ))}
        </dl>
      </section>

      <footer className="print-footer">
        <span>Edify Planning Tool · Donor Reporting Impact · {snapshot.scopeLabel}</span>
        <span>{new Date(snapshot.generatedAt).toLocaleString()}</span>
      </footer>
    </main>
  );
}

function MetricRow({ m }: { m: DonorMetric }) {
  return (
    <tr>
      <td>{METRIC_GROUP_LABELS[m.group]}</td>
      <td>{m.label}</td>
      <td className="num donor-ready">{fmt(m.value, m.unit)}</td>
      <td className="num">{m.breakdown ? fmt(m.breakdown.confirmed, m.unit) : "—"}</td>
      <td className="num">{m.breakdown ? (m.breakdown.pendingEvidence + m.breakdown.pendingVerification).toLocaleString() : "—"}</td>
      <td className="num">{m.breakdown ? m.breakdown.excluded.toLocaleString() : "—"}</td>
      <td>{METRIC_STATUS_LABELS[m.status]}</td>
      <td>{sourceLabel(m.source)}</td>
    </tr>
  );
}

function PrintStyles() {
  // Inlined so the print route is self-contained and unaffected by the
  // app shell's stylesheets. Tuned for A4 / Letter.
  const css = `
    .print-doc { font-family: var(--font-source-sans), Inter, system-ui, sans-serif; color: #0f172a; padding: 32px 40px 56px; max-width: 880px; margin: 0 auto; background: #fff; line-height: 1.45; font-size: 12px; }
    .print-header { border-bottom: 2px solid #0f172a; padding-bottom: 14px; margin-bottom: 22px; }
    .print-eyebrow { font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 800; color: #475569; }
    .print-doc h1 { font-size: 22px; font-weight: 800; letter-spacing: -0.02em; margin: 6px 0 4px; }
    .print-subtitle { font-size: 12px; color: #334155; margin: 0 0 8px; }
    .print-meta { display: flex; gap: 16px; flex-wrap: wrap; font-size: 10.5px; color: #475569; }
    .print-readiness b { color: #0f172a; }
    .print-action { margin-top: 12px; display: inline-block; padding: 8px 14px; background: #0f172a; color: #fff; border: none; border-radius: 8px; font-size: 11px; font-weight: 700; cursor: pointer; }
    .print-doc h2 { font-size: 14px; font-weight: 800; letter-spacing: -0.01em; margin: 18px 0 8px; padding-top: 4px; }
    .print-doc table { width: 100%; border-collapse: collapse; font-size: 11px; }
    .print-doc th, .print-doc td { padding: 6px 8px; border-bottom: 1px solid #e2e8f0; text-align: left; vertical-align: top; }
    .print-doc th { font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 800; color: #475569; background: #f8fafc; }
    .print-doc .num { text-align: right; font-variant-numeric: tabular-nums; }
    .print-doc .donor-ready { font-weight: 800; }
    .kpi-table td:first-child { color: #475569; font-weight: 700; }
    .readiness-table td:first-child { font-weight: 700; }
    .kv-table td:first-child { color: #475569; font-weight: 700; width: 40%; }
    .warnings { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
    .warnings li { border: 1px solid #e2e8f0; padding: 10px 12px; border-radius: 8px; }
    .warning-blocker { border-color: #fda4af; background: #fff1f2; }
    .warning-warning { border-color: #fde68a; background: #fffbeb; }
    .warning-info    { border-color: #cbd5e1; background: #f8fafc; }
    .warning-title { display: flex; gap: 8px; align-items: center; font-weight: 800; }
    .warning-badge { padding: 1px 6px; border-radius: 4px; font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 800; }
    .warning-badge-blocker { background: #fee2e2; color: #b91c1c; }
    .warning-badge-warning { background: #fef3c7; color: #b45309; }
    .warning-badge-info    { background: #e2e8f0; color: #475569; }
    .warning-affected { font-size: 10px; color: #475569; margin: 4px 0 0; }
    .defs { columns: 2; column-gap: 20px; }
    .def { break-inside: avoid; margin-bottom: 10px; }
    .def dt { font-weight: 800; font-size: 11px; }
    .def dd { margin: 2px 0 0; font-size: 10.5px; color: #334155; }
    .print-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 26px; padding-top: 12px; border-top: 1px solid #e2e8f0; font-size: 10px; color: #475569; }
    @media print {
      @page { size: A4; margin: 14mm 14mm 18mm; }
      .print-doc { padding: 0; max-width: none; }
      .no-print  { display: none !important; }
      .page-break { break-before: page; }
      table { page-break-inside: auto; }
      tr { page-break-inside: avoid; page-break-after: auto; }
      thead { display: table-header-group; }
    }
  `;
  return <style>{css}</style>;
}
