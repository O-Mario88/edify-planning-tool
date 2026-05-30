"use client";

import Link from "next/link";
import { SectionCard } from "@/components/ui/primitives";
import {
  publicHolidays,
  conferenceWeeks,
  blackoutDates,
} from "@/lib/leave-mock";
import { cn } from "@/lib/utils";

type Row = {
  id: string;
  date: string;
  description: string;
  type: "Public Holiday" | "Organization";
  status: "Planning Blocked";
};

function shortDate(iso: string) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" });
}

function rangeLabel(s: string, e: string) {
  return `${shortDate(s)} – ${shortDate(e)}`;
}

const rows: Row[] = [
  ...publicHolidays.map<Row>((h) => ({
    id: `H-${h.date}`,
    date: shortDate(h.date),
    description: h.title,
    type: "Public Holiday",
    status: "Planning Blocked",
  })),
  ...conferenceWeeks.map<Row>((c) => ({
    id: `C-${c.startDate}`,
    date: rangeLabel(c.startDate, c.endDate),
    description: c.title,
    type: "Organization",
    status: "Planning Blocked",
  })),
  ...blackoutDates.map<Row>((b) => ({
    id: `B-${b.startDate}`,
    date: rangeLabel(b.startDate, b.endDate),
    description: b.title,
    type: "Organization",
    status: "Planning Blocked",
  })),
];

export function HolidayBlackoutDatesTable() {
  return (
    <SectionCard
      title="Holiday & Blackout Dates"
      actions={
        <Link className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="/leave">
          View All
        </Link>
      }
    >
      {/* Same scroll-pattern as the sibling Upcoming Leave card so
          both align with the Team Availability heatmap on the right.
          Sticky thead keeps column labels visible while the body
          scrolls. */}
      <div className="flex-1 min-h-0 overflow-y-auto max-h-[420px] -mx-1 px-1">
        <table className="w-full dtable">
          <thead className="sticky top-0 z-10 bg-white">
            <tr>
              <th scope="col" className="text-left">Date</th>
              <th scope="col" className="text-left">Description</th>
              <th scope="col" className="text-left">Type</th>
              <th scope="col" className="text-left">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="text-[12px] muted whitespace-nowrap">{r.date}</td>
                <td className="text-body font-semibold whitespace-nowrap">{r.description}</td>
                <td>
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 text-[11.5px] font-semibold whitespace-nowrap",
                      r.type === "Public Holiday"
                        ? "text-rose-700"
                        : "text-violet-700",
                    )}
                  >
                    <span
                      className={cn(
                        "w-2 h-2 rounded-full inline-block",
                        r.type === "Public Holiday" ? "bg-[#be123c]" : "bg-[#6d28d9]",
                      )}
                    />
                    {r.type}
                  </span>
                </td>
                <td>
                  <span className="inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-bold bg-red-100 text-red-700">
                    {r.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}
