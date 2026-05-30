"use client";

import Link from "next/link";
import { type ReactNode } from "react";
import { Bell, ChevronDown, Mail, Menu, Search, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

// Shared header used across dashboards, plans, reports, budget, and data
// intake. Replaces the 7 near-duplicate header components — Bell, search,
// avatar, and filter pill are no longer copy-pasted per module.
//
// Every slot is optional. Pass only what the screen needs.
//
//   <EntityHeader
//     title="My Targets"
//     subtitle="This Week's plan, route map, and progress"
//     roleLabel="CCEO"
//     actions={<Button>Schedule Activity</Button>}
//     filters={<MonthWeekFilter />}
//   />

export type Breadcrumb = { label: string; href?: string };

export function EntityHeader({
  title,
  subtitle,
  roleLabel,
  breadcrumbs,
  search,
  filters,
  actions,
  statusBadge,
  notifications,
  messages,
  profile,
  onMenu,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  /** e.g. "CCEO", "Country Director". Displayed as a small chip next to title. */
  roleLabel?: string;
  breadcrumbs?: Breadcrumb[];
  /** Pass a controlled <SearchInput/> or a placeholder string. */
  search?: ReactNode | { placeholder: string };
  /** Filter pills, period selector, etc. Rendered to the right of the title. */
  filters?: ReactNode;
  /** Primary + secondary buttons. Pinned far right. */
  actions?: ReactNode;
  /** Optional status pill rendered next to the title (e.g. "Live", "Draft"). */
  statusBadge?: ReactNode;
  /** Bell + count. Hidden if not provided. */
  notifications?: { count?: number; href?: string };
  /** Mail icon + unread count. Hidden if not provided. Defaults to /messages. */
  messages?: { count?: number; href?: string };
  /** Avatar / profile menu trigger. */
  profile?: { name: string; initials: string };
  /** Sidebar menu toggle (mobile). */
  onMenu?: () => void;
  className?: string;
}) {
  const searchEl =
    search && typeof search === "object" && "placeholder" in search
      ? <SearchInput placeholder={search.placeholder} />
      : (search as ReactNode | undefined);

  return (
    <header className={cn("px-4 sm:px-5 md:px-6 pt-4 pb-3", className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-[11px] muted mb-1.5">
          {breadcrumbs.map((b, i) => (
            <span key={i} className="flex items-center gap-1.5">
              {b.href ? (
                <Link href={b.href} className="hover:text-[var(--color-edify-primary)]">{b.label}</Link>
              ) : (
                <span className={i === breadcrumbs.length - 1 ? "text-[var(--color-edify-text)] font-semibold" : ""}>
                  {b.label}
                </span>
              )}
              {i < breadcrumbs.length - 1 && <ChevronRight size={10} className="opacity-60" />}
            </span>
          ))}
        </nav>
      )}

      {/* Title row + right-side cluster share one flex line. Subtitle is
          pulled out and rendered on its own row below so a long descriptive
          subtitle no longer pushes filters/search/bell/avatar onto a fourth
          line — they sit on the title row, aligned to its vertical center. */}
      <div className="flex items-center gap-3 flex-wrap">
        {onMenu && (
          <button
            type="button"
            onClick={onMenu}
            aria-label="Open menu"
            className="h-10 w-10 rounded-xl border border-[var(--color-edify-border)] bg-white grid place-items-center md:hidden shrink-0"
          >
            <Menu size={16} />
          </button>
        )}

        <div className="min-w-0 shrink-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="page-title">
              {title}
            </h1>
            {roleLabel && (
              <span className="inline-flex items-center px-2 py-[2px] rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] text-caption font-extrabold tracking-wide uppercase">
                {roleLabel}
              </span>
            )}
            {statusBadge}
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap justify-end ml-auto">
          {filters}
          {searchEl}

          {messages && (
            <Link
              href={messages.href ?? "/messages"}
              prefetch={false}
              aria-label={`Messages${messages.count ? ` (${messages.count} unread)` : ""}`}
              className="relative h-10 w-10 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center justify-center"
            >
              <Mail size={16} />
              {messages.count !== undefined && messages.count > 0 && (
                <span className="absolute -top-1 -right-1 bg-[var(--color-edify-primary)] text-white text-[10px] font-bold rounded-full px-[5px] py-[1px]">
                  {messages.count}
                </span>
              )}
            </Link>
          )}

          {notifications && (
            <Link
              href={notifications.href ?? "/notifications"}
              prefetch={false}
              aria-label={`Notifications${notifications.count ? ` (${notifications.count} unread)` : ""}`}
              className="relative h-10 w-10 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center justify-center"
            >
              <Bell size={16} />
              {notifications.count !== undefined && notifications.count > 0 && (
                <span className="absolute -top-1 -right-1 bg-[var(--color-danger)] text-white text-[10px] font-bold rounded-full px-[5px] py-[1px]">
                  {notifications.count}
                </span>
              )}
            </Link>
          )}

          {profile && (
            <button
              type="button"
              aria-label={`Open ${profile.name} profile menu`}
              className="flex items-center gap-1 pl-1"
            >
              <div className="w-9 h-9 rounded-full bg-[var(--color-edify-primary)] text-white font-bold flex items-center justify-center">
                {profile.initials}
              </div>
              <ChevronDown size={12} className="text-[var(--color-edify-muted)]" />
            </button>
          )}

          {actions}
        </div>
      </div>

      {subtitle && (
        <p className="text-body muted mt-1.5 max-w-[64ch] [text-wrap:balance]">
          {subtitle}
        </p>
      )}
    </header>
  );
}

function SearchInput({ placeholder }: { placeholder: string }) {
  return (
    <div className="relative">
      <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none" />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        className="pl-9 pr-3 h-10 w-[230px] rounded-xl border border-[var(--color-edify-border)] bg-white text-[13px] placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
      />
    </div>
  );
}
