"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  ClipboardList,
  Inbox,
  Layers,
  ShieldAlert,
  Telescope,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useSetPageTitle } from "@/components/shell/PageTitleContext";
import { MobileCollapsibleSection } from "@/components/mobile/views/MobileSubpageShell";
import { AggregatedFieldContextCard } from "@/components/field-intelligence/AggregatedFieldContextCard";
import { BestPerformersCard } from "@/components/leaderboard/BestPerformersCard";
import type { AggregatedFieldContext } from "@/lib/field-intelligence-mock";

type HrAlert = {
  href:    string;
  tone:    "rose" | "amber" | "blue";
  title:   string;
  body:    string;
  cta:     string;
  Icon:    LucideIcon;
};

const HR_ALERTS: HrAlert[] = [
  {
    href:  "/team-targets?view=reviews",
    tone:  "rose",
    title: "3 HR decisions awaiting your call",
    body:  "Escalations routed from CD / RVP — review and resolve.",
    cta:   "Open decisions",
    Icon:  Inbox,
  },
  {
    href:  "/team-targets?view=support",
    tone:  "amber",
    title: "4 staff flagged for support",
    body:  "Workload, route difficulty, repeated requests — needs HR + PL review.",
    cta:   "Review staff",
    Icon:  ShieldAlert,
  },
  {
    href:  "/team-targets?view=reviews-due",
    tone:  "blue",
    title: "6 performance reviews due this month",
    body:  "Across 5 program leads — schedule a window with each PL.",
    cta:   "Open review queue",
    Icon:  ClipboardList,
  },
];

const TONE_FRAME: Record<HrAlert["tone"], string> = {
  rose:  "bg-rose-50 border-rose-200",
  amber: "bg-amber-50 border-amber-200",
  blue:  "bg-blue-50 border-blue-200",
};
const TONE_ICON: Record<HrAlert["tone"], string> = {
  rose:  "bg-rose-100 text-rose-700",
  amber: "bg-amber-100 text-amber-800",
  blue:  "bg-blue-100 text-blue-800",
};
const TONE_TITLE: Record<HrAlert["tone"], string> = {
  rose:  "text-rose-900",
  amber: "text-amber-900",
  blue:  "text-blue-900",
};

type HrKpi = {
  href:    string;
  label:   string;
  value:   string;
  caption: string;
  Icon:    LucideIcon;
  tint:    "edify" | "amber" | "red" | "violet";
};

const HR_KPIS: HrKpi[] = [
  { href: "/team-targets?view=reviews",      label: "Active Performance Reviews", value: "12", caption: "Across 5 program leads",    Icon: ClipboardList,  tint: "edify"  },
  { href: "/team-targets?view=support",      label: "Staff Flagged for Support",  value: "4",  caption: "Requires HR + PL review",   Icon: AlertTriangle,  tint: "amber"  },
  { href: "/team-targets?view=hr-decisions", label: "Open HR Decisions",          value: "3",  caption: "Routed from CD / RVP",      Icon: Inbox,          tint: "red"    },
  { href: "/field-intelligence",             label: "Aggregated Barriers",        value: "18", caption: "Field signals this month",  Icon: Layers,         tint: "violet" },
];

const TINT_BG: Record<HrKpi["tint"], string> = {
  edify:  "bg-[var(--color-edify-soft)]/70 text-[var(--color-edify-primary)]",
  amber:  "bg-amber-50 text-amber-700",
  red:    "bg-rose-50 text-rose-700",
  violet: "bg-violet-50 text-violet-700",
};

const QUICK_ACTIONS = [
  { href: "/team-targets",       title: "Open performance review queue", subtitle: "Reviews routed by Program Leads",  Icon: Users        },
  { href: "/team-targets",       title: "Review staff support signals",  subtitle: "Flagged staff & support requests", Icon: ShieldAlert  },
  { href: "/field-intelligence", title: "Aggregated field intelligence", subtitle: "Country-level patterns & themes",  Icon: Telescope    },
];

export function HrMobileView({ ctx }: { ctx: AggregatedFieldContext }) {
  useSetPageTitle("People & Performance");

  return (
    <div className="px-3 sm:px-4 pt-3 pb-28 space-y-3">
      <section className="space-y-2.5">
        {HR_ALERTS.map((a) => (
          <Link
            key={a.title}
            href={a.href}
            className={`block rounded-2xl border px-3 py-2.5 ${TONE_FRAME[a.tone]}`}
          >
            <div className="flex items-start gap-2.5">
              <span className={`w-8 h-8 rounded-md grid place-items-center mt-0.5 shrink-0 ${TONE_ICON[a.tone]}`}>
                <a.Icon size={14} />
              </span>
              <div className="flex-1 min-w-0">
                <div className={`text-[13px] font-extrabold leading-tight ${TONE_TITLE[a.tone]}`}>
                  {a.title}
                </div>
                <div className="text-[11.5px] muted mt-1 leading-snug">{a.body}</div>
                <span className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] mt-1.5">
                  {a.cta}
                  <ArrowRight size={11} />
                </span>
              </div>
            </div>
          </Link>
        ))}
      </section>

      <section className="grid grid-cols-2 gap-2.5">
        {HR_KPIS.map((k) => (
          <Link
            key={k.label}
            href={k.href}
            className="card rounded-2xl p-3 hover:bg-[var(--color-edify-soft)]/30 transition-colors"
          >
            <div className="flex items-center gap-2 mb-1.5">
              <span className={`w-7 h-7 rounded-md grid place-items-center ${TINT_BG[k.tint]}`}>
                <k.Icon size={13} />
              </span>
              <span className="text-caption font-bold uppercase tracking-wider muted leading-tight">
                {k.label}
              </span>
            </div>
            <div className="text-[22px] font-extrabold tabular leading-none">{k.value}</div>
            <div className="text-caption muted mt-1 leading-snug">{k.caption}</div>
          </Link>
        ))}
      </section>

      <MobileCollapsibleSection title="Best performers" defaultOpen={false}>
        <BestPerformersCard audience="hr" />
      </MobileCollapsibleSection>

      <MobileCollapsibleSection title="Field intelligence (aggregated)" defaultOpen={false}>
        <AggregatedFieldContextCard
          ctx={ctx}
          title="Country field intelligence"
          subtitle="Barriers · support themes · team health · open decisions."
        />
      </MobileCollapsibleSection>

      <section className="space-y-2">
        <div className="text-[11px] font-bold uppercase tracking-wider muted px-1">Quick actions</div>
        {QUICK_ACTIONS.map((a) => (
          <Link
            key={a.title}
            href={a.href}
            className="card rounded-2xl p-3 flex items-center gap-3"
          >
            <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
              <a.Icon size={15} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-extrabold tracking-tight truncate">{a.title}</div>
              <div className="text-[11.5px] muted truncate">{a.subtitle}</div>
            </div>
            <ArrowRight size={13} className="text-[var(--color-edify-muted)] shrink-0" />
          </Link>
        ))}
      </section>
    </div>
  );
}
