"use client";

import {
  Building2,
  MapPin,
  User,
  CalendarCheck,
  Sparkles,
  ShieldCheck,
  AlertOctagon,
  type LucideIcon,
} from "lucide-react";
import {
  MobileSubpageShell,
  MobileKpiGrid,
  MobileSectionCard,
  type MobileKpiTile,
  type KpiTone,
} from "@/components/mobile/views/MobileSubpageShell";
import { type SchoolRow } from "@/lib/workflow-mock";

const STATUS_TONE: Record<SchoolRow["status"], KpiTone> = {
  "Active":            "green",
  "Becoming Inactive": "amber",
  "Inactive":          "rose",
};

const SEGMENT_TONE: Record<SchoolRow["segment"], KpiTone> = {
  "Core":   "green",
  "Client": "edify",
};

export function SchoolDetailMobileView({ school }: { school: SchoolRow }) {
  const tiles: MobileKpiTile[] = [
    { key: "ssa",      Icon: ShieldCheck,  label: "SSA Score",        value: `${school.ssaScore}%`,                  caption: school.ssaCompleted ? "Completed" : "Pending", tone: school.ssaScore >= 50 ? "green" : school.ssaScore >= 30 ? "amber" : "rose" },
    { key: "segment",  Icon: Sparkles,     label: "Segment",          value: school.segment,                          caption: school.status, tone: SEGMENT_TONE[school.segment] },
    { key: "weakest",  Icon: AlertOctagon, label: "Weakest Area",     value: school.weakestIntervention,             caption: "needs focus", tone: "rose" },
    { key: "visit",    Icon: CalendarCheck,label: "Last Visit",       value: school.lastVisit,                        caption: school.noVisit ? "No visit" : "On record", tone: school.noVisit ? "rose" : "green" },
  ];

  return (
    <MobileSubpageShell
      title={school.name}
      subtitle={`${school.cluster} · ${school.district}`}
    >
      <MobileKpiGrid tiles={tiles} cols={2} />

      <MobileSectionCard title="At a Glance">
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          <DetailRow Icon={Building2} label="School ID" value={school.id} />
          <DetailRow Icon={MapPin}   label="District" value={school.district} />
          <DetailRow Icon={User}     label="CCEO"     value={school.cceo} />
          <DetailRow Icon={User}     label="Partner"  value={school.partner} />
          <DetailRow Icon={CalendarCheck} label="Last visit" value={school.lastVisit} />
        </ul>
      </MobileSectionCard>

      <MobileSectionCard title="Recommended Action" subtitle={school.recommended}>
        <div className="px-3 pb-3 pt-1 flex flex-wrap gap-1.5">
          {school.noVisit && <Tag tone="rose">No visit</Tag>}
          {school.noTraining && <Tag tone="amber">No training</Tag>}
          {!school.ssaCompleted && <Tag tone="violet">SSA incomplete</Tag>}
          <Tag tone={STATUS_TONE[school.status]}>{school.status}</Tag>
          <Tag tone="slate">{school.dataQuality}</Tag>
        </div>
      </MobileSectionCard>
    </MobileSubpageShell>
  );
}

function DetailRow({ Icon, label, value }: { Icon: LucideIcon; label: string; value: string }) {
  return (
    <li className="px-3 py-2.5 flex items-center gap-3">
      <span className="h-7 w-7 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
        <Icon size={13} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-caption muted leading-tight">{label}</div>
        <div className="text-body font-extrabold tracking-tight truncate">{value}</div>
      </div>
    </li>
  );
}

function Tag({ tone, children }: { tone: KpiTone; children: React.ReactNode }) {
  const t =
    tone === "green"  ? "bg-emerald-100 text-emerald-700" :
    tone === "amber"  ? "bg-amber-100   text-amber-700"   :
    tone === "rose"   ? "bg-rose-100    text-rose-700"    :
    tone === "violet" ? "bg-violet-100  text-violet-700"  :
    tone === "blue"   ? "bg-sky-100     text-sky-700"     :
    tone === "edify"  ? "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]" :
                        "bg-slate-100   text-slate-700";
  return (
    <span className={`inline-flex items-center px-2 py-1 rounded-md text-caption font-extrabold ${t}`}>
      {children}
    </span>
  );
}
