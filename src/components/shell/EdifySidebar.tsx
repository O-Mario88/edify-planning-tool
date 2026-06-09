"use client";

import { SidebarBrand } from "@/components/shell/SidebarBrand";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import {
  LayoutDashboard,
  ClipboardList,
  Building2,
  Compass,
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
  Network,
  type LucideIcon,
} from "lucide-react";
import { cceoSidebarItems } from "@/lib/cceo-mock";
import { ROLE_REDIRECT, type EdifyRole as PublicEdifyRole } from "@/lib/auth-public";
import { cn } from "@/lib/utils";
import { SidebarProfile } from "@/components/shell/SidebarProfile";
import { useMobileDrawer } from "@/components/auth/MobileDrawerShell";

// ────────── Role-aware Dashboard target ──────────
//
// One sidebar for every dashboard. The only per-role difference is where
// "Dashboard" points; the rest is identical. The role → route map is
// sourced from auth-public so the redirect, login form, and sidebar
// stay in lockstep.

export type EdifyRole = PublicEdifyRole;

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
  network:         Network,
  sparkles:        Sparkles,
  handshake:       Handshake,
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
        { label: "My Plan",          href: "/my-plan",              Icon: ClipboardList      },
        { label: "Completed Log",    href: "/completed-activities", Icon: ClipboardList      },
        // No "Schools" — the School Directory is an operational surface for
        // CCEO/PL/IA. The CD leads through analytics + recruitment intelligence.
        { label: "Recruitment",      href: "/recruitment",          Icon: Compass            },
        { label: "SSA Performance",  href: "/ssa",                  Icon: Activity           },
        { label: "Analytics",        href: "/analytics",            Icon: BarChart3          },
        { label: "Reports",          href: "/reports",              Icon: FileText           },
        { label: "Special Projects", href: "/special-projects",     Icon: Sparkles           },
        { label: "Project Schools",  href: "/special-projects/schools", Icon: GraduationCap  },
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

