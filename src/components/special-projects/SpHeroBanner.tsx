"use client";

import { TrendingUp } from "lucide-react";
import { specialProjectsHero } from "@/lib/special-projects-mock";

// Hero panel — wide enterprise impact banner. Mountain backdrop is rendered
// from an inline SVG silhouette layered behind a dark Edify-tone overlay so
// the banner is self-contained and printable.
export function SpHeroBanner() {
  return (
    <section
      className="relative overflow-hidden rounded-2xl text-white"
      style={{
        backgroundImage:
          [
            "linear-gradient(90deg, rgba(28,47,58,.92) 0%, rgba(38,61,74,.78) 50%, rgba(82,112,131,.55) 100%)",
            "radial-gradient(900px 280px at 78% 60%, rgba(255,200,120,.18), transparent 70%)",
            "linear-gradient(180deg, #3b5667 0%, #1f3340 100%)",
          ].join(", "),
      }}
    >
      {/* Mountains silhouette */}
      <svg
        viewBox="0 0 1400 320"
        preserveAspectRatio="none"
        className="absolute inset-0 w-full h-full opacity-35 pointer-events-none"
        aria-hidden
      >
        <path
          d="M0 240 L120 180 L220 220 L340 150 L460 210 L580 170 L700 230 L820 160 L940 210 L1060 180 L1180 230 L1280 200 L1400 240 L1400 320 L0 320 Z"
          fill="#223846"
        />
        <path
          d="M0 270 L160 220 L280 260 L420 200 L560 250 L700 220 L840 260 L980 220 L1120 260 L1260 230 L1400 260 L1400 320 L0 320 Z"
          fill="#1a2c37"
        />
      </svg>

      <div className="relative flex items-center justify-between gap-6 px-6 py-7">
        <div className="max-w-[68%] min-w-0">
          <h2 className="text-[22px] font-extrabold leading-tight">
            {specialProjectsHero.title}
          </h2>
          <p className="text-body text-white/85 mt-1.5 leading-snug">
            {specialProjectsHero.subtitle}
          </p>
        </div>

        <div className="rounded-xl bg-white/[.10] border border-white/15 backdrop-blur-sm px-4 py-3 min-w-[220px]">
          <div className="flex items-start justify-between gap-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-white/80">
              {specialProjectsHero.impactCard.label}
            </div>
            <TrendingUp size={14} className="text-emerald-300" />
          </div>
          <div className="text-[28px] font-extrabold tabular leading-none mt-1.5">
            {specialProjectsHero.impactCard.value}
          </div>
          <div className="text-[11px] text-emerald-300 font-semibold mt-1">
            {specialProjectsHero.impactCard.caption}
          </div>
        </div>
      </div>
    </section>
  );
}
