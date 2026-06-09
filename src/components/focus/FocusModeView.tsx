"use client";

// Focus Mode — the field user's stripped-down view.
//
// The product principle: when staff are in the field, the app should
// give them ONE thing to do, not seventeen tabs. No charts. No
// analytics. No deep navigation. Just:
//
//   • Today's school
//   • Activity purpose
//   • Distance / route hint
//   • Start visit
//   • Upload Evidence
//   • Submit Debrief
//   • Next school
//
// Variant for Partner users:
//
//   • Assigned training/visit
//   • Attendance capture
//   • Evidence upload
//   • Submit report
//   • Returned corrections (if any)
//
// Reuses the existing 10-Second Command pattern — the visual chrome
// is deliberately spare so the eye locks onto the primary CTA.

import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import {
  MapPin, Camera, FileText, ArrowRight, CheckCircle2, Compass,
  Upload, ClipboardCheck, Users as UsersIcon,
} from "lucide-react";
import type { FocusStep } from "./focus-composers";
import { spring } from "@/lib/motion";

export type FocusVariant = "cceo" | "partner";

const ICON: Record<FocusStep["icon"], typeof MapPin> = {
  compass: Compass, camera: Camera, file: FileText, upload: Upload,
  check: CheckCircle2, users: UsersIcon, mapPin: MapPin, clipboardCheck: ClipboardCheck,
};

export function FocusModeView({
  greeting,
  primaryStop,
  steps,
  nextUp,
  variant,
}: {
  /// "Good morning, Paul." — same hour-aware greeting as the rest of the app.
  greeting: string;
  /// The school / training the user is focused on right now.
  primaryStop: {
    schoolName: string;
    districtName?: string;
    purpose: string;        // "In-School coaching · Foundational Literacy"
    distanceLabel?: string; // "12 km · 18 min drive"
    /// Partner field officers: evidence they need to capture today.
    requiredEvidence?: string[];
    startCta: { label: string; href: string };
  };
  /// 3-5 steps for the field workflow. UI walks down them.
  steps: FocusStep[];
  /// Next school in the route — shown as a quiet "after this" card.
  nextUp?: { schoolName: string; whenLabel: string; href: string };
  variant: FocusVariant;
}) {
  const reduce = useReducedMotion();
  return (
    <div className="space-y-4 max-w-[640px] mx-auto px-3 sm:px-4 py-4">
      {/* Greeting + focus chip */}
      <header className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-full bg-emerald-100 text-emerald-800 text-[10px] font-extrabold uppercase tracking-[0.12em]">
          <Compass size={11} />
          Focus mode · {variant === "cceo" ? "Field" : "Partner"}
        </span>
        <p className="text-body text-[var(--color-edify-muted)] truncate">{greeting}</p>
      </header>

      {/* The primary stop — the one thing the user is doing now */}
      <motion.section
        initial={reduce ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={reduce ? { duration: 0 } : spring.soft}
        className="rounded-3xl bg-[var(--color-edify-deep)] text-white p-5"
      >
        <div className="text-caption uppercase tracking-[0.12em] text-white/70 font-extrabold">
          {variant === "cceo" ? "Today's school" : "Today's activity"}
        </div>
        <h1 className="text-[22px] sm:text-[26px] font-extrabold tracking-tight mt-1 leading-tight">
          {primaryStop.schoolName}
        </h1>
        {primaryStop.districtName ? (
          <p className="text-body text-white/80 mt-0.5">{primaryStop.districtName}</p>
        ) : null}
        <p className="text-[13.5px] font-semibold mt-3 text-white/95 leading-snug">{primaryStop.purpose}</p>
        {primaryStop.distanceLabel ? (
          <p className="inline-flex items-center gap-1 mt-2 text-[11px] text-white/80">
            <MapPin size={11} /> {primaryStop.distanceLabel}
          </p>
        ) : null}
        {primaryStop.requiredEvidence && primaryStop.requiredEvidence.length > 0 ? (
          <div className="mt-3 rounded-xl bg-white/10 border border-white/15 backdrop-blur px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-[0.12em] font-extrabold text-white/70 mb-1.5">
              Required evidence
            </div>
            <ul className="grid grid-cols-2 gap-x-2 gap-y-1">
              {primaryStop.requiredEvidence.map((item) => (
                <li key={item} className="text-[11.5px] text-white/90 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <Link
          href={primaryStop.startCta.href}
          className="inline-flex items-center gap-1.5 mt-4 h-10 px-4 rounded-xl bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[13.5px] font-extrabold transition-colors"
        >
          {primaryStop.startCta.label}
          <ArrowRight size={14} />
        </Link>
      </motion.section>

      {/* Step list — the field workflow in order */}
      <section className="space-y-2.5">
        <h2 className="text-caption font-extrabold uppercase tracking-[0.12em] text-[var(--color-edify-muted)] pl-1">
          Your steps
        </h2>
        {steps.map((step) => {
          const Icon = ICON[step.icon];
          return (
            <Link
              key={step.key}
              href={step.cta.href}
              className={`block rounded-2xl border p-3 transition-colors ${
                step.done
                  ? "border-emerald-200 bg-emerald-50/50"
                  : "border-[var(--color-edify-divider)] bg-white hover:bg-[var(--color-edify-soft)]/40"
              }`}
            >
              <div className="flex items-start gap-3">
                <span className={`w-9 h-9 rounded-xl grid place-items-center shrink-0 ${
                  step.done ? "bg-emerald-100 text-emerald-700" : "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]"
                }`}>
                  {step.done ? <CheckCircle2 size={16} /> : <Icon size={16} />}
                </span>
                <div className="flex-1 min-w-0">
                  <p className={`text-body-lg font-extrabold leading-snug ${
                    step.done ? "text-emerald-900" : "text-[var(--color-edify-text)]"
                  }`}>
                    {step.label}
                  </p>
                  <p className="text-[12px] text-[var(--color-edify-muted)] mt-0.5 leading-snug">
                    {step.detail}
                  </p>
                </div>
                <span className={`inline-flex items-center gap-1 h-7 px-2.5 rounded-lg text-[11.5px] font-bold shrink-0 mt-0.5 ${
                  step.done
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-[var(--color-edify-primary)] text-white"
                }`}>
                  {step.cta.label}
                  <ArrowRight size={11} />
                </span>
              </div>
            </Link>
          );
        })}
      </section>

      {/* Next up — quiet pointer to the after-this stop */}
      {nextUp ? (
        <section className="rounded-2xl border border-[var(--color-edify-divider)] bg-white p-3">
          <p className="text-caption font-extrabold uppercase tracking-[0.12em] text-[var(--color-edify-muted)]">
            After this
          </p>
          <Link
            href={nextUp.href}
            className="mt-1 flex items-center justify-between gap-2"
          >
            <div className="min-w-0">
              <p className="text-[13.5px] font-extrabold text-[var(--color-edify-text)] truncate">
                {nextUp.schoolName}
              </p>
              <p className="text-[11.5px] text-[var(--color-edify-muted)]">{nextUp.whenLabel}</p>
            </div>
            <ArrowRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
          </Link>
        </section>
      ) : null}

      {/* No charts. No analytics. By design. */}
      <p className="text-caption text-[var(--color-edify-muted)] text-center pt-2">
        Focus mode. No charts, no noise. Tap the header bar to switch to the full dashboard.
      </p>
    </div>
  );
}

// Composers live in ./focus-composers.ts (non-client) so the server
// page can call them during SSR.
