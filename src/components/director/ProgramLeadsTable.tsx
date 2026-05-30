"use client";

import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { Users } from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { programLeads, type ProgramLeadRow } from "@/lib/director-mock";

const riskTone = (r: ProgramLeadRow["riskStatus"]) =>
  r === "On Track" ? "green" : r === "Watch" ? "amber" : "red";

const targetTone = (pct: number) =>
  pct >= 80
    ? "var(--color-success)"
    : pct >= 65
      ? "var(--color-edify-orange)"
      : "var(--color-danger)";

const columns: ColumnDef<ProgramLeadRow>[] = [
  {
    id: "name",
    header: "Lead Name",
    cell: ({ row }) => (
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-full bg-[var(--color-edify-primary)] text-white text-[11px] font-bold grid place-items-center shrink-0">
          {row.original.initials}
        </div>
        <div className="text-body font-semibold whitespace-nowrap">{row.original.name}</div>
      </div>
    ),
  },
  {
    id: "region",
    header: "Region",
    cell: ({ row }) => <span className="text-[12px] muted">{row.original.region}</span>,
  },
  {
    id: "target",
    header: "Team Target %",
    cell: ({ row }) => (
      <div className="flex items-center gap-2 min-w-[120px]">
        <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
          <div
            className="h-full rounded-full"
            style={{
              width: `${row.original.teamTargetPct}%`,
              background: targetTone(row.original.teamTargetPct),
            }}
          />
        </div>
        <div className="text-[12px] font-bold tabular w-[36px] text-right">
          {row.original.teamTargetPct}%
        </div>
      </div>
    ),
  },
  {
    id: "staff",
    header: "Staff Under Them",
    cell: ({ row }) => (
      <span className="text-body tabular font-semibold">{row.original.staffUnderThem}</span>
    ),
  },
  {
    id: "planned",
    header: "Activities Planned",
    cell: ({ row }) => (
      <span className="text-body tabular">{row.original.activitiesPlanned.toLocaleString()}</span>
    ),
  },
  {
    id: "verified",
    header: "Verified Activities",
    cell: ({ row }) => (
      <span className="text-body tabular">
        {row.original.verifiedActivities.toLocaleString()}
      </span>
    ),
  },
  {
    id: "sf_pending",
    header: "Salesforce Pending",
    cell: ({ row }) => (
      <span className="text-body tabular">{row.original.salesforcePending.toLocaleString()}</span>
    ),
  },
  {
    id: "backlog",
    header: "Backlog",
    cell: ({ row }) => (
      <span className="text-body tabular">{row.original.backlog.toLocaleString()}</span>
    ),
  },
  {
    id: "risk",
    header: "Risk Status",
    cell: ({ row }) => (
      <StatusBadge tone={riskTone(row.original.riskStatus)}>{row.original.riskStatus}</StatusBadge>
    ),
  },
];

export function ProgramLeadsPerformanceTable() {
  // @tanstack/react-table isn't React-Compiler-compatible — the compiler
  // skips memoizing this component body. Documented and accepted; the
  // table's data is small (<200 rows) so non-memoization is fine.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: programLeads,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });
  return (
    <SectionCard
      icon={<Users size={13} />}
      title="Country Program Leads Performance"
      actions={
        <a className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="#program-leads">
          View All program leads performance →
        </a>
      }
    >
      {/* Mobile card list — same data, but each lead becomes a row
          card so the 9-column table doesn't force horizontal scroll
          on a phone. From md+ we drop back to the dense table. */}
      <ul className="md:hidden flex flex-col gap-2">
        {programLeads.map((r) => (
          <li key={r.id} className="rounded-xl border border-[var(--color-edify-border)] bg-white px-3 py-2.5 flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold grid place-items-center shrink-0">
              {r.initials}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-body font-extrabold text-slate-900 truncate flex-1">{r.name}</span>
                <StatusBadge tone={riskTone(r.riskStatus)}>{r.riskStatus}</StatusBadge>
              </div>
              <div className="text-caption muted leading-tight mb-1.5">
                {r.region} · {r.staffUnderThem} staff · {r.activitiesPlanned.toLocaleString()} planned
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${r.teamTargetPct}%`, background: targetTone(r.teamTargetPct) }}
                  />
                </div>
                <span className="text-[11px] font-extrabold tabular w-[32px] text-right">{r.teamTargetPct}%</span>
              </div>
            </div>
          </li>
        ))}
      </ul>

      <div className="hidden md:block overflow-x-auto scrollbar -mx-1 px-1">
        <table className="w-full dtable">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="bg-[var(--color-edify-soft)]/60">
                {hg.headers.map((h) => (
                  <th key={h.id} className="text-left whitespace-nowrap">
                    {flexRender(h.column.columnDef.header, h.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-[var(--color-edify-soft)]/40">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
