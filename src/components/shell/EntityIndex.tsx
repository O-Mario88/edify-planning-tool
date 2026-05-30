import Link from "next/link";
import { type ReactNode } from "react";
import { ChevronRight, type LucideIcon } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";

// Reusable scaffold for entity index / list pages. Delegates to the
// canonical <PageHeader> so every list page inherits the premium
// full-width chrome (title, subtitle, search, back, identity cluster)
// in lockstep with the rest of the app.
//
// EntityIndex stays as a server component (no `"use client"`) so it
// can accept `Icon: LucideIcon` props from server pages. The Icon is
// rendered *here* (server side) and passed to PageHeader as a
// pre-rendered ReactNode via `titleBadge` — avoids the
// "function-prop-across-server-client-boundary" error.
export function EntityIndex({
  title,
  subtitle,
  Icon,
  count,
  searchPlaceholder,
  filters,
  children,
  noBack = false,
  backFallbackHref,
}: {
  title:     string;
  subtitle?: string;
  Icon?:     LucideIcon;
  count?:    number;
  searchPlaceholder?: string;
  /** Extra meta strip rendered under the title row — typically
   *  category tabs or facet pills owned by the page. */
  filters?:  ReactNode;
  children:  ReactNode;
  noBack?:   boolean;
  backFallbackHref?: string;
}) {
  // Pre-render the entity-type icon + count chip here on the server so
  // they cross the boundary as serialized JSX rather than as a raw
  // LucideIcon function reference.
  const leadingChip = (Icon || typeof count === "number") ? (
    <span className="inline-flex items-center gap-2">
      {Icon && (
        <span className="h-7 w-7 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
          <Icon size={14} />
        </span>
      )}
      {typeof count === "number" && (
        <span className="inline-flex items-center px-2 py-[3px] rounded-md text-[11px] font-extrabold bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]">
          {count}
        </span>
      )}
    </span>
  ) : undefined;

  return (
    <>
      <PageHeader
        title={title}
        subtitle={subtitle}
        titleBadge={leadingChip}
        searchPlaceholder={searchPlaceholder}
        noBack={noBack}
        backFallbackHref={backFallbackHref}
        meta={
          filters ? (
            <div className="flex flex-wrap items-center gap-2">{filters}</div>
          ) : undefined
        }
      />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
        {children}
      </div>
    </>
  );
}

// Tabular index row used inside <EntityIndex>. Click anywhere to drill
// through to the detail page.
export function IndexRow({
  href,
  Icon,
  iconBg = "bg-[var(--color-edify-soft)]/80",
  iconText = "text-[var(--color-edify-primary)]",
  title,
  subtitle,
  meta,
  badges,
  rightTop,
  rightBottom,
}: {
  href: string;
  Icon?: LucideIcon;
  iconBg?: string;
  iconText?: string;
  title: string;
  subtitle?: string;
  meta?: string;
  badges?: { label: string; tone: "edify" | "green" | "amber" | "rose" | "violet" | "slate" | "blue" }[];
  rightTop?: ReactNode;
  rightBottom?: ReactNode;
}) {
  const toneClass = (tone: NonNullable<typeof badges>[number]["tone"]) =>
    tone === "green"  ? "bg-emerald-100 text-emerald-700" :
    tone === "amber"  ? "bg-amber-100   text-amber-700"   :
    tone === "rose"   ? "bg-rose-100    text-rose-700"    :
    tone === "violet" ? "bg-violet-100  text-violet-700"  :
    tone === "blue"   ? "bg-sky-100     text-sky-700"     :
    tone === "slate"  ? "bg-slate-100   text-slate-700"   :
                        "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]";
  return (
    <Link
      href={href}
      className="flex items-start gap-3 px-4 py-3.5 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
    >
      {Icon && (
        <span className={`h-9 w-9 rounded-md grid place-items-center shrink-0 ${iconBg} ${iconText}`}>
          <Icon size={15} />
        </span>
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <div className="text-body font-extrabold tracking-tight truncate">{title}</div>
          {badges && badges.length > 0 && (
            <div className="flex items-center gap-1 shrink-0">
              {badges.map((b, i) => (
                <span key={i} className={`inline-flex px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap ${toneClass(b.tone)}`}>
                  {b.label}
                </span>
              ))}
            </div>
          )}
        </div>
        {subtitle && <div className="text-caption muted truncate">{subtitle}</div>}
        {meta && <div className="text-caption muted truncate">{meta}</div>}
      </div>
      {(rightTop || rightBottom) && (
        <div className="text-right shrink-0">
          {rightTop && <div className="text-body-lg font-extrabold tabular leading-none">{rightTop}</div>}
          {rightBottom && <div className="text-[10px] muted mt-0.5">{rightBottom}</div>}
        </div>
      )}
      <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0 self-center" />
    </Link>
  );
}