// ────────── Project Coordinator menu ──────────
//
// Owns special projects & targeted interventions. Their day job: create
// projects, map them to SSA interventions, assign schools from the
// directory, monitor project delivery + impact, coordinate partners.
function buildProjectCoordinatorMenu(dashboardHref: string): MenuSection[] {
  return [
    {
      label: "Main Navigation",
      items: [
        { label: "Dashboard",        href: dashboardHref,       Icon: LayoutDashboard },
        { label: "Special Projects", href: "/special-projects", Icon: Sparkles        },
        { label: "Project Schools",  href: "/special-projects/schools", Icon: GraduationCap },
        { label: "Project Pipeline", href: "/special-projects/pipeline", Icon: Handshake },
        { label: "Schools",          href: "/schools",          Icon: Building2       },
        // No "Clusters" workspace — cluster assignment is a CCEO/PL
        // responsibility; the coordinator only views a school's cluster on the
        // project surfaces (read-only).
        { label: "SSA Performance",  href: "/ssa",              Icon: Activity        },
        { label: "Partners",         href: "/partners",         Icon: Handshake       },
        { label: "Analytics",        href: "/analytics",        Icon: BarChart3       },
        { label: "Reports",          href: "/reports",          Icon: FileText        },
        { label: "Messages",         href: "/messages",         Icon: MessageSquare   },
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
        { label: "Planning",        href: "/planning",    Icon: ClipboardCheckIcon },
        { label: "My Plan",         href: "/my-plan",     Icon: CalendarCheck   },
        { label: "Completed Log",   href: "/completed-activities", Icon: ClipboardCheckIcon },
        { label: "My Targets",      href: "/my-targets",  Icon: Award           },
        { label: "Routes",          href: "/route",       Icon: Map             },
        { label: "Calendar",        href: "/calendar",    Icon: CalendarRange   },
      ],
    },
    {
      label: "Schools",
      items: [
        { label: "Schools",         href: "/schools",       Icon: Building2 },
        { label: "Clusters",        href: "/clusters",      Icon: Network   },
        { label: "SSA Performance", href: "/ssa",           Icon: Activity  },
        { label: "Core Schools",    href: "/core-schools",  Icon: Star      },
        { label: "Project Schools", href: "/special-projects/schools", Icon: Sparkles },
        { label: "Project Pipeline", href: "/special-projects/pipeline", Icon: Handshake },
      ],
    },
    {
      label: "Team",
      items: [
        // "My Team" was removed — it pointed to the same surface as
        // "Team Targets" and the duplication just bloated the menu.
        { label: "Team Targets",    href: "/team-targets",  Icon: Target    },
        { label: "Partners",        href: "/partners",      Icon: Handshake },
      ],
    },
    {
      label: "Activity",
      items: [
        { label: "Budget",           href: "/budget",               Icon: Calculator         },
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
        { label: "Cluster Payments",  href: "/disbursements/cluster-payments", Icon: Network    },
        { label: "Weekly Funds",      href: "/weekly-funds",         Icon: Wallet             },
        { label: "Fund Requests",     href: "/fund-requests",        Icon: Wallet             },
        { label: "Budget",            href: "/budget",        Icon: Calculator         },
        { label: "Cost Settings",     href: "/cost-settings", Icon: ShieldCheck        },
        { label: "Project Pipeline",  href: "/special-projects/pipeline", Icon: Handshake },
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
      ],
    },
    {
      label: "Activity",
      items: [
        { label: "Field Intelligence", href: "/field-intelligence", Icon: Brain },
        { label: "Special Projects", href: "/special-projects",   Icon: Sparkles },
        { label: "Project Pipeline", href: "/special-projects/pipeline", Icon: Handshake },
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
// HR supports PEOPLE, not schools. Per the access spec, HR gets exactly three
// working surfaces — Staff Performance, Leave Planner, Daily Field Debrief —
// plus insights + account. No School Directory, no partner/payment/fund/project
// operational pages (those are blocked in middleware + backend permissions).
function buildHrMenu(dashboardHref: string): MenuSection[] {
  return [
    {
      label: "My Work",
      items: [
        { label: "Dashboard",         href: dashboardHref,    Icon: LayoutDashboard },
      ],
    },
    {
      label: "People",
      items: [
        { label: "Staff Performance", href: "/staff",         Icon: UserCog },
        { label: "Leave Planner",     href: "/leave",         Icon: CalendarRange },
        { label: "Daily Debrief",     href: "/debriefs",      Icon: Brain },
      ],
    },
    {
      label: "Insights",
      items: [
        { label: "Analytics",         href: "/analytics",     Icon: BarChart3 },
        { label: "Reports",           href: "/reports",       Icon: FileText },
      ],
    },
    {
      label: "Account",
      items: [
        { label: "Messages",          href: "/messages",      Icon: MessageSquare },
        { label: "Settings",          href: "/settings",      Icon: Settings },
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
        { label: "Planning",         href: "/planning",      Icon: ClipboardList },
        { label: "My Plan",          href: "/my-plan",       Icon: CalendarCheck },
        { label: "Completed Log",    href: "/completed-activities", Icon: ClipboardList },
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
        { label: "Clusters",        href: "/partner/clusters",          Icon: Network },
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
  user = { staffId: "STF-DM-014", name: "Daniel Mwangi", initials: "DM", color: "#10b981", district: "Wakiso", online: true },
}: {
  role?: EdifyRole;
  user?: {
    staffId: string;
    name: string;
    initials: string;
    color?: string;
    district?: string;
    online?: boolean;
  };
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
  const isProjectCoord = role === "ProjectCoordinator";
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
                : isProjectCoord
                  ? buildProjectCoordinatorMenu(ROLE_REDIRECT[role])
                  : isPartner
                    ? buildPartnerMenu(ROLE_REDIRECT[role])
                    : buildAdminMenu(ROLE_REDIRECT[role]);

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

        {/* Brand — one shared block for every role. */}
        <SidebarBrand href={ROLE_REDIRECT[role]} />

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

        {/* Account — the single identity surface (photo-frame avatar + menu). */}
        <div className="mt-auto px-3 pb-4 border-t border-white/10 pt-3">
          <SidebarProfile
            staffId={user.staffId}
            name={user.name}
            initials={user.initials}
            color={user.color}
            role={role}
            district={user.district}
            online={user.online}
            onNavigate={() => setOpen(false)}
          />
        </div>
      </aside>
    </>
  );
}
