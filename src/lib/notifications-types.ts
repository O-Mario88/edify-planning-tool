// Notification view types + the backend→view adapter. Lives apart from any mock
// so components import types without pulling fake data (backend-only migration).

import {
  Bell, Wallet, FileCheck2, ClipboardList, Handshake, School, Network, Activity,
  CalendarClock, Users, MessageSquare, ShieldCheck, type LucideIcon,
} from "lucide-react";

export type NotificationCategory =
  | "Message" | "Approval" | "Evidence" | "Payment" | "Planning" | "Partner"
  | "Debrief" | "School" | "Cluster" | "SSA" | "Reschedule" | "HR" | "System";

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
  category?: NotificationCategory;
  priority?: NotificationPriority;
  actionRequired?: boolean;
  contextLabel?: string;
  actionLabel?: string;
};

export type NotificationCounts = { all: number; unread: number; action: number; urgent: number };

// The raw backend row (edify-api Notification model).
export type BackendNotification = {
  id: string;
  title: string;
  body?: string | null;
  contextType?: string | null;
  contextId?: string | null;
  targetRoute?: string | null;
  actionRequired: boolean;
  priority: "low" | "normal" | "high" | "urgent";
  status: "unread" | "read" | "archived";
  createdAt: string;
};

// Static tint classes (Tailwind can't see interpolated class names).
const TINT: Record<string, { iconBg: string; iconText: string }> = {
  emerald: { iconBg: "bg-emerald-50", iconText: "text-emerald-600" },
  amber: { iconBg: "bg-amber-50", iconText: "text-amber-600" },
  violet: { iconBg: "bg-violet-50", iconText: "text-violet-600" },
  sky: { iconBg: "bg-sky-50", iconText: "text-sky-600" },
  indigo: { iconBg: "bg-indigo-50", iconText: "text-indigo-600" },
  slate: { iconBg: "bg-slate-50", iconText: "text-slate-600" },
};

// contextType / title keyword → category + icon + tint.
function classify(ctx: string, title: string): { category: NotificationCategory; Icon: LucideIcon; iconBg: string; iconText: string } {
  const s = `${ctx} ${title}`.toLowerCase();
  const pick = (category: NotificationCategory, Icon: LucideIcon, tint: keyof typeof TINT): ReturnType<typeof classify> =>
    ({ category, Icon, ...TINT[tint] });
  if (/payment|disburse|paid|fund/.test(s)) return pick("Payment", Wallet, "emerald");
  if (/evidence/.test(s)) return pick("Evidence", FileCheck2, "amber");
  if (/debrief/.test(s)) return pick("Debrief", ClipboardList, "violet");
  if (/partner/.test(s)) return pick("Partner", Handshake, "violet");
  if (/ssa|verif|salesforce/.test(s)) return pick("SSA", ShieldCheck, "sky");
  if (/cluster/.test(s)) return pick("Cluster", Network, "indigo");
  if (/school/.test(s)) return pick("School", School, "sky");
  if (/plan|activity/.test(s)) return pick("Planning", Activity, "sky");
  if (/reschedul/.test(s)) return pick("Reschedule", CalendarClock, "amber");
  if (/leave|staff|hr/.test(s)) return pick("HR", Users, "slate");
  if (/message/.test(s)) return pick("Message", MessageSquare, "sky");
  if (/approv/.test(s)) return pick("Approval", ClipboardList, "emerald");
  return pick("System", Bell, "slate");
}

const PRIORITY_MAP: Record<BackendNotification["priority"], NotificationPriority> = {
  low: "normal", normal: "normal", high: "important", urgent: "urgent",
};

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export function adaptNotification(n: BackendNotification): Notification {
  const c = classify(n.contextType ?? "", n.title);
  return {
    id: n.id,
    title: n.title,
    body: n.body ?? "",
    href: n.targetRoute ?? "/notifications",
    unread: n.status === "unread",
    ago: timeAgo(n.createdAt),
    Icon: c.Icon, iconBg: c.iconBg, iconText: c.iconText,
    category: c.category,
    priority: PRIORITY_MAP[n.priority],
    actionRequired: n.actionRequired,
    contextLabel: n.contextType ? n.contextType.replace(/_/g, " ") : undefined,
  };
}
