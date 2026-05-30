// PartnerImpactCard — the "did partner support actually improve schools"
// answer in a single card. Plugs into the spec's most important
// distinction: don't just count activities, count school improvement.

import { TrendingUp, GraduationCap, School, BarChart3 } from "lucide-react";
import type { PartnerImpactSummary } from "@/lib/partner/partner-types";

export function PartnerImpactCard({ impact }: { impact: PartnerImpactSummary | undefined }) {
  if (!impact) {
    return (
      <section className="card p-3.5">
        <h3 className="text-[13px] font-extrabold tracking-tight">Partner impact</h3>
        <p className="text-[12px] muted mt-1">No impact data yet for this period.</p>
      </section>
    );
  }
  return (
    <section className="card p-3.5">
      <header className="flex items-center gap-2 mb-3">
        <span className="w-6 h-6 rounded-md bg-emerald-50 text-emerald-700 grid place-items-center">
          <TrendingUp size={13} />
        </span>
        <h3 className="text-[13px] font-extrabold tracking-tight">Partner impact</h3>
        <span className="ml-auto text-caption uppercase tracking-wide muted font-bold">
          {impact.periodIso}
        </span>
      </header>
      <p className="text-[12px] muted leading-snug">
        Don&apos;t just count what was delivered — count what changed in schools.
      </p>
      <div className="grid grid-cols-2 gap-2.5 mt-3">
        <Tile label="Schools supported" value={String(impact.schoolsSupported)} Icon={School}        tone="edify"  />
        <Tile label="Teachers trained"  value={String(impact.teachersTrained)}  Icon={GraduationCap} tone="edify"  />
        <Tile label="Verified activities" value={String(impact.verifiedActivities)} Icon={BarChart3} tone="green"  />
        <Tile label="SSA score Δ"        value={fmtDelta(impact.meanSsaDelta)} Icon={TrendingUp}    tone="green"  />
      </div>
      {(impact.schoolsImprovedFromCriticalToAtRisk + impact.schoolsImprovedFromAtRiskToOnTrack) > 0 ? (
        <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5">
          <p className="text-[12px] font-extrabold text-emerald-900">
            {impact.schoolsImprovedFromCriticalToAtRisk + impact.schoolsImprovedFromAtRiskToOnTrack} schools moved up a band this period.
          </p>
          <p className="text-[11px] text-emerald-800 mt-0.5">
            {impact.schoolsImprovedFromCriticalToAtRisk} Critical → At Risk · {impact.schoolsImprovedFromAtRiskToOnTrack} At Risk → On Track
          </p>
        </div>
      ) : null}
      {typeof impact.costPerImprovedSchoolUgx === "number" ? (
        <p className="text-[11.5px] muted mt-3">
          <span className="font-bold text-[var(--color-edify-text)]">UGX {(impact.costPerImprovedSchoolUgx / 1_000_000).toFixed(2)}M</span>
          {" "}per improved school this period.
        </p>
      ) : null}
    </section>
  );
}

const TONE_BG: Record<"edify" | "green" | "amber" | "rose", string> = {
  edify:  "bg-[var(--color-edify-soft)]/60",
  green:  "bg-emerald-50",
  amber:  "bg-amber-50",
  rose:   "bg-rose-50",
};
const TONE_FG: Record<"edify" | "green" | "amber" | "rose", string> = {
  edify:  "text-[var(--color-edify-primary)]",
  green:  "text-emerald-700",
  amber:  "text-amber-700",
  rose:   "text-rose-700",
};

function Tile({
  label, value, Icon, tone,
}: {
  label: string; value: string;
  Icon: typeof TrendingUp;
  tone: "edify" | "green" | "amber" | "rose";
}) {
  return (
    <div className={`rounded-xl border border-[var(--color-edify-divider)] ${TONE_BG[tone]} px-3 py-2.5`}>
      <div className={`inline-flex items-center gap-1 ${TONE_FG[tone]}`}>
        <Icon size={11} />
        <span className="text-[10px] font-bold uppercase tracking-wide">{label}</span>
      </div>
      <div className="text-[18px] font-extrabold tabular num-hero mt-1 text-[var(--color-edify-text)]">{value}</div>
    </div>
  );
}

function fmtDelta(n: number): string {
  const s = n.toFixed(1);
  return n > 0 ? `+${s}` : s;
}
