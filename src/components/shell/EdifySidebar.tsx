"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import {
  LayoutDashboard,
  ClipboardList,
  Building2,
  Activity,
  Star,
  Map,
  Target,
  Trophy,
  TrendingUp,
  Brain,
  CalendarRange,
  Sparkles,
  ShieldCheck,
  FileText,
  Settings,
  Database,
  ExternalLink,
  CalendarCheck,
  Award,
  AlertOctagon,
  BarChart3,
  MapPin,
  MessageSquare,
  BookOpen,
  UserCog,
  Handshake,
  GraduationCap,
  Footprints,
  HelpCircle,
  ClipboardCheck as ClipboardCheckIcon,
  Calculator,
  Wallet,
  Send,
  Globe,
  Upload,
  PanelLeftClose,
  type LucideIcon,
} from "lucide-react";
import { cceoSidebarItems, cceoUser as cceoUserMock } from "@/lib/cceo-mock";
import { ROLE_REDIRECT, type EdifyRole as PublicEdifyRole } from "@/lib/auth-public";
import { cn } from "@/lib/utils";
import { SignOutButton } from "@/components/auth/SignOutButton";
import { useMobileDrawer } from "@/components/auth/MobileDrawerShell";

// ────────── Role-aware Dashboard target ──────────
//
// One sidebar for every dashboard. The only per-role difference is where
// "Dashboard" points; the rest is identical. The role → route map is
// sourced from auth-public so the redirect, login form, and sidebar
// stay in lockstep.

export type EdifyRole = PublicEdifyRole;

const SUBTITLE_BY_ROLE: Record<EdifyRole, string> = {
  CCEO:                "Field Operations Console",
  CountryProgramLead:  "Country Program Lead Console",
  CountryDirector:     "Country Director Console",
  RVP:                 "Regional VP Console",
  ProgramAccountant:   "Finance Console",
  ImpactAssessment:    "M&E / Impact Console",
  HumanResource:       "People & Performance",
  Admin:               "Admin Console",
  PartnerAdmin:        "Partner Command Center",
  PartnerFieldOfficer: "Partner Command Center",
  PartnerViewer:       "Partner Command Center",
};

// ────────── Menu structure (sectioned for clarity) ──────────

type MenuItem = { label: string; href: string; Icon: LucideIcon; badge?: number };
type MenuSection = { label: string; items: MenuItem[] };

// CCEO sidebar mirrors the dashboard reference (Dashboard / Core Schools /
// SSA Performance / Service Package / …). Items are flat (no section
// labels) to match the design.
const CCEO_ICON: Record<string, LucideIcon> = {
  layoutDashboard: LayoutDashboard,
  school:          Star,
  activity:        Activity,
  calendarCheck:   CalendarCheck,
  calendarRange:   CalendarRange,
  award:           Award,
  alertOctagon:    AlertOctagon,
  trophy:          Trophy,
  target:          Target,
  clipboardList:   ClipboardList,
  fileText:        FileText,
  barChart:        BarChart3,
  mapPin:          MapPin,
  messageSquare:   MessageSquare,
  bookOpen:        BookOpen,
  wallet:          Wallet,
};

function buildCceoMenu(): MenuSection[] {
  // Group items by their `section` field while preserving array order
  // inside each section. Matches the labelled-section rhythm every
  // other role's sidebar uses (My Work / Schools / Activity / Insights
  // / Account), so a CCEO opening the app reads the same skeleton as
  // a Country Director or Program Lead.
  const order: { label: string; key: string }[] = [
    { label: "My Work",  key: "My Work"  },
    { label: "Schools",  key: "Schools"  },
    { label: "Activity", key: "Activity" },
    { label: "Insights", key: "Insights" },
    { label: "Account",  key: "Account"  },
  ];
  return order
    .map(({ label, key }) => ({
      label,
      items: cceoSidebarItems
        .filter((it) => it.section === key)
        .map((it) => ({
          label: it.label,
          href:  it.href,
          Icon:  CCEO_ICON[it.icon] ?? LayoutDashboard,
          badge: it.badge,
        })),
    }))
    .filter((s) => s.items.length > 0);
}

