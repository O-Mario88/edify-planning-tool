"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, type LucideIcon } from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { useSetPageTitle } from "@/components/shell/PageTitleContext";
import { cn } from "@/lib/utils";

// Reusable phone-shell scaffold for sub-page mobile views.
// Provides the dark hero header, the standard MobileBottomNav, and
// helpers for KPI tiles and section cards so stamping new mobile pages
// stays consistent across the app.

export type KpiTone = "edify" | "amber" | "rose" | "green" | "violet" | "blue" | "yellow" | "slate";

export type MobileKpiTile = {
  key: string;
  Icon: LucideIcon;
  label: string;
  value: string;
  caption?: string;
  tone?: KpiTone;
};

const TONE_BG: Record<KpiTone, string> = {
  edify:  "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  amber:  "bg-amber-100   text-amber-700",
  rose:   "bg-rose-100    text-rose-700",
  green:  "bg-emerald-100 text-emerald-700",
  violet: "bg-violet-100  text-violet-700",
  blue:   "bg-sky-100     text-sky-700",
  yellow: "bg-yellow-100  text-yellow-700",
  slate:  "bg-slate-100   text-slate-700",
};

export function MobileSubpageShell({
  title,
  subtitle,
  notificationsCount = 3,
  children,
}: {
  title?: string;
  subtitle?: string;
  /** Deprecated — kept for compatibility with older callers. */
  initials?: string;
  /** Deprecated — the shell-level NotificationBell reads from the
   *  shared store. Kept to avoid breaking older callers. */
  notificationsCount?: number;
  children: ReactNode;
}) {
  // Register the title with the shell-level MobileTopBar instead of
  // rendering our own dark bar — the global one provides identical
  // chrome (hamburger + title + bell + avatar) and rendering both
  // creates a duplicate-header bug.
  useSetPageTitle(title ?? "Edify");
  void notificationsCount; // legacy prop, no-op now

  return (
    <MobileShell>
      {subtitle && (
        <p className="px-4 pt-2 pb-1 text-[11.5px] muted leading-snug">{subtitle}</p>
      )}
      <main className="flex-1 px-3 pt-3 pb-4 space-y-3 bg-[var(--color-page)]">
        {children}
      </main>
      <MobileBottomNav />
    </MobileShell>
  );
}

export function MobileKpiGrid({
  tiles,
  cols = 2,
}: {
  tiles: MobileKpiTile[];
  cols?: 2 | 3 | 4;
}) {
  const gridCls =
    cols === 2 ? "grid-cols-2" :
    cols === 3 ? "grid-cols-3" :
                 "grid-cols-4";
  return (
    <section className={cn("grid gap-2", gridCls)}>
      {tiles.map((t) => (
        <div key={t.key} className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-3">
          <span className={cn("h-8 w-8 rounded-md grid place-items-center", TONE_BG[t.tone ?? "edify"])}>
            <t.Icon size={14} />
          </span>
          <div className="text-caption muted font-semibold leading-tight mt-1.5 line-clamp-2 min-h-[28px]">
            {t.label}
          </div>
          <div className="text-[20px] font-extrabold tabular leading-none mt-0.5">{t.value}</div>
          {t.caption && (
            <div className="text-[10px] muted font-semibold mt-0.5 line-clamp-1">{t.caption}</div>
          )}
        </div>
      ))}
    </section>
  );
}

