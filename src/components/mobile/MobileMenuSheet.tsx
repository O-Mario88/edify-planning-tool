"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Menu,
  X,
  LayoutDashboard,
  ClipboardList,
  Building2,
  Activity,
  Star,
  Map,
  Target,
  Trophy,
  Brain,
  CalendarRange,
  Sparkles,
  Wallet,
  Eye,
  ShieldCheck,
  Database,
  FileText,
  Settings,
  ExternalLink,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { SignOutButton } from "@/components/auth/SignOutButton";
import { ROLE_REDIRECT, type EdifyRole } from "@/lib/auth-public";

// Self-contained mobile menu drawer. Renders its own hamburger trigger
// (styled to match the dark mobile-view headers) and slides in a left
// drawer carrying the same menu sections as EdifySidebar. Used inside
// HomeView and the other mobile-view headers so users can navigate
// between dashboards without touching the bottom nav.

type MenuItem = { label: string; href: string; Icon: LucideIcon };
type MenuSection = { label: string; items: MenuItem[] };

function buildSections(role?: EdifyRole): MenuSection[] {
  const dashboardHref = role ? ROLE_REDIRECT[role] : "/dashboards/cpl";
  return [
  {
    label: "Workspace",
    items: [
      { label: "Dashboard",       href: dashboardHref,       Icon: LayoutDashboard },
      { label: "My Work Plan",    href: "/dashboards/cceo",  Icon: ClipboardList },
      { label: "Planning Tool",   href: "/planning",         Icon: ClipboardList },
      { label: "Routes",          href: "/route",          Icon: Map },
    ],
  },
  {
    label: "Schools & SSA",
    items: [
      { label: "Schools",         href: "/schools",          Icon: Building2 },
      { label: "SSA Performance", href: "/ssa",              Icon: Activity },
      { label: "Core Schools",    href: "/core-schools",     Icon: Star },
      { label: "Daily Field Debrief", href: "/field-intelligence", Icon: Brain },
    ],
  },
  {
    label: "Performance",
    items: [
      { label: "Team Targets",    href: "/team-targets",     Icon: Target },
      { label: "Leaderboard",     href: "/leaderboard",      Icon: Trophy },
      { label: "Special Projects", href: "/special-projects", Icon: Sparkles },
    ],
  },
  {
    label: "Operations",
    items: [
      { label: "Leave & Holidays", href: "/leave",           Icon: CalendarRange },
      { label: "Salesforce Queue", href: "/queue",         Icon: Database },
      { label: "Finance",          href: "/dashboards/accountant", Icon: Wallet },
      { label: "Monitoring",       href: "/dashboards/impact",     Icon: Eye },
    ],
  },
  {
    label: "Account",
    items: [
      { label: "Reports",          href: "/reports",         Icon: FileText },
      { label: "Administration",   href: "#admin",           Icon: ShieldCheck },
      { label: "Settings",         href: "/settings",        Icon: Settings },
    ],
  },
  ];
}

export function MobileMenuSheet({
  variant = "dark",
  role,
}: {
  /** "dark" matches the dark hero header; "light" matches the light sub-page header. */
  variant?: "dark" | "light";
  role?: EdifyRole;
}) {
  const sections = buildSections(role);
  const desktopHref = role ? ROLE_REDIRECT[role] : "/dashboards/cpl";
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // We close the drawer inline on each <Link onClick> instead of an
  // effect that watches `pathname` — the React compiler flags setState
  // inside route-watching effects as a cascading-render risk.

  // Lock body scroll while open + close on Escape
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const triggerClass =
    variant === "dark"
      ? "h-9 w-9 grid place-items-center rounded-md text-white hover:bg-white/[.06]"
      : "h-9 w-9 grid place-items-center rounded-md text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60";

  return (
    <>
      {/* Trigger — placed inline by the parent header */}
      <button
        type="button"
        aria-label="Open menu"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className={triggerClass}
      >
        <Menu size={variant === "dark" ? 20 : 18} />
      </button>

      {/* Backdrop */}
      {open && (
        <div
          role="presentation"
          onClick={() => setOpen(false)}
          className="fixed inset-0 bg-black/55 backdrop-blur-sm z-50"
        />
      )}

      {/* Drawer */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 w-[280px] max-w-[85vw] z-50 transform transition-transform duration-200 sidebar-bg text-white flex flex-col",
          open ? "translate-x-0 shadow-2xl" : "-translate-x-full",
        )}
      >
        {/* Brand header */}
        <div className="flex items-center gap-3 px-5 pt-4 pb-3 border-b border-white/10">
          <div className="w-9 h-9 rounded-xl bg-white grid place-items-center shadow shrink-0">
            <Image src="/edify-logo.png" alt="Edify" width={28} height={11} className="object-contain" style={{ width: "auto", height: "auto" }} priority />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[16px] font-extrabold tracking-tight leading-tight">EDIFY</div>
            <div className="text-caption tracking-wide text-white/60 font-medium leading-tight truncate">
              Field Operations
            </div>
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close menu"
            className="h-8 w-8 rounded-md border border-white/15 grid place-items-center text-white/85 hover:bg-white/10"
          >
            <X size={14} />
          </button>
        </div>

        {/* Menu */}
        <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-3 text-[13px]">
          {sections.map((section) => (
            <div key={section.label}>
              <div className="text-[10px] font-bold uppercase tracking-wider text-white/45 px-3 mb-1">
                {section.label}
              </div>
              <div className="space-y-[2px]">
                {section.items.map((m) => {
                  const target = m.href.split("#")[0];
                  const active =
                    pathname === target ||
                    (target.length > 1 && pathname.startsWith(target + "/"));
                  return (
                    <Link
                      key={m.label}
                      href={m.href}
                      onClick={() => setOpen(false)}
                      className={cn(
                        "menu-item flex items-center gap-3 px-3 py-2.5 rounded-lg",
                        active && "active",
                      )}
                    >
                      <span className="menu-icon">
                        <m.Icon size={14} />
                      </span>
                      <span className="truncate">{m.label}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Sign-Out */}
        <div className="p-3 border-t border-white/10 space-y-2">
          <Link
            href={desktopHref}
            className="w-full h-9 rounded-md border border-white/15 text-[12px] font-semibold text-white/90 hover:bg-white/10 flex items-center justify-center gap-1.5"
          >
            Open desktop view
            <ExternalLink size={11} />
          </Link>
          <SignOutButton variant="dark" />
        </div>
      </aside>
    </>
  );
}