// ────────── RVP menu (Regional VP specific) ──────────
//
// RVPs work above country directors — they approve cross-country
// fund requests, set quarterly targets across the region, monitor
// annual plans and budgets, and review forecasts. They DO NOT see:
//   • Schools / SSA / Visits / Trainings (CCEO + PL field activity)
//   • My Plan / My Targets / Routes / Calendar (personal field tools)
//   • Approvals (queue of team / country approvals) → replaced by
//     the regional Fund Approval surface below
//   • Salesforce Queue / Data Intake / Cost Settings (Accountant / IA)
//   • Staff / HR queues
//
// The RVP menu mirrors the design reference exactly: a "Monitoring"
// section (Dashboard, Country Overview, Fund Approval), a "Planning"
// section (Annual Plan, Quarterly Targets, Budgets & Funds), an
// "Insights" section (Analytics, Reports, Forecasts), and an "Admin"
// section (Users & Access, Settings).
function buildRvpMenu(dashboardHref: string): MenuSection[] {
  return [
    {
      label: "Monitoring",
      items: [
        { label: "Dashboard",        href: dashboardHref,                  Icon: LayoutDashboard    },
        { label: "Country Overview", href: "/dashboards/rvp/country-summary", Icon: Globe            },
        { label: "Fund Approval",    href: "/approvals",                   Icon: ClipboardCheckIcon },
        { label: "Monthly Request",  href: "/monthly-fund-request",        Icon: ClipboardCheckIcon },
      ],
    },
    {
      label: "Planning",
      items: [
        { label: "Annual Plan",       href: "/fy",            Icon: CalendarRange  },
        { label: "Quarterly Targets", href: "/team-targets",  Icon: Target         },
        { label: "Budgets & Funds",   href: "/budget",        Icon: Calculator     },
      ],
    },
    {
      label: "Insights",
      items: [
        { label: "Best Performing",   href: "/leaderboard",   Icon: Award          },
        { label: "Analytics",         href: "/analytics",     Icon: BarChart3      },
        { label: "Reports",           href: "/reports",       Icon: FileText       },
      ],
    },
    {
      label: "Account",
      items: [
        // No "Users & Access" — /admin is gated to the Admin role in
        // middleware.ts, so an RVP linking there would just be bounced.
        { label: "Messages",          href: "/messages",      Icon: MessageSquare  },
        { label: "Settings",          href: "/settings",      Icon: Settings       },
      ],
    },
  ];
}

// ────────── CD menu (Country Director specific) ──────────
//
// The Country Director sits above the field. They DO NOT see:
//   • Today's Tasks · My Plan · My Targets · Routes · Calendar
//     (personal field-work surfaces — for CCEO + PL)
//   • Visits · Trainings
//     (day-to-day field activity — for CCEO + PL)
//   • My Team · Partners · Leaderboard
//     (PL's team management — supervised circle, not country-wide)
//   • Coverage · Core Schools (drill-down) · Field Intelligence
//     (school-level operational surfaces)
//   • Salesforce Queue · Data Intake · Cost Settings
//     (Accountant / IA / Admin)
//   • Country comparison · Region overview
//     (RVP cross-country scope)
//   • Staff roster · Performance reviews
//     (HR — only Leave & Holidays leaks through)
//
// The CD menu is a single Main Navigation section focused on
// country-level decisions (targets, planning oversight, schools
// roll-up, SSA, analytics, reports, special projects, finance,
// approvals). User administration and audit logs are NOT surfaced
// here — /admin is gated to the Admin role in middleware.ts.
function buildCdMenu(dashboardHref: string): MenuSection[] {
  return [
    {
      label: "Main Navigation",
      items: [
        { label: "Dashboard",        href: dashboardHref,           Icon: LayoutDashboard    },
        { label: "Targets",          href: "/team-targets",         Icon: Award              },
        { label: "Planning",         href: "/planning",             Icon: ClipboardList      },
        { label: "Schools",          href: "/schools",              Icon: Building2          },
        { label: "SSA Performance",  href: "/ssa",                  Icon: Activity           },
        { label: "Best Performing",  href: "/leaderboard",          Icon: Trophy             },
        { label: "Analytics",        href: "/analytics",            Icon: BarChart3          },
        { label: "Reports",          href: "/reports",              Icon: FileText           },
        { label: "Special Projects", href: "/special-projects",     Icon: Sparkles           },
        { label: "Finance",          href: "/budget",               Icon: Calculator         },
        { label: "Weekly Funds",     href: "/weekly-funds",         Icon: Wallet             },
        { label: "Disbursements",    href: "/disbursements",        Icon: Send               },
        { label: "Approvals",        href: "/approvals",            Icon: ClipboardCheckIcon },
        { label: "Monthly Request",  href: "/monthly-fund-request", Icon: ClipboardCheckIcon },
        { label: "Messages",         href: "/messages",             Icon: MessageSquare      },
      ],
    },
  ];
}

