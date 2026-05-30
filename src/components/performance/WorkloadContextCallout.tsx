"use client";

// Workload Context Callout — shown on the CCEO's /my-targets page.
//
// Critical for transparency: nobody should be surprised by their
// adjusted pace. This component explains, in plain language, *why*
// their adjusted pace differs from their raw pace and which factors
// of their portfolio drove the difference.

import { Info, Briefcase, Globe, AlertTriangle, MapPin } from "lucide-react";
import type { ComplexityResult } from "@/lib/performance/fwi-types";

export function WorkloadContextCallout({
  staffName,
  rawPacePct,
  adjustedPacePct,
  complexityPercentile,
  contributions,
}: {
  staffName: string;
  rawPacePct: number;
  adjustedPacePct: number;
  /// 0..1 — staff's complexity rank inside the team.
  complexityPercentile: number;
  contributions: ComplexityResult["contributions"];
}) {
  const delta = adjustedPacePct - rawPacePct;
  const direction = delta > 0 ? "boost" : delta < 0 ? "dampen" : "none";
  const pctLabel = pctBand(complexityPercentile);

  // Top 3 contributing factors — surface only what's actually
  // moving the needle, not all 10.
  const top = topContributions(contributions, 3);

  return (
    <section className="rounded-2xl border border-[var(--color-edify-border)] bg-gradient-to-br from-white to-[var(--color-edify-soft)]/40 p-4 sm:p-5">
      <header className="flex items-start gap-3 mb-3">
        <div className="w-9 h-9 rounded-xl bg-violet-50 grid place-items-center text-violet-600 shrink-0">
          <Info size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-[15px] font-extrabold tracking-tight">Your workload context</h3>
          <p className="text-[12px] muted leading-snug mt-0.5">
            Performance is measured against your portfolio&apos;s actual load, not just the headline target.
          </p>
        </div>
      </header>

      {/* The headline sentence — the single most important payload. */}
      <p className="text-[13px] leading-relaxed text-[var(--color-edify-text)]">
        {staffName.split(" ")[0]}, your portfolio sits in the{" "}
        <span className="font-extrabold">{pctLabel}</span> of team load.
        {direction === "boost" && (
          <>
            {" "}Your raw pace of <span className="font-extrabold tabular">{rawPacePct}%</span> shows as{" "}
            <span className="font-extrabold tabular text-emerald-700">{adjustedPacePct}%</span> after the fairness adjustment —
            {" "}a <span className="font-extrabold tabular text-emerald-700">+{delta}</span> point lift because the portfolio is heavier than the team median.
          </>
        )}
        {direction === "dampen" && (
          <>
            {" "}Your raw pace of <span className="font-extrabold tabular">{rawPacePct}%</span> shows as{" "}
            <span className="font-extrabold tabular text-amber-700">{adjustedPacePct}%</span> after the fairness adjustment —
            {" "}a <span className="font-extrabold tabular text-amber-700">{delta}</span> point adjustment because the portfolio is lighter than the team median.
          </>
        )}
        {direction === "none" && (
          <>
            {" "}Your raw pace of <span className="font-extrabold tabular">{rawPacePct}%</span> is unchanged — your portfolio load is right at team median.
          </>
        )}
      </p>

      {/* Top 3 load factors */}
      <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2">
        {top.map((c) => {
          const { key, ...rest } = c;
          return <FactorTile key={key} {...rest} />;
        })}
      </div>
    </section>
  );
}

function pctBand(p: number): string {
  if (p >= 0.85) return "top quintile";
  if (p >= 0.65) return "upper third";
  if (p >= 0.35) return "middle band";
  if (p >= 0.15) return "lower third";
  return "bottom quintile";
}

const FACTOR_LABEL: Record<string, { label: string; Icon: typeof Briefcase }> = {
  schools:            { label: "Schools",              Icon: Briefcase },
  partnerSchools:     { label: "Partner schools",      Icon: Briefcase },
  districts:          { label: "Districts spanned",    Icon: Globe },
  secondaryDistricts: { label: "Secondary districts",  Icon: MapPin },
  highRisk:           { label: "High-risk schools",    Icon: AlertTriangle },
  ssaWeakness:        { label: "SSA weakness",         Icon: AlertTriangle },
  distance:           { label: "Average distance",     Icon: MapPin },
  hotelTrips:         { label: "Overnight trips",      Icon: MapPin },
  partners:           { label: "Partners coordinated", Icon: Briefcase },
  specialProjects:    { label: "Special projects",     Icon: Briefcase },
};

function topContributions(
  contributions: ComplexityResult["contributions"],
  n: number,
): Array<{ key: keyof ComplexityResult["contributions"]; value: number; label: string; Icon: typeof Briefcase }> {
  const entries = Object.entries(contributions) as Array<[keyof ComplexityResult["contributions"], number]>;
  return entries
    .filter(([, v]) => v > 0)
    .sort(([, a], [, b]) => b - a)
    .slice(0, n)
    .map(([key, value]) => ({
      key,
      value,
      label: FACTOR_LABEL[key]?.label ?? key,
      Icon: FACTOR_LABEL[key]?.Icon ?? Briefcase,
    }));
}

function FactorTile({
  label,
  value,
  Icon,
}: {
  label: string;
  value: number;
  Icon: typeof Briefcase;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] bg-white px-3 py-2.5">
      <div className="flex items-center gap-2 mb-1">
        <span className="w-6 h-6 rounded-md bg-[var(--color-edify-soft)] grid place-items-center text-[var(--color-edify-primary)]">
          <Icon size={12} />
        </span>
        <span className="text-caption font-bold uppercase tracking-wide muted">{label}</span>
      </div>
      <div className="text-[16px] font-extrabold tabular num-hero leading-none">
        +{value.toFixed(1)}
        <span className="text-caption font-semibold muted ml-1">pts</span>
      </div>
    </div>
  );
}
