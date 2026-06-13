"use client";

// Donor Reporting Impact — the donor-facing layer of the analytics
// surface. Renders evidence-backed reach, training, geography, evidence,
// cost, and impact metrics with explicit verification status and data
// source on every number. Drops into any role analytics page; the
// underlying data is produced upstream by `getDonorMetricSnapshot`.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BadgeCheck,
  Building2,
  ChevronDown,
  ClipboardCheck,
  Download,
  FileSpreadsheet,
  FileText,
  GraduationCap,
  HelpCircle,
  Info,
  MapPin,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";
import { ProgressRing, StatusBadge } from "@/components/ui/primitives";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { cn } from "@/lib/utils";
import {
  METRIC_GROUP_LABELS,
  METRIC_STATUS_LABELS,
  type DonorMetric,
  type DonorMetricGroup,
  type DonorMetricSnapshot,
  type DonorMetricStatus,
  type MetricSource,
} from "@/lib/donor-metrics-types";

// ── Tiny presentation helpers ──────────────────────────────────────

const GROUP_ICON: Record<DonorMetricGroup, LucideIcon> = {
  reach:      Users,
  training:   GraduationCap,
  geography:  MapPin,
  evidence:   ClipboardCheck,
  cost:       FileSpreadsheet,
  impact:     Sparkles,
};

const GROUP_TONE: Record<DonorMetricGroup, { fg: string; bg: string }> = {
  reach:      { fg: "#0f8a5f", bg: "#e6f5ee" },
  training:   { fg: "#2f6fe0", bg: "#e6f0fc" },
  geography:  { fg: "#7c3aed", bg: "#ede9fe" },
  evidence:   { fg: "#0a4856", bg: "#e8f1f3" },
  cost:       { fg: "#b45309", bg: "#fef3c7" },
  impact:     { fg: "#d93b50", bg: "#fdf0f1" },
};

const STATUS_CHIP: Record<DonorMetricStatus, "green" | "amber" | "red" | "blue" | "grey"> = {
  verified:                  "green",
  confirmed:                 "blue",
  pending_evidence:          "amber",
  pending_cceo_confirmation: "amber",
  pending_me_verification:   "amber",
  excluded:                  "grey",
};

function formatNumber(value: number | null, unit?: string): string {
  if (value === null) return "—";
  if (unit === "UGX") {
    if (value >= 1_000_000_000) return `UGX ${(value / 1_000_000_000).toFixed(2)} bn`;
    if (value >= 1_000_000)     return `UGX ${(value / 1_000_000).toFixed(1)} M`;
    if (value >= 1_000)         return `UGX ${(value / 1_000).toFixed(0)} k`;
    return `UGX ${value.toLocaleString()}`;
  }
  return value.toLocaleString();
}

function sourceLabel(source: MetricSource): string {
  switch (source) {
    case "derived":         return "Live · derived from records";
    case "estimated":       return "Estimated · awaiting taxonomy";
    case "pending_schema":  return "Awaiting schema — not donor-reportable";
  }
}

function sourceTone(source: MetricSource): "green" | "amber" | "red" | "blue" | "grey" {
  switch (source) {
    case "derived":         return "green";
    case "estimated":       return "blue";
    case "pending_schema":  return "red";
  }
}

// ── Metric card ────────────────────────────────────────────────────