// ────────── CPL menu (Program Lead specific) ──────────
//
// The PL gets a deliberately narrow menu. They DO NOT see:
//   • Coverage           (CCEO / CD)
//   • Leaderboard        (CD / RVP / HR)
//   • Field Intelligence (IA)
//   • Special Projects   (RVP / CD)
//   • Operating Cycle    (CD / RVP / Admin)
//   • Budget             (Accountant / CD / RVP)
//   • Data Intake        (IA / Admin)
//   • Cost Settings      (Accountant / Admin)
//   • Salesforce Queue   (IA / Accountant)
//   • Administration     (Admin)
//   • Staff              (HR / Admin)
//
// Everything the PL CAN reach maps to their day job: lead their team,
// approve their team's plans + funds, monitor their team's field work.
function buildCplMenu(dashboardHref: string): MenuSection[] {
  return [
    {
      label: "My Work",
      items: [
        { label: "Dashboard",       href: dashboardHref,  Icon: LayoutDashboard },
        { label: "Today's Tasks",   href: "/today",       Icon: CalendarCheck   },
        { label: "My Plan",         href: "/my-plan",     Icon: ClipboardList   },
        { label: "My Targets",      href: "/my-targets",  Icon: Award           },
        { label: "Routes",          href: "/route",       Icon: Map             },
        { label: "Calendar",        href: "/calendar",    Icon: CalendarRange   },
      ],
    },
    {
      label: "Schools",
      items: [
        { label: "My Portfolio",    href: "/portfolio",     Icon: Building2 },
        { label: "Schools",         href: "/schools",       Icon: Building2 },
        { label: "SSA Performance", href: "/ssa",           Icon: Activity  },
        { label: "Core Schools",    href: "/core-schools",  Icon: Star      },
      ],
    },
    {
      label: "Team",
      items: [
        // "My Team" was removed — it pointed to the same surface as
        // "Team Targets" and the duplication just bloated the menu.
        { label: "Team Targets",    href: "/team-targets",  Icon: Target    },
        { label: "Best Performing", href: "/leaderboard",   Icon: Trophy    },
        { label: "Partners",        href: "/partners",      Icon: Handshake },
      ],
    },
    {
      label: "Activity",
      items: [
        { label: "Approvals",        href: "/approvals",            Icon: ClipboardCheckIcon },
        { label: "Monthly Request",  href: "/monthly-fund-request", Icon: ClipboardCheckIcon },
        { label: "Weekly Funds",     href: "/weekly-funds",         Icon: Wallet             },
        { label: "Visits",           href: "/visits",               Icon: Footprints         },
        { label: "Trainings",        href: "/trainings",            Icon: GraduationCap      },
      ],
    },
    {
      label: "Insights",
      items: [
        { label: "Analytics",       href: "/analytics",     Icon: BarChart3       },
        { label: "Reports",         href: "/reports",       Icon: FileText        },
      ],
    },
    {
      label: "Account",
      items: [
        { label: "Messages",        href: "/messages",      Icon: MessageSquare   },
        { label: "Leave & Holidays",href: "/leave",         Icon: CalendarRange   },
        { label: "Help",            href: "/help",          Icon: HelpCircle      },
        { label: "Settings",        href: "/settings",      Icon: Settings        },
      ],
    },
  ];
}

