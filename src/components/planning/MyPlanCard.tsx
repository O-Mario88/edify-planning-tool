"use client";

// My Plan — the CCEO / Program Lead operating instrument.
//
// Not a static target sheet: pick a horizon and the whole card responds —
// the plan-health ring, the smart headline, the per-activity pace bars and
// the highlighted column all re-resolve. Pacing (plan vs. verified
// delivery), forecast and the headline are computed by `planView` in
// lib/plan-cascade. Client component — it owns the horizon + drill-down
// state and the count-up motion.

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import {
  CalendarCheck,
  Printer,
  ArrowRight,
  ChevronDown,
  CornerDownRight,
  Footprints,
  Handshake,
  ClipboardCheck,
  Users,
  FileText,
  Building2,
  GraduationCap,
  type LucideIcon,
} from "lucide-react";
import {
  planView,
  monthlyPlanSnapshot,
  PLAN_PERIODS,
  type PlanPeriod,
  type PlanLineGroup,
  type PaceVerdict,
} from "@/lib/plan-cascade";
import { cn } from "@/lib/utils";

const ugx = (n: number) => `UGX ${n.toLocaleString()}`;

// ────────── motion ──────────

function useCountUp(target: number, ms = 650): number {
  const [n, setN] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    const start = from.current;
    from.current = target;
    if (start === target) {
      setN(target);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      const eased = 1 - Math.pow(1 - k, 3);
      setN(Math.round(start + (target - start) * eased));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return n;
}

function CountUp({ value, className }: { value: number; className?: string }) {
  const n = useCountUp(value);
  return <span className={className}>{n.toLocaleString()}</span>;
}

// ────────── pace styling ──────────

const VERDICT_STYLE: Record<
  PaceVerdict,
  { text: string; bar: string; chip: string; ring: string }
> = {
  Ahead: {
    text: "text-emerald-700",
    bar: "bg-emerald-500",
    chip: "bg-emerald-100 text-emerald-800 border-emerald-200",
    ring: "#34d399",
  },
  "On track": {
    text: "text-sky-700",
    bar: "bg-sky-500",
    chip: "bg-sky-100 text-sky-800 border-sky-200",
    ring: "#38bdf8",
  },
  Behind: {
    text: "text-amber-700",
    bar: "bg-amber-500",
    chip: "bg-amber-100 text-amber-800 border-amber-200",
    ring: "#fbbf24",
  },
};

const PLAN_ICON: Record<string, LucideIcon> = {
  "visits-staff": Footprints,
  "visits-partner": Handshake,
  ssa: ClipboardCheck,
  cluster: Users,
  exam: FileText,
  "core-visit-staff": Building2,
  "core-train-staff": GraduationCap,
  "core-visit-partner": Building2,
  "core-train-partner": GraduationCap,
};

const GROUP_STYLE: Record<PlanLineGroup, { dot: string; chip: string }> = {
  "Field activities": {
    dot: "bg-[var(--color-edify-primary)]",
    chip: "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  },
  "Core schools": {
    dot: "bg-amber-500",
    chip: "bg-amber-100 text-amber-700",
  },
};

// label · pace bar · Week · Month · Quarter · Mid-Year · Year
const PLAN_GRID =
  "minmax(148px,216px) minmax(120px,1.4fr) 46px 50px 54px 64px 72px";

// ────────── health ring ──────────

function Ring({ pct, color }: { pct: number; color: string }) {
  const size = 60;
  const stroke = 6;
  const r = size / 2 - stroke;
  const c = 2 * Math.PI * r;
  const off = c * (1 - Math.min(100, Math.max(0, pct)) / 100);
  return (
    <span
      className="relative grid place-items-center shrink-0"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgba(255,255,255,0.16)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={off}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset 600ms ease" }}
        />
      </svg>
      <span className="absolute text-[15px] font-extrabold tabular text-white">
        {pct}%
      </span>
    </span>
  );
}

// ────────── card ──────────

export function MyPlanCard({
  role,
  hideOpenLink = false,
}: {
  role: "cceo" | "cpl";
  /** Set on the /my-plan page itself so the card doesn't link to itself. */
  hideOpenLink?: boolean;
}) {
  const [period, setPeriod] = useState<PlanPeriod>("Month");
  const [openKey, setOpenKey] = useState<string | null>(null);
  const v = planView(period);
  const snap = monthlyPlanSnapshot();
  const title = role === "cceo" ? "My field plan" : "My Team plan";
  const groups: PlanLineGroup[] = ["Field activities", "Core schools"];
  const vs = VERDICT_STYLE[v.verdict];
  const health = useCountUp(v.healthPct);

  return (
    <section className="rounded-3xl overflow-hidden border border-[var(--color-edify-border)] bg-white shadow-[0_1px_2px_rgba(15,23,32,0.04),0_24px_50px_-32px_rgba(15,23,32,0.32)]">
      {/* ── Hero band ── */}
      <header className="relative px-5 sm:px-6 pt-5 pb-5 text-white bg-gradient-to-br from-[var(--color-edify-deep)] to-[var(--color-edify-primary)]">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.08]"
          style={{
            backgroundImage:
              "radial-gradient(440px 170px at 88% 0%, #ffffff, transparent 70%)",
          }}
        />

        {/* Row 1 — identity + actions */}
        <div className="relative flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <span className="grid place-items-center h-10 w-10 rounded-xl bg-white/[0.12] border border-white/15 shrink-0">
              <CalendarCheck size={18} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[16px] font-extrabold tracking-tight leading-tight">
                {title}
              </h3>
              <p className="text-[11px] text-white/65 mt-0.5 leading-snug max-w-[440px]">
                Plan vs. delivery across every horizon — every activity is a
                budget line and a Salesforce record.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="hidden md:inline-flex items-center gap-1.5 text-[10px] text-white/55 mr-0.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              {v.freshness}
            </span>
            <button
              type="button"
              onClick={() => window.print()}
              className="inline-flex items-center gap-1 rounded-lg bg-white/[0.10] border border-white/15 px-2.5 py-1.5 text-[11px] font-extrabold hover:bg-white/20 transition-colors"
            >
              <Printer size={11} /> Export
            </button>
            {!hideOpenLink && (
              <Link
                href="/my-plan"
                className="inline-flex items-center gap-1 rounded-lg bg-white/[0.10] border border-white/15 px-2.5 py-1.5 text-[11px] font-extrabold hover:bg-white/20 transition-colors"
              >
                Open plan <ArrowRight size={11} />
              </Link>
            )}
          </div>
        </div>

        {/* Row 2 — plan health + smart headline */}
        <div className="relative mt-3.5 flex items-center gap-3.5 rounded-2xl bg-white/[0.07] border border-white/10 p-3">
          <Ring pct={health} color={vs.ring} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-[0.13em] font-bold text-white/55">
                Plan health · {period}
              </span>
              <span
                className={cn(
                  "inline-flex items-center rounded-md border px-1.5 py-[1px] text-[9px] font-extrabold uppercase tracking-wide",
                  vs.chip,
                )}
              >
                {v.verdict}
              </span>
            </div>
            <div className="text-body font-semibold leading-snug mt-0.5">
              {v.headline}
            </div>
            <div className="text-[10px] text-white/55 mt-1">
              <CountUp value={v.totalActual} /> of{" "}
              {v.totalPlanned.toLocaleString()} delivered · {snap.schoolsCovered}{" "}
              schools · {ugx(snap.autoBudget)} budget
            </div>
          </div>
        </div>

        {/* Row 3 — horizon selector */}
        <div className="relative mt-3 grid grid-cols-3 sm:grid-cols-5 gap-2.5">
          {PLAN_PERIODS.map((p) => {
            const active = p === period;
            return (
              <button
                key={p}
                type="button"
                aria-pressed={active}
                onClick={() => setPeriod(p)}
                className={cn(
                  "rounded-xl border px-3 py-2.5 text-left transition-all",
                  active
                    ? "border-white/35 bg-white/[0.18] shadow-lg shadow-black/10"
                    : "border-white/10 bg-white/[0.05] hover:bg-white/[0.10]",
                )}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="text-[9px] uppercase tracking-[0.13em] font-bold text-white/55">
                    {p}
                  </span>
                  <span className="text-[8.5px] font-bold text-emerald-300">
                    +{v.periodDelta[p]}%
                  </span>
                </div>
                <div className="text-[21px] font-extrabold tabular leading-none mt-1.5">
                  <CountUp value={v.periodPlanned[p]} />
                </div>
                <div className="text-[8.5px] text-white/45 mt-1">
                  planned activities
                </div>
              </button>
            );
          })}
        </div>
      </header>

      {/* ── Activity matrix ── */}
      <div className="px-5 sm:px-6 py-4">
        <div className="overflow-x-auto">
          <div className="min-w-[620px]">
            {/* Column header */}
            <div
              className="grid items-end gap-2 px-2 pb-1.5 text-[9px] font-bold uppercase tracking-[0.1em] muted"
              style={{ gridTemplateColumns: PLAN_GRID }}
            >
              <span>Activity</span>
              <span className="text-[8.5px] text-[var(--color-edify-primary)]">
                {period} pace
              </span>
              {PLAN_PERIODS.map((p) => (
                <span
                  key={p}
                  className={cn(
                    "text-right transition-colors",
                    p === period && "text-[var(--color-edify-primary)]",
                  )}
                >
                  {p}
                </span>
              ))}
            </div>

            {groups.map((group) => {
              const lines = v.lines.filter((l) => l.group === group);
              const gs = GROUP_STYLE[group];
              return (
                <div key={group}>
                  <div className="flex items-center gap-2 px-2 pt-3 pb-1">
                    <span className={cn("h-2 w-2 rounded-full", gs.dot)} />
                    <span className="text-[10px] font-extrabold uppercase tracking-wide">
                      {group}
                    </span>
                    {group === "Core schools" && (
                      <span className="text-[10px] muted font-medium">
                        · 2 visits + 2 trainings per school
                      </span>
                    )}
                  </div>
                  <div className="space-y-0.5">
                    {lines.map((l) => {
                      const Icon = PLAN_ICON[l.key] ?? CalendarCheck;
                      const vl = VERDICT_STYLE[l.verdict];
                      const open = openKey === l.key;
                      return (
                        <div key={l.key}>
                          <button
                            type="button"
                            aria-expanded={open}
                            onClick={() => setOpenKey(open ? null : l.key)}
                            className={cn(
                              "w-full grid items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors",
                              open
                                ? "bg-[var(--color-edify-soft)]/55"
                                : "hover:bg-[var(--color-edify-soft)]/40",
                            )}
                            style={{ gridTemplateColumns: PLAN_GRID }}
                          >
                            {/* label */}
                            <div className="flex items-center gap-2.5 min-w-0">
                              <span
                                className={cn(
                                  "grid place-items-center h-8 w-8 rounded-lg shrink-0",
                                  gs.chip,
                                )}
                              >
                                <Icon size={15} />
                              </span>
                              <span className="text-[12px] font-semibold truncate">
                                {l.label}
                              </span>
                              <ChevronDown
                                size={12}
                                className={cn(
                                  "shrink-0 text-[var(--color-edify-muted)] transition-transform",
                                  open && "rotate-180",
                                )}
                              />
                            </div>
                            {/* pace bar */}
                            <div className="flex items-center gap-2">
                              <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                                <div
                                  className={cn(
                                    "h-full rounded-full transition-[width] duration-500",
                                    vl.bar,
                                  )}
                                  style={{
                                    width: `${Math.min(100, Math.max(4, l.pacePct))}%`,
                                  }}
                                />
                              </div>
                              <span
                                className={cn(
                                  "text-[10px] tabular shrink-0 w-[52px] text-right font-extrabold",
                                  vl.text,
                                )}
                              >
                                {l.actual}
                                <span className="muted font-medium">
                                  /{l.planned}
                                </span>
                              </span>
                            </div>
                            {/* period numbers */}
                            {PLAN_PERIODS.map((p) => (
                              <span
                                key={p}
                                className={cn(
                                  "text-right tabular transition-colors",
                                  p === period
                                    ? "text-body font-extrabold text-[var(--color-edify-primary)]"
                                    : "text-[12px] muted",
                                )}
                              >
                                {l.byPeriod[p]}
                              </span>
                            ))}
                          </button>

                          {open && (
                            <div className="animate-in fade-in slide-in-from-top-1 duration-200 mx-2 mb-1 mt-0.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 px-3 py-2.5">
                              <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                                {PLAN_PERIODS.map((p) => (
                                  <div
                                    key={p}
                                    className="rounded-md bg-white border border-[var(--color-edify-border)] px-2 py-1.5"
                                  >
                                    <div className="text-[8.5px] uppercase tracking-wide muted font-bold">
                                      {p}
                                    </div>
                                    <div className="text-[11.5px] font-extrabold tabular mt-0.5">
                                      {l.actualByPeriod[p]}
                                      <span className="muted font-medium">
                                        {" "}
                                        / {l.byPeriod[p]}
                                      </span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                              <div className="mt-2 text-caption muted flex items-center gap-1.5">
                                <CornerDownRight
                                  size={11}
                                  className="text-[var(--color-edify-primary)] shrink-0"
                                />
                                Projected year-end:{" "}
                                <span className="font-extrabold text-[var(--color-edify-text)]">
                                  {l.forecastYear}
                                </span>{" "}
                                of {l.byPeriod.Year} (
                                {Math.round(
                                  (l.forecastYear / l.byPeriod.Year) * 100,
                                )}
                                %)
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {/* Totals */}
            <div
              className="grid items-center gap-2 mt-2.5 rounded-xl bg-gradient-to-br from-[var(--color-edify-deep)] to-[var(--color-edify-primary)] text-white px-2 py-2.5"
              style={{ gridTemplateColumns: PLAN_GRID }}
            >
              <span className="text-[11px] font-extrabold uppercase tracking-wide pl-0.5">
                Total planned
              </span>
              <span className="text-[10px] text-white/65 tabular">
                {v.totalActual.toLocaleString()} /{" "}
                {v.totalPlanned.toLocaleString()} this {period.toLowerCase()}
              </span>
              {PLAN_PERIODS.map((p) => (
                <span
                  key={p}
                  className={cn(
                    "text-right tabular font-extrabold transition-all",
                    p === period
                      ? "text-[15px]"
                      : "text-[12px] text-white/75",
                  )}
                >
                  {v.periodPlanned[p].toLocaleString()}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-3 flex items-start gap-2 text-caption muted">
          <CornerDownRight
            size={12}
            className="mt-[1px] shrink-0 text-[var(--color-edify-primary)]"
          />
          <span>
            Every planned activity auto-generates the Accountant&apos;s budget
            and the Impact Assessment verification plan — no re-entry.
          </span>
        </div>
      </div>
    </section>
  );
}

// ────────── skeleton ──────────

export function MyPlanCardSkeleton() {
  return (
    <section className="rounded-3xl overflow-hidden border border-[var(--color-edify-border)] bg-white shadow-[0_1px_2px_rgba(15,23,32,0.04),0_24px_50px_-32px_rgba(15,23,32,0.32)]">
      <div className="px-5 sm:px-6 pt-5 pb-5 bg-gradient-to-br from-[var(--color-edify-deep)] to-[var(--color-edify-primary)]">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl bg-white/15 animate-pulse" />
          <div className="space-y-1.5">
            <div className="h-3.5 w-40 rounded bg-white/15 animate-pulse" />
            <div className="h-2.5 w-64 rounded bg-white/10 animate-pulse" />
          </div>
        </div>
        <div className="mt-3.5 h-[78px] rounded-2xl bg-white/[0.07] animate-pulse" />
        <div className="mt-3 grid grid-cols-3 sm:grid-cols-5 gap-2.5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-[74px] rounded-xl bg-white/[0.06] animate-pulse"
            />
          ))}
        </div>
      </div>
      <div className="px-5 sm:px-6 py-4 space-y-2">
        {Array.from({ length: 9 }).map((_, i) => (
          <div
            key={i}
            className="h-9 rounded-lg bg-[var(--color-edify-soft)]/50 animate-pulse"
          />
        ))}
      </div>
    </section>
  );
}
