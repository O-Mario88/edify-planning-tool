"use client";

import {
  ChevronDown,
  Navigation,
  Clock,
  Gauge,
  Map as MapIcon,
  Play,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import {
  routeWeek,
  routeInsight,
  routeGroups,
  type RouteGroup,
  type RouteQualityLabel,
} from "@/lib/mobile-mock";
import { cn } from "@/lib/utils";

const RATING_TONE: Record<RouteQualityLabel, string> = {
  Excellent: "bg-emerald-50 text-emerald-700 border-emerald-200",
  Good:      "bg-blue-50 text-blue-700 border-blue-200",
  Average:   "bg-amber-50 text-amber-700 border-amber-200",
  Poor:      "bg-rose-50 text-rose-700 border-rose-200",
};

const STOP_TONE: Record<string, string> = {
  "Cluster Training":   "bg-emerald-50 text-emerald-700",
  "Cluster Meeting":    "bg-blue-50 text-blue-700",
  "School Visit":       "bg-[var(--color-edify-soft)] text-[var(--color-edify-dark)]",
  "Partner Follow-Up":  "bg-amber-50 text-amber-700",
};

export function RouteView() {
  return (
    <MobileShell>
      <MobileTopBar backHref="/dashboard" />

      <main className="flex-1 px-3 py-3 space-y-3">
        {/* Week selector */}
        <button
          type="button"
          className="w-full h-10 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center justify-center gap-2 text-[13px] font-bold"
        >
          {routeWeek.label} <span className="muted font-medium text-[12px]">{routeWeek.range}</span>
          <ChevronDown size={14} className="text-[var(--color-edify-muted)]" />
        </button>

        {/* Route Insight */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-3">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-body-lg font-extrabold tracking-tight">Route Insight</h3>
            <span className={cn("inline-flex items-center px-2.5 py-[3px] rounded-md text-[11px] font-extrabold border", RATING_TONE[routeInsight.rating])}>
              {routeInsight.rating}
            </span>
          </div>
          <p className="text-[12px] muted leading-snug">
            You will visit{" "}
            <span className="font-bold text-[var(--color-edify-text)]">{routeInsight.schools} schools</span> across{" "}
            <span className="font-bold text-[var(--color-edify-text)]">{routeInsight.routes} routes</span>.
          </p>

          <div className="grid grid-cols-3 gap-2 mt-3">
            <Stat icon={<Navigation size={14} className="text-emerald-600" />} value={`${routeInsight.distanceKm} km`} label="Est. Distance" />
            <Stat icon={<Clock size={14} className="text-blue-600" />} value={routeInsight.travelTime} label="Est. Travel Time" />
            <Stat icon={<Gauge size={14} className="text-violet-600" />} value={routeInsight.routeQuality} label="Route Quality" />
          </div>

          {/* Decorative map silhouette */}
          <MapSketch />
        </section>

        {/* Route groups */}
        {routeGroups.map((g) => (
          <RouteGroupCard key={g.id} group={g} />
        ))}
      </main>

      <MobileBottomNav />
    </MobileShell>
  );
}

function Stat({ icon, value, label }: { icon: React.ReactNode; value: string; label: string }) {
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] p-2.5 bg-white">
      <div className="flex items-center gap-1.5">{icon}<span className="text-body-lg font-extrabold tabular leading-none">{value}</span></div>
      <div className="text-caption muted font-semibold mt-1.5">{label}</div>
    </div>
  );
}

function RouteGroupCard({ group }: { group: RouteGroup }) {
  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm">
      <div className="p-3 border-b border-[#eef2f4] flex items-center gap-3">
        <div className="w-8 h-8 rounded-md bg-emerald-50 text-emerald-700 grid place-items-center text-[12px] font-extrabold">
          {group.id === "r-1" ? 1 : 2}
        </div>
        <div className="flex-1">
          <div className="text-body-lg font-extrabold tracking-tight leading-tight">{group.name}</div>
          <div className="text-[11px] muted mt-0.5">
            {group.schoolsCount} Schools · {group.distanceKm} km · {group.travelTime}
          </div>
        </div>
        <span className={cn("inline-flex items-center px-2 py-[3px] rounded-md text-[11px] font-extrabold border", RATING_TONE[group.rating])}>
          {group.rating}
        </span>
      </div>

      <div className="px-3 py-2 divide-y divide-[var(--color-edify-divider)]">
        {group.stops.map((s) => (
          <div key={s.seq} className="flex items-start gap-3 py-2">
            <div className="flex flex-col items-center pt-0.5">
              <div className="w-6 h-6 rounded-full bg-emerald-500 text-white grid place-items-center text-[11px] font-extrabold">
                {s.seq}
              </div>
              {s.seq < group.stops.length && <div className="w-px h-4 bg-emerald-200 mt-1" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-bold leading-tight">
                {s.schoolName}
                {s.isStart && <span className="ml-1.5 text-caption font-extrabold text-emerald-600">(Start)</span>}
              </div>
              <span className={cn("inline-flex mt-1 px-2 py-[2px] rounded-md text-caption font-extrabold", STOP_TONE[s.type])}>
                {s.type}
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2 p-3 border-t border-[#eef2f4]">
        <button
          type="button"
          className="h-10 rounded-lg border border-[var(--color-edify-border)] bg-white inline-flex items-center justify-center gap-1.5 text-body font-bold"
        >
          <MapIcon size={14} />
          Open in Maps
        </button>
        <button
          type="button"
          className="h-10 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white inline-flex items-center justify-center gap-1.5 text-body font-bold"
        >
          <Play size={14} fill="currentColor" />
          Start Route
        </button>
      </div>
    </section>
  );
}

function MapSketch() {
  return (
    <div className="mt-3 h-[150px] rounded-xl overflow-hidden relative bg-[linear-gradient(180deg,#eef4f7_0%,#dceaf1_100%)] border border-[var(--color-edify-border)]">
      <svg viewBox="0 0 320 150" className="absolute inset-0 w-full h-full" aria-hidden>
        <path d="M10 80 C 60 30, 130 130, 200 70 S 300 60, 320 90" fill="none" stroke="#7ba3b8" strokeWidth="2" strokeDasharray="4 4" />
        <path d="M40 130 C 100 90, 180 130, 240 80" fill="none" stroke="#7ba3b8" strokeWidth="2" strokeDasharray="3 3" opacity="0.6" />
        <Pin x={32} y={82} label="Pakele" />
        <Pin x={120} y={50} label="Kitgum Town" />
        <Pin x={200} y={70} label="Orom" />
        <Pin x={245} y={92} label="Kal" />
        <Pin x={195} y={120} label="Matidi" />
      </svg>
    </div>
  );
}

function Pin({ x, y, label }: { x: number; y: number; label: string }) {
  return (
    <g>
      <circle cx={x} cy={y} r={5.5} fill="#10b981" stroke="#fff" strokeWidth="2" />
      <text x={x + 9} y={y + 3} fontSize="9" fill="#0f1720" fontWeight="700">
        {label}
      </text>
    </g>
  );
}
