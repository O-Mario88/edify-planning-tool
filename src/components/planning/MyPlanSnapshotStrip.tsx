"use client";

import { useEffect, useRef, useState } from "react";
import { CircleDot, UserRound, CalendarClock, CalendarRange, AlertTriangle, type LucideIcon } from "lucide-react";
import type { SnapshotChip, SnapshotChipKey, SnapshotTone } from "@/lib/planning/my-plan-brief";

// Personal execution snapshot — the urgency strip under the briefing
// hero. Clickable; each chip scrolls to its lane and briefly rings the
// target so the eye lands. Count-up animates only on value changes, so
// the initial render is calm and SSR-stable.

const ICON: Record<SnapshotChipKey, LucideIcon> = {
  open: CircleDot,
  waiting: UserRound,
  today: CalendarClock,
  week: CalendarRange,
  attention: AlertTriangle,
};

const TONE: Record<SnapshotTone, { icon: string; tile: string; sparkline: string }> = {
  emerald: { icon: "bg-emerald-100 text-emerald-700",     tile: "border-emerald-100 hover:border-emerald-300",     sparkline: "stroke-emerald-400" },
  sky:     { icon: "bg-sky-100 text-sky-700",             tile: "border-sky-100 hover:border-sky-300",             sparkline: "stroke-sky-400" },
  amber:   { icon: "bg-amber-100 text-amber-700",         tile: "border-amber-100 hover:border-amber-300",         sparkline: "stroke-amber-400" },
  rose:    { icon: "bg-rose-100 text-rose-700",           tile: "border-rose-100 hover:border-rose-300",           sparkline: "stroke-rose-400" },
  violet:  { icon: "bg-violet-100 text-violet-700",       tile: "border-violet-100 hover:border-violet-300",       sparkline: "stroke-violet-400" },
  slate:   { icon: "bg-slate-100 text-slate-500",         tile: "border-slate-200 hover:border-slate-300",         sparkline: "stroke-slate-300" },
};

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function Counter({ value }: { value: number }) {
  const [n, setN] = useState(value);
  const fromRef = useRef(value);
  useEffect(() => {
    const from = fromRef.current;
    fromRef.current = value;
    if (from === value) return;
    if (prefersReducedMotion()) { setN(value); return; }
    let raf = 0;
    const t0 = performance.now();
    const dur = 700;
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / dur);
      const eased = 1 - Math.pow(1 - k, 3);
      setN(Math.round(from + (value - from) * eased));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{n.toLocaleString()}</>;
}

// Decorative deterministic sparkline — gives each tile a small pulse
// without inventing data. Seed = chip key, so it's stable across renders
// and users; pure visual rhythm.
function sparklinePath(seed: string, width = 96, height = 18): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  const points = 14;
  let d = "";
  for (let i = 0; i < points; i++) {
    h = (h * 9301 + 49297) % 233280;
    const y = ((h / 233280) * (height - 4)) + 2;
    const x = (i / (points - 1)) * width;
    d += (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
  }
  return d;
}

function handleScroll(target: string) {
  const el = document.querySelector(target);
  if (!(el instanceof HTMLElement)) return;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  // Soft highlight pulse — anchors the eye after the scroll lands.
  el.classList.add("ring-2", "ring-[var(--color-edify-primary)]/30");
  window.setTimeout(() => {
    el.classList.remove("ring-2", "ring-[var(--color-edify-primary)]/30");
  }, 900);
}

export function MyPlanSnapshotStrip({ chips }: { chips: SnapshotChip[] }) {
  return (
    <div
      role="list"
      aria-label="My Plan urgency snapshot"
      className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5"
    >
      {chips.map((c) => {
        const Icon = ICON[c.key];
        const tone = TONE[c.tone];
        return (
          <a
            key={c.key}
            role="listitem"
            href={c.target}
            onClick={(e) => { e.preventDefault(); handleScroll(c.target); }}
            className={`group relative flex items-center gap-3 rounded-2xl border bg-white px-3.5 py-3 transition-all hover:-translate-y-px hover:shadow-[0_10px_24px_-16px_rgba(15,23,32,0.28)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/40 no-underline ${tone.tile} dark:bg-slate-900/40 dark:border-slate-800`}
          >
            <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${tone.icon}`}>
              <Icon size={17} aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-1.5">
                <div className="text-[22px] font-extrabold tabular leading-none text-slate-900 dark:text-slate-50">
                  <Counter value={c.count} />
                </div>
                {c.caption && (
                  <span className="text-[10.5px] font-semibold text-slate-500 dark:text-slate-400 truncate">
                    {c.caption}
                  </span>
                )}
              </div>
              <div className="mt-0.5 text-[11.5px] font-bold text-slate-700 dark:text-slate-200 truncate">
                {c.label}
              </div>
              <svg
                aria-hidden
                className="mt-0.5 block h-[18px] w-full opacity-70 group-hover:opacity-100 transition-opacity"
                viewBox="0 0 96 18"
                preserveAspectRatio="none"
              >
                <path
                  d={sparklinePath(c.key)}
                  fill="none"
                  strokeWidth={1.4}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className={tone.sparkline}
                />
              </svg>
            </div>
          </a>
        );
      })}
    </div>
  );
}
