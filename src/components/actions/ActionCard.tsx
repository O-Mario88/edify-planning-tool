"use client";

// ActionCard — the smallest atom of the 10-Second Command System.
//
// Used by:
//   • NextThreeActionsRow (large variant — the hero decisions)
//   • UnifiedInbox        (compact variant — rows in the queue)
//
// Single source-of-truth for how an ActionItem renders. Keeps the
// language consistent: same risk-dot scale, same CTA placement, same
// "why this matters" body copy treatment.

import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { ArrowRight, ShieldCheck, AlertTriangle, ShieldAlert, type LucideIcon } from "lucide-react";
import type { ActionItem, RiskLevel, ApprovalSafety } from "@/lib/actions/action-types";
import { cn } from "@/lib/utils";
import { spring } from "@/lib/motion";

// Risk → dot colour. Same scale used by every other risk pill in the
// app so users only learn the language once.
const RISK_DOT: Record<RiskLevel, string> = {
  Critical: "bg-rose-500",
  High:     "bg-orange-500",
  Medium:   "bg-amber-500",
  Low:      "bg-emerald-500",
};

// Safety badge — small chip in the header so a user can scan a list
// and know which ones are safe to bulk-approve.
const SAFETY_BADGE: Record<ApprovalSafety, { label: string; cls: string; Icon: LucideIcon }> = {
  SafeToApprove: { label: "Safe",       cls: "bg-emerald-50 text-emerald-700 border-emerald-200", Icon: ShieldCheck },
  NeedsReview:   { label: "Review",     cls: "bg-amber-50 text-amber-800 border-amber-200",       Icon: AlertTriangle },
  Blocked:       { label: "Blocked",    cls: "bg-rose-50 text-rose-700 border-rose-200",          Icon: ShieldAlert },
};

export type ActionCardVariant = "hero" | "compact";

