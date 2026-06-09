"use client";

import {
  ChevronDown,
  Navigation,
  Clock,
  Gauge,
  Map as MapIcon,
  Play,
  Building2,
  Route as RouteIcon,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import {
  routeWeek,
  routeInsight,
  routeGroups,
  type RouteGroup,
  type RouteQualityLabel,
} from "@/lib/mobile-mock";
import { cn } from "@/lib/utils";
import { ActionButton } from "@/components/ui/ActionButton";
import { PageHeader } from "@/components/ui/PageHeader";

// Route plan — desktop / tablet layout.
//
// Three bands:
//   1. Header with title + week selector + Start All button.
//   2. Summary cards row (schools / routes / distance / travel time) +
//      a wide Route Insight card with the map sketch.
//   3. Route group cards in a responsive 2-column grid.

const RATING_TONE: Record<RouteQualityLabel, string> = {
  Excellent: "bg-emerald-50 text-emerald-700 border-emerald-200",
  Good:      "bg-blue-50 text-blue-700 border-blue-200",
  Average:   "bg-amber-50 text-amber-700 border-amber-200",
  Poor:      "bg-rose-50 text-rose-700 border-rose-200",
};

const STOP_TONE: Record<string, string> = {
  "Cluster Training":  "bg-emerald-50 text-emerald-700",
  "Cluster Meeting":   "bg-blue-50 text-blue-700",
  "School Visit":      "bg-[var(--color-edify-soft)] text-[var(--color-edify-dark)]",
  "Partner Follow-Up": "bg-amber-50 text-amber-700",
};

export function RouteDesktopView() {
  return (
    <>
      <PageHeader
        title="Route Plan"
        subtitle="Optimised travel routes derived from your selected schools, clusters, and partner visits. Each group is ranked by distance, travel time, and route quality."
        actions={
          <>
            <ActionButton
              label={
                <span className="inline-flex items-center gap-2">
                  <span>{routeWeek.label}</span>
                  <span className="muted font-medium">{routeWeek.range}</span>
                  <ChevronDown size={14} className="text-[var(--color-edify-muted)]" />
                </span>
              }
              ariaLabel={`Select week — currently ${routeWeek.label} ${routeWeek.range}`}
              className="h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-bold"
              toast={{
                tone: "info",
                title: "Week picker opened",
                body: `Currently viewing ${routeWeek.label} (${routeWeek.range}).`,
              }}
            />
            <ActionButton
              Icon={Play}
              label="Start all routes"
              ariaLabel="Start all routes for this week"
              className="h-10 px-3 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-white text-body font-bold shadow-sm shadow-emerald-500/25"
              toast={{
                tone: "success",
                title: "Week started",
                body: `${routeInsight.routes} routes activated across ${routeInsight.schools} schools.`,
              }}
            />
          </>
        }
      />

      <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6 space-y-4">
        {/* Summary row */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Summary Icon={Building2}   tone="edify"  label="Schools"        value={routeInsight.schools} />
          <Summary Icon={RouteIcon}   tone="violet" label="Routes"         value={routeInsight.routes} />
          <Summary Icon={Navigation}  tone="green"  label="Est. distance"  value={`${routeInsight.distanceKm} km`} />
          <Summary Icon={Clock}       tone="sky"    label="Travel time"    value={routeInsight.travelTime} />
        </section>

        {/* Insight + map */}
        <section className="grid grid-cols-12 gap-4 items-stretch">
          <div className="col-span-12 lg:col-span-5 card p-3.5 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
                <Sparkles size={14} className="text-[var(--color-edify-primary)]" />
                Route Insight
              </h3>
              <span className={cn(
                "inline-flex items-center px-2.5 py-[3px] rounded-md text-[11px] font-extrabold border whitespace-nowrap",
                RATING_TONE[routeInsight.rating],
              )}>
                {routeInsight.rating}
              </span>
            </div>
            <p className="text-body muted leading-snug">
              You will visit{" "}
              <span className="font-extrabold text-[var(--color-edify-text)]">{routeInsight.schools} schools</span> across{" "}
              <span className="font-extrabold text-[var(--color-edify-text)]">{routeInsight.routes} routes</span>.
            </p>
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <Fact Icon={Navigation} tone="green"  label="Est. distance" value={`${routeInsight.distanceKm} km`} />
              <Fact Icon={Clock}      tone="sky"    label="Travel time"   value={routeInsight.travelTime} />
              <Fact Icon={Gauge}      tone="violet" label="Route quality" value={routeInsight.routeQuality} />
              <Fact Icon={RouteIcon}  tone="edify"  label="Groups"        value={`${routeGroups.length}`} />
            </ul>
          </div>

          <div className="col-span-12 lg:col-span-7">
            <div className="card rounded-2xl p-3 h-full flex flex-col">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
                  <MapIcon size={14} className="text-[var(--color-edify-primary)]" />
                  Map preview
                </h3>
                <span className="text-caption muted">Stops + arterial roads (illustrative)</span>
              </div>
              <MapSketch />
            </div>
          </div>
        </section>

        {/* Route groups */}
        <section className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {routeGroups.map((g, i) => (
            <RouteGroupCard key={g.id} group={g} index={i + 1} />
          ))}
        </section>
      </div>
    </>
  );
}

// ────────── Pieces ──────────

type SummaryTone = "edify" | "green" | "amber" | "rose" | "violet" | "sky";
const SUMMARY_TONE: Record<SummaryTone, string> = {
  edify:  "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  green:  "bg-emerald-100 text-emerald-700",
  amber:  "bg-amber-100   text-amber-700",
  rose:   "bg-rose-100    text-rose-700",
  violet: "bg-violet-100  text-violet-700",
  sky:    "bg-sky-100     text-sky-700",
};

function Summary({ Icon, label, value, tone }: { Icon: LucideIcon; label: string; value: number | string; tone: SummaryTone }) {
  return (
    <div className="card rounded-2xl p-3">
      <div className="flex items-center gap-2 mb-1.5">
        <span className={cn("h-8 w-8 rounded-md grid place-items-center shrink-0", SUMMARY_TONE[tone])}>
          <Icon size={13} />
        </span>
        <span className="text-caption muted font-semibold leading-tight truncate">{label}</span>
      </div>
      <div className="text-[20px] font-extrabold tabular leading-none">{value}</div>
    </div>
  );
}

function Fact({ Icon, label, value, tone }: { Icon: LucideIcon; label: string; value: string; tone: SummaryTone }) {
  return (
    <li className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] px-3 py-2 flex items-center gap-2">
      <span className={cn("h-7 w-7 rounded-md grid place-items-center shrink-0", SUMMARY_TONE[tone])}>
        <Icon size={12} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] muted font-bold uppercase tracking-wide truncate">{label}</div>
        <div className="text-[13px] font-extrabold tabular leading-tight truncate">{value}</div>
      </div>
    </li>
  );
}