// ────────── Accountant menu (Program Accountant specific) ──────────
//
// The Accountant operates the country's money: confirm treasury
// receipts, disburse weekly funds, monitor field balances, approve
// expense reconciliations. They DO NOT see:
//   • Schools / SSA / Visits / Trainings / Core Schools / Coverage
//   • My Plan / My Targets / Routes (field-work surfaces)
//   • Approvals queue for plans / quarterly targets (CD/PL/RVP own that)
//   • Team Targets / My Team / Partners / Leaderboard
//   • Special Projects / Field Intelligence / Country Overview
//
// Everything the Accountant CAN reach maps to finance ops: their own
// dashboard, the Field Fund Disbursement console, the weekly-funds
// pipeline view, treasury intake, cost settings, reports.
function buildAccountantMenu(dashboardHref: string): MenuSection[] {
  return [
    {
      label: "Finance Ops",
      items: [
        { label: "Dashboard",         href: dashboardHref,           Icon: LayoutDashboard    },
        { label: "Fund Approvals",    href: "/approvals",            Icon: ClipboardCheckIcon },
        { label: "Monthly Request",   href: "/monthly-fund-request", Icon: ClipboardCheckIcon },
        { label: "Disbursements",     href: "/disbursements",        Icon: Send               },
        { label: "Weekly Funds",      href: "/weekly-funds",         Icon: Wallet             },
        { label: "Fund Requests",     href: "/fund-requests",        Icon: Wallet             },
        { label: "Budget",            href: "/budget",        Icon: Calculator         },
        { label: "Cost Settings",     href: "/cost-settings", Icon: ShieldCheck        },
      ],
    },
    {
      label: "Intake",
      items: [
        { label: "Data Intake",       href: "/data-intake",   Icon: Upload          },
        { label: "Salesforce Queue",  href: "/queue",         Icon: Database        },
      ],
    },
    {
      label: "Insights",
      items: [
        { label: "Analytics",         href: "/analytics",     Icon: BarChart3       },
        { label: "Reports",           href: "/reports",       Icon: FileText        },
      ],
    },
    {
      label: "Account",
      items: [
        { label: "Messages",          href: "/messages",      Icon: MessageSquare   },
        { label: "Leave & Holidays",  href: "/leave",         Icon: CalendarRange   },
        { label: "Help",              href: "/help",          Icon: HelpCircle      },
        { label: "Settings",          href: "/settings",      Icon: Settings        },
      ],
    },
  ];
}

// ────────── Impact Assessment menu (M&E specific) ──────────
//
// Impact Assessment runs data quality, verification, and M&E. The
// field-officer personal toolkit (Today's Tasks · My Plan · My Targets
// · Routes) and day-to-day field activity (Visits · Trainings) are NOT
// here — IA analyses school data, it does not run school visits. Cost
// Settings is Admin-only in middleware.ts so it is not surfaced.
function buildImpactMenu(dashboardHref: string): MenuSection[] {
  return [
    {
      label: "My Work",
      items: [
        { label: "Dashboard",        href: dashboardHref,    Icon: LayoutDashboard },
        { label: "Calendar",         href: "/calendar",      Icon: CalendarRange },
      ],
    },
    {
      label: "Schools",
      items: [
        { label: "Schools",          href: "/schools",       Icon: Building2 },
        { label: "SSA Performance",  href: "/ssa",           Icon: Activity },
        { label: "Core Schools",     href: "/core-schools",  Icon: Star },
        { label: "Coverage",         href: "/coverage",      Icon: Handshake },
      ],
    },
    {
      label: "Team",
      items: [
        { label: "Team Targets",     href: "/team-targets",  Icon: Target },
        { label: "Partners",         href: "/partners",      Icon: Handshake },
        { label: "Leaderboard",      href: "/leaderboard",   Icon: Trophy },
      ],
    },
    {
      label: "Activity",
      items: [
        { label: "Field Intelligence", href: "/field-intelligence", Icon: Brain },
        { label: "Special Projects", href: "/special-projects",   Icon: Sparkles },
      ],
    },
    {
      label: "Programs",
      items: [
        { label: "Operating Cycle",  href: "/fy",            Icon: CalendarRange },
        { label: "Budget",           href: "/budget",        Icon: Calculator },
        { label: "Data Intake",      href: "/data-intake",   Icon: Upload },
      ],
    },
    {
      label: "Insights",
      items: [
        { label: "Analytics",        href: "/analytics",     Icon: BarChart3 },
        { label: "Reports",          href: "/reports",       Icon: FileText },
        { label: "Salesforce Queue", href: "/queue",         Icon: Database },
      ],
    },
    {
      label: "Account",
      items: [
        { label: "Messages",         href: "/messages",      Icon: MessageSquare },
        { label: "Leave & Holidays", href: "/leave",         Icon: CalendarRange },
        { label: "Help",             href: "/help",          Icon: HelpCircle },
        { label: "Settings",         href: "/settings",      Icon: Settings },
      ],
    },
  ];
}