function MetricCard({ m }: { m: DonorMetric }) {
  const Icon = GROUP_ICON[m.group];
  const tone = GROUP_TONE[m.group];
  const isPending = m.source === "pending_schema";

  return (
    <article
      className={cn(
        "card p-3.5 flex flex-col gap-2 rounded-xl bg-white",
        isPending && "opacity-95",
      )}
      title={m.definition}
    >
      <div className="flex items-center gap-2">
        <span
          className="grid place-items-center h-8 w-8 rounded-lg shrink-0"
          style={{ background: tone.bg, color: tone.fg }}
        >
          <Icon size={15} strokeWidth={2.2} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-extrabold uppercase tracking-[0.06em] text-[var(--color-edify-muted)] truncate">
            {METRIC_GROUP_LABELS[m.group]}
          </div>
          <div className="text-body font-extrabold leading-tight text-[var(--color-edify-text)] line-clamp-2">
            {m.label}
          </div>
        </div>
      </div>

      <div className="flex items-baseline gap-1.5 mt-0.5">
        <span className="text-[22px] font-extrabold tabular leading-none num-hero">
          {formatNumber(m.value, m.unit)}
        </span>
        {m.unit && m.unit !== "UGX" && m.value !== null && (
          <span className="text-caption font-semibold text-[var(--color-edify-muted)] truncate">
            {m.unit}
          </span>
        )}
      </div>

      {m.breakdown && (
        <div className="text-caption text-[var(--color-edify-muted)] leading-snug">
          <span className="font-bold text-[var(--color-success)]">
            {formatNumber(m.breakdown.donorReady, m.unit)}
          </span>
          <span> donor-ready</span>
          {m.breakdown.pendingEvidence > 0 && (
            <>
              <span> · </span>
              <span className="font-semibold text-amber-800">
                {formatNumber(m.breakdown.pendingEvidence, m.unit)} pending
              </span>
            </>
          )}
          {m.breakdown.excluded > 0 && (
            <>
              <span> · </span>
              <span className="font-semibold text-[#475467]">
                {m.breakdown.excluded} excluded
              </span>
            </>
          )}
        </div>
      )}

      {m.caption && (
        <div className="text-caption text-[var(--color-edify-muted)] leading-snug">{m.caption}</div>
      )}

      <div className="flex items-center gap-1.5 flex-wrap mt-auto pt-1.5">
        <StatusBadge tone={STATUS_CHIP[m.status]}>
          {METRIC_STATUS_LABELS[m.status]}
        </StatusBadge>
        <StatusBadge tone={sourceTone(m.source)}>
          {sourceLabel(m.source)}
        </StatusBadge>
      </div>
    </article>
  );
}

// ── Group block ────────────────────────────────────────────────────

function GroupBlock({
  group,
  metrics,
}: {
  group: DonorMetricGroup;
  metrics: DonorMetric[];
}) {
  if (metrics.length === 0) return null;
  const Icon = GROUP_ICON[group];
  const tone = GROUP_TONE[group];
  return (
    <section className="space-y-2.5">
      <div className="flex items-center gap-2">
        <span
          className="grid place-items-center h-6 w-6 rounded-md"
          style={{ background: tone.bg, color: tone.fg }}
        >
          <Icon size={12} strokeWidth={2.4} />
        </span>
        <h4 className="text-[12px] font-extrabold tracking-tight uppercase text-[var(--color-edify-text)]">
          {METRIC_GROUP_LABELS[group]}
        </h4>
        <span className="text-caption text-[var(--color-edify-muted)] font-semibold">
          {metrics.length} {metrics.length === 1 ? "metric" : "metrics"}
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
        {metrics.map((m) => (
          <MetricCard key={m.key} m={m} />
        ))}
      </div>
    </section>
  );
}

// ── Readiness card ─────────────────────────────────────────────────

