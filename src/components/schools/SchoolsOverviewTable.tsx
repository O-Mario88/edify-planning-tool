"use client";

import Link from "next/link";
import {
  Building2,
  MoreVertical,
  MapPin,
} from "lucide-react";
import { SectionCard, StatusBadge, TableEmptyRow } from "@/components/ui/primitives";
import { ExportButton } from "@/components/ui/ExportButton";
import {
  formatDate,
  type SchoolRow,
  type SsaStatus,
  type SchoolStatus,
  type Priority,
} from "@/lib/schools-mock";

export type SchoolGroup = { key: string; schools: SchoolRow[] };

const statusTone: Record<SchoolStatus, "green" | "red" | "grey"> = {
  Active:   "green",
  Inactive: "red",
  Closed:   "grey",
};

const ssaTone: Record<SsaStatus, "green" | "amber" | "red"> = {
  Completed:        "green",
  "Not Completed":  "red",
  Overdue:          "amber",
};

const priorityTone: Record<Priority, "red" | "amber" | "blue" | "grey"> = {
  Critical: "red",
  High:     "red",
  Medium:   "amber",
  Low:      "grey",
};

export function SchoolsOverviewTable({
  schools,
  totalAssignedCount,
  groups,
  toolbar,
  filterBar,
}: {
  schools?: SchoolRow[];
  totalAssignedCount: number;
  /** When provided, schools render bucketed under group headers. */
  groups?: SchoolGroup[];
  /** Override the header right-side action buttons. */
  toolbar?: React.ReactNode;
  /** Sub-bar rendered between header and table (filter chips, group selector, etc). */
  filterBar?: React.ReactNode;
}) {
  // No pagination — every assigned school renders, the card itself
  // scrolls vertically (sticky thead) and horizontally for the wide
  // column set. Replaces the old "slice(0, 9) + pager" pattern: we
  // trust the user to scroll the card rather than juggle pages.
  const renderGroups: SchoolGroup[] = groups
    ? groups
    : [{ key: "All schools", schools: schools ?? [] }];
  const visibleCount = renderGroups.reduce((a, g) => a + g.schools.length, 0);
  const isGrouped = !!groups && groups.length > 1;
  return (
    <SectionCard
      icon={<Building2 size={13} />}
      title="Schools Overview"
      actions={
        toolbar ?? (
          <div className="flex items-center gap-2">
            <ExportButton
              rows={renderGroups.flatMap((g) => g.schools).map((s) => ({
                School: s.schoolName, District: s.district, Region: s.region,
                Type: s.schoolType ?? s.segment ?? "", SSA_status: s.ssaStatus,
                SSA_score: s.ssaScore, CCEO: s.assignedCceoName ?? "",
              }))}
              filename="schools-overview"
            />
          </div>
        )
      }
    >
      {filterBar}
      {/* In-card scroll region. Vertical scroll caps the card at a
          predictable height (≈ 14 rows); horizontal scroll keeps the
          wide column set readable inside narrow grid slots. The
          sticky thead means column labels follow the user down the
          list — every premium table app does this. */}
      <div className="overflow-auto scrollbar -mx-1 px-1 max-h-[560px] rounded-md">
        <table className="w-full dtable">
          <thead className="sticky top-0 z-10 bg-white shadow-[0_1px_0_var(--color-edify-divider)]">
            <tr>
              <th scope="col" className="text-left">School Name</th>
              <th scope="col" className="text-left">District</th>
              <th scope="col" className="text-left">Shipping Address</th>
              <th scope="col" className="text-left">School Type</th>
              <th scope="col" className="text-left">Status</th>
              <th scope="col" className="text-left">Assigned Staff</th>
              <th scope="col" className="text-left">Assigned Partner</th>
              <th scope="col" className="text-left">SSA Status</th>
              <th scope="col" className="text-left">Latest Visit</th>
              <th scope="col" className="text-left">Latest Training</th>
              <th scope="col" className="text-left">Priority</th>
              <th scope="col" className="text-left">Recommended Next Action</th>
              <th aria-label="Row menu" className="w-[28px]" />
            </tr>
          </thead>
          <tbody>
            {renderGroups.flatMap((g) => [
              isGrouped ? (
                <tr key={`gh-${g.key}`} className="bg-[var(--color-edify-soft)]/70">
                  <td colSpan={13} className="!py-1.5">
                    <div className="flex items-center gap-2 text-[12px] font-bold text-[var(--color-edify-dark)]">
                      <MapPin size={12} className="text-[var(--color-edify-primary)]" />
                      <span>{g.key}</span>
                      <span className="muted font-medium">· {g.schools.length} schools</span>
                    </div>
                  </td>
                </tr>
              ) : null,
              ...g.schools.map((s) => {
              const staffName = s.assignedCceoName.split(" ")[0] + " " + (s.assignedCceoName.split(" ")[1]?.[0] ?? "") + ".";
              return (
                <tr key={s.schoolId} className="hover:bg-[var(--color-edify-soft)]/40">
                  <td>
                    <Link
                      href={`/schools/${s.schoolId}`}
                      className="flex items-center gap-2 group"
                    >
                      <span className="icon-tile icon-tile-sm">
                        <Building2 size={11} />
                      </span>
                      <span className="text-body font-semibold whitespace-nowrap group-hover:text-[var(--color-edify-primary)]">
                        {s.schoolName}
                      </span>
                    </Link>
                  </td>
                  <td className="text-[12px] muted">{s.district}</td>
                  <td className="text-[11.5px] muted whitespace-nowrap">
                    <span className="inline-flex items-center gap-1">
                      <MapPin size={10} className="text-[var(--color-edify-primary)]" />
                      {s.shippingAddress}
                    </span>
                  </td>
                  <td className="text-[12px] muted">{s.schoolType}</td>
                  <td>
                    <StatusBadge tone={statusTone[s.schoolStatus]}>{s.schoolStatus}</StatusBadge>
                  </td>
                  <td className="text-[12px]">
                    {staffName.trim() || <span className="muted">—</span>}
                  </td>
                  <td>
                    {s.assignedPartnerName ? (
                      <span className="chip chip-amber">{s.assignedPartnerName}</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    <StatusBadge tone={ssaTone[s.ssaStatus]}>{s.ssaStatus}</StatusBadge>
                  </td>
                  <td className="text-[12px] muted">
                    {s.noVisit ? (
                      <span className="text-[var(--color-danger)] font-semibold">No Visit</span>
                    ) : (
                      formatDate(s.latestVisitDate)
                    )}
                  </td>
                  <td className="text-[12px] muted">
                    {s.noTraining ? (
                      <span className="text-[var(--color-danger)] font-semibold">No Training</span>
                    ) : (
                      formatDate(s.latestTrainingDate)
                    )}
                  </td>
                  <td>
                    <StatusBadge tone={priorityTone[s.priority]}>{s.priority}</StatusBadge>
                  </td>
                  <td className="text-[12px] muted whitespace-nowrap">{s.recommendedNextAction}</td>
                  <td className="text-right">
                    <button
                      type="button"
                      aria-label="Row actions"
                      className="w-7 h-7 rounded-md hover:bg-[var(--color-edify-soft)] grid place-items-center text-[var(--color-edify-muted)]"
                    >
                      <MoreVertical size={14} />
                    </button>
                  </td>
                </tr>
              );
            }),
            ])}
            {visibleCount === 0 && (
              <TableEmptyRow
                colSpan={13}
                title="No schools assigned to you yet"
                body="When schools are assigned to your CCEO ID in Salesforce, they will appear here. Region or filter combinations may also produce zero matches — adjust the filters above."
              />
            )}
          </tbody>
        </table>
      </div>

      {/* Footer — count only. Pagination removed in favour of
          in-card vertical scroll (every assigned school renders). */}
      <div className="mt-3 pt-3 border-t border-[#eef2f4] flex items-center justify-between text-[12px]">
        <div className="muted">
          Showing all{" "}
          <span className="font-semibold text-[var(--color-edify-text)]">
            {visibleCount.toLocaleString()}
          </span>{" "}
          of{" "}
          <span className="font-semibold text-[var(--color-edify-text)]">
            {totalAssignedCount.toLocaleString()}
          </span>{" "}
          schools · scroll inside the card to see more
        </div>
      </div>
    </SectionCard>
  );
}
