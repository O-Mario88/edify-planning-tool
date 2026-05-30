"use client";

// PartnerImpactRecordsList — every impact record (per school × per
// intervention) showing baseline → next SSA delta, impact rating,
// attribution, and recommended next step. The page-level filters
// narrow by rating; expand any row for the full audit trail.

import { useMemo, useState } from "react";
import {
  Building2, Calendar, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronUp,
  ShieldCheck, Wallet, Sparkles, AlertTriangle, type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  partnerImpactRecords,
  IMPACT_RATING_LABEL,
  ATTRIBUTION_LABEL,
  IMPACT_STATUS_LABEL,
  recommendationFor,
  formatChange,
  type PartnerImpactRecord,
  type ImpactRating,
} from "@/lib/partner/partner-impact";

type FilterKey = "all" | "improved" | "no_change" | "decline" | "awaiting";

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all",       label: "All" },
  { key: "improved",  label: "Improved" },
  { key: "no_change", label: "No change" },
  { key: "decline",   label: "Decline" },
  { key: "awaiting",  label: "Awaiting next SSA" },
];

const RATING_TONE: Record<ImpactRating, string> = {
  strong_improvement:     "bg-emerald-100 text-emerald-800",
  meaningful_improvement: "bg-emerald-50 text-emerald-700",
  small_improvement:      "bg-emerald-50 text-emerald-700",
  no_change:              "bg-slate-100 text-slate-700",
  decline:                "bg-rose-50 text-rose-700",
  significant_decline:    "bg-rose-100 text-rose-800",
};

function changeMatchesFilter(r: PartnerImpactRecord, f: FilterKey): boolean {
  if (f === "all") return true;
  if (f === "awaiting") return r.scoreChange == null;
  if (r.scoreChange == null) return false;
  if (f === "improved") return r.scoreChange > 0;
  if (f === "no_change") return r.scoreChange === 0;
  if (f === "decline") return r.scoreChange < 0;
  return true;
}

export function PartnerImpactRecordsList() {
  const [filter, setFilter] = useState<FilterKey>("all");
  const [openId, setOpenId] = useState<string | null>(null);

  const rows = useMemo(() => {
    return partnerImpactRecords.filter((r) => changeMatchesFilter(r, filter));
  }, [filter]);

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div>
          <h3 className="text-body-lg font-extrabold tracking-tight">Impact records</h3>
          <p className="text-[11.5px] muted mt-0.5">
            One row per school + intervention. Baseline SSA → next SSA delta in the same area you supported.
          </p>
        </div>
      </header>

      {/* Filter chips */}
      <div className="flex items-center gap-1 flex-wrap mb-3">
        {FILTERS.map((f) => {
          const isActive = filter === f.key;
          const count = f.key === "all"
            ? partnerImpactRecords.length
            : partnerImpactRecords.filter((r) => changeMatchesFilter(r, f.key)).length;
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                "inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-semibold transition-colors whitespace-nowrap",
                isActive
                  ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
                  : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
              )}
            >
              {f.label}
              <span className={cn(
                "inline-flex items-center justify-center min-w-[16px] h-[14px] px-1 rounded-md text-[9px] font-extrabold",
                isActive ? "bg-[var(--color-edify-primary)] text-white" : "bg-slate-100 text-slate-700",
              )}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      <ul className="divide-y divide-[var(--color-edify-divider)]">
        {rows.map((r) => (
          <ImpactRow
            key={r.id}
            record={r}
            open={openId === r.id}
            onToggle={() => setOpenId((cur) => (cur === r.id ? null : r.id))}
          />
        ))}
      </ul>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[12px] muted">
        Showing <span className="font-semibold text-[var(--color-edify-text)]">{rows.length}</span>{" "}
        of <span className="font-semibold text-[var(--color-edify-text)]">{partnerImpactRecords.length}</span> impact records
      </div>
    </section>
  );
}

