"use client";

// PageHeader — premium full-width page chrome. The visual lead of
// every page. Identity chrome (message · notification · avatar) is
// rendered via the shared <IdentityCluster>.
//
// Built to match the multi-billion design reference: big extrabold
// title, single-line subtitle, right cluster of filter pills + search
// + bell + avatar. Sits below the dark MobileTopBar on mobile/tablet
// and serves as the primary chrome on desktop. One component, applied
// across every page so the read is consistent edge-to-edge.
//
// Visual contract:
//   • Title:    extrabold, 22-26px responsive
//   • Subtitle: 12.5-13px, soft gray, clamped width
//   • Filters:  pill chips with leading icon + chevron-down
//   • Search:   rounded input with magnifier, optional
//   • Bell:     NotificationBell (desktop only — MobileTopBar carries it on mobile/tablet)
//   • Avatar:   identity initials (desktop only — same reason)
//   • Back:     leading BackButton (auto-hides if no history + no fallback)
//
// Pages compose this with their own `filters` + `actions` rather than
// re-rolling chrome.

import { type ReactNode } from "react";
import {
  Search,
  ChevronDown,
  type LucideIcon,
} from "lucide-react";
import { BackButton } from "@/components/ui/BackButton";
import { IdentityCluster } from "@/components/shell/IdentityCluster";
import { Breadcrumbs } from "@/components/ui/Breadcrumbs";
import {
  useSetPageTitle,
} from "@/components/shell/PageTitleContext";
import { cn } from "@/lib/utils";

export type PageHeaderFilter = {
  Icon:  LucideIcon;
  label: string;
  /** Optional click handler. Without it the chip is a styled
   *  read-only token (matches the reference look). */
  onClick?: () => void;
};

export type PageHeaderProps = {
  title:     string;
  subtitle?: string;
  /** Decorative icon rendered after the title (small, inline). */
  Icon?:     LucideIcon;
  iconClassName?: string;
  /** Small node rendered inline next to the title — typically a count
   *  chip ("5 partners") or a status pill ("Live"). */
  titleBadge?: ReactNode;
  /** Date / period label surfaced to the MobileTopBar. */
  dateLabel?: string;
  /** Pill-shaped filter chips on the right side. */
  filters?:  PageHeaderFilter[];
  /** When set, a search input is rendered with this placeholder. */
  searchPlaceholder?: string;
  /** Custom actions appended *after* filters/search but before the
   *  bell + avatar. Use sparingly — most pages should rely on
   *  filters + search. */
  actions?:  ReactNode;
  /** Slot rendered *below* the title row, full-width. */
  meta?:     ReactNode;
  /** Opt out of the leading back button — set on top-level role
   *  landing pages where back has no meaningful destination. */
  noBack?:   boolean;
  /** Structural parent to navigate to if browser history is empty. */
  backFallbackHref?: string;
  /** Hide the desktop bell + avatar chrome (e.g. inside a tabbed shell
   *  that already provides them). Default: shown. */
  hideIdentityChrome?: boolean;
  /** Show the H1 title on mobile + tablet. Defaults to `false` because
   *  the dark MobileTopBar already carries the page title there, and
   *  repeating it in the light header wastes ~80px and reads as a
   *  duplicate. Set `true` for pages where the headline is meaningfully
   *  different from the system title (e.g. a personalised greeting). */
  showTitleOnMobile?: boolean;
  /** Override the trailing breadcrumb's label with a richer string
   *  (typically an entity name resolved server-side, e.g.
   *  "St. Mary's Primary" instead of the generic "School"). */
  breadcrumbTrailingLabel?: string;
  /** Hide auto-generated breadcrumbs on this page (rare — only set
   *  on top-level role landing pages where breadcrumbs are noise). */
  hideBreadcrumbs?: boolean;
  className?: string;
};

