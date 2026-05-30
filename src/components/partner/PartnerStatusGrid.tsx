// PartnerStatusGrid — the bottom 4-column status snapshot. Mirrors
// the verification funnel: what's blocking (evidence missing), what
// needs your action (returned for correction), what's in review
// (awaiting verification), what's done (verified / counted). Each
// card: count badge, top-3 items, CTA.

import Link from "next/link";
import { AlertCircle, RotateCcw, Eye, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { StatusBucket } from "@/lib/partner/partner-dashboard-mock";

const TONE_SCHEME: Record<
  StatusBucket["tone"],
  { icon: typeof AlertCircle; tile: string; iconBox: string; pill: string; cta: string; ctaText: string }
> = {
  rose: {
    icon: AlertCircle,
    tile:    "border-rose-200 bg-rose-50/40",
    iconBox: "bg-rose-100 text-rose-600",
    pill:    "bg-rose-100 text-rose-700",
    cta:     "bg-rose-500 hover:bg-rose-600",
    ctaText: "text-white",
  },
  amber: {
    icon: RotateCcw,
    tile:    "border-amber-200 bg-amber-50/40",
    iconBox: "bg-amber-100 text-amber-700",
    pill:    "bg-amber-100 text-amber-700",
    cta:     "bg-amber-500 hover:bg-amber-600",
    ctaText: "text-white",
  },
  blue: {
    icon: Eye,
    tile:    "border-blue-200 bg-blue-50/40",
    iconBox: "bg-blue-100 text-blue-700",
    pill:    "bg-blue-100 text-blue-700",
    cta:     "border border-blue-300 bg-white hover:bg-blue-50",
    ctaText: "text-blue-700",
  },
  emerald: {
    icon: CheckCircle2,
    tile:    "border-emerald-200 bg-emerald-50/40",
    iconBox: "bg-emerald-100 text-emerald-700",
    pill:    "bg-emerald-100 text-emerald-700",
    cta:     "border border-emerald-300 bg-white hover:bg-emerald-50",
    ctaText: "text-emerald-700",
  },
};

export function PartnerStatusGrid({ buckets }: { buckets: StatusBucket[] }) {
  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {buckets.map((b) => (
        <Bucket key={b.key} bucket={b} />
      ))}
    </section>
  );
}

function Bucket({ bucket: b }: { bucket: StatusBucket }) {
  const scheme = TONE_SCHEME[b.tone];
  const Icon = scheme.icon;
  return (
    <article className={cn("rounded-2xl border p-4 flex flex-col", scheme.tile)}>
      <header className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={cn("grid place-items-center h-8 w-8 rounded-lg shrink-0", scheme.iconBox)}>
            <Icon size={14} />
          </span>
          <h3 className="text-[13px] font-extrabold tracking-tight">{b.title}</h3>
        </div>
        <span
          className={cn(
            "inline-flex items-center justify-center min-w-[24px] h-[22px] px-1.5 rounded-md text-[11px] font-extrabold tabular",
            scheme.pill,
          )}
        >
          {b.count}
        </span>
      </header>

      <ul className="mt-3 space-y-1.5 flex-1">
        {b.items.map((item, i) => (
          <li key={i} className="flex items-start gap-2 text-[11.5px]">
            <span className="mt-1.5 inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-edify-muted)] shrink-0" />
            <div className="flex-1 min-w-0 flex items-baseline justify-between gap-2">
              <span className="font-semibold text-[var(--color-edify-text)] truncate">{item.label}</span>
              <span className="muted text-caption whitespace-nowrap">{item.sub}</span>
            </div>
          </li>
        ))}
      </ul>

      <Link
        href={b.ctaHref}
        className={cn(
          "mt-4 inline-flex items-center justify-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-extrabold transition-colors",
          scheme.cta,
          scheme.ctaText,
        )}
      >
        {b.ctaLabel}
      </Link>
    </article>
  );
}
