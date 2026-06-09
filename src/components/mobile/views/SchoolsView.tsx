"use client";

import { useState } from "react";
import {
  Phone,
  Circle,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import { SchoolsIntelligence } from "@/components/schools/SchoolsIntelligence";
import { type SchoolRow } from "@/lib/schools-mock";
import {
  stAgnesBrief,
} from "@/lib/mobile-mock";
import { cn } from "@/lib/utils";

// Lighter, mobile-tighter cadence chips: thin border, light tint, no
// drop shadow. We deliberately don't reach for the global
// `premium-badge-*` palette here — at 22px / 800-weight / tinted-fill
// they screamed when stacked next to three rows of task text. The
// smaller h-[18px] / 600-weight / muted-fill reads as a refined
// metadata chip — the task itself stays the headline.
const CADENCE_PILL: Record<string, string> = {
  "This Week":  "bg-rose-50 text-rose-700 border-rose-100",
  "This Month": "bg-amber-50 text-amber-700 border-amber-100",
  "Next Month": "bg-sky-50 text-sky-700 border-sky-100",
};

export function SchoolsView({ intelligenceSchools = [] }: { intelligenceSchools?: SchoolRow[] } = {}) {
  return (
    <MobileShell>
      <MobileTopBar backHref="/dashboard" />

      <main className="flex-1 px-3 py-3 space-y-3 pb-24">
        {/* Intelligence hero — same component the desktop renders.
            Three purpose-built tabs that answer the questions a CCEO
            opens this page to ask, ranked from real SSA + operational
            state via lib/schools-intelligence. */}
        <SchoolsIntelligence schools={intelligenceSchools} />

        {/* School Brief — focused detail card */}
        <section className="rounded-2xl bg-[var(--color-card)] border border-[var(--border-danger)] shadow-sm overflow-hidden">
          <div className="p-3 border-b border-[var(--border-subtle)] flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="text-body-lg font-extrabold tracking-tight leading-tight truncate">{stAgnesBrief.schoolName}</div>
              <div className="text-[11px] muted">{stAgnesBrief.district} District</div>
            </div>
            <span className="premium-badge premium-badge-danger">
              {stAgnesBrief.performance}
            </span>
          </div>

          {/* Contact row */}
          <div className="grid grid-cols-2 gap-3 p-3 text-[12px]">
            <div>
              <div className="text-caption muted font-semibold uppercase tracking-wide">Contact Person</div>
              <div className="font-bold mt-1">{stAgnesBrief.contactName} <span className="muted font-medium">{stAgnesBrief.contactRole}</span></div>
              <a href={`tel:${stAgnesBrief.contactPhone}`} className="inline-flex items-center gap-1 text-emerald-600 font-semibold mt-0.5">
                <Phone size={11} />
                {stAgnesBrief.contactPhone}
              </a>
            </div>
            <div>
              <div className="text-caption muted font-semibold uppercase tracking-wide">District</div>
              <div className="font-bold mt-1">{stAgnesBrief.district}</div>
            </div>
            <div>
              <div className="text-caption muted font-semibold uppercase tracking-wide">SSA Weakest Intervention</div>
              <div className="font-bold mt-1">{stAgnesBrief.ssaWeakestIntervention}</div>
            </div>
            <div>
              <div className="text-caption muted font-semibold uppercase tracking-wide">Recommended Training</div>
              <div className="font-bold mt-1">{stAgnesBrief.recommendedTraining}</div>
            </div>
            <div>
              <div className="text-caption muted font-semibold uppercase tracking-wide">Latest Visit</div>
              <div className="font-bold mt-1">{stAgnesBrief.latestVisit.date} <span className="muted font-medium">({stAgnesBrief.latestVisit.ago})</span></div>
            </div>
            <div>
              <div className="text-caption muted font-semibold uppercase tracking-wide">Last Training</div>
              <div className="font-bold mt-1">{stAgnesBrief.lastTraining.date} <span className="muted font-medium">({stAgnesBrief.lastTraining.ago})</span></div>
            </div>
          </div>

          {/* Pending tasks. Premium row: a muted ring (open task) instead
              of an emerald solid circle (which read as "done"), the task
              label as the headline, and a refined cadence chip on the
              right. The chip color signals urgency without yelling. */}
          <div className="border-t border-[var(--border-subtle)] px-3 py-2.5">
            <div className="text-[12px] font-extrabold tracking-tight mb-2">Pending Tasks</div>
            <ul className="space-y-2">
              {stAgnesBrief.pendingTasks.map((t) => (
                <li key={t.id} className="flex items-center gap-2 text-body">
                  <Circle size={11} className="text-[var(--color-edify-muted)]/60 shrink-0" />
                  <span className="flex-1 leading-tight">{t.label}</span>
                  <span className={cn(
                    "inline-flex items-center h-[18px] px-1.5 rounded-md border text-[10.5px] font-semibold whitespace-nowrap shrink-0",
                    CADENCE_PILL[t.cadence],
                  )}>
                    {t.cadence}
                  </span>
                </li>
              ))}
            </ul>
          </div>

        </section>
      </main>

      <MobileBottomNav />
    </MobileShell>
  );
}
