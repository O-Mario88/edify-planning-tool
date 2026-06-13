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
      </div>
    </section>
  );
}
