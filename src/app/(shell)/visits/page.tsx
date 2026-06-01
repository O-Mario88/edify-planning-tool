"use client";

import Link from "next/link";
import { EntityIndex } from "@/components/shell/EntityIndex";
import { StatusBadge, type ChipTone } from "@/components/ui/primitives";
import { CheckCircle2, AlertOctagon, Footprints, type LucideIcon } from "lucide-react";
import { planItems } from "@/lib/mobile-mock";
import { ConfirmCompletionButton } from "@/components/my-targets/ConfirmCompletionButton";

// Visits are derived from PlanItems whose type is "Visit" or "Follow-Up
// Visit". Production would have a dedicated `visits` table; for now the
// same plan store covers both surfaces. A visit is confirmed by entering its
// Salesforce Visit ID (SVE-) — that's all a visit needs (no trainee counts).
export default function VisitsIndex() {
  const visits = planItems.filter((p) => p.type === "Visit" || p.type === "Follow-Up Visit");

  const rowIcon = (status: string): { Icon: LucideIcon; bg: string; text: string } =>
    status === "Verified" ? { Icon: CheckCircle2, bg: "bg-emerald-100", text: "text-emerald-700" }
    : status === "Awaiting SF ID" ? { Icon: AlertOctagon, bg: "bg-rose-100", text: "text-rose-700" }
    : { Icon: Footprints, bg: "bg-sky-100", text: "text-sky-700" };

  const tone = (status: string): ChipTone =>
    status === "Verified" ? "green"
    : status === "Awaiting SF ID" ? "red"
    : status === "In Progress" ? "blue" : "amber";

  return (
    <EntityIndex
      title="Visits"
      subtitle="Every school visit on your plan. Confirm a visit by entering its Salesforce Visit ID (SVE-)."
      Icon={Footprints}
      count={visits.length}
      searchPlaceholder="Search by school, cluster"
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {visits.map((v) => {
          const ic = rowIcon(v.status);
          return (
            <div key={v.id} className="flex items-center gap-3 px-4 py-3.5">
              <span className={`h-9 w-9 rounded-md grid place-items-center shrink-0 ${ic.bg} ${ic.text}`}>
                <ic.Icon size={15} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight truncate">{v.type} — {v.context}</div>
                <div className="text-caption muted truncate">{v.weekLabel} · {v.date}</div>
              </div>
              <StatusBadge tone={tone(v.status)}>{v.status}</StatusBadge>
              {v.status !== "Verified" && (
                <ConfirmCompletionButton
                  activity={{ id: v.id, schoolName: v.context, activityType: v.type, purpose: v.date }}
                />
              )}
              <Link href={`/plans/${v.id}`} className="btn btn-sm" aria-label={`View ${v.type}`}>
                View
              </Link>
            </div>
          );
        })}
      </section>
    </EntityIndex>
  );
}
