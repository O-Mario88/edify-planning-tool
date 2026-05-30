"use client";

// MobileTopBar — premium dark chrome for mobile + tablet (<lg).
//
// One sticky, full-width dark bar that frames every page below `lg`.
// Mirrors the reference design: hamburger (light-on-dark) at the left,
// page title (bold white) next to it, optional date pill + bell +
// avatar at the right.
//
// Where the parts come from:
//   • Hamburger: useMobileDrawer (mounted via EdifySidebar) — its
//     fixed-position button gets visually replaced by ours; we hide
//     the original to avoid the double-burger. The drawer still opens
//     via setOpen so behaviour is unchanged.
//   • Title + date: PageTitleContext — pages register via
//     `useSetPageTitle(title, dateLabel)`.
//   • Bell: NotificationBell with `variant="today"` styling override
//     for the dark surface.
//   • Avatar: signed-in user's initials.
//
// Hidden at `lg` — desktop keeps the pinned sidebar + classic
// in-page PageHeader.

import { useState, useEffect } from "react";
import { Menu, ChevronDown, Search, type LucideIcon } from "lucide-react";
import { usePageTitle } from "@/components/shell/PageTitleContext";
import { AvatarMenu } from "@/components/shell/AvatarMenu";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { MessageBell } from "@/components/messages/MessageBell";
import { cn } from "@/lib/utils";

export function MobileTopBar({
  // Legacy props — identity now flows through PageTitleContext via
  // useShellIdentity(); these are accepted for backward compatibility
  // and ignored.
  userInitials: _legacyInitials,
  userColor:    _legacyColor,
}: {
  userInitials?: string;
  userColor?:    string;
} = {}) {
  void _legacyInitials;
  void _legacyColor;
  const { title, dateLabel } = usePageTitle();

  // The hamburger trigger in useMobileDrawer is mounted by the
  // sidebar component as a `fixed` button at top-left. We render our
  // own visually-aligned hamburger here that forwards the click via
  // a button event, then hide the original so users see only one.
  useEffect(() => {
    const orig = document.querySelector<HTMLButtonElement>(
      'button[aria-label="Open menu"]',
    );
    if (orig) orig.classList.add("!hidden");
    return () => {
      const o = document.querySelector<HTMLButtonElement>(
        'button[aria-label="Open menu"]',
      );
      if (o) o.classList.remove("!hidden");
    };
  }, []);

  function openDrawer() {
    // Forward the click to the original hamburger so the drawer's
    // state machine stays in one place.
    document
      .querySelector<HTMLButtonElement>('button[aria-label="Open menu"]')
      ?.click();
  }

  // Scroll-shadow effect — the top bar grows a stronger bottom shadow
  // once the page has scrolled, signalling "more content above". A
  // small but defining piece of premium mobile chrome (iOS, Linear,
  // Things all do this). Uses a passive listener so it never blocks
  // the scroll itself.
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        // Sticky so it stays in thumb reach at any scroll position.
        // `lg:hidden` keeps it mobile + tablet only — desktop uses
        // the pinned sidebar + in-page PageHeader.
        "lg:hidden sticky top-0 z-30",
        "flex items-center gap-2 px-3 sm:px-4 h-14",
        // Premium gradient instead of a flat dark fill — a subtle
        // top→bottom tint plus a warm radial accent in the top-right
        // gives the chrome material the same depth the .hero-mobile
        // surface has. The shadow strengthens on scroll.
        "bg-gradient-to-b from-[#15263a] via-[#0e1c2c] to-[#0a1623] text-white",
        "border-b border-white/10",
        "transition-shadow duration-300",
        scrolled
          ? "shadow-[0_8px_24px_-8px_rgba(15,23,32,0.55)]"
          : "shadow-[0_2px_8px_-4px_rgba(15,23,32,0.30)]",
      )}
    >
      <IconShellButton onClick={openDrawer} ariaLabel="Open menu" Icon={Menu} />

      {/* Title — auto-shrinks on narrow viewports so common page names
          (Annual Budget Breakdown, Partner Delivery Command Center)
          fit without ellipsis. Falls back to truncate on extremes. */}
      <h1
        className="font-extrabold tracking-tight text-white truncate flex-1 min-w-0"
        style={{ fontSize: "clamp(13.5px, 4.1vw, 16.5px)", lineHeight: 1.15 }}
      >
        {title}
      </h1>

      {dateLabel && (
        <button
          type="button"
          className="hidden xs:inline-flex items-center gap-1.5 h-8 px-3 rounded-full border border-white/15 bg-white/5 text-white text-[12px] font-semibold shrink-0 max-w-[160px] truncate"
        >
          <span className="truncate">{dateLabel}</span>
          <ChevronDown size={12} className="text-white/60 shrink-0" />
        </button>
      )}

      {/* Magnifier opens the universal ⌘K command palette on mobile —
          dispatches a custom event the CommandPalette listens for so
          we don't have to thread state across the shell. Tightened
          to h-9 w-9 (36px) so the title gets more breathing room. */}
      <button
        type="button"
        aria-label="Search"
        onClick={() => window.dispatchEvent(new CustomEvent("edify:open-command-palette"))}
        className="grid place-items-center h-9 w-9 rounded-xl text-white hover:bg-white/10 active:bg-white/[0.14] transition-colors shrink-0 pressable"
      >
        <Search size={16} />
      </button>

      {/* Messages — completes the canonical chrome cluster (avatar +
          bell + message + search) on every authenticated mobile page.
          Hidden on the narrowest viewports (<sm) to keep the title
          breathable; appears at 360px+ where there's room.  Opens the
          floating MessageDrawer instead of navigating away. */}
      <div className="hidden sm:block">
        <MessageBell variant="dark" />
      </div>

      <NotificationBell variant="dark" />

      <AvatarMenu variant="dark" />
    </header>
  );
}

// ────────── Subcomponents tuned for the dark surface ──────────

function IconShellButton({
  onClick,
  ariaLabel,
  Icon,
}: {
  onClick: () => void;
  ariaLabel: string;
  Icon: LucideIcon;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className="grid place-items-center h-9 w-9 rounded-xl bg-white/[0.06] border border-white/[0.12] text-white hover:bg-white/[0.12] active:bg-white/[0.16] transition-colors shrink-0 pressable"
    >
      <Icon size={17} />
    </button>
  );
}

// DarkBell removed — the canonical NotificationBell + MessageBell
// (with `variant="dark"`) now handle the dark-topbar surface, opening
// the floating drawers instead of a local popover.
// UserAvatar removed — superseded by AvatarMenu which carries the
// same trigger styling plus the dropdown menu for profile actions.
