import { type ReactNode } from "react";
import Link from "next/link";
import { ChevronRight, type LucideIcon } from "lucide-react";
import { HeaderChrome } from "@/components/shell/HeaderChrome";

// Reusable scaffold for entity detail pages (staff, cluster, district,
// project, fund request, …). The outer flex + sidebar comes from the
// shared (shell) route-group layout — DO NOT remount the sidebar here.

export type Breadcrumb = { label: string; href?: string };

export function EntityDetail({
  breadcrumbs,
  title,
  subtitle,
  Icon,
  badge,
  actions,
  children,
}: {
  breadcrumbs: Breadcrumb[];
  title: string;
  subtitle?: string;
  Icon?: LucideIcon;
  badge?: { label: string; tone: "edify" | "green" | "amber" | "rose" | "violet" | "blue" | "slate" };
  actions?: ReactNode;
  children: ReactNode;
}) {
  const badgeTone =
    badge?.tone === "green"  ? "bg-emerald-100 text-emerald-700" :
    badge?.tone === "amber"  ? "bg-amber-100   text-amber-700"   :
    badge?.tone === "rose"   ? "bg-rose-100    text-rose-700"    :
    badge?.tone === "violet" ? "bg-violet-100  text-violet-700"  :
    badge?.tone === "blue"   ? "bg-sky-100     text-sky-700"     :
    badge?.tone === "slate"  ? "bg-slate-100   text-slate-700"   :
                                "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]";

  return (
    <>
      <header className="pl-16 pr-4 pt-5 lg:pl-6 lg:pr-6 pb-4">
          {/* Breadcrumbs */}
          <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-[11.5px] muted">
            {breadcrumbs.map((b, i) => (
              <span key={i} className="flex items-center gap-1.5">
                {b.href ? (
                  <Link href={b.href} className="hover:text-[var(--color-edify-primary)]">
                    {b.label}
                  </Link>
                ) : (
                  <span className={i === breadcrumbs.length - 1 ? "text-[var(--color-edify-text)] font-semibold" : ""}>
                    {b.label}
                  </span>
                )}
                {i < breadcrumbs.length - 1 && <ChevronRight size={10} className="opacity-60" />}
              </span>
            ))}
          </nav>

          {/* Title row */}
          <div className="mt-1 flex items-start gap-3 flex-wrap">
            {Icon && (
              <span className="h-10 w-10 rounded-xl bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0 mt-0.5">
                <Icon size={20} />
              </span>
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="page-title">
                  {title}
                </h1>
                {badge && (
                  <span className={`inline-flex items-center px-2 py-[3px] rounded-md text-caption font-extrabold whitespace-nowrap ${badgeTone}`}>
                    {badge.label}
                  </span>
                )}
              </div>
              {subtitle && (
                <p className="text-body muted mt-0.5 max-w-[760px]">{subtitle}</p>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {actions}
              {/* Canonical identity chrome (search · message · bell) so
                  detail pages read like every PageHeader page. Desktop
                  only — the dark MobileTopBar carries the bells below lg. */}
              <HeaderChrome className="hidden lg:flex" />
            </div>
          </div>
        </header>

      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
        {children}
      </div>
    </>
  );
}

// Tile primitive used in entity-detail KPI rows.
export function DetailKpi({
  label,
  value,
  caption,
  Icon,
  tone = "edify",
}: {
  label: string;
  value: string;
  caption?: string;
  Icon?: LucideIcon;
  tone?: "edify" | "green" | "amber" | "rose" | "violet";
}) {
  const t =
    tone === "green"  ? "bg-emerald-100 text-emerald-700" :
    tone === "amber"  ? "bg-amber-100   text-amber-700"   :
    tone === "rose"   ? "bg-rose-100    text-rose-700"    :
    tone === "violet" ? "bg-violet-100  text-violet-700"  :
                        "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]";
  return (
    <div className="card p-3.5 flex items-start gap-3">
      {Icon && (
        <span className={`h-9 w-9 rounded-xl grid place-items-center shrink-0 ${t}`}>
          <Icon size={16} />
        </span>
      )}
      <div className="min-w-0">
        <div className="text-caption muted font-semibold leading-tight">{label}</div>
        <div className="text-[22px] font-extrabold tabular leading-none mt-1">{value}</div>
        {caption && <div className="text-caption muted mt-1 truncate">{caption}</div>}
      </div>
    </div>
  );
}

// Stack of detail facts. Each is label + value.
export function DetailFacts({
  rows,
}: {
  rows: { label: string; value: ReactNode }[];
}) {
  return (
    <dl className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
      {rows.map((r, i) => (
        <div key={i} className="flex items-baseline gap-4 px-4 py-3">
          <dt className="text-caption muted font-bold uppercase tracking-wide w-[160px] shrink-0">
            {r.label}
          </dt>
          <dd className="text-body font-extrabold tracking-tight min-w-0">{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}