// ────────── HR menu (People & Performance specific) ──────────
//
// HR works people, not schools: performance reviews, staff support
// signals, recognition, and aggregated field intelligence. School,
// field-visit, finance, and data-intake surfaces are NOT here — they
// do not map to anything on the HR console.
function buildHrMenu(dashboardHref: string): MenuSection[] {
  return [
    {
      label: "My Work",
      items: [
        { label: "Dashboard",        href: dashboardHref,    Icon: LayoutDashboard },
        { label: "Calendar",         href: "/calendar",      Icon: CalendarRange },
      ],
    },
    {
      label: "Team",
      items: [
        { label: "Team Targets",     href: "/team-targets",  Icon: Target },
        { label: "Best Performing",  href: "/leaderboard",   Icon: Trophy },
        { label: "Staff",            href: "/staff",         Icon: UserCog },
      ],
    },
    {
      label: "Activity",
      items: [
        { label: "Field Intelligence", href: "/field-intelligence", Icon: Brain },
      ],
    },
    {
      label: "Insights",
      items: [
        { label: "Analytics",        href: "/analytics",     Icon: BarChart3 },
        { label: "Reports",          href: "/reports",       Icon: FileText },
      ],
    },
    {
      label: "Account",
      items: [
        { label: "Messages",         href: "/messages",      Icon: MessageSquare },
        { label: "Leave & Holidays", href: "/leave",         Icon: CalendarRange },
        { label: "Help",             href: "/help",          Icon: HelpCircle },
        { label: "Settings",         href: "/settings",      Icon: Settings },
      ],
    },
  ];
}

// ────────── Admin menu (full access) ──────────
//
// The Admin is the system superuser — every surface is reachable,
// including /admin, /cost-settings, and the full field toolkit. By
// definition the Admin sees everything, so nothing here is gated.
function buildAdminMenu(dashboardHref: string): MenuSection[] {
  return [
    {
      label: "My Work",
      items: [
        { label: "Dashboard",        href: dashboardHref,    Icon: LayoutDashboard },
        { label: "Today's Tasks",    href: "/today",         Icon: CalendarCheck },
        { label: "My Plan",          href: "/my-plan",       Icon: ClipboardList },
        { label: "My Targets",       href: "/my-targets",    Icon: Award },
        { label: "Routes",           href: "/route",         Icon: Map },
        { label: "Calendar",         href: "/calendar",      Icon: CalendarRange },
      ],
    },
    {
      label: "Schools",
      items: [
        { label: "Schools",          href: "/schools",       Icon: Building2 },
        { label: "SSA Performance",  href: "/ssa",           Icon: Activity },
        { label: "Core Schools",     href: "/core-schools",  Icon: Star },
        { label: "Coverage",         href: "/coverage",      Icon: Handshake },
      ],
    },
    {
      label: "Team",
      items: [
        { label: "Staff",            href: "/staff",         Icon: UserCog },
        { label: "Partners",         href: "/partners",      Icon: Handshake },
        { label: "Leaderboard",      href: "/leaderboard",   Icon: Trophy },
      ],
    },
    {
      label: "Activity",
      items: [
        { label: "Visits",           href: "/visits",             Icon: Footprints },
        { label: "Trainings",        href: "/trainings",          Icon: GraduationCap },
        { label: "Field Intelligence", href: "/field-intelligence", Icon: Brain },
        { label: "Special Projects", href: "/special-projects",   Icon: Sparkles },
      ],
    },
    {
      label: "Programs",
      items: [
        { label: "Operating Cycle",  href: "/fy",            Icon: CalendarRange },
        { label: "Budget",           href: "/budget",        Icon: Calculator },
        { label: "Data Intake",      href: "/data-intake",   Icon: Upload },
        { label: "Cost Settings",    href: "/cost-settings", Icon: ShieldCheck },
      ],
    },
    {
      label: "Insights",
      items: [
        { label: "Analytics",        href: "/analytics",     Icon: BarChart3 },
        { label: "Reports",          href: "/reports",       Icon: FileText },
        { label: "Salesforce Queue", href: "/queue",         Icon: Database },
      ],
    },
    {
      label: "Account",
      items: [
        { label: "Messages",         href: "/messages",      Icon: MessageSquare },
        { label: "Leave & Holidays", href: "/leave",         Icon: CalendarRange },
        { label: "Help",             href: "/help",          Icon: HelpCircle },
        { label: "Settings",         href: "/settings",      Icon: Settings },
        { label: "Administration",   href: "/admin",         Icon: ShieldCheck },
      ],
    },
  ];
}

