"use client";

// 60-second hero for the Country Program Lead dashboard.
//
// First card the CPL sees. Answers "what changed since I last logged
// in?" with a curated, action-first list — instead of dropping the
// user into a generic KPI strip. Items derive from `cpl-engine.ts`
// (real signal where possible) and link directly into the page
// section that owns the follow-up.
//
// Visual contract:
//   • Single full-width card. Dark, premium chrome (gradient backdrop,
//     low-saturation accents) — clearly different from the white
//     SectionCard chrome that fills the rest of the page.
//   • Compact: 4 items max, each one row tall.
//   • Every item has a CTA — no dead content.

import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Send,
  ShieldCheck,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { recentChanges, type ActivityChange } from "@/lib/cpl-engine";
import { cn } from "@/lib/utils";

const ICON: Record<ActivityChange["icon"], LucideIcon> = {
  approval: ClipboardList,
  verify:   CheckCircle2,
  alert:    AlertTriangle,
  submit:   Send,
  fund:     Wallet,
};

const TONE_DOT: Record<ActivityChange["tone"], string> = {
  info:     "bg-sky-500",
  success:  "bg-emerald-500",
  warning:  "bg-amber-500",
  critical: "bg-rose-500",
};

const TONE_TEXT: Record<ActivityChange["tone"], string> = {
  info:     "text-sky-300",
  success:  "text-emerald-300",
  warning:  "text-amber-300",
  critical: "text-rose-300",
};

const TONE_RING: Record<ActivityChange["tone"], string> = {
  info:     "bg-sky-500/15 text-sky-200",
  success:  "bg-emerald-500/15 text-emerald-200",
  warning:  "bg-amber-500/15 text-amber-100",
  critical: "bg-rose-500/15 text-rose-200",
};

export function WhatChangedHero({ firstName }: { firstName?: string }) {
  const items = recentChanges();
  const greet = firstName ? `, ${firstName}` : "";
  return (
    <section
      className="relative rounded-2xl overflow-hidden text-white"
      style={{
        backgroundImage:
          "linear-gradient(135deg, #0e1c2c 0%, #102236 50%, #0a1623 100%)",
      }}
    >
      <div className="absolute inset-0 opacity-[0.08] pointer-events-none" style={{
        backgroundImage:
          "radial-gradient(60% 80% at 100% 0%, #22d3ee 0%, transparent 60%), radial-gradient(40% 60% at 0% 100%, #10b981 0%, transparent 60%)",
      }} />
      <div className="relative p-5 sm:p-6">
        <header className="flex items-start justify-between gap-3 flex-wrap mb-4">
          <div className="min-w-0">
            <div className="inline-flex items-center gap-2 text-[var(--text-caption)] font-bold uppercase tracking-[0.16em] text-white/55">
              <ShieldCheck size={11} />
              60-second briefing
            </div>
            <h1 className="text-[var(--text-h-sm)] sm:text-[var(--text-h-md)] font-extrabold tracking-tight leading-tight mt-1.5">
              Here&apos;s what changed{greet}.
            </h1>
            <p className="text-[var(--text-body)] text-white/65 mt-1 leading-snug max-w-[440px]">
              The few things worth acting on this morning, scoped to your team. Each item links to the surface that owns it.
            </p>
          </div>
          <Link
            href="#approvals"
            className="h-9 px-3 rounded-xl bg-white/[0.10] hover:bg-white/[0.16] border border-white/15 text-[var(--text-body)] font-semibold inline-flex items-center gap-1.5 backdrop-blur shrink-0"
          >
            Open approvals queue
            <ChevronRight size={13} />
          </Link>
        </header>

        {items.length === 0 ? (
          <div className="rounded-xl bg-white/[0.04] border border-white/10 p-4 text-[var(--text-body)] text-white/70 inline-flex items-center gap-2">
            <CheckCircle2 size={14} className="text-emerald-300" />
            Nothing has changed since your last visit. Your Team is on plan.
          </div>
        ) : (
          <ul className="space-y-1.5">
            {items.map((it) => {
              const Icon = ICON[it.icon];
              return (
                <li key={it.id}>
                  <Link
                    href={it.href}
                    className="grid grid-cols-[auto_1fr_auto] items-center gap-3 rounded-xl px-3 py-2.5 bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 transition-colors"
                  >
                    <span className={cn("h-8 w-8 rounded-lg grid place-items-center", TONE_RING[it.tone])}>
                      <Icon size={14} />
                    </span>
                    <div className="min-w-0">
                      <div className="text-[var(--text-body-lg)] font-extrabold tracking-tight leading-tight truncate flex items-center gap-2">
                        <span className={cn("h-1.5 w-1.5 rounded-full", TONE_DOT[it.tone])} aria-hidden />
                        {it.headline}
                      </div>
                      <div className="text-[var(--text-caption)] text-white/55 leading-tight truncate mt-0.5">
                        {it.detail} · <span className={cn("font-semibold", TONE_TEXT[it.tone])}>{it.when}</span>
                      </div>
                    </div>
                    <div className="hidden sm:flex items-center gap-1.5 text-[var(--text-caption)] font-semibold text-white/75 whitespace-nowrap">
                      {it.ctaLabel}
                      <ChevronRight size={12} />
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