export function PageHeader({
  title,
  subtitle,
  Icon,
  iconClassName,
  titleBadge,
  dateLabel,
  filters,
  searchPlaceholder,
  actions,
  meta,
  noBack = false,
  backFallbackHref,
  hideIdentityChrome = false,
  showTitleOnMobile = false,
  breadcrumbTrailingLabel,
  hideBreadcrumbs = false,
  className,
}: PageHeaderProps) {
  // Identity is read by the AvatarMenu directly via useShellIdentity()
  // — no need to thread initials/color through this component anymore.
  useSetPageTitle(title, dateLabel);

  const hasRightCluster =
    (filters && filters.length > 0) ||
    Boolean(searchPlaceholder) ||
    Boolean(actions) ||
    !hideIdentityChrome;

  return (
    <header
      className={cn(
        // Generous, page-lead spacing. Below `lg` the dark MobileTopBar
        // is sticky above us so this surface starts the content area.
        "px-4 pt-4 pb-4 lg:px-6 lg:pt-6 lg:pb-5 bg-[var(--color-page)]",
        className,
      )}
    >
      {/* Breadcrumbs — only meaningful on routes deeper than one
          segment. The Breadcrumbs component auto-hides on top-level
          routes; `hideBreadcrumbs` lets pages opt out explicitly. */}
      {!hideBreadcrumbs && (
        <Breadcrumbs trailingLabel={breadcrumbTrailingLabel} className="mb-2" />
      )}

      <div className="flex items-start justify-between gap-4 flex-wrap">
        {/* Left: back button + title + subtitle */}
        <div className="flex items-start gap-3 min-w-0 flex-1">
          {!noBack && (
            <BackButton
              fallbackHref={backFallbackHref}
              className="mt-1 lg:mt-2"
              size="sm"
            />
          )}
          <div className="min-w-0">
            {/* H1 hidden below `lg` by default — the dark MobileTopBar
                already carries the page title there. Pages with a
                meaningfully-different headline (e.g. a greeting) opt
                back in via `showTitleOnMobile`. */}
            <h1
              className={cn(
                // Scale the title across desktop widths so long titles
                // (e.g. "Verified Impact Leaderboard") stay on one line
                // at lg and only swell at xl where horizontal room
                // returns. `text-balance` makes any remaining wrap
                // distribute evenly across two lines rather than
                // dropping a single short word to the second line.
                "text-[20px] lg:text-[22px] xl:text-[26px] font-extrabold tracking-tight items-center gap-2 leading-tight flex-wrap text-balance",
                showTitleOnMobile ? "inline-flex" : "hidden lg:inline-flex",
              )}
            >
              {title}
              {Icon && (
                <Icon
                  size={18}
                  className={iconClassName ?? "text-[var(--color-edify-muted)]"}
                />
              )}
              {titleBadge && (
                <span className="inline-flex items-center text-[12px]">{titleBadge}</span>
              )}
            </h1>
            {/* Mobile-only subtitle. On desktop the subtitle is hoisted
                BELOW the title+chrome row (see <p> after this flex) so
                a wide chrome cluster doesn't squeeze it into a narrow
                multi-line column under the title. */}
            {subtitle && (
              <p className="text-body text-secondary mt-1 leading-snug lg:hidden">
                {subtitle}
              </p>
            )}
          </div>
        </div>

        {/* Right cluster — filters + search + bell + avatar. Inline
            with the title at lg+ (≥1024px) so the chrome lives in the
            header bar, not in a second row inside the body. Wraps to
            its own row on tablet/mobile where horizontal room is tight.
            `ml-auto` keeps it anchored right at every breakpoint so the
            avatar/bell/message always sit at the far edge. */}
        {hasRightCluster && (
          <div className="flex items-center gap-2 flex-wrap shrink-0 w-full lg:w-auto lg:ml-auto">
            {filters?.map((f, i) => (
              <FilterPill key={`${f.label}-${i}`} {...f} />
            ))}

            {/* Search slot — *always* present on desktop, so every page
                gets the same premium chrome (filters + long search +
                identity right). When the page provides
                `searchPlaceholder`, that's used as the input
                placeholder. Otherwise the input falls back to a
                "Search everything…" affordance that opens the ⌘K
                command palette on focus — turns every page's search
                box into the global navigator. */}
            <div className="relative w-full sm:flex-1 sm:min-w-[200px] sm:max-w-[640px] order-last sm:order-none">
              <Search
                size={13}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none"
              />
              {searchPlaceholder ? (
                <>
                  <input
                    aria-label={searchPlaceholder}
                    placeholder={searchPlaceholder}
                    className="h-10 w-full pl-9 pr-14 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-card)] text-body text-[var(--color-edify-text)] placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 shadow-[0_1px_2px_rgba(15,23,32,0.04)]"
                  />
                  <kbd className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none hidden md:inline-flex items-center gap-0.5 h-5 px-1.5 rounded border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)] text-[10px] font-bold text-[var(--color-edify-muted)]">
                    ⌘K
                  </kbd>
                </>
              ) : (
                <button
                  type="button"
                  aria-label="Open command palette"
                  onClick={() => window.dispatchEvent(new CustomEvent("edify:open-command-palette"))}
                  className="h-10 w-full pl-9 pr-12 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-card)] text-body text-left text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 shadow-[0_1px_2px_rgba(15,23,32,0.04)] transition-colors flex items-center"
                >
                  Search everything…
                  <kbd className="absolute right-2 top-1/2 -translate-y-1/2 hidden md:inline-flex items-center gap-0.5 h-5 px-1.5 rounded border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)] text-[10px] font-bold text-[var(--color-edify-muted)]">
                    ⌘K
                  </kbd>
                </button>
              )}
            </div>

            {actions}

            {/* Desktop-only identity chrome. On mobile/tablet the dark
                MobileTopBar already carries bell + avatar; rendering
                them again here would duplicate.
                `ml-auto` pushes the cluster to the far-right edge of
                the row so message · bell · avatar always anchor right
                regardless of filter / search width. */}
            {!hideIdentityChrome && (
              <IdentityCluster variant="default" className="hidden lg:flex ml-auto" />
            )}
          </div>
        )}
      </div>

      {/* Desktop subtitle row — lives BELOW the title+chrome row so a
          wide right cluster (filters · search · Export · identity)
          doesn't squeeze the subtitle into a tall narrow column under
          the title. Mobile renders the subtitle inline under the
          title (see the <p className="lg:hidden"> above). */}
      {subtitle && (
        <p className="hidden lg:block text-[13px] text-secondary leading-snug mt-2 max-w-[760px]">
          {subtitle}
        </p>
      )}

      {meta && <div className="mt-3">{meta}</div>}
    </header>
  );
}

// ────────── FilterPill — the chip used inside PageHeader ──────────

function FilterPill({ Icon, label, onClick }: PageHeaderFilter) {
  const className =
    "inline-flex items-center gap-1.5 h-10 px-3.5 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-card)] text-body font-semibold text-[var(--color-edify-text)] shadow-[0_1px_2px_rgba(15,23,32,0.04)] hover:bg-[var(--color-edify-soft)]/40 transition-colors";
  const content = (
    <>
      <Icon size={14} className="text-[var(--color-edify-muted)]" />
      <span className="truncate max-w-[160px]">{label}</span>
      <ChevronDown size={13} className="text-[var(--color-edify-muted)]" />
    </>
  );
  return onClick ? (
    <button type="button" onClick={onClick} className={className}>
      {content}
    </button>
  ) : (
    <span className={className}>{content}</span>
  );
}