// ────────── Partner menu (Partner Command Center) ──────────
//
// The Partner Admin / FieldOfficer / Viewer sidebar. Three sections —
// MY WORK / INBOX / RESOURCES — mirroring the reference design exactly.
// INBOX items carry badge counts that match the Partner Action Inbox
// tabs on the dashboard so the sidebar reads as a quick-pivot view
// into the same underlying queue.
// Partner sidebar — workflow-based, flat. No big internal menu.
// Reading order matches the partner's day: see the situation
// (Overview), plan the work (My Work / Schedule), deliver today
// (Today), prove it (Evidence / Corrections), get paid (Payments),
// then ground it in school improvement (Schools / Support Journey)
// before account chrome (Reports / Messages / Profile / Help).
//
// Badges only where attention is needed — counts that change the
// partner's behaviour, never decoration.
function buildPartnerMenu(dashboardHref: string): MenuSection[] {
  return [
    {
      label: "",
      items: [
        { label: "Overview",        href: dashboardHref,                Icon: LayoutDashboard },
        { label: "My Plan",         href: "/partner/assignments",       Icon: ClipboardList,      badge: 12 },
        { label: "Schedule",        href: "/partner/schedule",          Icon: CalendarRange,      badge: 5  },
        { label: "Today",           href: "/partner/today",             Icon: CalendarCheck },
        { label: "Evidence",        href: "/partner/evidence",          Icon: Upload,             badge: 7  },
        { label: "Corrections",     href: "/partner/corrections",       Icon: AlertOctagon,       badge: 3  },
        { label: "Payments",        href: "/partner/payments",          Icon: Wallet,             badge: 4  },
        { label: "Schools",         href: "/partner/schools",           Icon: Building2 },
        { label: "Support Journey", href: "/partner/support-journey",   Icon: ClipboardCheckIcon },
        { label: "Impact",          href: "/partner/impact",            Icon: TrendingUp },
        { label: "Reports",         href: "/partner/reports",           Icon: FileText },
        { label: "Messages",        href: "/partner/messages",          Icon: MessageSquare,      badge: 2  },
        { label: "Profile",         href: "/partner/profile",           Icon: UserCog },
        { label: "Help",            href: "/partner/help",              Icon: HelpCircle },
      ],
    },
  ];
}

// ────────── Component ──────────