function ImpactRow({
  record: r, open, onToggle,
}: {
  record: PartnerImpactRecord;
  open: boolean;
  onToggle: () => void;
}) {
  const change = r.scoreChange;
  const awaitingSsa = change == null;
  const TrendIcon: LucideIcon =
    awaitingSsa ? Sparkles : change! > 0 ? TrendingUp : change! < 0 ? TrendingDown : Minus;
  const trendCls =
    awaitingSsa ? "text-[var(--color-edify-muted)]" :
    change! > 0 ? "text-emerald-700" :
    change! < 0 ? "text-rose-700" : "muted";

  // The full-text rating chip ("MEANINGFUL IMPROVEMENT" etc.) needs
  // ~180px and was strangling the school-name + meta column at
  // tablet widths (768–1023). Hide it below lg; the delta number +
  // trend icon already convey direction. The chip is also rendered
  // inside the expanded panel so the full label is one tap away.
  const ratingChip = r.impactRating ? (
    <span className={cn("hidden lg:inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide whitespace-nowrap", RATING_TONE[r.impactRating])}>
      {IMPACT_RATING_LABEL[r.impactRating]}
    </span>
  ) : (
    <span className="hidden lg:inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide bg-blue-50 text-blue-700 whitespace-nowrap">
      Awaiting next SSA
    </span>
  );

  const rec = recommendationFor(r);
  const recTone =
    rec?.tone === "good" ? "border-emerald-200 bg-emerald-50 text-emerald-800" :
    rec?.tone === "danger" ? "border-rose-200 bg-rose-50 text-rose-800" :
    "border-amber-200 bg-amber-50 text-amber-800";

  return (
    <li>
      {/* Collapsed row */}
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
        className="w-full cursor-pointer flex items-center gap-3 px-1 py-3 hover:bg-[var(--color-edify-soft)]/30 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/30"
      >
        <span className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          <Building2 size={13} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-body font-extrabold tracking-tight truncate">{r.schoolName}</span>
            <span className="text-caption muted">·</span>
            <span className="text-caption muted">{r.district}</span>
          </div>
          <div className="text-caption muted leading-tight mt-0.5">
            {r.ssaInterventionArea} · {r.activityType} · {formatDate(r.activityDate)}
          </div>
        </div>

        {/* Score: baseline → next. Hidden below lg — at tablet widths
            it competed with the rating chip + delta and forced the
            school-name column to wrap awkwardly. The same numbers
            appear in the expanded panel for any viewport. */}
        <div className="hidden lg:flex items-center gap-2 shrink-0 text-[11.5px]">
          <span className="font-extrabold tabular text-[var(--color-edify-text)]">{r.baselineScore}/10</span>
          <span className="muted">→</span>
          {r.nextScore != null ? (
            <span className="font-extrabold tabular text-[var(--color-edify-text)]">{r.nextScore}/10</span>
          ) : (
            <span className="muted">—</span>
          )}
        </div>

        {/* Delta */}
        <span className={cn("inline-flex items-center gap-1 text-[13px] font-extrabold tabular w-[58px] justify-end shrink-0", trendCls)}>
          <TrendIcon size={11} />
          {change != null ? formatChange(change) : "—"}
        </span>

        {/* Rating chip */}
        {ratingChip}

        {/* Expand */}
        <span className="text-[var(--color-edify-muted)] shrink-0 ml-1">
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </div>

      {/* Expanded detail */}
      {open && (
        <div className="px-1 pb-4 pt-1 grid grid-cols-1 md:grid-cols-12 gap-3 bg-[var(--color-edify-soft)]/40 border-t border-[var(--color-edify-divider)]/60">
          {/* Left col — facts */}
          <div className="md:col-span-7 space-y-2 pt-3">
            <Detail Icon={Calendar} primary={<><span className="font-extrabold">Baseline SSA:</span> {r.baselineScore}/10 on {formatDate(r.baselineSsaDate)}</>} />
            <Detail
              Icon={Calendar}
              primary={
                r.nextScore != null && r.nextSsaDate ? (
                  <><span className="font-extrabold">Next SSA:</span> {r.nextScore}/10 on {formatDate(r.nextSsaDate)}</>
                ) : (
                  <><span className="font-extrabold">Next SSA:</span> Awaiting (window closes {formatDate(r.impactWindowEnd)})</>
                )
              }
              tone={awaitingSsa ? "muted" : undefined}
            />
            <Detail Icon={ShieldCheck} primary={<><span className="font-extrabold">Status:</span> {IMPACT_STATUS_LABEL[r.impactStatus]}</>} />
            {r.attributionType && (
              <Detail Icon={Sparkles} primary={<><span className="font-extrabold">Attribution:</span> {ATTRIBUTION_LABEL[r.attributionType]}</>} />
            )}
            {r.costOfSupport != null && (
              <Detail
                Icon={Wallet}
                primary={
                  <>
                    <span className="font-extrabold">Cost of support:</span> {fmtUgx(r.costOfSupport)}
                    {r.costPerImprovementPoint != null && (
                      <span className="muted"> · {fmtUgx(r.costPerImprovementPoint)} per +1 point</span>
                    )}
                  </>
                }
              />
            )}
            {r.bundleActivities && r.bundleActivities.length > 0 && (
              <div className="rounded-md bg-white border border-[var(--color-edify-divider)] px-2.5 py-2 mt-2">
                <div className="text-[10px] uppercase tracking-wider font-bold muted">Other activities in this impact window</div>
                <ul className="mt-1 text-[11.5px] space-y-0.5">
                  {r.bundleActivities.map((b, i) => (
                    <li key={i}>
                      <span className="font-extrabold">{b.kind}</span>
                      <span className="muted"> · {b.by} · {b.date}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {r.notes && (
              <p className="text-[11.5px] muted leading-snug pt-1 italic">{r.notes}</p>
            )}
          </div>

          {/* Right col — recommendation */}
          <div className="md:col-span-5 pt-3">
            {rec ? (
              <div className={cn("rounded-xl border px-3.5 py-3 flex items-start gap-2.5", recTone)}>
                <span className="shrink-0 mt-0.5">
                  {rec.tone === "good"
                    ? <Sparkles size={14} />
                    : rec.tone === "danger"
                      ? <AlertTriangle size={14} />
                      : <AlertTriangle size={14} />}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[12px] font-extrabold leading-tight">{rec.headline}</div>
                  <p className="text-[11.5px] mt-1 leading-snug">{rec.action}</p>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-[var(--color-edify-divider)] bg-white px-3.5 py-3">
                <div className="text-[12px] font-extrabold">No measurement yet</div>
                <p className="text-[11.5px] muted mt-1 leading-snug">
                  Impact window closes {formatDate(r.impactWindowEnd)}. The next SSA will be compared to baseline {r.baselineScore}/10.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

function Detail({
  Icon, primary, tone,
}: {
  Icon: LucideIcon;
  primary: React.ReactNode;
  tone?: "muted";
}) {
  return (
    <div className="flex items-start gap-2">
      <span className={cn("mt-0.5 shrink-0", tone === "muted" ? "text-[var(--color-edify-muted)]" : "text-[var(--color-edify-primary)]")}>
        <Icon size={12} />
      </span>
      <div className={cn("text-[12px] leading-snug", tone === "muted" ? "muted" : "text-[var(--color-edify-text)]")}>{primary}</div>
    </div>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtUgx(n: number): string {
  if (n >= 1_000_000) return `UGX ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `UGX ${(n / 1_000).toFixed(0)}K`;
  return `UGX ${n}`;
}
