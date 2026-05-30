"use client";

// PartnerPriorityActions — the 3 cards under "Top 3 Priority Actions".
// Each card is the partner's most important call-to-action this week:
// what's the activity, which school it's tied to, when it's due, the
// reason it's urgent, what's required, and two CTAs (primary action +
// secondary view).

import Link from "next/link";
import { Calendar, Building2, AlertTriangle, FileText, ArrowRight } from "lucide-react";
import type { PartnerPriorityAction } from "@/lib/partner/partner-dashboard-mock";

const PRIORITY_TONE: Record<PartnerPriorityAction["priority"], { bg: string; text: string; dot: string }> = {
  HIGH:   { bg: "bg-rose-50",  text: "text-rose-700",  dot: "bg-rose-500"  },
  MEDIUM: { bg: "bg-amber-50", text: "text-amber-700", dot: "bg-amber-500" },
};

export function PartnerPriorityActions({ actions }: { actions: PartnerPriorityAction[] }) {
  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-[15px] font-extrabold tracking-tight">Top 3 Priority Actions</h2>
          <p className="text-[12px] muted mt-0.5">These actions need your attention this week.</p>
        </div>
        <Link
          href="#all-actions"
          className="text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline inline-flex items-center gap-1"
        >
          View All actions <ArrowRight size={11} />
        </Link>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {actions.map((a) => (
          <ActionCard key={a.id} action={a} />
        ))}
      </div>
    </section>
  );
}

function ActionCard({ action: a }: { action: PartnerPriorityAction }) {
  const tone = PRIORITY_TONE[a.priority];
  return (
    <article className="card p-3.5 flex flex-col">
      <div className="flex items-center justify-between mb-2.5">
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-[3px] rounded-md text-[10px] font-extrabold uppercase tracking-wide ${tone.bg} ${tone.text}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${tone.dot}`} />
          {a.priority} Priority
        </span>
        <span className="text-caption font-semibold muted">{a.dueLabel}</span>
      </div>

      <h3 className="text-[14.5px] font-extrabold tracking-tight leading-tight">{a.activityTitle}</h3>
      <p className="text-[12px] muted mt-0.5">{a.activityType}</p>

      <div className="mt-3 space-y-1.5 text-[12px]">
        <Row Icon={Building2} primary={a.schoolName} secondary={a.districtSub} />
        <Row Icon={Calendar} primary={a.dueDateLabel} />
        <Row Icon={AlertTriangle} primary={<><span className="font-semibold">Reason:</span> {a.reason}</>} tone="warn" />
        <Row Icon={FileText} primary={<><span className="font-semibold">Requires:</span> {a.requires}</>} />
      </div>

      <div className="mt-auto pt-4 flex items-center gap-2">
        <Link
          href={a.primaryCta.href}
          className="flex-1 inline-flex items-center justify-center gap-1.5 h-9 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold hover:bg-[var(--color-edify-dark)] transition-colors"
        >
          {a.primaryCta.label}
        </Link>
        <Link
          href={a.secondaryCta.href}
          className="inline-flex items-center justify-center h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-card)] text-[var(--color-edify-text)] text-[12px] font-semibold hover:bg-[var(--color-edify-soft)] transition-colors"
        >
          {a.secondaryCta.label}
        </Link>
      </div>
    </article>
  );
}

function Row({
  Icon, primary, secondary, tone,
}: {
  Icon: typeof Calendar;
  primary: React.ReactNode;
  secondary?: React.ReactNode;
  tone?: "warn";
}) {
  return (
    <div className="flex items-start gap-2">
      <span className={`mt-0.5 ${tone === "warn" ? "text-rose-500" : "text-[var(--color-edify-muted)]"} shrink-0`}>
        <Icon size={12} />
      </span>
      <div className="min-w-0 flex-1">
        <div className={`text-[12px] leading-snug ${tone === "warn" ? "text-rose-700" : "text-[var(--color-edify-text)]"}`}>
          {primary}
        </div>
        {secondary && <div className="text-[11px] muted mt-0.5">{secondary}</div>}
      </div>
    </div>
  );
}
