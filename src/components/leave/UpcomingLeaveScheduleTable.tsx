"use client";

import Link from "next/link";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import {
  leaveRequests,
  type LeaveStatus,
  type PlanningImpact,
} from "@/lib/leave-mock";

const statusTone: Record<LeaveStatus, "green" | "amber" | "red" | "grey"> = {
  Approved:  "green",
  Pending:   "amber",
  Rejected:  "red",
  Cancelled: "grey",
};

const impactTone: Record<PlanningImpact, "red" | "amber" | "grey"> = {
  Blocked:   "red",
  Potential: "amber",
  None:      "grey",
};

function shortDate(iso: string) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" });
}

export function UpcomingLeaveScheduleTable() {
  return (
    <SectionCard
      title="Upcoming Leave Schedule"
      actions={
        <Link className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="/leave">
          View All
        </Link>
      }
    >
      {/* Constrain the table to a card-sized scroll area so the
          surrounding row stays balanced with the Team Availability
          heatmap on the right. `flex-1 min-h-0` lets the container
          fill the SectionCard's height; `max-h-[420px]` caps it on
          tall viewports so the card never out-grows its neighbour.
          The thead stays sticky so column meaning never disappears. */}
      <div className="flex-1 min-h-0 overflow-y-auto max-h-[420px] -mx-1 px-1">
        <table className="w-full dtable">
          <thead className="sticky top-0 z-10 bg-white">
            <tr>
              <th scope="col" className="text-left">Staff Name</th>
              <th scope="col" className="text-left">Region</th>
              <th scope="col" className="text-left">Leave Type</th>
              <th scope="col" className="text-left">Start Date</th>
              <th scope="col" className="text-left">End Date</th>
              <th scope="col" className="text-right">Working Days</th>
              <th scope="col" className="text-left">Approval Status</th>
              <th scope="col" className="text-left">Planning Impact</th>
            </tr>
          </thead>
          <tbody>
            {leaveRequests.map((l) => (
              <tr key={l.leaveId}>
                <td className="text-body font-semibold whitespace-nowrap">{l.staffName}</td>
                <td className="text-[12px] muted">{l.region}</td>
                <td className="text-[12px] muted whitespace-nowrap">{l.leaveType}</td>
                <td className="text-[12px] muted whitespace-nowrap">{shortDate(l.startDate)}</td>
                <td className="text-[12px] muted whitespace-nowrap">{shortDate(l.endDate)}</td>
                <td className="text-right tabular text-body font-semibold">{l.workingDays}</td>
                <td>
                  <StatusBadge tone={statusTone[l.approvalStatus]}>{l.approvalStatus}</StatusBadge>
                </td>
                <td>
                  <StatusBadge tone={impactTone[l.planningImpact]}>{l.planningImpact}</StatusBadge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
