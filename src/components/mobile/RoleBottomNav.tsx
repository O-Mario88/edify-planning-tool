"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  ClipboardList,
  Building2,
  MoreHorizontal,
  Plus,
  Users,
  ClipboardCheck,
  Target,
  Wallet,
  Globe,
  Receipt,
  Activity,
  ShieldCheck,
  Compass,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { EdifyRole } from "@/lib/auth-public";
import { useRole } from "@/components/auth/SessionContext";

// Role-aware mobile bottom nav. One component, one nav contract per role,
// no duplicated tab arrays scattered across views. The CCEO + CPL tab sets
// match the existing dedicated bottom-nav components; every other role
// gets a sensible default surfaced from their dashboard verbs.

type Tab = {
  key: string;
  label: string;
  href: string;
  Icon: LucideIcon;
  match: string[];
};

type Layout =
  | { kind: "fab"; tabs: [Tab, Tab, null, Tab, Tab]; fab: { href: string; label: string } }
  | { kind: "flat"; tabs: Tab[] };

const CCEO_LAYOUT: Layout = {
  kind: "fab",
  tabs: [
    { key: "home",         label: "Home",         href: "/dashboards/cceo", Icon: Home,        match: ["/dashboards/cceo", "/work-plan", "/dashboard"] },
    { key: "plan",         label: "Plan",         href: "/my-plan",      Icon: ClipboardList,  match: ["/my-plan", "/planning"] },
    null,
    // Core Schools — opens the executive Core School Dashboard, which
    // surfaces the full list of Core Schools through its Best Performing
    // + Needing Attention tables and the package funnel.
    { key: "core_schools", label: "Core Schools", href: "/core-schools", Icon: Building2,      match: ["/core-schools"] },
    { key: "more",         label: "More",         href: "/more",         Icon: MoreHorizontal, match: ["/more", "/today", "/queue", "/schools"] },
  ],
  fab: { href: "/plans/new", label: "Create or Edit Plan" },
};

const CPL_LAYOUT: Layout = {
  kind: "flat",
  tabs: [
    { key: "home",      label: "Home",      href: "/dashboards/cpl", Icon: Home,            match: ["/dashboards/cpl"] },
    { key: "field",     label: "My Field",  href: "/today",          Icon: Compass,         match: ["/today", "/my-plan", "/plans/new", "/field-intelligence", "/my-targets"] },
    { key: "team",      label: "Team",      href: "/my-team",        Icon: Users,           match: ["/my-team"] },
    { key: "approvals", label: "Approvals", href: "/approvals",      Icon: ClipboardCheck,  match: ["/approvals"] },
    { key: "more",      label: "More",      href: "/more",           Icon: MoreHorizontal,  match: ["/more", "/queue"] },
  ],
};

const DIRECTOR_LAYOUT: Layout = {
  kind: "flat",
  tabs: [
    { key: "home",     label: "Home",     href: "/dashboards/director", Icon: Home,           match: ["/dashboards/director"] },
    { key: "schools",  label: "Schools",  href: "/schools",             Icon: Building2,      match: ["/schools"] },
    { key: "ssa",      label: "SSA",      href: "/ssa",                 Icon: Activity,       match: ["/ssa"] },
    { key: "team",     label: "Team",     href: "/team-targets",        Icon: Users,          match: ["/team-targets"] },
    { key: "more",     label: "More",     href: "/more",              Icon: MoreHorizontal, match: ["/more"] },
  ],
};

const RVP_LAYOUT: Layout = {
  kind: "flat",
  tabs: [
    { key: "home",     label: "Home",     href: "/dashboards/rvp",  Icon: Home,           match: ["/dashboards/rvp"] },
    { key: "region",   label: "Region",   href: "/special-projects",Icon: Globe,          match: ["/special-projects"] },
    { key: "team",     label: "Team",     href: "/team-targets",    Icon: Users,          match: ["/team-targets"] },
    { key: "leaders",  label: "Leaders",  href: "/leaderboard",     Icon: Target,         match: ["/leaderboard"] },
    { key: "more",     label: "More",     href: "/more",          Icon: MoreHorizontal, match: ["/more"] },
  ],
};

const ACCOUNTANT_LAYOUT: Layout = {
  kind: "flat",
  tabs: [
    { key: "home",     label: "Home",     href: "/dashboards/accountant", Icon: Home,           match: ["/dashboards/accountant"] },
    { key: "requests", label: "Requests", href: "/dashboards/accountant", Icon: Receipt,        match: ["/dashboards/accountant#requests"] },
    { key: "disburse", label: "Disburse", href: "/dashboards/accountant", Icon: Wallet,         match: ["/dashboards/accountant#disburse"] },
    { key: "reports",  label: "Reports",  href: "/reports",                Icon: ClipboardList,  match: ["/reports"] },
    { key: "more",     label: "More",     href: "/more",                 Icon: MoreHorizontal, match: ["/more"] },
  ],
};

