"use client";

// MessageContextCard — adaptive context block. Renders only the
// related fields populated on the message. Surfaces the school /
// cluster / activity / evidence / payment context so the reader sees
// "what this message is about" without having to click through.

import Link from "next/link";
import {
  ArrowUpRight,
  Building2,
  Calendar,
  CheckCircle2,
  ClipboardList,
  FileText,
  Layers,
  Users,
  Wallet,
} from "lucide-react";
import type { Message } from "@/lib/messages-v2/types";

export function MessageContextCard({ message }: { message: Message }) {
  const r = message.related;
  if (!r) return null;

  // Collect populated rows in a stable order.
  const rows: { Icon: typeof Building2; label: string; value: string; href?: string }[] = [];

  if (r.schoolName)      rows.push({ Icon: Building2,     label: "School",         value: r.schoolName,     href: r.schoolId ? `/schools/${r.schoolId}` : undefined });
  if (r.clusterName)     rows.push({ Icon: Layers,        label: "Cluster",        value: r.clusterName,    href: r.clusterId ? `/clusters/${r.clusterId}` : undefined });
  if (r.activityType)    rows.push({ Icon: ClipboardList, label: "Activity",       value: r.activityType,   href: r.activityId ? `/dashboards/partner` : undefined });
  if (r.ssaArea)         rows.push({ Icon: CheckCircle2,  label: "SSA area",       value: r.ssaArea });
  if (r.partnerName)     rows.push({ Icon: Users,         label: "Partner",        value: r.partnerName,    href: r.partnerId ? `/partners/${r.partnerId}` : undefined });
  if (r.evidenceStatus)  rows.push({ Icon: FileText,      label: "Evidence",       value: r.evidenceStatus, href: r.evidenceId ? `/partner/evidence` : undefined });
  if (r.paymentAmount)   rows.push({ Icon: Wallet,        label: "Amount",         value: r.paymentAmount });
  if (r.paymentStatus)   rows.push({ Icon: Wallet,        label: "Payment status", value: r.paymentStatus });
  if (r.debriefCategory) rows.push({ Icon: ClipboardList, label: "Debrief",        value: r.debriefCategory });
  if (r.dueDate)         rows.push({ Icon: Calendar,      label: "Due",            value: r.dueDate });

  if (rows.length === 0) return null;

  return (
    <section className="card p-3.5 lg:p-5">
      <h3 className="text-[11px] font-extrabold tracking-[0.08em] uppercase text-[var(--color-edify-muted)]">
        Context
      </h3>
      <dl className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
        {rows.map((row) => (
          <div key={`${row.label}-${row.value}`} className="flex items-start gap-2.5 min-w-0">
            <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)]/70 text-[var(--color-edify-primary)] shrink-0">
              <row.Icon size={13} />
            </span>
            <div className="min-w-0 flex-1">
              <dt className="text-caption uppercase tracking-[0.06em] font-bold text-[var(--color-edify-muted)]">
                {row.label}
              </dt>
              <dd className="text-[13px] font-semibold text-[var(--color-edify-text)] leading-snug mt-0.5 truncate">
                {row.href ? (
                  <Link href={row.href} className="inline-flex items-center gap-1 hover:underline">
                    {row.value}
                    <ArrowUpRight size={11} className="text-[var(--color-edify-muted)]" />
                  </Link>
                ) : row.value}
              </dd>
            </div>
          </div>
        ))}
      </dl>
    </section>
  );
}
