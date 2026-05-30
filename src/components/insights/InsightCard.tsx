import Link from "next/link";
import {
  Lightbulb,
  AlertTriangle,
  TrendingUp,
  Sparkles,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type InsightTone = "info" | "warning" | "success" | "highlight";

export type Insight = {
  id:           string;
  tone:         InsightTone;
  headline:     string;
  body:         string;
  ctaLabel?:    string;
  ctaHref?:     string;
};

const ICON: Record<InsightTone, LucideIcon> = {
  info:      Lightbulb,
  warning:   AlertTriangle,
  success:   TrendingUp,
  highlight: Sparkles,
};

const TONE: Record<InsightTone, { bg: string; border: string; icon: string; pill: string }> = {
  info:      { bg: "bg-sky-50",      border: "border-sky-200",      icon: "bg-sky-100 text-sky-700",        pill: "bg-sky-100 text-sky-700" },
  warning:   { bg: "bg-amber-50",    border: "border-amber-200",    icon: "bg-amber-100 text-amber-700",    pill: "bg-amber-100 text-amber-700" },
  success:   { bg: "bg-emerald-50",  border: "border-emerald-200",  icon: "bg-emerald-100 text-emerald-700",pill: "bg-emerald-100 text-emerald-700" },
  highlight: { bg: "bg-violet-50",   border: "border-violet-200",   icon: "bg-violet-100 text-violet-700",  pill: "bg-violet-100 text-violet-700" },
};

// Executive insight card — system-generated observation with optional CTA.
// Used on Country Director, RVP, CPL, and Impact dashboards to make the
// system feel like it's thinking on the leader's behalf.
export function InsightCard({ insight }: { insight: Insight }) {
  const Icon = ICON[insight.tone];
  const tone = TONE[insight.tone];
  return (
    <article className={cn("rounded-2xl border p-4 flex items-start gap-3", tone.bg, tone.border)}>
      <span className={cn("h-10 w-10 rounded-xl grid place-items-center shrink-0", tone.icon)}>
        <Icon size={16} />
      </span>
      <div className="flex-1 min-w-0">
        <h3 className="text-[13.5px] font-extrabold tracking-tight leading-snug">{insight.headline}</h3>
        <p className="text-[11.5px] muted leading-snug mt-1">{insight.body}</p>
        {insight.ctaLabel && insight.ctaHref && (
          <Link
            href={insight.ctaHref}
            className="mt-2 inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline"
          >
            {insight.ctaLabel}
            <ChevronRight size={11} />
          </Link>
        )}
      </div>
    </article>
  );
}

export function InsightStrip({ insights, title = "What the system is noticing" }: { insights: Insight[]; title?: string }) {
  if (insights.length === 0) return null;
  return (
    <section>
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
          <Sparkles size={14} className="text-violet-600" />
          {title}
        </h2>
        <span className="text-caption muted">{insights.length} insight{insights.length === 1 ? "" : "s"}</span>
      </div>
      {/* Grid: skip the md:grid-cols-2 step that produced a half-empty
          row when there are 3 insights (the common case). md+ goes
          straight to 3 columns so every insight has a peer on its row. */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {insights.map((i) => <InsightCard key={i.id} insight={i} />)}
      </div>
    </section>
  );
}
