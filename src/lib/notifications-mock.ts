// Shared notification data — used by the header NotificationBell drawer.
//
// Schema upgrade (per the floating-drawer spec): notifications now carry
// category, priority, actionRequired, and optional context so the drawer
// can group/filter and the row UI can paint priority + category badges.
// Older callers that only read {title, body, href, unread, ago, Icon} are
// unaffected — those keys are preserved.

import {
  AlertTriangle,
  ClipboardCheck,
  ShieldCheck,
  Wallet,
  Trophy,
  CalendarRange,
  Mail,
  GraduationCap,
  Truck,
  Heart,
  type LucideIcon,
} from "lucide-react";

export type NotificationCategory =
  | "Message"
  | "Approval"
  | "Evidence"
  | "Payment"
  | "Planning"
  | "Partner"
  | "Debrief"
  | "School"
  | "Cluster"
  | "SSA"
  | "Reschedule"
  | "HR"
  | "System";

export type NotificationPriority = "normal" | "important" | "urgent" | "critical";

export type Notification = {
  id: string;
  title: string;
  body: string;
  href: string;
  unread: boolean;
  ago: string;
  Icon: LucideIcon;
  iconBg: string;
  iconText: string;
  /** What kind of thing this notification is about. */
  category?: NotificationCategory;
  /** Visual prominence — drives the priority badge.  Default: normal. */
  priority?: NotificationPriority;
  /** True when the user has to ACT (review, approve, confirm, fix).
   *  False for FYI / informational items. */
  actionRequired?: boolean;
  /** Short label shown under the title for context — e.g.
   *  "Hope Primary · Attendance sheet". */
  contextLabel?: string;
  /** Label on the action button when actionRequired is true. */
  actionLabel?: string;
};

export const NOTIFICATIONS: Notification[] = [
  {
    id: "n-1",
    title: "12 plans awaiting your approval",
    body: "Submitted by 6 CCEOs across Kigun and Mbarara.",
    href: "/approvals",
    unread: true,
    ago: "12m",
    Icon: ClipboardCheck,
    iconBg: "bg-amber-100",
    iconText: "text-amber-700",
    category: "Approval",
    priority: "urgent",
    actionRequired: true,
    contextLabel: "Kigun · Mbarara",
    actionLabel: "Review Queue",
  },
  {
    id: "n-2",
    title: "3 staff members behind target",
    body: "Mid-year flag triggered — open the support-review checklist.",
    href: "/team-targets",
    unread: true,
    ago: "32m",
    Icon: AlertTriangle,
    iconBg: "bg-rose-100",
    iconText: "text-rose-700",
    category: "HR",
    priority: "important",
    actionRequired: true,
    contextLabel: "Mid-year review",
    actionLabel: "Open checklist",
  },
  {
    id: "n-3",
    title: "Daily Field Debrief is due",
    body: "You haven't submitted today's debrief yet.",
    href: "/debriefs/new",
    unread: true,
    ago: "1h",
    Icon: ShieldCheck,
    iconBg: "bg-emerald-100",
    iconText: "text-emerald-700",
    category: "Debrief",
    priority: "important",
    actionRequired: true,
    actionLabel: "Submit Debrief",
  },
  {
    id: "n-4",
    title: "5 fund requests need disbursement",
    body: "Disbursement window closes Friday at 17:00.",
    href: "/disbursements",
    unread: false,
    ago: "3h",
    Icon: Wallet,
    iconBg: "bg-violet-100",
    iconText: "text-violet-700",
    category: "Payment",
    priority: "important",
    actionRequired: true,
    contextLabel: "Window closes Fri 17:00",
    actionLabel: "Open Queue",
  },
  {
    id: "n-5",
    title: "You moved to #2 on the verified leaderboard",
    body: "Sarah Okello overtook Daniel Mwangi this cycle.",
    href: "/leaderboard",
    unread: false,
    ago: "Yesterday",
    Icon: Trophy,
    iconBg: "bg-yellow-100",
    iconText: "text-yellow-700",
    category: "System",
    priority: "normal",
    actionRequired: false,
  },
  {
    id: "n-6",
    title: "Public holiday on Friday",
    body: "Planning auto-blocked — your route runner skipped 2 stops.",
    href: "/leave",
    unread: false,
    ago: "2d",
    Icon: CalendarRange,
    iconBg: "bg-sky-100",
    iconText: "text-sky-700",
    category: "Planning",
    priority: "normal",
    actionRequired: false,
  },
  {
    id: "n-7",
    title: "Evidence correction needed",
    body: "Attendance sheet for the Jan 14 visit is missing signatures.",
    href: "/data-verification?filter=returned",
    unread: true,
    ago: "4h",
    Icon: AlertTriangle,
    iconBg: "bg-rose-100",
    iconText: "text-rose-700",
    category: "Evidence",
    priority: "urgent",
    actionRequired: true,
    contextLabel: "Hope Primary · Attendance",
    actionLabel: "Review evidence",
  },
  {
    id: "n-8",
    title: "New message from Mary",
    body: "Re: Sunrise Primary — let's reschedule the cluster meeting.",
    href: "/messages",
    unread: true,
    ago: "5h",
    Icon: Mail,
    iconBg: "bg-sky-100",
    iconText: "text-sky-700",
    category: "Message",
    priority: "normal",
    actionRequired: false,
    contextLabel: "Mary Akello · IA",
  },
  {
    id: "n-9",
    title: "Cluster meeting rescheduled to next Tuesday",
    body: "Kireka cluster moved from Thursday to Tuesday — 3 schools affected.",
    href: "/clusters",
    unread: false,
    ago: "Yesterday",
    Icon: Truck,
    iconBg: "bg-amber-100",
    iconText: "text-amber-700",
    category: "Reschedule",
    priority: "normal",
    actionRequired: false,
    contextLabel: "Kireka cluster",
  },
  {
    id: "n-10",
    title: "Training scheduled: Numeracy Foundations",
    body: "Cluster Faleha · May 5 · 14 participants. Materials ready.",
    href: "/trainings",
    unread: false,
    ago: "2d",
    Icon: GraduationCap,
    iconBg: "bg-violet-100",
    iconText: "text-violet-700",
    category: "Cluster",
    priority: "normal",
    actionRequired: false,
    contextLabel: "Faleha · May 5",
  },
  {
    id: "n-11",
    title: "Partner submitted SSA evidence",
    body: "Living Word School · Q1 SSA assessment uploaded for review.",
    href: "/ssa",
    unread: false,
    ago: "3d",
    Icon: Heart,
    iconBg: "bg-emerald-100",
    iconText: "text-emerald-700",
    category: "SSA",
    priority: "normal",
    actionRequired: false,
    contextLabel: "Living Word School",
  },
];

export const unreadNotificationCount = NOTIFICATIONS.filter((n) => n.unread).length;
export const urgentNotificationCount = NOTIFICATIONS.filter((n) =>
  n.unread && (n.priority === "urgent" || n.priority === "critical")
).length;
export const actionRequiredCount = NOTIFICATIONS.filter((n) =>
  n.unread && n.actionRequired
).length;
