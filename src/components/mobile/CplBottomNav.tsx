"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  Users,
  ClipboardCheck,
  Compass,
  MoreHorizontal,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Country Program Lead bottom nav. Five evenly-spaced tabs (no center FAB)
// because the lead's primary actions are review/approve, not field tracking.

type Tab = {
  key: string;
  label: string;
  href: string;
  Icon: LucideIcon;
  match: string[];
};

const TABS: Tab[] = [
  { key: "home",      label: "Home",      href: "/dashboards/cpl",  Icon: Home,            match: ["/dashboards/cpl"] },
  { key: "field",     label: "My Field",  href: "/today",            Icon: Compass,         match: ["/today", "/my-plan", "/plans/new", "/field-intelligence"] },
  { key: "team",      label: "Team",      href: "/my-team",          Icon: Users,           match: ["/my-team"] },
  { key: "approvals", label: "Approvals", href: "/approvals",        Icon: ClipboardCheck,  match: ["/approvals"] },
  { key: "more",      label: "More",      href: "/more",             Icon: MoreHorizontal,  match: ["/more", "/queue", "/my-targets"] },
];

export function CplBottomNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Country Program Lead nav"
      className="fixed bottom-0 left-0 right-0 z-30 md:hidden bg-white border-t border-[var(--color-edify-border)] pb-[env(safe-area-inset-bottom)]"
    >
      <div className="grid grid-cols-5 h-16">
        {TABS.map((tab) => {
          const active = tab.match.some((p) => pathname === p || pathname.startsWith(p + "/"));
          const Icon = tab.Icon;
          return (
            <Link
              key={tab.key}
              href={tab.href}
              className={cn(
                "flex flex-col items-center justify-center gap-0.5 text-caption font-semibold relative",
                active ? "text-[var(--color-edify-primary)]" : "text-[var(--color-edify-muted)]",
              )}
            >
              <Icon size={20} />
              {tab.label}
              {active && (
                <span className="absolute top-0 left-1/2 -translate-x-1/2 w-8 h-[3px] rounded-full bg-[var(--color-edify-primary)]" />
              )}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