export function ActionCard({
  item,
  variant = "hero",
  selected,
  onSelect,
}: {
  item: ActionItem;
  variant?: ActionCardVariant;
  selected?: boolean;
  /// Only used by the inbox — when defined, a checkbox is rendered.
  onSelect?: (id: string, next: boolean) => void;
}) {
  const reduce = useReducedMotion();
  const safety = SAFETY_BADGE[item.approvalSafety];
  const isCompact = variant === "compact";

  return (
    <motion.div
      whileHover={reduce ? undefined : { y: -2, transition: spring.hover }}
      className={cn(
        "rounded-2xl border bg-white",
        selected
          ? "border-[var(--color-edify-primary)] ring-2 ring-[var(--color-edify-primary)]/30"
          : "border-[var(--color-edify-divider)]",
        isCompact ? "p-3" : "p-4",
      )}
    >
      <div className="flex items-start gap-2.5">
        {onSelect ? (
          <input
            type="checkbox"
            checked={!!selected}
            disabled={item.approvalSafety === "Blocked"}
            onChange={(e) => onSelect(item.id, e.target.checked)}
            className="mt-1 h-4 w-4 rounded border-[var(--color-edify-border)] accent-[var(--color-edify-primary)] disabled:opacity-40"
            aria-label={`Select ${item.title}`}
          />
        ) : (
          <span
            className={cn("mt-1.5 inline-block h-2 w-2 rounded-full shrink-0", RISK_DOT[item.riskLevel])}
            aria-label={`Risk: ${item.riskLevel}`}
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={cn(
                "inline-flex items-center gap-1 px-1.5 py-[1.5px] rounded-md border text-[10px] font-bold uppercase tracking-wide",
                safety.cls,
              )}
            >
              <safety.Icon size={10} />
              {safety.label}
            </span>
            {item.dueDate ? (
              <span className="text-caption font-semibold text-[var(--color-edify-muted)]">
                Due {formatDue(item.dueDate)}
              </span>
            ) : null}
          </div>
          <h3 className={cn(
            "font-extrabold tracking-tight text-[var(--color-edify-text)] mt-1.5 leading-snug",
            isCompact ? "text-[13px]" : "text-[15px]",
          )}>
            {item.title}
          </h3>
          <p className={cn(
            "text-[var(--color-edify-muted)] mt-1 leading-snug",
            isCompact ? "text-[12px] line-clamp-2" : "text-body",
          )}>
            {item.description}
          </p>
          <div className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-[var(--color-edify-muted)]">
            <span className="font-semibold">{item.affectedEntity.label}</span>
          </div>
          {/* Action row — must hold up at three column widths:
              • mobile (cards stack 1-col): plenty of room, side-by-side reads natural
              • md (3-col grid, each card ≈230px): NOT enough room for two
                inline buttons with long labels — they wrap inside the
                button ("Open / coaching plan" on two lines, arrow squished)
              • lg+: full room again, side-by-side
              Strategy: stack vertically + full-width on mobile and md,
              flip to inline at lg. `whitespace-nowrap` on each CTA kills
              the in-button line break that caused the original ugliness. */}
          <div className={cn(
            "flex flex-col lg:flex-row lg:items-center lg:flex-wrap gap-2 mt-3",
            isCompact && "mt-2.5",
          )}>
            <PrimaryCTA href={item.primaryAction.href} label={item.primaryAction.label} disabled={item.approvalSafety === "Blocked"} />
            {item.secondaryAction ? (
              <SecondaryCTA href={item.secondaryAction.href} label={item.secondaryAction.label} />
            ) : !isCompact ? (
              <SecondaryCTA
                href={defaultDetailHref(item.affectedEntity)}
                label={defaultDetailLabel(item.affectedEntity.kind)}
              />
            ) : null}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// CTA sizing rules:
//   • `w-full lg:w-auto` — stacked buttons take the full card width on
//     mobile/tablet so they read as clear horizontal pills; revert to
//     content width at lg where the row layout returns.
//   • `justify-center lg:justify-start` — center the label when the
//     button is full-width (balanced), left-align when content-width.
//   • `whitespace-nowrap` — never break a label mid-word inside the
//     button. If a label doesn't fit, the layout above handles it by
//     stacking — never by mangling the label.
//   • `h-9` (was h-8) — a hair taller for premium feel + WCAG min
//     touch target on the stacked mobile/tablet shape.
const CTA_SIZE = "h-9 px-3.5 w-full lg:w-auto justify-center lg:justify-start whitespace-nowrap";

function PrimaryCTA({ href, label, disabled }: { href?: string; label: string; disabled?: boolean }) {
  if (disabled) {
    return (
      <span className={cn("inline-flex items-center gap-1 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] text-[12px] font-bold cursor-not-allowed", CTA_SIZE)}>
        {label}
      </span>
    );
  }
  const inner = (
    <>
      {label}
      <ArrowRight size={12} />
    </>
  );
  const cls = cn("inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors", CTA_SIZE);
  return href ? (
    <Link href={href} className={cls}>{inner}</Link>
  ) : (
    <button type="button" className={cls}>{inner}</button>
  );
}

function SecondaryCTA({ href, label }: { href?: string; label: string }) {
  const cls = cn("inline-flex items-center rounded-lg border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60 transition-colors", CTA_SIZE);
  return href ? <Link href={href} className={cls}>{label}</Link> : <button type="button" className={cls}>{label}</button>;
}

// Fallback secondary CTA (hero variant only) — when an action doesn't
// declare its own secondary action, render a deterministic "View"
// affordance routed to the affected entity. Keeps the 3-card row
// visually consistent: every card has primary + secondary.
function defaultDetailHref(e: ActionItem["affectedEntity"]): string {
  switch (e.kind) {
    case "School":   return `/schools#${e.id}`;
    case "Plan":     return `/plans#${e.id}`;
    case "Fund":     return `/disbursements#${e.id}`;
    case "Activity": return `/visits#${e.id}`;
    case "Staff":    return `/my-team#${e.id}`;
    case "District": return `/districts#${e.id}`;
    case "Country":  return `/dashboards#${e.id}`;
    case "System":   return `/notifications`;
  }
}

function defaultDetailLabel(kind: ActionItem["affectedEntity"]["kind"]): string {
  switch (kind) {
    case "School":   return "Open school";
    case "Plan":     return "View Plan";
    case "Fund":     return "View slip";
    case "Activity": return "View activity";
    case "Staff":    return "Open Profile";
    case "District": return "Open District";
    case "Country":  return "View Dashboard";
    case "System":   return "View Details";
  }
}

function formatDue(iso: string): string {
  const due = new Date(iso);
  const today = new Date();
  const diffDays = Math.round((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays < 0) return `${Math.abs(diffDays)}d overdue`;
  if (diffDays === 0) return "today";
  if (diffDays === 1) return "tomorrow";
  if (diffDays < 7) return `in ${diffDays}d`;
  return due.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
