"use client";

// PlanIndexAccordion — the /plans listing as an inline accordion.
//
// The previous flow opened every plan in a dedicated `/plans/[id]`
// detail page. Round-trip after round-trip just to read a row's
// Type/Date/Week/Status was friction the planner felt, especially on
// mobile. The accordion shows the same facts inline by expanding the
// row in place. The detail page is kept around for deep-links + edit,
// but the listing now answers the common "what's in this row?"
// question without leaving the page.

import { useState } from "react";
import Link from "next/link";
import {
  Calendar,
  ChevronRight,
  ClipboardList,
  MapPin,
  Pencil,
} from "lucide-react";
import type { PlanItem, PlanItemStatus } from "@/lib/mobile-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<PlanItemStatus, string> = {
  "Planned":        "bg-amber-50    text-amber-700",
  "In Progress":    "bg-blue-50     text-blue-700",
  "Verified":       "bg-emerald-50  text-emerald-700",
  "Awaiting SF ID": "bg-rose-50     text-rose-700",
};

const TYPE_LABEL: Record<PlanItem["type"], string> = {
  "Cluster Training":  "Cluster Training",
  "Cluster Meeting":   "Cluster Meeting",
  "Visit":             "School Visit",
  "Follow-Up Visit":   "Follow-Up Visit",
};

export function PlanIndexAccordion({ items }: { items: PlanItem[] }) {
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
      {items.map((p) => {
        const open = openId === p.id;
        const typeLabel = TYPE_LABEL[p.type];
        return (
          <article key={p.id} className={cn(
            "transition-colors",
            open && "bg-[var(--color-edify-soft)]/30",
          )}>
            {/* Header row — always visible. Clicking it toggles the
                expanded body. Accessible: button + aria-expanded. */}
            <button
              type="button"
              onClick={() => setOpenId(open ? null : p.id)}
              aria-expanded={open}
              aria-controls={`plan-${p.id}-detail`}
              className="w-full flex items-start gap-3 px-4 py-3.5 text-left hover:bg-[var(--color-edify-soft)]/40 transition-colors"
            >
              <span className="h-9 w-9 rounded-md grid place-items-center shrink-0 bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]">
                <Calendar size={15} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-body font-extrabold tracking-tight truncate">
                    {typeLabel} — {p.context}
                  </div>
                  <span className={cn(
                    "inline-flex px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap shrink-0",
                    STATUS_TONE[p.status],
                  )}>
                    {p.status}
                  </span>
                </div>
                <div className="text-caption muted truncate">
                  {p.weekLabel} · {p.date}
                </div>
                {p.title && p.title !== typeLabel && (
                  <div className="text-caption muted truncate">{p.title}</div>
                )}
              </div>
              <ChevronRight
                size={14}
                className={cn(
                  "text-[var(--color-edify-muted)] shrink-0 self-center transition-transform",
                  open && "rotate-90",
                )}
              />
            </button>

            {/* Expanded body — quick facts strip + edit affordance. The
                strip uses a single card with a 2×2 (mobile) / 1×4 (sm+)
                grid of label / value pairs so users see Type / Date /
                Week / Status without leaving the listing. */}
            {open && (
              <div id={`plan-${p.id}-detail`} className="px-4 pb-4 -mt-1 space-y-3">
                <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-3 rounded-xl bg-white border border-[var(--color-edify-border)] p-3.5">
                  <Fact icon={<ClipboardList size={11} />} label="Type" value={typeLabel} />
                  <Fact icon={<Calendar size={11} />}      label="Date" value={p.date} />
                  <Fact icon={<Calendar size={11} />}      label="Week" value={p.weekLabel} />
                  <Fact label="Status" value={
                    <span className={cn(
                      "inline-flex items-center px-1.5 py-[1.5px] rounded-md text-[10.5px] font-bold",
                      STATUS_TONE[p.status],
                    )}>
                      {p.status}
                    </span>
                  } />
                  <Fact icon={<MapPin size={11} />}        label="Context" value={p.context} fullWidth />
                  <Fact label="Plan ID" value={<span className="font-mono text-[12px]">{p.id}</span>} />
                  <Fact label="Filter"  value={p.filter} />
                </dl>

                <div className="flex items-center gap-2">
                  <Link
                    href={`/plans/${p.id}`}
                    className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60 transition-colors"
                  >
                    <Pencil size={12} />
                    Open / Edit
                  </Link>
                </div>
              </div>
            )}
          </article>
        );
      })}
    </section>
  );
}

function Fact({
  icon,
  label,
  value,
  fullWidth = false,
}: {
  icon?: React.ReactNode;
  label: string;
  value: React.ReactNode;
  fullWidth?: boolean;
}) {
  return (
    <div className={cn("min-w-0", fullWidth && "col-span-2 sm:col-span-4")}>
      <dt className="text-[10px] muted font-semibold uppercase tracking-wide flex items-center gap-1">
        {icon && <span className="text-[var(--color-edify-muted)]">{icon}</span>}
        {label}
      </dt>
      <dd className="text-[13px] font-extrabold tracking-tight mt-0.5 truncate">{value}</dd>
    </div>
  );
}
