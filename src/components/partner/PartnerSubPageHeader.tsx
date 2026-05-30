"use client";

// PartnerSubPageHeader — shared header used by every partner sub-page
// (My Activities, My Schools, Planning, Evidence, Reports, Inbox/[tab]).
// Accepts icon NAMES (strings) — not components — so server pages can
// describe their KPI strip + filters across the server→client
// boundary without tripping the "Functions cannot be passed to Client
// Components" rule.

import Link from "next/link";
import {
  ArrowLeft, Calendar, Filter, Activity, AlertTriangle, AlertOctagon,
  CalendarCheck, CalendarRange, Building2, TrendingUp, ListChecks,
  Upload, RotateCcw, Clock, ShieldCheck, FileText, Send, Sparkles,
  Inbox, Users, type LucideIcon,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { cn } from "@/lib/utils";

export type IconKey =
  | "calendar" | "filter" | "activity" | "alert" | "alert-oct"
  | "cal-check" | "cal-range" | "building" | "trending" | "checks"
  | "upload" | "rotate" | "clock" | "shield" | "file"
  | "send" | "sparkles" | "inbox" | "users";

const ICONS: Record<IconKey, LucideIcon> = {
  "calendar":  Calendar,
  "filter":    Filter,
  "activity":  Activity,
  "alert":     AlertTriangle,
  "alert-oct": AlertOctagon,
  "cal-check": CalendarCheck,
  "cal-range": CalendarRange,
  "building":  Building2,
  "trending":  TrendingUp,
  "checks":    ListChecks,
  "upload":    Upload,
  "rotate":    RotateCcw,
  "clock":     Clock,
  "shield":    ShieldCheck,
  "file":      FileText,
  "send":      Send,
  "sparkles":  Sparkles,
  "inbox":     Inbox,
  "users":     Users,
};

export type PartnerSubKpi = {
  label: string;
  value: string | number;
  caption?: string;
  iconKey?: IconKey;
  tone?: "neutral" | "good" | "warn" | "danger";
};

export type PartnerSubFilter = { iconKey: IconKey; label: string };

export function PartnerSubPageHeader({
  title,
  subtitle,
  filters,
  kpis,
}: {
  title: string;
  subtitle: string;
  filters?: PartnerSubFilter[];
  kpis?: PartnerSubKpi[];
}) {
  // Resolve filter icons on the client side so the server page only
  // has to ship strings.
  const pageHeaderFilters = filters?.map((f) => ({
    Icon: ICONS[f.iconKey],
    label: f.label,
  }));

  return (
    <>
      <PageHeader
        title={title}
        subtitle={subtitle}
        filters={pageHeaderFilters}
      />
      <div className="px-4 sm:px-5 md:px-6">
        <Link
          href="/dashboards/partner"
          className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]"
        >
          <ArrowLeft size={12} />
          Back to Partner
        </Link>
      </div>
      {kpis && kpis.length > 0 && (
        <div className="px-4 sm:px-5 md:px-6 mt-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {kpis.map((k, i) => (
              <KpiTile key={k.label} kpi={k} stagger={`stagger-${i + 1}`} />
            ))}
          </div>
        </div>
      )}
    </>
  );
}

const TONE: Record<NonNullable<PartnerSubKpi["tone"]>, { bg: string; text: string; ring: string }> = {
  neutral: { bg: "bg-[var(--color-edify-soft)]",    text: "text-[var(--color-edify-primary)]", ring: "ring-1 ring-[var(--color-edify-divider)]" },
  good:    { bg: "bg-emerald-50",                    text: "text-emerald-700",                  ring: "ring-1 ring-emerald-100" },
  warn:    { bg: "bg-amber-50",                      text: "text-amber-700",                    ring: "ring-1 ring-amber-100" },
  danger:  { bg: "bg-rose-50",                       text: "text-rose-700",                     ring: "ring-1 ring-rose-100" },
};

// Maps tone to a subtle text-shadow halo behind the hero number.
// Matches the system .glow-* utilities so the colour stays consistent
// with the rest of the dashboard.
const GLOW: Record<NonNullable<PartnerSubKpi["tone"]>, string> = {
  neutral: "glow-slate",
  good:    "glow-emerald",
  warn:    "glow-amber",
  danger:  "glow-rose",
};

function KpiTile({ kpi, stagger }: { kpi: PartnerSubKpi; stagger?: string }) {
  const t = TONE[kpi.tone ?? "neutral"];
  const Icon = kpi.iconKey ? ICONS[kpi.iconKey] : null;
  return (
    <div className={cn(
      // .card-elevated brings the inner top-light highlight + 4-layer
      // floating shadow; .card-lift adds the 2px lift on hover (a
      // proper desktop affordance) and pressable handles touch.
      "card-elevated card-lift pressable rounded-2xl p-3.5 md:p-4 tile-in",
      stagger,
    )}>
      <div className="flex items-start justify-between gap-2">
        {/* line-clamp-2 (not truncate) so labels like "On hold /
            returned" survive the narrow 2-col phone grid without
            losing characters to an ellipsis. */}
        <span className="text-[10px] uppercase tracking-[0.08em] font-extrabold text-[var(--color-edify-muted)] leading-tight line-clamp-2 min-h-[24px]">
          {kpi.label}
        </span>
        {Icon && (
          <span className={cn("grid place-items-center h-7 w-7 rounded-md shrink-0", t.bg, t.text, t.ring)}>
            <Icon size={13} />
          </span>
        )}
      </div>
      <div className={cn(
        "text-[22px] md:text-[26px] font-extrabold num-hero text-[var(--color-edify-text)] leading-none mt-2",
        GLOW[kpi.tone ?? "neutral"],
      )}>
        {kpi.value}
      </div>
      {kpi.caption && (
        <div className="text-[11px] muted mt-1.5 line-clamp-2">{kpi.caption}</div>
      )}
    </div>
  );
}
