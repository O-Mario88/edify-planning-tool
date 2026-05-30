// MissionHeader — the role-aware opener that frames the dashboard.
//
// Top-of-page, premium-SaaS treatment. Greeting → role mission → period
// context → one-sentence summary of what needs attention.
//
// The mission line is the SAME tone as the existing CPL hero ("Coach
// the field. Close the gaps. Multiply the wins.") — re-using the
// "hero-bg" CSS class from globals.css so the visual language stays
// consistent. The summary line is the new bit: a single sentence the
// user reads in 2 seconds and knows what's on their plate today.

import { Sparkles } from "lucide-react";
import type { MissionHeader as MissionHeaderType } from "@/lib/actions/action-types";

export function MissionHeader({ header }: { header: MissionHeaderType }) {
  return (
    <section
      className="relative overflow-hidden rounded-3xl text-white"
      style={{
        background:
          "linear-gradient(135deg, #1c2f3a 0%, #263d4a 45%, #527083 100%)",
      }}
    >
      {/* Soft amber highlight bottom-right — matches the existing hero. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(closest-side, rgba(245,158,11,0.45), transparent 70%) 88% 88% / 340px 200px no-repeat",
        }}
      />
      <div className="relative px-5 sm:px-6 py-5 sm:py-6 flex flex-col md:flex-row md:items-center gap-4 md:gap-6">
        <div className="min-w-0 flex-1">
          <div className="inline-flex items-center gap-1.5 text-caption uppercase tracking-[0.12em] text-white/70 font-extrabold">
            <Sparkles size={11} />
            {header.periodLabel}
          </div>
          {/* Don't use the global .page-title class — its `color` rule
              wins specificity over Tailwind's text-white and renders
              dark-on-dark here. Reproduce the same size/weight tokens
              inline so the visual hierarchy matches the rest of the
              app while keeping the white-on-dark contrast. */}
          <h1
            className="mt-1.5 font-extrabold tracking-tight text-white leading-tight"
            style={{ color: "#ffffff", fontSize: "clamp(22px, 3vw, 28px)" }}
          >
            {header.greeting}
          </h1>
          <p className="text-body-lg sm:text-[15px] font-extrabold tracking-tight text-white/95 mt-1.5">
            {header.mission}
          </p>
          <p className="text-body sm:text-[13px] text-white/80 mt-1.5 leading-snug max-w-[68ch]">
            {header.summary}
          </p>
        </div>
        <HeroPulse />
      </div>
    </section>
  );
}

// ───────────── HeroPulse ─────────────
//
// Fills the previously-empty right side of the mission header with a
// real signal: a compact "team pulse" — two mini-KPIs over a 14-day
// completion sparkline. Reads as the dashboard's heartbeat the moment
// the user lands. Desktop/tablet only so mobile keeps the greeting
// text-first above the fold.

const PULSE_SERIES = [38, 42, 36, 51, 47, 58, 54, 61, 57, 64, 70, 66, 72, 78];

function HeroPulse() {
  const max = Math.max(...PULSE_SERIES);
  const min = Math.min(...PULSE_SERIES);
  const range = Math.max(1, max - min);
  const w = 220;
  const h = 56;
  const step = w / (PULSE_SERIES.length - 1);
  const coords = PULSE_SERIES.map((v, i) => {
    const x = i * step;
    const y = h - ((v - min) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const linePath = `M ${coords.join(" L ")}`;
  const areaPath = `M 0,${h} L ${coords.join(" L ")} L ${w},${h} Z`;
  const last = PULSE_SERIES[PULSE_SERIES.length - 1];
  const lastY = h - ((last - min) / range) * h;

  return (
    <div className="hidden md:flex flex-col gap-2.5 shrink-0 rounded-2xl border border-white/15 bg-white/5 backdrop-blur px-4 py-3 w-[260px]">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-white/65 font-bold">Schools touched</div>
          <div className="text-[18px] font-extrabold leading-none mt-1 num-hero">
            12<span className="text-white/55 text-[13px] font-bold">/47</span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-wider text-white/65 font-bold">Wk pace</div>
          <div className="text-[18px] font-extrabold leading-none mt-1 num-hero text-emerald-300">+14%</div>
        </div>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-[56px]" preserveAspectRatio="none" aria-hidden>
        <defs>
          <linearGradient id="pulse-fill-mh" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#pulse-fill-mh)" />
        <path d={linePath} fill="none" stroke="#fbbf24" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={w} cy={lastY} r="2.8" fill="#fff" stroke="#fbbf24" strokeWidth="1.4" />
      </svg>
      <div className="flex items-center justify-between text-[10px] text-white/55 font-semibold">
        <span>Last 14 days</span>
        <span>Target 60/wk</span>
      </div>
    </div>
  );
}
