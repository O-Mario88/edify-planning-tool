// Per-category display metadata. Single source of truth for labels +
// icons + accent colour. Used by both the list (kind dot + label) and
// the detail page (top-bar category, header accent).

import {
  AlertOctagon,
  AlertTriangle,
  Award,
  Bell,
  Building2,
  CheckCircle2,
  ClipboardCheck,
  ClipboardList,
  Coins,
  FileText,
  Megaphone,
  RotateCcw,
  Sparkles,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import type { MessageCategory } from "./types";

export type CategoryMeta = {
  key:    MessageCategory;
  label:  string;
  Icon:   LucideIcon;
  /** Used for the dot, the left accent stripe on unread rows, and the
   *  category chip in the detail header. */
  dot:    string;
  stripe: string;
  chip:   string;
};

export const CATEGORY_META: Record<MessageCategory, CategoryMeta> = {
  "field-debrief":        { key: "field-debrief",        label: "Field Debrief",        Icon: ClipboardList,    dot: "bg-blue-500",    stripe: "before:bg-blue-400/70",    chip: "bg-blue-50 text-blue-700 border-blue-200" },
  "partner-debrief":      { key: "partner-debrief",      label: "Partner Debrief",      Icon: Users,            dot: "bg-violet-500",  stripe: "before:bg-violet-400/70",  chip: "bg-violet-50 text-violet-700 border-violet-200" },
  "evidence-review":      { key: "evidence-review",      label: "Evidence Review",      Icon: FileText,         dot: "bg-sky-500",     stripe: "before:bg-sky-400/70",     chip: "bg-sky-50 text-sky-700 border-sky-200" },
  "correction-request":   { key: "correction-request",   label: "Correction Request",   Icon: RotateCcw,        dot: "bg-amber-500",   stripe: "before:bg-amber-400/80",   chip: "bg-amber-50 text-amber-800 border-amber-200" },
  "payment-update":       { key: "payment-update",       label: "Payment Update",       Icon: Wallet,           dot: "bg-emerald-500", stripe: "before:bg-emerald-400/70", chip: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  "planning-assignment":  { key: "planning-assignment",  label: "Planning Assignment",  Icon: ClipboardCheck,   dot: "bg-indigo-500",  stripe: "before:bg-indigo-400/70",  chip: "bg-indigo-50 text-indigo-700 border-indigo-200" },
  "partner-scheduling":   { key: "partner-scheduling",   label: "Partner Scheduling",   Icon: Bell,             dot: "bg-cyan-500",    stripe: "before:bg-cyan-400/70",    chip: "bg-cyan-50 text-cyan-700 border-cyan-200" },
  "school-followup":      { key: "school-followup",      label: "School Follow-Up",     Icon: Building2,        dot: "bg-teal-500",    stripe: "before:bg-teal-400/70",    chip: "bg-teal-50 text-teal-700 border-teal-200" },
  "cluster-update":       { key: "cluster-update",       label: "Cluster Update",       Icon: Building2,        dot: "bg-teal-500",    stripe: "before:bg-teal-400/70",    chip: "bg-teal-50 text-teal-700 border-teal-200" },
  "ssa-update":           { key: "ssa-update",           label: "SSA Update",           Icon: Award,            dot: "bg-fuchsia-500", stripe: "before:bg-fuchsia-400/70", chip: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200" },
  "finance":              { key: "finance",              label: "Finance",              Icon: Coins,            dot: "bg-amber-600",   stripe: "before:bg-amber-500/70",   chip: "bg-amber-50 text-amber-800 border-amber-200" },
  "hr-support":           { key: "hr-support",           label: "HR Support",           Icon: Users,            dot: "bg-rose-500",    stripe: "before:bg-rose-400/70",    chip: "bg-rose-50 text-rose-700 border-rose-200" },
  "system-notification":  { key: "system-notification",  label: "System Notification",  Icon: Bell,             dot: "bg-slate-500",   stripe: "before:bg-slate-400/70",   chip: "bg-slate-50 text-slate-700 border-slate-200" },
  "leadership-decision":  { key: "leadership-decision",  label: "Leadership Decision",  Icon: Megaphone,        dot: "bg-orange-500",  stripe: "before:bg-orange-400/70",  chip: "bg-orange-50 text-orange-700 border-orange-200" },
  "general":              { key: "general",              label: "General",              Icon: Sparkles,         dot: "bg-slate-400",   stripe: "before:bg-slate-300/70",   chip: "bg-slate-50 text-slate-700 border-slate-200" },
};

export function categoryMeta(key: MessageCategory): CategoryMeta {
  return CATEGORY_META[key];
}

// Icon set for priority badges — kept separate from category icons.
export const PRIORITY_ICON: Record<"Critical" | "Urgent" | "Important" | "Normal", LucideIcon> = {
  Critical:  AlertOctagon,
  Urgent:    AlertTriangle,
  Important: CheckCircle2,
  Normal:    CheckCircle2,
};
