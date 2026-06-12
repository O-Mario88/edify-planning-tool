import { Sparkles } from "lucide-react";
import type { DailyBrief } from "@/lib/planning/my-plan-brief";

// Daily Field Briefing hero — calm, premium tinted surface that lets the
// app speak intelligently to the user. One sentence of focus, one short
// verdict chip. Server-rendered.

const VERDICT_TONE: Record<DailyBrief["verdict"], { surface: string; chip: string; dot: string }> = {
  blockers: {
    surface: "from-rose-50 via-white to-white border-rose-200/60 dark:from-rose-950/30 dark:via-slate-900/60 dark:to-slate-900/60 dark:border-rose-900/40",
    chip: "bg-rose-100 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:border-rose-900/50",
    dot: "bg-rose-500",
  },
  fieldHeavy: {
    surface: "from-amber-50 via-white to-white border-amber-200/60 dark:from-amber-950/30 dark:via-slate-900/60 dark:to-slate-900/60 dark:border-amber-900/40",
    chip: "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-900/50",
    dot: "bg-amber-500",
  },
  needsAttention: {
    surface: "from-amber-50 via-white to-white border-amber-200/60 dark:from-amber-950/30 dark:via-slate-900/60 dark:to-slate-900/60 dark:border-amber-900/40",
    chip: "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-900/50",
    dot: "bg-amber-500",
  },
  fundingHold: {
    surface: "from-sky-50 via-white to-white border-sky-200/60 dark:from-sky-950/30 dark:via-slate-900/60 dark:to-slate-900/60 dark:border-sky-900/40",
    chip: "bg-sky-100 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:border-sky-900/50",
    dot: "bg-sky-500",
  },
  onTrack: {
    surface: "from-emerald-50 via-white to-white border-emerald-200/60 dark:from-emerald-950/30 dark:via-slate-900/60 dark:to-slate-900/60 dark:border-emerald-900/40",
    chip: "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:border-emerald-900/50",
    dot: "bg-emerald-500",
  },
  clear: {
    surface: "from-emerald-50 via-white to-white border-emerald-200/60 dark:from-emerald-950/30 dark:via-slate-900/60 dark:to-slate-900/60 dark:border-emerald-900/40",
    chip: "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:border-emerald-900/50",
    dot: "bg-emerald-500",
  },
};

export function MyPlanBriefingHero({ brief }: { brief: DailyBrief }) {
  const tone = VERDICT_TONE[brief.verdict];
  return (
    <section
      aria-label="Daily field briefing"
      className={`relative overflow-hidden rounded-2xl border bg-gradient-to-br px-5 sm:px-6 py-4 ${tone.surface}`}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.6]"
        style={{
          backgroundImage:
            "radial-gradient(520px 200px at 92% 5%, rgba(255,255,255,0.55), transparent 70%)",
        }}
      />
      <div className="relative">
        {/* Top row — eyebrow + verdict chip. Chip lives in the same row as the
            eyebrow on every breakpoint so the greeting always reads on one
            line on phones (no squeezed multi-line headlines). */}
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 text-[10.5px] font-bold uppercase tracking-[0.13em] text-slate-500 dark:text-slate-400">
            <Sparkles size={11} className="text-slate-400" />
            <span>Daily Field Briefing</span>
            <span className="hidden sm:inline text-slate-300 dark:text-slate-600">·</span>
            <span className="hidden sm:inline text-[10.5px] font-semibold tracking-normal normal-case text-slate-500 dark:text-slate-400">
              {brief.dateLabel}
            </span>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10.5px] font-extrabold uppercase tracking-wide shrink-0 ${tone.chip}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${tone.dot} animate-pulse`} />
            {brief.verdictLabel}
          </span>
        </div>
        <h2 className="mt-1.5 text-[18px] sm:text-[20px] font-extrabold leading-tight text-slate-900 dark:text-slate-50">
          {brief.greeting}
        </h2>
        <p className="sm:hidden mt-0.5 text-[10.5px] font-semibold normal-case text-slate-500 dark:text-slate-400">
          {brief.dateLabel}
        </p>
        <p className="mt-1 text-[13.5px] sm:text-[14.5px] leading-snug text-slate-700 dark:text-slate-200 max-w-[720px]">
          {brief.focus}
        </p>
        {brief.secondary && (
          <p className="mt-1 text-[12px] leading-snug text-slate-500 dark:text-slate-400 max-w-[720px]">
            {brief.secondary}
          </p>
        )}
      </div>
    </section>
  );
}