function ReadinessCard({ snapshot }: { snapshot: DonorMetricSnapshot }) {
  const { readiness } = snapshot;
  const ringColor =
    readiness.score >= 85
      ? "var(--color-success)"
      : readiness.score >= 70
        ? "#f59e0b"
        : "var(--color-danger)";
  const summaryTone =
    readiness.score >= 85
      ? "green"
      : readiness.score >= 70
        ? "amber"
        : "red";

  return (
    <section className="card p-4 rounded-2xl">
      <div className="flex flex-col lg:flex-row items-start gap-4">
        <div className="flex items-center gap-4 shrink-0">
          <ProgressRing
            pct={readiness.score}
            size={96}
            stroke={9}
            color={ringColor}
            label={`${readiness.score}%`}
            sublabel="ready"
          />
          <div className="min-w-0">
            <div className="text-[10px] font-extrabold uppercase tracking-[0.1em] text-[var(--color-edify-muted)]">
              Donor Reporting Readiness
            </div>
            <div className="text-body-lg font-extrabold tracking-tight text-[var(--color-edify-text)] mt-0.5 max-w-[420px]">
              {readiness.summary}
            </div>
            <div className="mt-1.5">
              <StatusBadge tone={summaryTone}>
                {readiness.score >= 85
                  ? "Safe to issue"
                  : readiness.score >= 70
                    ? "Close gaps first"
                    : "Hold donor letter"}
              </StatusBadge>
            </div>
          </div>
        </div>

        <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5 w-full">
          {readiness.components.map((c) => {
            const tone =
              c.pct >= 85
                ? { bar: "var(--color-success)", chip: "green" as const }
                : c.pct >= 60
                  ? { bar: "#f59e0b", chip: "amber" as const }
                  : { bar: "var(--color-danger)", chip: "red" as const };
            return (
              <div
                key={c.key}
                className="rounded-lg border border-[var(--color-edify-divider)] bg-white px-3 py-2.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[11px] font-extrabold text-[var(--color-edify-text)] truncate">
                    {c.label}
                  </div>
                  <StatusBadge tone={tone.chip}>{c.pct}%</StatusBadge>
                </div>
                <div className="h-1.5 rounded-full bg-[var(--color-edify-divider)] mt-2 overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${c.pct}%`, background: tone.bar }}
                  />
                </div>
                {c.note && (
                  <div className="text-[10px] text-[var(--color-edify-muted)] mt-1.5 leading-snug">
                    {c.note}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ── Data-quality warnings ──────────────────────────────────────────

function DataQualityPanel({ snapshot }: { snapshot: DonorMetricSnapshot }) {
  const { warnings, enrollmentCoverage } = snapshot;
  if (warnings.length === 0 && enrollmentCoverage.schoolsMissingEnrollment === 0) {
    return null;
  }
  return (
    <section className="card p-4 rounded-2xl">
      <div className="flex items-center gap-2 mb-3">
        <span className="grid place-items-center h-7 w-7 rounded-md bg-amber-100 text-[#b45309]">
          <AlertTriangle size={14} strokeWidth={2.4} />
        </span>
        <div>
          <h3 className="text-[13px] font-extrabold tracking-tight">Data Quality &amp; Caveats</h3>
          <p className="text-[11px] muted">
            Surface every number's provenance and gap before the donor letter goes out.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2.5">
        {warnings.map((w, i) => {
          const tone =
            w.severity === "blocker"
              ? { ring: "ring-[#fda4af]", bg: "bg-[#fff1f2]", chipTone: "red" as const, label: "Blocker" }
              : w.severity === "warning"
                ? { ring: "ring-[#fde68a]", bg: "bg-[#fffbeb]", chipTone: "amber" as const, label: "Warning" }
                : { ring: "ring-[#cbd5e1]", bg: "bg-[#f8fafc]", chipTone: "blue" as const, label: "Note" };
          return (
            <article
              key={i}
              className={cn("rounded-lg ring-1 p-3", tone.ring, tone.bg)}
            >
              <div className="flex items-center gap-2 mb-1">
                <StatusBadge tone={tone.chipTone}>{tone.label}</StatusBadge>
                <h4 className="text-[12px] font-extrabold tracking-tight">{w.title}</h4>
              </div>
              <p className="text-[11px] text-[var(--color-edify-text)] leading-snug">{w.detail}</p>
              {w.affectedMetricKeys.length > 0 && (
                <div className="flex items-center gap-1 flex-wrap mt-2">
                  <span className="text-[10px] font-semibold uppercase tracking-[0.08em] muted">
                    Affects
                  </span>
                  {w.affectedMetricKeys.map((k) => (
                    <span
                      key={k}
                      className="text-[10px] font-semibold rounded bg-white ring-1 ring-[var(--color-edify-divider)] px-1.5 py-0.5 text-[var(--color-edify-text)]"
                    >
                      {k}
                    </span>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

// ── Enrollment coverage callout ────────────────────────────────────

function EnrollmentCoverageCard({ snapshot }: { snapshot: DonorMetricSnapshot }) {
  const c = snapshot.enrollmentCoverage;
  const pct = c.schoolsReached
    ? Math.round((c.schoolsWithEnrollment / c.schoolsReached) * 100)
    : 0;
  return (
    <section className="card p-4 rounded-2xl flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="grid place-items-center h-7 w-7 rounded-md bg-[#e6f5ee] text-[var(--color-success)]">
          <Building2 size={14} strokeWidth={2.4} />
        </span>
        <div>
          <h3 className="text-[13px] font-extrabold tracking-tight">Student Impact Coverage</h3>
          <p className="text-[11px] muted">
            Students Impacted is computed from school enrollment, deduplicated per school per reporting period.
          </p>
        </div>
      </div>
      <MetricStrip
        bare
        columns="grid-cols-3"
        metrics={[
          { key: "schoolsReached", label: "Schools reached", value: c.schoolsReached.toLocaleString() },
          { key: "enrollmentOnFile", label: "Enrollment on file", value: c.schoolsWithEnrollment.toLocaleString() },
          {
            key: "missingEnrollment",
            label: "Missing enrollment",
            value: c.schoolsMissingEnrollment.toLocaleString(),
            tone: c.schoolsMissingEnrollment > 0 ? "alert" : "good",
          },
        ]}
      />
      <div>
        <div className="h-1.5 rounded-full bg-[var(--color-edify-divider)] overflow-hidden">
          <div
            className="h-full rounded-full bg-[var(--color-success)]"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="text-[11px] muted mt-1.5 leading-snug">{c.note}</div>
      </div>
    </section>
  );
}

// ── Intervention + District tables ─────────────────────────────────

function InterventionsTable({ snapshot }: { snapshot: DonorMetricSnapshot }) {
  return (
    <section className="card p-4 rounded-2xl">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div>
          <h3 className="text-[13px] font-extrabold tracking-tight">By Intervention</h3>
          <p className="text-[11px] muted">
            Trainings, reach, and cost across the eight intervention areas.
          </p>
        </div>
        <button
          type="button"
          onClick={() => downloadCsv("interventions")}
          className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg bg-white ring-1 ring-[var(--color-edify-border)] hover:ring-slate-300 text-[11px] font-semibold text-slate-700 transition-all"
        >
          <Download size={11} />
          Export Intervention Breakdown
        </button>
      </div>
      <div className="overflow-x-auto -mx-1 px-1">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="text-left border-b border-[var(--color-edify-divider)] text-[var(--color-edify-muted)]">
              <th className="py-2 font-extrabold uppercase tracking-[0.06em]">Intervention</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Trainings</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Schools</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Teachers</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Students</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Cost</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.interventions.map((row) => (
              <tr
                key={row.area}
                className="border-b border-[var(--color-edify-divider)] last:border-0"
              >
                <td className="py-2.5 font-extrabold text-[var(--color-edify-text)]">{row.area}</td>
                <td className="py-2.5 text-right tabular">{row.trainings.toLocaleString()}</td>
                <td className="py-2.5 text-right tabular">{row.schoolsReached.toLocaleString()}</td>
                <td className="py-2.5 text-right tabular text-[var(--color-edify-muted)]">
                  {row.teachersTrained === 0 ? "—" : row.teachersTrained.toLocaleString()}
                </td>
                <td className="py-2.5 text-right tabular text-[var(--color-edify-muted)]">
                  {row.studentsImpacted === null
                    ? "—"
                    : row.studentsImpacted.toLocaleString()}
                </td>
                <td className="py-2.5 text-right tabular">
                  {row.costUgx === null ? "—" : formatNumber(row.costUgx, "UGX")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DistrictsTable({ snapshot }: { snapshot: DonorMetricSnapshot }) {
  if (snapshot.districts.length === 0) return null;
  return (
    <section className="card p-4 rounded-2xl">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div>
          <h3 className="text-[13px] font-extrabold tracking-tight">District Coverage</h3>
          <p className="text-[11px] muted">
            Schools, trainings, visits, and cost grouped by district. Deduplicated by districtId.
          </p>
        </div>
        <button
          type="button"
          onClick={() => downloadCsv("districts")}
          className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg bg-white ring-1 ring-[var(--color-edify-border)] hover:ring-slate-300 text-[11px] font-semibold text-slate-700 transition-all"
        >
          <Download size={11} />
          Export District Breakdown
        </button>
      </div>
      <div className="overflow-x-auto -mx-1 px-1">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="text-left border-b border-[var(--color-edify-divider)] text-[var(--color-edify-muted)]">
              <th className="py-2 font-extrabold uppercase tracking-[0.06em]">District</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Schools</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Teachers</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Leaders</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Students</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Trainings</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Visits</th>
              <th className="py-2 font-extrabold uppercase tracking-[0.06em] text-right">Cost</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.districts.map((row) => (
              <tr
                key={row.district}
                className="border-b border-[var(--color-edify-divider)] last:border-0"
              >
                <td className="py-2.5 font-extrabold text-[var(--color-edify-text)]">{row.district}</td>
                <td className="py-2.5 text-right tabular">{row.schoolsReached.toLocaleString()}</td>
                <td className="py-2.5 text-right tabular text-[var(--color-edify-muted)]">
                  {row.teachersTrained === 0 ? "—" : row.teachersTrained.toLocaleString()}
                </td>
                <td className="py-2.5 text-right tabular text-[var(--color-edify-muted)]">
                  {row.schoolLeadersTrained === 0 ? "—" : row.schoolLeadersTrained.toLocaleString()}
                </td>
                <td className="py-2.5 text-right tabular text-[var(--color-edify-muted)]">
                  {row.studentsImpacted === null
                    ? "—"
                    : row.studentsImpacted.toLocaleString()}
                </td>
                <td className="py-2.5 text-right tabular">{row.trainings.toLocaleString()}</td>
                <td className="py-2.5 text-right tabular">{row.visits.toLocaleString()}</td>
                <td className="py-2.5 text-right tabular">
                  {row.costUgx === null ? "—" : formatNumber(row.costUgx, "UGX")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ── Filter strip & export bar ──────────────────────────────────────

function FilterStrip({ snapshot }: { snapshot: DonorMetricSnapshot }) {
  const f = snapshot.filters;
  const chips: { label: string; value: string }[] = [
    { label: "Cycle", value: f.operationalCycleLabel },
    { label: "Period", value: `${f.dateRangeStart} → ${f.dateRangeEnd}` },
    { label: "School type", value: titleCase(f.schoolType ?? "all") },
    { label: "Delivered by", value: titleCase(f.deliveredBy ?? "all") },
    ...(f.district ? [{ label: "District", value: f.district }] : []),
    ...(f.cluster ? [{ label: "Cluster", value: f.cluster }] : []),
    ...(f.interventionArea
      ? [{ label: "Intervention", value: f.interventionArea }]
      : []),
  ];
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {chips.map((c) => (
        <span
          key={c.label}
          className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-lg bg-white ring-1 ring-[var(--color-edify-border)] text-[11px] font-semibold text-slate-700"
        >
          <span className="text-[var(--color-edify-muted)] font-bold uppercase tracking-[0.06em] text-[9.5px]">
            {c.label}
          </span>
          <span>{c.value}</span>
          <ChevronDown size={11} className="text-slate-400" />
        </span>
      ))}
    </div>
  );
}

function titleCase(s: string): string {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1).replaceAll("_", " ");
}

// ── Main component ────────────────────────────────────────────────

const GROUP_ORDER: DonorMetricGroup[] = [
  "reach",
  "training",
  "geography",
  "evidence",
  "impact",
  "cost",
];

export interface DonorReportingImpactProps {
  snapshot: DonorMetricSnapshot;
  /**
   * When true, hides the geography / districts tables (used by CCEO
   * surface where the role only ever covers a single district).
   */
  hideDistricts?: boolean;
  /** Optional override for the surface heading. */
  heading?: string;
  /** Optional dense mode — slightly tighter grid for narrow surfaces. */
  dense?: boolean;
}

export function DonorReportingImpact({
  snapshot,
  hideDistricts,
  heading,
  dense,
}: DonorReportingImpactProps) {
  void dense; // reserved for future layout variant
  const metricsByGroup = useMemo(() => {
    const map: Record<DonorMetricGroup, DonorMetric[]> = {
      reach: [], training: [], geography: [], evidence: [], cost: [], impact: [],
    };
    for (const m of snapshot.metrics) map[m.group].push(m);
    return map;
  }, [snapshot.metrics]);

  const [showDefinitions, setShowDefinitions] = useState(false);

  return (
    <section
      aria-label="Donor Reporting Impact"
      className="rounded-2xl ring-1 ring-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 p-4 lg:p-5 space-y-4"
    >
      {/* Header */}
      <header className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="inline-flex items-center gap-1.5 h-6 px-2 rounded-md bg-[var(--color-edify-primary)] text-white text-[10px] font-extrabold uppercase tracking-[0.12em]">
              <BadgeCheck size={12} strokeWidth={2.6} />
              Donor Reporting Impact
            </span>
            <span className="text-caption font-extrabold uppercase tracking-[0.1em] text-[var(--color-edify-muted)]">
              {scopeLabel(snapshot)}
            </span>
          </div>
          <h2 className="text-[18px] lg:text-[20px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
            {heading ?? "Evidence-backed reach, training, geography & school improvement"}
          </h2>
          <p className="text-[12px] text-[var(--color-edify-muted)] mt-0.5 max-w-[680px]">
            Every number below is deduplicated, role-scoped, and carries its data source.
            Donor-ready figures count only verified or confirmed records; pending evidence is
            shown separately and never folded into headline totals.
          </p>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap shrink-0">
          <button
            type="button"
            onClick={() => setShowDefinitions((v) => !v)}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-xl bg-white ring-1 ring-[var(--color-edify-border)] hover:ring-slate-300 text-[12px] font-semibold text-slate-700 shadow-sm transition-all"
          >
            <HelpCircle size={12} className="text-slate-400" />
            {showDefinitions ? "Hide definitions" : "Show definitions"}
          </button>
          <ExportMenu />
          <a
            href="/donor-reporting/print"
            target="_blank"
            rel="noopener"
            className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-[12px] font-extrabold shadow-[0_10px_28px_-12px_rgba(15,23,32,0.55)] transition-colors"
          >
            <FileText size={12} strokeWidth={2.4} />
            Donor Summary PDF
          </a>
        </div>
      </header>

      <FilterStrip snapshot={snapshot} />

      <ReadinessCard snapshot={snapshot} />

      {GROUP_ORDER.map((g) => {
        if (hideDistricts && g === "geography") {
          // CCEO surface — drop multi-district geography group entirely
          // because the role covers a single district. Cluster card moves
          // into reach for that variant.
          return null;
        }
        return (
          <GroupBlock key={g} group={g} metrics={metricsByGroup[g] ?? []} />
        );
      })}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <EnrollmentCoverageCard snapshot={snapshot} />
        <DataQualityPanel snapshot={snapshot} />
      </div>

      <InterventionsTable snapshot={snapshot} />

      {!hideDistricts && <DistrictsTable snapshot={snapshot} />}

      {showDefinitions && <DefinitionsList snapshot={snapshot} />}

      <footer className="flex items-center justify-between gap-2 flex-wrap text-caption text-[var(--color-edify-muted)] pt-1">
        <div className="inline-flex items-center gap-1.5">
          <Info size={11} />
          Generated {new Date(snapshot.generatedAt).toLocaleString()} by {snapshot.generatedBy}.
          Filters: {snapshot.filters.operationalCycleLabel} · {snapshot.filters.dateRangeStart} → {snapshot.filters.dateRangeEnd}.
        </div>
        <div className="font-semibold">
          {snapshot.metrics.filter((m) => m.source === "derived").length} live ·{" "}
          {snapshot.metrics.filter((m) => m.source === "estimated").length} estimated ·{" "}
          {snapshot.metrics.filter((m) => m.source === "pending_schema").length} pending schema
        </div>
      </footer>
    </section>
  );
}

function DefinitionsList({ snapshot }: { snapshot: DonorMetricSnapshot }) {
  return (
    <section className="card p-4 rounded-2xl">
      <h3 className="text-[13px] font-extrabold tracking-tight mb-2">Metric Definitions</h3>
      <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2.5">
        {snapshot.metrics.map((m) => (
          <div key={m.key} className="text-[11.5px] leading-snug">
            <dt className="font-extrabold text-[var(--color-edify-text)]">{m.label}</dt>
            <dd className="text-[var(--color-edify-muted)] mt-0.5">{m.definition}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function scopeLabel(snapshot: DonorMetricSnapshot): string {
  switch (snapshot.roleScope) {
    case "CCEO":             return `CCEO · ${snapshot.scopeLabel}`;
    case "ProgramLead":      return `Program Lead · ${snapshot.scopeLabel}`;
    case "ImpactAssessment": return `Impact Assessment · ${snapshot.scopeLabel}`;
    case "CountryDirector":  return `Country Director · ${snapshot.scopeLabel}`;
    case "RVP":              return `RVP · ${snapshot.scopeLabel}`;
  }
}

// Trigger a CSV download by navigating to the route handler URL. The
// handler responds with Content-Disposition: attachment, so the browser
// streams the file straight to disk without leaving the analytics page.
// Wrapping in a function (rather than using <a href>) sidesteps the
// Next lint rule that pushes every <a> through `next/link`.
function downloadCsv(kind: string) {
  if (typeof window !== "undefined") {
    window.location.href = `/api/donor-reporting/export/${kind}`;
  }
}

// ── ExportMenu ─────────────────────────────────────────────────────
//
// Single dropdown that consolidates the seven CSV exports. Each item
// is a real <a> link to /api/donor-reporting/export/[kind]; the route
// handler computes the snapshot for the calling user and streams the
// CSV. Excel users open the .csv straight into Excel — no extra
// dependency, no in-browser sheet generation.

const EXPORTS: { kind: string; label: string; sub: string }[] = [
  { kind: "donor-summary",    label: "Donor Summary",                sub: "Full KPI table with status + source" },
  { kind: "districts",        label: "District Breakdown",           sub: "Schools, teachers, leaders, cost by district" },
  { kind: "interventions",    label: "Intervention Breakdown",       sub: "Reach + improvement across the 8 areas" },
  { kind: "schools-reached",  label: "Schools Reached",              sub: "District-rolled schools-reached list" },
  { kind: "evidence-pending", label: "Evidence Pending",             sub: "Every gap blocking the donor letter" },
  { kind: "teacher-training", label: "Teacher Training Attendance",  sub: "Teachers / leaders by intervention + district" },
  { kind: "student-impact",   label: "Student Impact Summary",       sub: "Enrollment-driven student counts + caveats" },
];

function ExportMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Click-outside + Escape close. Keeps the menu predictable inside the
  // analytics surface, which already hosts several other popovers.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 h-9 px-3 rounded-xl bg-white ring-1 ring-[var(--color-edify-border)] hover:ring-slate-300 text-[12px] font-semibold text-slate-700 shadow-sm transition-all"
      >
        <FileSpreadsheet size={12} className="text-slate-400" />
        Excel / CSV
        <ChevronDown size={11} className="text-slate-400" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-1.5 w-[300px] rounded-xl bg-white ring-1 ring-[var(--color-edify-border)] shadow-[0_18px_48px_-18px_rgba(15,23,32,0.32)] p-1.5"
        >
          {EXPORTS.map((e) => (
            <button
              key={e.kind}
              type="button"
              role="menuitem"
              className="flex items-start gap-2 px-2.5 py-2 rounded-lg hover:bg-[var(--color-edify-soft)] transition-colors w-full text-left"
              onClick={() => {
                setOpen(false);
                downloadCsv(e.kind);
              }}
            >
              <Download size={12} className="text-slate-400 mt-0.5 shrink-0" />
              <div className="min-w-0">
                <div className="text-[12px] font-extrabold text-[var(--color-edify-text)] leading-tight">
                  {e.label}
                </div>
                <div className="text-[10.5px] text-[var(--color-edify-muted)] leading-tight mt-0.5">
                  {e.sub}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
