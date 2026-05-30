"use client";

import { useState } from "react";
import Link from "next/link";
import { Users, ShieldAlert } from "lucide-react";
import { SectionCard, TableEmptyRow } from "@/components/ui/primitives";
import {
  type StaffTargetRow,
  type PaceStatus,
} from "@/lib/team-targets-mock";
import { SupportReviewDrawer } from "./SupportReviewDrawer";
import { cn } from "@/lib/utils";

const PACE_TONE: Record<PaceStatus, string> = {
  "On Track":        "bg-emerald-100 text-emerald-700",
  "Slightly Behind": "bg-amber-100 text-amber-700",
  "Behind":          "bg-orange-100 text-orange-700",
  "High Risk":       "bg-rose-100 text-rose-700",
  "Critical":        "bg-rose-100 text-rose-700",
};

const PACE_DOT: Record<PaceStatus, string> = {
  "On Track":        "bg-emerald-500",
  "Slightly Behind": "bg-amber-500",
  "Behind":          "bg-orange-500",
  "High Risk":       "bg-rose-500",
  "Critical":        "bg-rose-700",
};

export function StaffTargetTable({ rows }: { rows: StaffTargetRow[] }) {
  const [activeStaff, setActiveStaff] = useState<StaffTargetRow | null>(null);

  return (
    <>
      <SectionCard
        icon={<Users size={13} />}
        title="Target Performance by Staff"
        actions={
          <Link href="/staff" className="text-[12px] font-semibold text-[var(--color-edify-primary)]">
            View All staff performance →
          </Link>
        }
      >
        <table className="w-full dtable">
          <thead>
            <tr>
              <th scope="col" className="text-left">Staff Name</th>
              <th scope="col" className="text-left">Region</th>
              <th scope="col" className="text-right">Monthly Target<br /><span className="font-medium normal-case muted text-caption">Activities</span></th>
              <th scope="col" className="text-right">Completed<br /><span className="font-medium normal-case muted text-caption">Activities</span></th>
              <th scope="col" className="text-right">Remaining<br /><span className="font-medium normal-case muted text-caption">Activities</span></th>
              <th scope="col" className="text-right">Quarterly Target<br /><span className="font-medium normal-case muted text-caption">Activities</span></th>
              <th scope="col" className="text-left">Achievement %<br /><span className="font-medium normal-case muted text-caption">Monthly</span></th>
              <th scope="col" className="text-left">Pace Status</th>
              <th scope="col" className="text-right">Salesforce<br /><span className="font-medium normal-case muted text-caption">Compliance</span></th>
              <th scope="col" className="text-right">Core School<br /><span className="font-medium normal-case muted text-caption">Progress</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.staffId} className="hover:bg-[var(--color-edify-soft)]/40 cursor-pointer" onClick={() => setActiveStaff(s)}>
                <td>
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full bg-[var(--color-edify-primary)] text-white text-[11px] font-bold grid place-items-center shrink-0">
                      {s.initials}
                    </div>
                    <div className="min-w-0">
                      <div className="text-body font-semibold whitespace-nowrap">{s.staffName}</div>
                      {s.midYearBelow40Triggered && (
                        <div className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 mt-0.5">
                          <ShieldAlert size={10} />
                          Support review required
                        </div>
                      )}
                    </div>
                  </div>
                </td>
                <td className="text-[12px] muted">{s.region}</td>
                <td className="text-right tabular text-body font-semibold">{s.monthlyTargetActivities}</td>
                <td className="text-right tabular text-body">{s.completedActivities}</td>
                <td className="text-right tabular text-body text-[var(--color-danger)] font-bold">{s.remainingActivities}</td>
                <td className="text-right tabular text-body">{s.quarterlyTargetActivities}</td>
                <td>
                  <div className="flex items-center gap-2 min-w-[120px]">
                    <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", PACE_DOT[s.paceStatus])}
                        style={{ width: `${Math.min(s.achievementPercent, 100)}%` }}
                      />
                    </div>
                    <span className="text-[12px] font-bold tabular w-9 text-right">{s.achievementPercent}%</span>
                  </div>
                </td>
                <td>
                  <span className={cn("inline-flex items-center gap-1.5 px-2 py-[2px] rounded-md text-[11px] font-bold", PACE_TONE[s.paceStatus])}>
                    <span className={cn("w-1.5 h-1.5 rounded-full", PACE_DOT[s.paceStatus])} />
                    {s.paceStatus}
                  </span>
                </td>
                <td className="text-right">
                  <span
                    className={cn(
                      "inline-flex items-center justify-center w-12 h-6 rounded-md text-[11.5px] font-bold tabular",
                      s.salesforceCompliancePercent >= 80
                        ? "bg-emerald-100 text-emerald-700"
                        : s.salesforceCompliancePercent >= 60
                          ? "bg-amber-100 text-amber-700"
                          : "bg-rose-100 text-rose-700",
                    )}
                  >
                    {s.salesforceCompliancePercent}%
                  </span>
                </td>
                <td className="text-right tabular text-body">{s.coreSchoolProgressPercent}%</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <TableEmptyRow
                colSpan={10}
                title="No staff under your supervision yet"
                body="When CCEOs are assigned to you in Salesforce, their target pacing will appear here. New supervisors typically see this list populate within 24 hours."
              />
            )}
          </tbody>
        </table>

        <div className="mt-3 pt-3 border-t border-[#eef2f4] text-caption muted leading-snug">
          Click any row to open the Support Review drawer. PIP escalation is gated until a support plan +
          report are complete.
        </div>
      </SectionCard>

      {activeStaff && (
        <SupportReviewDrawer staff={activeStaff} onClose={() => setActiveStaff(null)} />
      )}
    </>
  );
}
