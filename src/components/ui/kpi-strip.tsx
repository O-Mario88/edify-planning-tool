"use client";

// KpiStrip — the system-wide metric language of the product.
//
// One premium horizontal strip replaces every grid of KPI tiles: a single
// rounded container, an uppercase section title, and segmented hairline cells —
// each with an icon, uppercase label, a large value, and an optional
// sub-value/percentage. Tone colours the value for at-a-glance status. Cells can
// deep-link (href) or act as filter triggers (onClick + active).
//
// This is the ONLY KPI surface. The legacy MetricStrip is now a thin adapter
// over this component, so every existing strip across the app renders through
// one design. Values are always supplied by the caller from backend data — the
// strip itself never invents numbers; pass loading/error/empty to reflect the
// real fetch state instead of showing misleading zeroes.

import Link from "next/link";
import { cn } from "@/lib/utils";

export type KpiTone = "default" | "success" | "warning" | "danger" | "info" | "muted";

export type KpiStripItem = {
  id: string;
  label: string;
  value: string | number;
  /** Smaller supporting line — a percentage, proportion, or caption. */
  subValue?: string;
  /** Any node — typically a Lucide icon element <School size={12} />. */
  icon?: React.ReactNode;
  tone?: KpiTone;
  /** Optional independent colour for the sub-value (e.g. a trend delta). Falls back to tone. */
  subTone?: KpiTone;
  tooltip?: string;
  /** Makes the cell a deep link. */
  href?: string;
  /** Makes the cell a button (ignored when href is set). */
  onClick?: () => void;
  /** Highlights the cell as the active selection (filter cells). */
  active?: boolean;
};

export type KpiStripProps = {
  title?: string;
  subtitle?: string;
  items: KpiStripItem[];
  loading?: boolean;
  error?: string;
  /** Retry handler for the error state (optional). */
  onRetry?: () => void;
  emptyMessage?: string;
  /** Override the responsive column classes. */
  columns?: string;
  /** Render just the hairline cell grid (no card chrome) for embedding. */
  bare?: boolean;
  className?: string;
};

const VALUE_TONE: Record<KpiTone, string> = {
  default: "text-[var(--text-primary)]",
  success: "text-emerald-600",
  warning: "text-amber-600",
  danger: "text-rose-600",
  info: "text-sky-600",
  muted: "muted",
};

const ICON_TONE: Record<KpiTone, string> = {
  default: "text-[var(--color-edify-muted)]",
  success: "text-emerald-500",
  warning: "text-amber-500",
  danger: "text-rose-500",
  info: "text-sky-500",
  muted: "text-[var(--color-edify-muted)]",
};

// Hairline collapsing borders → a single continuous band that wraps cleanly
// (no leading/trailing dividers) and scrolls on the smallest viewports.
const COLS = "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6";

export function KpiStrip({
  title,
  subtitle,
  items,
  loading = false,
  error,
  onRetry,
  emptyMessage = "No records found for the selected filters.",
  columns,
  bare = false,
  className,
}: KpiStripProps) {
  let body: React.ReactNode;

  if (loading) {
    body = (
      <div className={cn("grid border-t border-l border-[var(--color-edify-divider)]", columns ?? COLS)} aria-busy="true">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="px-3 py-2.5 border-r border-b border-[var(--color-edify-divider)]">
            <div className="h-2.5 w-16 rounded bg-[var(--color-edify-soft)] animate-pulse" />
            <div className="h-4 w-12 rounded bg-[var(--color-edify-soft)] animate-pulse mt-2" />
          </div>
        ))}
      </div>
    );
  } else if (error) {
    body = (
      <div className="px-4 py-6 text-center" role="alert">
        <p className="text-[12px] font-semibold text-rose-600">{error}</p>
        {onRetry && (
          <button type="button" onClick={onRetry} className="mt-2 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline">
            Retry
          </button>
        )}
      </div>
    );
  } else if (items.length === 0) {
    body = <div className="px-4 py-6 text-center text-[12px] muted">{emptyMessage}</div>;
  } else {
    body = (
      <div className={cn("grid border-t border-l border-[var(--color-edify-divider)]", columns ?? COLS)}>
        {items.map((item) => (
          <Cell key={item.id} item={item} />
        ))}
      </div>
    );
  }

  if (bare) return <div className={cn("rounded-xl overflow-hidden", className)}>{body}</div>;

  return (
    <section className={cn("card rounded-2xl overflow-hidden", className)} aria-label={title}>
      {(title || subtitle) && (
        <header className="px-3.5 pt-3 pb-2 border-b border-[var(--color-edify-divider)]">
          {title && <h2 className="text-[12px] font-extrabold tracking-tight uppercase muted">{title}</h2>}
          {subtitle && <p className="text-[11px] muted mt-0.5">{subtitle}</p>}
        </header>
      )}
      {body}
    </section>
  );
}

function Cell({ item }: { item: KpiStripItem }) {
  const tone = item.tone ?? "default";
  const body = (
    <>
      <div className="flex items-center gap-1 text-[10px] muted font-bold uppercase tracking-wide leading-tight">
        {item.icon != null && (
          <span aria-hidden="true" className={cn("shrink-0 inline-flex", ICON_TONE[tone])}>
            {item.icon}
          </span>
        )}
        <span className="truncate">{item.label}</span>
      </div>
      <div className="mt-1.5 min-w-0">
        <span className={cn("block text-[17px] font-extrabold tabular leading-none truncate", VALUE_TONE[tone])}>
          {typeof item.value === "number" ? item.value.toLocaleString() : item.value}
        </span>
      </div>
      {item.subValue && (() => {
        const st = item.subTone ?? tone;
        return <div className={cn("text-[10px] font-medium mt-0.5 truncate", st === "default" ? "muted" : VALUE_TONE[st])}>{item.subValue}</div>;
      })()}
    </>
  );

  const base = "block px-3 py-2.5 border-r border-b border-[var(--color-edify-divider)] min-w-0";
  const activeCls = item.active ? "bg-[var(--color-edify-soft)]/70 ring-1 ring-inset ring-[var(--color-edify-primary)]/40" : "";

  if (item.href) {
    return (
      <Link href={item.href} title={item.tooltip} className={cn(base, "transition-colors hover:bg-[var(--color-edify-soft)]/50", activeCls)}>
        {body}
      </Link>
    );
  }
  if (item.onClick) {
    return (
      <button type="button" onClick={item.onClick} title={item.tooltip} aria-pressed={item.active} className={cn(base, "text-left w-full transition-colors hover:bg-[var(--color-edify-soft)]/50", activeCls)}>
        {body}
      </button>
    );
  }
  return (
    <div className={base} title={item.tooltip}>
      {body}
    </div>
  );
}
