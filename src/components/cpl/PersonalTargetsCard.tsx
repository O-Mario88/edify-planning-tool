"use client";

import {
  Target,
  Users,
  ClipboardList,
  UserCheck,
  Wallet,
  ChevronDown,
  ArrowUpRight,
  TrendingUp,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { ProgressRing, SectionCard } from "@/components/ui/primitives";
import {
  personalTargets,
  personalOverall,
  type PersonalTarget,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<PersonalTarget["icon"], LucideIcon> = {
  users:         Users,
  clipboardList: ClipboardList,
  userCheck:     UserCheck,
  wallet:        Wallet,
};

export function PersonalTargetsCard() {
  // Pace verdict — compares current pct against where you'd need to be
  // to land at 100% by month-end, assuming a mid-late-month look-in.
  // Demo uses a fixed 60% elapsed; production swaps for new Date().
  const monthElapsedPct = 60;
  const aheadOfPace = personalOverall.pct - monthElapsedPct;

  // Per-target pace verdicts feed the tile sub-line.
  const targetsWithPace = personalTargets.map((t) => ({
    ...t,
    aheadPp: t.pct - monthElapsedPct,
    forecast: Math.min(t.total, Math.round((t.current / Math.max(monthElapsedPct, 1)) * 100)),
  }));

  // The one-line story for the card. Picks the strongest framing
  // available: "ahead of pace by N pp" beats "on track" beats
  // "behind by N pp — pull forward visits this week".
  const headline =
    aheadOfPace >= 5
      ? `Ahead of pace by ${aheadOfPace} pp — you'll close around ${forecastTotal(targetsWithPace)} of ${totalSum(targetsWithPace)} this month.`
      : aheadOfPace >= -3
        ? `On pace to hit ${personalOverall.pct}% by month-end.`
        : `Behind pace by ${Math.abs(aheadOfPace)} pp — pull forward this week to recover.`;

  const aheadCount = targetsWithPace.filter((t) => t.aheadPp >= 0).length;
  const behindCount = targetsWithPace.length - aheadCount;

  return (
    <SectionCard
      icon={<Target size={13} />}
      title="My Personal Targets"
      subtitle={headline}
      actions={
        <button
          type="button"
          className="h-8 px-2.5 rounded-md border border-[var(--color-edify-border)] bg-white flex items-center gap-1.5 text-[var(--text-body)] font-semibold"
        >
          This Month
          <ChevronDown size={11} className="text-[var(--color-edify-muted)]" />
        </button>
      }
    >
      {/* Hero strip — the overall achievement read at full width.
          Layout fans out as space allows so the "Overall Personal
          Target Achievement" label never wraps to 3 lines on tablet:
            • base (phone): ring on top, text below, mini stats below
            • md+: ring left, [text + mini stats] right wrapping
            • lg+: ring left, text middle, mini stats right (3-col) */}
      <div className="card-elevated relative overflow-hidden p-4 mb-4 grid grid-cols-1 md:grid-cols-[auto_1fr] lg:grid-cols-[auto_1fr_auto] gap-4 items-center bg-gradient-to-br from-white via-emerald-50/30 to-white">
        {/* Soft emerald glow behind the ring — adds depth without
            competing with the page's other gradients. */}
        <div
          aria-hidden
          className="pointer-events-none absolute -left-12 -top-12 w-40 h-40 rounded-full"
          style={{
            background: "radial-gradient(closest-side, rgba(16,185,129,0.18) 0%, rgba(16,185,129,0) 70%)",
          }}
        />
        <ProgressRing
          pct={personalOverall.pct}
          size={84}
          stroke={8}
          color="var(--color-success)"
          label={`${personalOverall.pct}%`}
          sublabel="Overall"
        />
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500 whitespace-nowrap">
            Personal Target Achievement
          </div>
          <div className="text-[16px] font-extrabold leading-tight mt-0.5 flex flex-wrap items-baseline gap-x-2">
            <span>{personalOverall.pct}% complete</span>
            <span className="text-caption muted font-semibold">· {monthElapsedPct}% of month elapsed</span>
          </div>
          <div className="h-1.5 rounded-full bg-[#eef2f4] overflow-hidden mt-2">
            <div
              className="h-full rounded-full bg-[var(--color-success)]"
              style={{ width: `${personalOverall.pct}%` }}
            />
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px]">
            <span className="inline-flex items-center gap-0.5 font-semibold text-[var(--color-success)]">
              <ArrowUpRight size={11} />
              {personalOverall.trend}
            </span>
            <PaceChip aheadPp={aheadOfPace} />
          </div>
        </div>
        {/* Mini-stats — span full width below the text on md, then
            move to their own column at lg. */}
        <div className="grid grid-cols-2 lg:grid-cols-1 gap-2 lg:min-w-[140px] md:col-span-2 lg:col-span-1">
          <MiniStat
            label="On pace"
            value={aheadCount}
            total={targetsWithPace.length}
            tone="good"
          />
          <MiniStat
            label="Behind"
            value={behindCount}
            total={targetsWithPace.length}
            tone={behindCount > 0 ? "warn" : "muted"}
          />
        </div>
      </div>

      {/* Target tiles — full-width fans into 4 columns on desktop, 2
          on tablet, 1 on phone. Each tile collapses identity (icon +
          label), value (current of total), trend, and progress ring
          into one glance. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
        {targetsWithPace.map((t, i) => {
          const Icon = iconMap[t.icon];
          const onPace = t.aheadPp >= 0;
          const staggerCls = ["stagger-1", "stagger-2", "stagger-3", "stagger-4"][i] ?? "";
          return (
            <div
              key={t.key}
              className={cn(
                "card-elevated card-lift cursor-default tile-in p-2.5 flex flex-col gap-1.5 min-w-0",
                staggerCls,
                !onPace && "!border-amber-200 !bg-gradient-to-br !from-amber-50/40 !to-white",
              )}
            >
              {/* Top row — label on the left, donut on the right.
                  Label uses the same 10px uppercase scale as the
                  main KPI tiles above, so the two tile rows feel
                  like one family. Donut stays at 52px so the
                  percentage inside reads clean. */}
              <div className="flex items-center justify-between gap-2 min-w-0">
                <div className="flex items-center gap-1 text-[10px] muted font-bold leading-tight uppercase tracking-wide min-w-0 flex-1">
                  <Icon size={11} className="shrink-0" />
                  <span className="truncate">{t.label}</span>
                </div>
                <ProgressRing
                  pct={t.pct}
                  size={52}
                  stroke={5}
                  color={onPace ? "var(--color-success)" : "#f59e0b"}
                  label={`${t.pct}%`}
                />
              </div>

              {/* Value on its own row — full card width so `42 / 60`
                  never wraps. Size matched to the 8 KPI tiles above. */}
              <div className="flex items-baseline gap-1 leading-none">
                <span className={cn(
                  "text-[18px] font-extrabold tabular text-slate-900 num-hero",
                  onPace ? "glow-emerald" : "glow-amber",
                )}>
                  {t.current}
                </span>
                <span className="text-caption muted font-semibold">/ {t.total}</span>
              </div>

              {/* Trend + pace — both truncate so neither pushes
                  the other off the card on narrow tiles. */}
              <div className="flex items-center justify-between gap-1 text-[9.5px] mt-auto">
                <span className="inline-flex items-center gap-0.5 font-semibold text-[var(--color-success)] shrink-0">
                  <ArrowUpRight size={9} />
                  {t.delta}
                </span>
                <span
                  className={cn(
                    "inline-flex items-center gap-0.5 font-bold tabular truncate min-w-0",
                    onPace ? "text-emerald-700" : "text-amber-700",
                  )}
                  title={onPace ? "On pace for the month" : "Behind pace — pull this work forward"}
                >
                  {onPace ? (
                    <>
                      <TrendingUp size={9} className="shrink-0" />
                      <span className="truncate">Pace {t.forecast}/{t.total}</span>
                    </>
                  ) : (
                    <>
                      <Sparkles size={9} className="shrink-0" />
                      <span className="truncate">Push +{Math.abs(t.aheadPp)} pp</span>
                    </>
                  )}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}

// ───────────── Helpers ─────────────

function totalSum(rows: { total: number }[]): number {
  return rows.reduce((a, r) => a + r.total, 0);
}

function forecastTotal(rows: { forecast: number }[]): number {
  return rows.reduce((a, r) => a + r.forecast, 0);
}

// ───────────── PaceChip ─────────────

function PaceChip({ aheadPp }: { aheadPp: number }) {
  if (aheadPp >= 5) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-[11px] font-bold bg-emerald-100 text-emerald-700">
        <TrendingUp size={11} />
        Ahead by {aheadPp} pp
      </span>
    );
  }
  if (aheadPp >= -3) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-[11px] font-bold bg-sky-100 text-sky-700">
        On pace
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-[11px] font-bold bg-amber-100 text-amber-700">
      Behind by {Math.abs(aheadPp)} pp
    </span>
  );
}

// ───────────── MiniStat ─────────────

function MiniStat({
  label,
  value,
  total,
  tone,
}: {
  label: string;
  value: number;
  total: number;
  tone: "good" | "warn" | "muted";
}) {
  const cls =
    tone === "good"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : tone === "warn"
        ? "border-amber-200 bg-amber-50 text-amber-800"
        : "border-slate-200 bg-slate-50 text-slate-600";
  return (
    <div className={cn("rounded-lg border px-2.5 py-1.5 flex items-center justify-between gap-2", cls)}>
      <div className="text-[9.5px] font-bold uppercase tracking-wide opacity-80">
        {label}
      </div>
      <div className="text-body-lg font-extrabold tabular leading-none">
        {value}
        <span className="text-[10px] opacity-70 font-semibold ml-0.5">/ {total}</span>
      </div>
    </div>
  );
}
