"use client";

import { useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import {
  Filter as FilterIcon,
  Columns3,
  Plus,
  MoreHorizontal,
  Building2,
  CalendarDays,
} from "lucide-react";
import {
  plannedActivities as seedPlannedActivities,
  type PlannedActivityRow,
  type Priority,
  type PlanStatus,
  type DeliveryMode,
  type AssignedTo,
} from "@/lib/planning-mock";

// In-card vertical scroll cap. Previously this card paginated to
// keep its body flush with neighbour cards in the grid. Now it
// scrolls — every row is reachable without paging, and the sticky
// thead means columns stay labelled as the user moves.
const TABLE_MAX_HEIGHT = 560;

import { cn } from "@/lib/utils";
import { AddPlanDrawer } from "./AddPlanDrawer";
import { AddLeaveDrawer } from "./AddLeaveDrawer";

const priorityClass = (p: Priority) =>
  p === "High" ? "chip-red" : p === "Medium" ? "chip-amber" : "chip-grey";

const statusClass = (s: PlanStatus) =>
  s === "Planned"
    ? "chip-green"
    : s === "Submitted for Approval"
      ? "chip-blue"
      : "chip-amber";

const deliveryClass = (d: DeliveryMode) =>
  d === "In-School" ? "chip-soft" : d === "Cluster" ? "chip-soft" : "chip-soft";

const assignedClass = (a: AssignedTo) =>
  a === "Me"
    ? "chip-soft"
    : a === "Cluster"
      ? "chip-soft"
      : a === "Partner"
        ? "chip-amber"
        : "chip-green";

const ssaClass = (label: string) =>
  label === "Low SSA" ? "text-[var(--color-danger)]" : "text-[var(--color-edify-orange)]";

const columns: ColumnDef<PlannedActivityRow>[] = [
  {
    id: "schoolName",
    header: "School Name",
    cell: ({ row }) => (
      <div className="flex items-center gap-2">
        <span className="icon-tile icon-tile-sm">
          <Building2 size={11} />
        </span>
        <span className="text-body font-semibold whitespace-nowrap">
          {row.original.schoolName}
        </span>
      </div>
    ),
  },
  {
    id: "district",
    header: "District",
    cell: ({ row }) => <span className="text-[12px] muted">{row.original.district}</span>,
  },
  {
    id: "schoolType",
    header: "School Type",
    cell: ({ row }) => <span className="text-[12px] muted">{row.original.schoolType}</span>,
  },
  {
    id: "priority",
    header: "Priority",
    cell: ({ row }) => (
      <span className={cn("chip", priorityClass(row.original.priority))}>
        {row.original.priority}
      </span>
    ),
  },
  {
    id: "ssaStatus",
    header: "SSA Status",
    cell: ({ row }) => (
      <div className={cn("text-[12px] font-semibold", ssaClass(row.original.ssaStatus.label))}>
        {row.original.ssaStatus.label}
        <span className="muted font-normal ml-1">{row.original.ssaStatus.pct}</span>
      </div>
    ),
  },
  {
    id: "intervention",
    header: "Lowest Performing Intervention",
    cell: ({ row }) => (
      <span className="text-[12px] font-medium">{row.original.intervention}</span>
    ),
  },
  {
    id: "recommended",
    header: "Recommended Activity",
    cell: ({ row }) => (
      <span className="chip chip-soft whitespace-nowrap">{row.original.recommended}</span>
    ),
  },
  {
    id: "delivery",
    header: "Delivery Mode",
    cell: ({ row }) => (
      <span className={cn("chip", deliveryClass(row.original.delivery))}>
        {row.original.delivery}
      </span>
    ),
  },
  {
    id: "assignedTo",
    header: "Assigned To",
    cell: ({ row }) => (
      <span className={cn("chip", assignedClass(row.original.assignedTo))}>
        {row.original.assignedTo}
      </span>
    ),
  },
  {
    id: "schedule",
    header: "Cluster / Date or Month / Week",
    cell: ({ row }) => (
      <div className="leading-tight">
        <div className="text-[12px] font-semibold">{row.original.schedule.line1}</div>
        <div className="text-[11px] muted">{row.original.schedule.line2}</div>
      </div>
    ),
  },
  {
    id: "estCost",
    header: "Est. Cost (UGX)",
    cell: ({ row }) => (
      <div className="text-right tabular text-body font-semibold">
        {row.original.estCost.toLocaleString()}
      </div>
    ),
  },
  {
    id: "status",
    header: "Plan Status",
    cell: ({ row }) => (
      <span className={cn("chip", statusClass(row.original.status))}>
        {row.original.status}
      </span>
    ),
  },
  {
    id: "actions",
    header: "",
    cell: () => (
      <div className="text-right">
        <button
          type="button"
          aria-label="Row actions"
          className="w-7 h-7 rounded-md grid place-items-center text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]"
        >
          <MoreHorizontal size={14} />
        </button>
      </div>
    ),
  },
];

export function PlannedActivitiesCard() {
  const [activities, setActivities] = useState<PlannedActivityRow[]>(seedPlannedActivities);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [leaveDrawerOpen, setLeaveDrawerOpen] = useState(false);
  const [toast, setToast] = useState<{ msg: string; status: PlanStatus } | null>(null);
  const [highlightKey, setHighlightKey] = useState<string | null>(null);

  // capacity heuristic: count current rows by month/week so the drawer can warn
  const existingByWeek = useMemo(() => {
    const map: Record<string, number> = {};
    for (const a of activities) {
      const k = a.schedule.line1;
      if (k && k.includes("/")) map[k] = (map[k] ?? 0) + 1;
    }
    return map;
  }, [activities]);

  const handleSave = (row: PlannedActivityRow, status: PlanStatus) => {
    setActivities((prev) => [{ ...row, status }, ...prev]);
    const key = `${row.schoolName}|${row.recommended}|${row.schedule.line1}|${Date.now()}`;
    setHighlightKey(key);
    setToast({
      msg:
        status === "Submitted for Approval"
          ? `${row.schoolName}: submitted for plan approval — routed to Country Program Lead.`
          : `${row.schoolName}: saved as Draft.`,
      status,
    });
    setTimeout(() => setToast(null), 4500);
    setTimeout(() => setHighlightKey(null), 1800);
  };

  // @tanstack/react-table isn't React-Compiler-compatible — the compiler
  // skips memoizing this component body. Documented and accepted; the
  // table's data is small (planned activities for one user) so
  // non-memoization is fine.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: activities,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const totalCount = activities.length;

  return (
    <div className="card col-span-12 md:col-span-9 p-4 flex flex-col">
      {/* Card header */}
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span
              className="w-6 h-6 rounded-md flex items-center justify-center icon-tile"
              aria-hidden
            >
              <Columns3 size={13} />
            </span>
            <h3 className="text-[15px] font-bold">Planned Activities</h3>
          </div>
          <div className="text-[12px] muted mt-0.5">
            Plan and assign activities based on SSA recommendations.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" disabled title="Filtering this list is coming soon" className="btn opacity-50 cursor-not-allowed">
            <FilterIcon size={14} />
            Filters
          </button>
          <button type="button" disabled title="Column options are coming soon" className="btn opacity-50 cursor-not-allowed">
            <Columns3 size={14} />
            Columns
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => setLeaveDrawerOpen(true)}
          >
            <CalendarDays size={14} />
            Schedule Leave
          </button>
          <button type="button" className="btn btn-primary" onClick={() => setDrawerOpen(true)}>
            <Plus size={14} />
            Add Plan
          </button>
        </div>
      </div>

      {/* Table — vertical + horizontal scroll inside the card. Sticky
          thead keeps column labels on screen as the user moves down
          the list. Pagination removed: every row is reachable by
          scrolling, which is the premium pattern for dense
          operational tables. */}
      <div
        className="overflow-auto scrollbar -mx-1 px-1 rounded-md"
        style={{ maxHeight: TABLE_MAX_HEIGHT }}
      >
        <table className="w-full dtable">
          <thead className="sticky top-0 z-[1] bg-[var(--color-edify-soft)]/95 backdrop-blur">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h, i) => (
                  <th
                    key={h.id}
                    className={cn(
                      "text-left whitespace-nowrap",
                      i === 10 && "text-right",
                    )}
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row, idx) => {
              const isNew =
                idx === 0 &&
                activities.length > seedPlannedActivities.length &&
                highlightKey;
              return (
                <tr
                  key={row.id}
                  className={cn(
                    "hover:bg-[var(--color-edify-soft)]/40 transition-colors",
                    isNew && "bg-[var(--color-edify-soft)]",
                  )}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer — row count only. Scroll replaces paging. */}
      <div className="flex items-center justify-between pt-3 mt-3 border-t border-[#eef2f4]">
        <div className="text-[12px] muted">
          Showing all{" "}
          <span className="font-semibold text-[var(--color-edify-text)]">{totalCount}</span>{" "}
          activities · scroll inside the card to see more
        </div>
      </div>

      {/* Drawers */}
      <AddPlanDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onSave={handleSave}
        existingByWeek={existingByWeek}
      />
      <AddLeaveDrawer
        open={leaveDrawerOpen}
        onClose={() => setLeaveDrawerOpen(false)}
        onSave={(leaveId, conflictCount) => {
          setToast({
            msg: conflictCount > 0
              ? `Leave ${leaveId} scheduled — ${conflictCount} overlapping activities flagged for reassignment.`
              : `Leave ${leaveId} scheduled — no activity conflicts detected.`,
            status: "Planned",
          });
          setTimeout(() => setToast(null), 5000);
        }}
        activitiesList={activities}
      />

      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            className="fixed bottom-6 right-6 z-50 card px-4 py-3 flex items-center gap-3 max-w-[420px] shadow-lg"
          >
            <span
              className={cn(
                "w-7 h-7 rounded-full grid place-items-center text-white",
                toast.status === "Submitted for Approval"
                  ? "bg-[var(--color-edify-primary)]"
                  : "bg-[var(--color-edify-orange)]",
              )}
              aria-hidden
            >
              <Plus size={14} />
            </span>
            <div className="text-body leading-tight">
              <div className="font-bold">
                {toast.status === "Submitted for Approval" ? "Plan submitted" : "Draft saved"}
              </div>
              <div className="muted">{toast.msg}</div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
