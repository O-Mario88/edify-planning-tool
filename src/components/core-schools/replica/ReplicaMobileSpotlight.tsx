"use client";

import { ArrowUpRight, School, Sparkles, ShieldCheck } from "lucide-react";

// Mobile spotlight — a single premium card that lifts the three
// numbers a CCEO actually leads with into hero position so the user
// doesn't scroll past 9 KPIs before grasping the headline. Lives only
// on phone + tablet (lg:hidden); desktop already has the 9-KPI strip.
//
// Visual treatment is intentionally distinct from the rest of the
// page — deep navy gradient + ember glow on the right — so the eye
// reads it as "summary" rather than "another tile".
export function ReplicaMobileSpotlight() {
  return (
    <section className="relative overflow-hidden rounded-2xl text-white lg:hidden">
      {/* Layered background — gradient + radial glow + diagonal accent. */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(135deg, #050b14 0%, #0b1f33 40%, #1a3a5e 100%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-20 -top-20 w-64 h-64 rounded-full"
        style={{
          background:
            "radial-gradient(closest-side, rgba(251,191,36,0.32) 0%, rgba(251,191,36,0) 70%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -left-16 bottom-[-40%] w-72 h-72 rounded-full"
        style={{
          background:
            "radial-gradient(closest-side, rgba(56,189,248,0.22) 0%, rgba(56,189,248,0) 70%)",
        }}
      />

      <div className="relative p-4 sm:p-5">
        <div className="flex items-baseline justify-between gap-3 mb-3">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-[0.18em] font-bold text-amber-300/90">
              At a glance
            </div>
            <h2 className="text-[18px] sm:text-[20px] font-extrabold tracking-tight leading-tight">
              FY 2025 · Q2 snapshot
            </h2>
          </div>
          <span className="inline-flex items-center gap-1 text-caption font-extrabold tabular text-emerald-300 shrink-0">
            <ArrowUpRight size={11} />
            +0.4 SSA
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <SpotlightStat
            icon={<School size={13} className="text-sky-300" />}
            label="Schools"
            value="512"
            caption="Assessed 90.2%"
          />
          <SpotlightStat
            icon={<Sparkles size={13} className="text-amber-300" />}
            label="Avg SSA"
            value="7.6"
            unit="/10"
            caption="+0.4 vs Apr"
          />
          <SpotlightStat
            icon={<ShieldCheck size={13} className="text-emerald-300" />}
            label="On Track"
            value="55.9%"
            caption="286 schools"
          />
        </div>
      </div>
    </section>
  );
}

function SpotlightStat({
  icon,
  label,
  value,
  unit,
  caption,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  unit?: string;
  caption: string;
}) {
  return (
    <div className="rounded-xl bg-white/[.07] border border-white/10 backdrop-blur-sm px-2.5 py-2.5">
      <div className="flex items-center gap-1.5 mb-1">
        {icon}
        <span className="text-[9.5px] uppercase tracking-wide font-bold text-white/65">{label}</span>
      </div>
      <div className="flex items-baseline gap-0.5">
        <span className="text-[18px] font-extrabold tabular leading-none">{value}</span>
        {unit && <span className="text-[11px] muted text-white/65 font-semibold">{unit}</span>}
      </div>
      <div className="text-[9.5px] text-white/55 font-semibold leading-tight mt-1 truncate">{caption}</div>
    </div>
  );
}