const IMPACT_LAYOUT: Layout = {
  kind: "flat",
  tabs: [
    { key: "home",     label: "Home",     href: "/dashboards/impact", Icon: Home,           match: ["/dashboards/impact"] },
    { key: "queue",    label: "Queue",    href: "/queue",            Icon: ShieldCheck,    match: ["/queue"] },
    { key: "schools",  label: "Schools",  href: "/schools",            Icon: Building2,      match: ["/schools"] },
    { key: "ssa",      label: "SSA",      href: "/ssa",                Icon: Activity,       match: ["/ssa"] },
    { key: "more",     label: "More",     href: "/more",             Icon: MoreHorizontal, match: ["/more"] },
  ],
};

const HR_LAYOUT: Layout = {
  kind: "flat",
  tabs: [
    { key: "home",     label: "Home",     href: "/team-targets",    Icon: Home,           match: ["/team-targets"] },
    { key: "leaders",  label: "Leaders",  href: "/leaderboard",     Icon: Target,         match: ["/leaderboard"] },
    { key: "field",    label: "Field",    href: "/field-intelligence", Icon: Activity,    match: ["/field-intelligence"] },
    { key: "leave",    label: "Leave",    href: "/leave",           Icon: ClipboardList,  match: ["/leave"] },
    { key: "more",     label: "More",     href: "/more",          Icon: MoreHorizontal, match: ["/more"] },
  ],
};

const LAYOUT_BY_ROLE: Record<EdifyRole, Layout> = {
  CCEO:                CCEO_LAYOUT,
  CountryProgramLead:  CPL_LAYOUT,
  CountryDirector:     DIRECTOR_LAYOUT,
  RVP:                 RVP_LAYOUT,
  ProgramAccountant:   ACCOUNTANT_LAYOUT,
  ImpactAssessment:    IMPACT_LAYOUT,
  HumanResource:       HR_LAYOUT,
  Admin:               DIRECTOR_LAYOUT,
  // Partner sub-types share the CCEO field-officer layout — the
  // bottom nav is centred on Home / activities / submission, which
  // matches partner field workflow more closely than office layouts.
  PartnerAdmin:        CCEO_LAYOUT,
  PartnerFieldOfficer: CCEO_LAYOUT,
  PartnerViewer:       CCEO_LAYOUT,
};

export function RoleBottomNav({ role: roleProp }: { role?: EdifyRole } = {}) {
  // Fall back to the cookie-resolved session role when no explicit prop is
  // passed. This lets every mobile view drop in <MobileBottomNav /> without
  // threading the role through props.
  const sessionRole = useRole();
  const role = roleProp ?? sessionRole;
  const layout = LAYOUT_BY_ROLE[role];
  const pathname = usePathname();
  const activeColor    = role === "CCEO" ? "text-emerald-600"    : "text-[var(--color-edify-primary)]";
  const activeIconBg   = role === "CCEO" ? "bg-emerald-50"        : "bg-[var(--color-edify-soft)]";
  const activeIconRing = role === "CCEO" ? "ring-emerald-100"     : "ring-[var(--color-edify-divider)]";

  return (
    <nav
      aria-label="Primary"
      className="fixed bottom-0 left-0 right-0 z-30 md:hidden bg-[var(--color-card)]/95 backdrop-blur-md border-t border-[var(--color-edify-border)] pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_24px_-12px_rgba(0,0,0,0.4)]"
    >
      <div className={cn("relative grid h-16", layout.kind === "fab" ? "grid-cols-5" : "grid-cols-5")}>
        {layout.tabs.map((tab, i) => {
          if (tab === null) return <span key={`fab-${i}`} />;
          const Icon = tab.Icon;
          const active = tab.match.some((p) => pathname === p || pathname.startsWith(p + "/"));
          return (
            <Link
              key={tab.key}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex flex-col items-center justify-center gap-0.5 text-[10px] font-extrabold tracking-tight relative pressable",
                "transition-colors duration-200",
                active ? activeColor : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]",
              )}
            >
              {/* Icon sits inside a pill that fades in on active —
                  the affordance an iOS/Android user expects.
                  Inactive icons stay clean for visual quiet. */}
              <span
                className={cn(
                  "grid place-items-center h-8 w-12 rounded-full transition-all duration-300 ease-out",
                  active
                    ? cn(activeIconBg, "ring-1", activeIconRing, "scale-100")
                    : "scale-95",
                )}
              >
                <Icon size={18} strokeWidth={active ? 2.5 : 2} />
              </span>
              <span className={cn(
                "transition-all duration-200",
                active ? "opacity-100 translate-y-0" : "opacity-80 translate-y-px",
              )}>
                {tab.label}
              </span>
            </Link>
          );
        })}

        {layout.kind === "fab" && (
          <Link
            href={layout.fab.href}
            aria-label={layout.fab.label}
            className="absolute left-1/2 -translate-x-1/2 -top-5 h-14 w-14 rounded-full bg-gradient-to-b from-emerald-400 to-emerald-600 hover:from-emerald-300 hover:to-emerald-500 text-white shadow-[0_10px_24px_-6px_rgba(16,185,129,0.5),0_4px_8px_-2px_rgba(16,185,129,0.3)] grid place-items-center pressable ring-4 ring-white"
          >
            <Plus size={22} strokeWidth={2.5} />
          </Link>
        )}
      </div>
    </nav>
  );
}
