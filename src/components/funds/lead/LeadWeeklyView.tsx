"use client";

import { useState } from "react";
import { LeadWeeklyHeader } from "./LeadWeeklyHeader";
import { LeadWeeklyKpiRow } from "./LeadWeeklyKpiRow";
import { LeadWeeklyQueue } from "./LeadWeeklyQueue";

// Program Lead — Weekly Fund Approvals page.
//
// Layout:
//   1. Header     — title + period chips + Export
//   2. KPI strip  — 6 lead-side KPIs
//   3. Queue      — full-width inline-expanding accordion. Each row
//      reveals the LeadRequestDetail in place so PLs can approve /
//      return / message right from the row without losing scroll
//      context. The old right-side detail pane is gone — clicking a
//      row toggles its expansion; clicking the open row collapses it.
export function LeadWeeklyView() {
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);
  const onSelect = (id: string) =>
    setSelectedId((cur) => (cur === id ? undefined : id));

  return (
    <>
      <LeadWeeklyHeader />
      <LeadWeeklyKpiRow />

      <div className="px-3 sm:px-4 lg:px-6 pb-3 space-y-3 lg:space-y-4">
        <LeadWeeklyQueue selectedId={selectedId} onSelect={onSelect} />
      </div>
    </>
  );
}
