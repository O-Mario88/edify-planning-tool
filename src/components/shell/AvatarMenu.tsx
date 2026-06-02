"use client";

// AvatarMenu — the action menu behind the user-initials button.
//
// Before this lived, clicking the avatar did nothing on every page —
// arguably the most identifiable element on screen had zero
// affordance. Tapping it now opens a clean popover with the standard
// account menu every premium app ships:
//
//   • Profile          — /profile detail page
//   • Settings         — /settings
//   • Switch role      — opens the role picker (demo build)
//   • Sign Out         — /api/auth/logout
//
// Two visual variants:
//   • `default` — light pill matching the desktop PageHeader chrome
//   • `dark`    — flat circular avatar matching the dark MobileTopBar
//
// Mounted independently in MobileTopBar and PageHeader so each chrome
// surface gets the same menu without prop-drilling state.

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  User as UserIcon,
  Settings as SettingsIcon,
  UserCog,
  LogOut,
  Sun,
  Moon,
  Sparkles,
  Monitor,
  type LucideIcon,
} from "lucide-react";
import { useShellIdentity } from "@/components/shell/PageTitleContext";
import { useTheme, type ThemeMode } from "@/components/theme/ThemeProvider";
import { cn } from "@/lib/utils";

export type AvatarMenuVariant = "default" | "dark";

export function AvatarMenu({ variant = "default" }: { variant?: AvatarMenuVariant }) {
  const { name, initials, color } = useShellIdentity();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click + Esc.
  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const trigger =
    variant === "dark"
      ? "grid place-items-center h-9 w-9 rounded-full ring-2 ring-white/20 text-white font-extrabold text-[12px] shrink-0"
      : "grid place-items-center h-10 w-10 rounded-full text-white font-extrabold text-[12px] shrink-0 shadow-[0_1px_2px_rgba(15,23,32,0.08)]";

  return (
    <div ref={wrapperRef} className="relative shrink-0">
      <button
        type="button"
        aria-label={`Profile menu for ${name}`}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((v) => !v)}
        className={trigger}
        style={{ background: color }}
      >
        {initials}
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account menu"
          className="premium-popover absolute right-0 top-[calc(100%+8px)] w-[280px] rounded-2xl text-[var(--color-edify-text)] shadow-[0_18px_44px_-16px_rgba(0,0,0,0.4)] overflow-hidden z-50"
        >
          {/* Identity header */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-edify-divider)]">
            <span
              className="grid place-items-center h-10 w-10 rounded-full text-white font-extrabold text-[13px] shrink-0"
              style={{ background: color }}
            >
              {initials}
            </span>
            <div className="min-w-0">
              <div className="text-[13px] font-extrabold tracking-tight truncate">{name}</div>
              <div className="text-[11px] text-[var(--color-edify-muted)]">Signed in</div>
            </div>
          </div>

          {/* Menu items */}
          <div className="py-1.5">
            <MenuLink Icon={UserIcon}     label="Profile"     href="/profile"  onClose={() => setOpen(false)} />
            <MenuLink Icon={SettingsIcon} label="Settings"    href="/settings" onClose={() => setOpen(false)} />
            <RoleSwitchButton onClose={() => setOpen(false)} />
          </div>

          {/* Appearance — segmented control. Lives in the same menu so
              users find it where they expect (Apple, Linear, Cron all
              put theme in the avatar menu). */}
          <div className="border-t border-[var(--color-edify-divider)] px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-[0.08em] font-extrabold text-[var(--color-edify-muted)] mb-1.5 px-1">
              Appearance
            </div>
            <ThemeToggle />
          </div>

          {/* Sign Out */}
          <div className="border-t border-[var(--color-edify-divider)] py-1.5">
            <form action="/api/auth/logout" method="post">
              <button
                type="submit"
                className="w-full flex items-center gap-3 px-4 py-2 text-body font-semibold text-[#b42318] hover:bg-rose-50/40 dark:hover:bg-rose-500/10"
              >
                <LogOut size={14} />
                Sign Out
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

// ────────── Sub-items ──────────

export function MenuLink({
  Icon,
  label,
  href,
  onClose,
}: {
  Icon: LucideIcon;
  label: string;
  href: string;
  onClose: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onClose}
      className="flex items-center gap-3 px-4 py-2 text-body font-semibold text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]"
    >
      <Icon size={14} className="text-[var(--color-edify-muted)]" />
      {label}
    </Link>
  );
}

export function RoleSwitchButton({ onClose }: { onClose: () => void }) {
  // The full role picker is a separate component (RoleSwitcher) used
  // by the floating chip at the bottom-right. We trigger it by
  // dispatching a custom event the picker listens for, so we don't
  // re-implement its state machine here.
  return (
    <button
      type="button"
      onClick={() => {
        window.dispatchEvent(new CustomEvent("edify:open-role-switcher"));
        onClose();
      }}
      className="w-full flex items-center justify-between gap-3 px-4 py-2 text-body font-semibold text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]"
    >
      <span className="inline-flex items-center gap-3">
        <UserCog size={14} className="text-[var(--color-edify-muted)]" />
        Switch role
      </span>
      <span className="text-caption text-[var(--color-edify-muted)]">Demo</span>
    </button>
  );
}

// Premium segmented control — three options, each a fully-styled
// button. The active option fills with the card-elevated surface so
// the rail itself signals "this is what's in effect right now". Pure
// keyboard-accessible (real <button>s in a role="radiogroup").
export function ThemeToggle() {
  const { mode, setMode } = useTheme();
  const options: Array<{ value: ThemeMode; label: string; Icon: LucideIcon }> = [
    { value: "light",  label: "Light",  Icon: Sun      },
    { value: "dark",   label: "Dark",   Icon: Moon     },
    { value: "glass",  label: "Glass",  Icon: Sparkles },
    { value: "system", label: "System", Icon: Monitor  },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="grid grid-cols-4 gap-1 p-1 rounded-xl bg-[var(--color-edify-soft)] border border-[var(--color-edify-divider)]"
    >
      {options.map((o) => {
        const active = mode === o.value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => setMode(o.value)}
            className={cn(
              "flex flex-col items-center justify-center gap-1 h-14 rounded-lg text-[10px] font-extrabold transition-all duration-200",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-card)]",
              active
                ? "bg-[var(--color-card)] text-[var(--color-edify-text)] shadow-[0_2px_8px_-2px_rgba(0,0,0,0.18),inset_0_1px_0_var(--color-card-highlight)] border border-[var(--color-edify-border)]"
                : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)] active:scale-[0.97]",
            )}
          >
            <o.Icon size={15} strokeWidth={active ? 2.5 : 2} />
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
