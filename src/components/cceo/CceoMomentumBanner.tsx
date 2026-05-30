"use client";

import {
  CheckCircle2,
  Flame,
  Star,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import { cceoMomentum } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

// The closing momentum banner. Three live stats sit alongside the
// headline — On Track / Quality Score / Consistency — so the
// "celebration" reads as a status read-out, not a gold star. The
// streak is tied to a real metric (8 consecutive weeks at ≥ 90%
// completion) so it earns its place on the dashboard.
export function CceoMomentumBanner() {
  const m = cceoMomentum;
  return (
    <section className="relative overflow-hidden rounded-2xl text-white">
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(135deg, #0a1623 0%, #112a44 45%, #1a3a5e 100%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-[-20%] w-[60%]"
        style={{
          background:
            "radial-gradient(closest-side at 60% 50%, rgba(82,159,255,0.18) 0%, rgba(82,159,255,0) 70%)",
        }}
      />
      {/* Flexbox layout (was grid-cols-[1fr_auto] — the `auto` track
          grew unbounded because each stat caption fights to stay on
          one line, so it consumed ~80% of the banner and crushed the
          headline column into ~170px where every word wrapped onto
          its own line.  Flex with `flex-1 min-w-0` on the headline
          and `lg:w-[520px] shrink-0` on the stats forces a stable
          split: headline grows / stats fixed-width on desktop. */}
      <div className="relative p-4 lg:p-5 flex flex-col lg:flex-row gap-4 items-center">
        <div className="flex items-center gap-3 sm:gap-4 flex-1 min-w-0 w-full lg:w-auto">
          <span className="w-11 h-11 sm:w-12 sm:h-12 rounded-xl bg-amber-400/20 ring-1 ring-amber-300/40 grid place-items-center shrink-0">
            <Trophy size={20} className="text-amber-300 sm:hidden" />
            <Trophy size={22} className="text-amber-300 hidden sm:block" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-[16px] sm:text-[17px] lg:text-[18px] font-extrabold tracking-tight leading-tight">
              {m.headline}
            </h2>
            <p className="text-[11.5px] sm:text-[12px] text-white/75 leading-snug mt-0.5 max-w-[640px]">
              {m.body}
            </p>
          </div>
        </div>
        {/* Stats — stack 1-col on phone so captions never truncate;
            3-up from sm.  Fixed `lg:w-[520px]` on desktop so the
            stat strip never crushes the headline column. */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 sm:gap-2.5 w-full lg:w-[520px] shrink-0">
          <MomentumStat
            icon={CheckCircle2}
            label={m.stats[0].label}
            value={m.stats[0].value}
            caption={m.stats[0].caption}
            tone="emerald"
          />
          <MomentumStat
            icon={Star}
            label={m.stats[1].label}
            value={m.stats[1].value}
            caption={m.stats[1].caption}
            tone="amber"
            showLive={m.stats[1].showLive}
          />
          <MomentumStat
            icon={Flame}
            label={m.stats[2].label}
            value={m.stats[2].value}
            caption={m.stats[2].caption}
            tone="rose"
          />
        </div>
      </div>
    </section>
  );
}

// ───────────── MomentumStat ─────────────

type StatTone = "emerald" | "amber" | "rose";

const STAT_TONE: Record<StatTone, { iconBg: string; iconColor: string; ring: string }> = {
  emerald: { iconBg: "bg-emerald-400/15", iconColor: "text-emerald-300", ring: "ring-emerald-300/30" },
  amber:   { iconBg: "bg-amber-400/15",   iconColor: "text-amber-300",   ring: "ring-amber-300/30"   },
  rose:    { iconBg: "bg-rose-400/15",    iconColor: "text-rose-300",    ring: "ring-rose-300/30"    },
};

function MomentumStat({
  icon: Icon,
  label,
  value,
  caption,
  tone,
  showLive,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  caption: string;
  tone: StatTone;
  showLive?: boolean;
}) {
  const t = STAT_TONE[tone];
  return (
    <div className={cn("rounded-xl bg-white/5 border border-white/10 backdrop-blur p-3 flex items-center gap-2.5 ring-1", t.ring)}>
      <span className={cn("w-9 h-9 rounded-lg grid place-items-center shrink-0", t.iconBg)}>
        <Icon size={16} className={t.iconColor} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[9.5px] font-bold uppercase tracking-wide text-white/65 inline-flex items-center gap-1">
          {label}
          {showLive && (
            <span className="inline-flex items-center gap-1 text-[8.5px] font-extrabold text-emerald-300">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-300 animate-pulse" />
              LIVE
            </span>
          )}
        </div>
        <div className="text-[15px] font-extrabold tabular leading-none mt-0.5">{value}</div>
        <div className="text-caption text-white/65 font-semibold mt-1 leading-snug">{caption}</div>
      </div>
    </div>
  );
}