export function EdifySidebar({
  role = "CountryProgramLead",
  user = { name: "Daniel Mwangi", initials: "DM", online: true },
}: {
  role?: EdifyRole;
  user?: { name: string; initials: string; online?: boolean };
}) {
  const pathname = usePathname();
  const { setOpen, asideClassName, hamburger, backdrop, closeButton } = useMobileDrawer();

  // Auto-close the mobile drawer on every route change. Without this,
  // tapping a nav link navigates the page but the drawer stays open
  // covering the destination — users perceive that "nothing happened"
  // when in fact the click did work. Watching pathname is the right
  // signal because it captures every nav source (link tap, back
  // button, programmatic router.push) without per-link wiring.
  useEffect(() => {
    setOpen(false);
  }, [pathname, setOpen]);
  const isCceo = role === "CCEO";
  const isCpl  = role === "CountryProgramLead";
  const isCd   = role === "CountryDirector";
  const isRvp  = role === "RVP";
  const isAcct = role === "ProgramAccountant";
  const isImpact = role === "ImpactAssessment";
  const isHr   = role === "HumanResource";
  const isPartner = role === "PartnerAdmin" || role === "PartnerFieldOfficer" || role === "PartnerViewer";
  const sections = isCceo
    ? buildCceoMenu()
    : isCpl
      ? buildCplMenu(ROLE_REDIRECT[role])
      : isCd
        ? buildCdMenu(ROLE_REDIRECT[role])
        : isRvp
          ? buildRvpMenu(ROLE_REDIRECT[role])
          : isAcct
            ? buildAccountantMenu(ROLE_REDIRECT[role])
            : isImpact
              ? buildImpactMenu(ROLE_REDIRECT[role])
              : isHr
                ? buildHrMenu(ROLE_REDIRECT[role])
                : isPartner
                  ? buildPartnerMenu(ROLE_REDIRECT[role])
                  : buildAdminMenu(ROLE_REDIRECT[role]);

  // CCEO sidebar uses the persona-specific brand block from the
  // reference ("CCEO / CORE SCHOOLS" with a gold ribbon mark) and
  // shows the Sarah Okello profile, an inspirational quote, and a
  // Collapse affordance at the foot of the rail.
  const cceoBrand = (
    <div className="flex items-center gap-3 px-5 pt-4 lg:pt-5 pb-4 border-b border-white/10 lg:border-b-0">
      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-300 to-amber-500 flex items-center justify-center shadow shrink-0 text-[10px] font-extrabold text-amber-900 tracking-wider">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden>
          <path d="M12 2l2.39 4.84L20 7.74l-4 3.9.94 5.5L12 14.77l-4.94 2.37L8 11.64l-4-3.9 5.61-.9L12 2z" fill="#7c5314" stroke="#7c5314" strokeWidth="0.5" strokeLinejoin="round" />
          <rect x="6" y="17" width="12" height="5" rx="1" fill="#7c5314" />
        </svg>
      </div>
      <div className="leading-tight min-w-0">
        <div className="text-[19px] font-extrabold tracking-tight">CCEO</div>
        <div className="text-[10px] tracking-[0.18em] text-white/70 font-bold leading-tight uppercase">
          Core Schools
        </div>
      </div>
    </div>
  );

  const edifyBrand = (
    <div className="flex items-center gap-3 px-5 pt-4 lg:pt-5 pb-4 border-b border-white/10 lg:border-b-0">
      <div className="w-9 h-9 lg:w-10 lg:h-10 rounded-xl bg-white flex items-center justify-center shadow shrink-0">
        <Image src="/edify-logo.png" alt="Edify" width={32} height={13} className="object-contain" style={{ width: "auto", height: "auto" }} priority />
      </div>
      <div className="leading-tight min-w-0">
        <div className="text-[16px] lg:text-[19px] font-extrabold tracking-tight">EDIFY</div>
        <div className="text-caption lg:text-[10px] tracking-wide text-white/70 font-medium leading-tight max-w-[200px] truncate">
          {SUBTITLE_BY_ROLE[role]}
        </div>
      </div>
    </div>
  );

  return (
    <>
      {hamburger}
      {backdrop}
      <aside className={cn(
        "sidebar-bg text-white shrink-0 flex flex-col min-h-screen",
        // 280px in drawer mode (mobile + small tablets ≤10") matches the
        // MobileMenuSheet shell so the experience feels uniform; tightens
        // back to 244px at lg+ where the sidebar is persistent.
        "w-[280px] lg:w-[244px] max-w-[85vw] lg:max-w-none",
        asideClassName,
      )}>
        {closeButton}

        {/* Brand */}
        {isCceo ? cceoBrand : edifyBrand}

        {/* Menu */}
        <nav className="px-3 mt-1 space-y-3 text-[13px] flex-1 overflow-y-auto pb-3">
          {sections.map((section) => (
            <div key={section.label || "unsectioned"}>
              {section.label && (
                <div className="text-[10px] font-bold uppercase tracking-wider text-white/45 px-3 mb-1">
                  {section.label}
                </div>
              )}
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
                      prefetch={false}
                      // Belt-and-braces close: when the user taps the
                      // *currently active* link, `pathname` doesn't
                      // change so the effect above won't fire — close
                      // here too so the drawer never stays open.
                      onClick={() => setOpen(false)}
                      className={cn(
                        "menu-item flex items-center gap-3 px-3 py-2 rounded-lg",
                        active && "active",
                      )}
                    >
                      <span className="menu-icon">
                        <m.Icon size={14} />
                      </span>
                      <span className="truncate flex-1">{m.label}</span>
                      {m.badge && m.badge > 0 ? (
                        <span className="ml-auto px-1.5 min-w-[20px] h-5 rounded-md bg-rose-500 text-white text-caption font-extrabold tabular grid place-items-center">
                          {m.badge}
                        </span>
                      ) : null}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Profile + sign out (or CCEO foot block: profile → quote → collapse) */}
        <div className="mt-auto px-3 pb-4 space-y-3 border-t border-white/10 pt-3">
          {isCceo ? (
            <>
              {/* Compact CCEO profile row (matches reference). */}
              <div className="flex items-center gap-3 px-1">
                <div className="relative shrink-0">
                  <div className="w-10 h-10 rounded-full bg-emerald-500 text-white font-extrabold flex items-center justify-center text-[13px]">
                    {cceoUserMock.initials}
                  </div>
                  <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-400 border-2 border-[var(--color-edify-deep)]" />
                </div>
                <div className="leading-tight min-w-0 flex-1">
                  <div className="text-[13px] font-extrabold truncate">{cceoUserMock.name}</div>
                  <div className="text-caption text-white/70 font-semibold truncate">{cceoUserMock.role}</div>
                  <div className="text-caption text-white/60 truncate">{cceoUserMock.cluster}</div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-white/80">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
                    Online
                  </div>
                </div>
              </div>

              {/* Inspirational quote — italicised, attribution dimmed. */}
              <blockquote className="px-1 pt-2 border-t border-white/10">
                <p className="text-[12px] italic text-white/85 leading-snug">
                  &ldquo;{cceoUserMock.quote}&rdquo;
                </p>
                <footer className="mt-1 text-[11px] text-white/55 font-semibold">
                  — {cceoUserMock.quoteAttribution}
                </footer>
              </blockquote>

              {/* Collapse rail — visual affordance only; sign-out kept reachable. */}
              <div className="pt-2 border-t border-white/10 flex items-center justify-between gap-2">
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-white/75 hover:text-white px-1 py-1"
                >
                  <PanelLeftClose size={13} />
                  Collapse
                </button>
                <SignOutButton variant="dark" />
              </div>
            </>
          ) : (
            <div className="rounded-xl bg-white/[.06] border border-white/10 p-3">
              <div className="flex items-center gap-3">
                <div className="relative">
                  <div className="w-10 h-10 rounded-full bg-[var(--color-edify-primary)] text-white font-bold flex items-center justify-center shrink-0">
                    {user.initials}
                  </div>
                  {user.online && (
                    <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-400 border-2 border-[var(--color-edify-deep)]" />
                  )}
                </div>
                <div className="leading-tight min-w-0 flex-1">
                  <div className="text-[13px] font-bold truncate">{user.name}</div>
                  <div className="text-[11px] text-white/70 truncate">{role.replace(/([A-Z])/g, " $1").trim()}</div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-caption text-white/80">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
                    {user.online ? "Online" : "Offline"}
                  </div>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Link
                  href="/profile"
                  onClick={() => setOpen(false)}
                  className="h-8 rounded-md border border-white/15 text-[12px] font-semibold text-white/90 hover:bg-white/10 flex items-center justify-center gap-1.5"
                >
                  Profile
                  <ExternalLink size={11} />
                </Link>
                <SignOutButton variant="dark" />
              </div>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