export function MobileSectionCard({
  title,
  subtitle,
  ctaLabel,
  ctaHref,
  children,
}: {
  title: string;
  subtitle?: string;
  ctaLabel?: string;
  ctaHref?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm">
      <div className="px-3 pt-3 pb-2 flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-body font-extrabold tracking-tight">{title}</h3>
          {subtitle && (
            <div className="text-caption muted leading-tight mt-0.5">{subtitle}</div>
          )}
        </div>
        {ctaLabel && ctaHref && (
          <Link
            href={ctaHref}
            className="text-[11px] font-semibold text-emerald-600 inline-flex items-center gap-0.5 shrink-0"
          >
            {ctaLabel}
            <ChevronRight size={11} />
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

export type ListRow = {
  key: string;
  title: string;
  subtitle?: string;
  meta?: string;
  rightTop?: ReactNode;
  rightBottom?: ReactNode;
  pill?: { label: string; tone: KpiTone };
};

const PILL_TONE: Record<KpiTone, string> = {
  edify:  "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  amber:  "bg-amber-100   text-amber-700",
  rose:   "bg-rose-100    text-rose-700",
  green:  "bg-emerald-100 text-emerald-700",
  violet: "bg-violet-100  text-violet-700",
  blue:   "bg-sky-100     text-sky-700",
  yellow: "bg-yellow-100  text-yellow-700",
  slate:  "bg-slate-100   text-slate-700",
};

// Collapsible accordion section for mobile dashboards. Lets secondary
// content live on the same page without forcing the user to scroll
// past it. Header shows title + optional count badge + chevron; tapping
// anywhere on the header toggles the body. Headers stay tappable even
// when the body is empty so users can confirm "there's nothing here"
// without scrolling.
export function MobileCollapsibleSection({
  title,
  subtitle,
  count,
  defaultOpen = false,
  tone = "edify",
  children,
}: {
  title: string;
  subtitle?: string;
  /** Optional count badge in the header (e.g. inbox unread). */
  count?: number;
  defaultOpen?: boolean;
  tone?: KpiTone;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className={cn(
      "card rounded-2xl overflow-hidden",
      open && "card-rail-emerald",
    )}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cn(
          "w-full px-3.5 py-3 flex items-center gap-3 text-left pressable",
          "transition-colors duration-200",
          open
            ? "bg-gradient-to-r from-[var(--color-edify-soft)]/60 to-transparent"
            : "active:bg-slate-50",
        )}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-[13.5px] font-extrabold tracking-tight truncate">{title}</h3>
            {typeof count === "number" && (
              <span className={cn("pill", PILL_TONE_PILL[tone])}>
                {count}
              </span>
            )}
          </div>
          {subtitle && (
            <div className="text-caption muted leading-tight mt-0.5 truncate">{subtitle}</div>
          )}
        </div>
        <ChevronDown
          size={16}
          className={cn(
            "shrink-0 transition-transform duration-300 ease-out",
            open ? "rotate-180 text-[var(--color-edify-primary)]" : "muted",
          )}
        />
      </button>
      {/* Grid-template-rows trick animates height between 0fr → 1fr
          without measuring scrollHeight or coupling to JS. Smoother
          than max-height: 0 → 1000px which leaps once content exceeds
          the cap. */}
      <div className="accordion-body" data-open={open}>
        <div className="accordion-inner">
          <div className="border-t border-[var(--color-edify-border)] bg-[var(--color-page)]">
            {children}
          </div>
        </div>
      </div>
    </section>
  );
}

// Maps the KpiTone enum to the new .pill-* primitive. Existing
// PILL_TONE map kept for older callers using inline pills.
const PILL_TONE_PILL: Record<KpiTone, string> = {
  edify:  "pill-primary",
  amber:  "pill-warn",
  rose:   "pill-danger",
  green:  "pill-success",
  violet: "pill-violet",
  blue:   "pill-info",
  yellow: "pill-warn",
  slate:  "pill-slate",
};

export function MobileListRows({ rows }: { rows: ListRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="px-3 py-6 text-[12px] muted text-center">No items.</div>
    );
  }
  return (
    <ul className="divide-y divide-[var(--color-edify-divider)]">
      {rows.map((r) => (
        <li key={r.key} className="px-3 py-2.5 flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <div className="text-body font-extrabold tracking-tight leading-tight truncate">
                {r.title}
              </div>
              {r.pill && (
                <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap shrink-0", PILL_TONE[r.pill.tone])}>
                  {r.pill.label}
                </span>
              )}
            </div>
            {r.subtitle && <div className="text-caption muted truncate">{r.subtitle}</div>}
            {r.meta && <div className="text-caption muted truncate">{r.meta}</div>}
          </div>
          {(r.rightTop || r.rightBottom) && (
            <div className="text-right shrink-0">
              {r.rightTop && (
                <div className="text-body font-extrabold tabular leading-none">{r.rightTop}</div>
              )}
              {r.rightBottom && (
                <div className="text-[10px] muted font-semibold mt-0.5">{r.rightBottom}</div>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