function RouteGroupCard({ group, index }: { group: RouteGroup; index: number }) {
  return (
    <section className="card rounded-2xl overflow-hidden">
      <header className="p-4 border-b border-[var(--color-edify-border)] flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-700 grid place-items-center text-body-lg font-extrabold">
          {index}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[15px] font-extrabold tracking-tight leading-tight truncate">{group.name}</div>
          <div className="text-[11.5px] muted mt-0.5">
            {group.schoolsCount} Schools · {group.distanceKm} km · {group.travelTime}
          </div>
        </div>
        <span className={cn(
          "inline-flex items-center px-2.5 py-[3px] rounded-md text-[11px] font-extrabold border whitespace-nowrap",
          RATING_TONE[group.rating],
        )}>
          {group.rating}
        </span>
      </header>

      <ul className="px-4 py-2 divide-y divide-[var(--color-edify-border)]">
        {group.stops.map((s) => (
          <li key={s.seq} className="flex items-start gap-3 py-2.5">
            <div className="flex flex-col items-center pt-0.5 shrink-0">
              <div className="w-7 h-7 rounded-full bg-emerald-500 text-white grid place-items-center text-[12px] font-extrabold">
                {s.seq}
              </div>
              {s.seq < group.stops.length && <div className="w-px h-5 bg-emerald-200 mt-1" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between gap-2 min-w-0">
                <div className="text-[13px] font-extrabold tracking-tight truncate min-w-0 flex-1">
                  {s.schoolName}
                  {s.isStart && <span className="ml-1.5 text-caption font-extrabold text-emerald-600">(Start)</span>}
                </div>
                <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-caption font-extrabold shrink-0 whitespace-nowrap", STOP_TONE[s.type])}>
                  {s.type}
                </span>
              </div>
            </div>
          </li>
        ))}
      </ul>

    </section>
  );
}

function MapSketch() {
  return (
    <div
      className="h-[120px] rounded-xl overflow-hidden relative bg-[linear-gradient(180deg,#eef4f7_0%,#dceaf1_100%)] border border-[var(--color-edify-border)] flex items-center justify-center gap-3 px-4"
      aria-label="Route map placeholder"
    >
      <span className="h-10 w-10 rounded-xl bg-white/70 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
        <MapIcon size={18} />
      </span>
      <div className="min-w-0 text-center sm:text-left">
        <div className="text-body font-extrabold tracking-tight">Route map coming soon</div>
        <div className="text-[11px] muted">See grouped stops below.</div>
      </div>
    </div>
  );
}
