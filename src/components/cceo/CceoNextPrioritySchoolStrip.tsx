"use client";

import Link from "next/link";
import {
  ArrowRight,
  Building2,
  CalendarCheck,
  CalendarClock,
  Phone,
  School2,
  Target,
  User,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { cceoNextPrioritySchool } from "@/lib/cceo-mock";

// Full-width spotlight strip — one school the CCEO is expected to
// focus on next. Avatar block on the left, name + cluster header in
// the middle, four meta columns to the right (Contact / Weakness /
// Focus / Visits). Acts as the bridge between the dashboard's read
// surface (cards) and the "what do I do today" act surface.
export function CceoNextPrioritySchoolStrip() {
  const s = cceoNextPrioritySchool;
  return (
    <SectionCard
      icon={<School2 size={13} />}
      title="Quick Context"
      subtitle="Next Priority School"
      actions={
        <Link
          href="/schools"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          Open school
          <ArrowRight size={11} />
        </Link>
      }
    >
      <div className="grid grid-cols-1 md:grid-cols-[auto_1.4fr_repeat(4,minmax(0,1fr))] gap-4 items-center">
        {/* Avatar + school name + cluster */}
        <div className="flex items-center gap-3 md:contents">
          <span className="w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-700 text-white grid place-items-center shrink-0 shadow-[0_4px_12px_-2px_rgba(16,185,129,0.45)]">
            <School2 size={22} />
          </span>
          <div className="min-w-0">
            <div className="text-body-lg font-extrabold leading-tight text-slate-900 truncate">
              {s.schoolName}
            </div>
            <div className="text-[11px] muted leading-tight inline-flex items-center gap-1 mt-0.5">
              <Building2 size={10} />
              {s.cluster}
            </div>
          </div>
        </div>

        <MetaCol
          icon={User}
          label="Contact Person"
          value={`${s.contactPerson.name} (${s.contactPerson.role})`}
          sub={s.contactPerson.phone}
          subIcon={Phone}
        />
        <MetaCol
          icon={Target}
          label="Weakest Intervention"
          value={s.weakestIntervention}
          tone="warn"
        />
        <MetaCol
          icon={CalendarCheck}
          label="Recommended Focus"
          value={s.recommendedFocus}
        />
        <MetaCol
          icon={CalendarClock}
          label="Visits"
          value={`Last: ${s.lastVisit}`}
          sub={`Next planned: ${s.nextPlannedVisit}`}
        />
      </div>
    </SectionCard>
  );
}

// ───────────── MetaCol ─────────────

function MetaCol({
  icon: Icon,
  label,
  value,
  sub,
  subIcon: SubIcon,
  tone = "neutral",
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  sub?: string;
  subIcon?: LucideIcon;
  tone?: "neutral" | "warn";
}) {
  return (
    <div className="min-w-0">
      <div className="text-[9.5px] font-bold uppercase tracking-wide text-slate-500 inline-flex items-center gap-1">
        <Icon size={10} />
        {label}
      </div>
      <div className={
        tone === "warn"
          ? "text-body font-bold text-rose-700 leading-snug mt-1"
          : "text-body font-bold text-slate-900 leading-snug mt-1"
      }>
        {value}
      </div>
      {sub && (
        <div className="text-[11px] muted font-semibold mt-0.5 inline-flex items-center gap-1">
          {SubIcon && <SubIcon size={10} />}
          {sub}
        </div>
      )}
    </div>
  );
}
