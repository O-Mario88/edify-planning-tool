// Real disbursement-ledger export. Builds a CSV from the weekly-fund requests
// and triggers a browser download — the genuine action behind every
// "Export Ledger" button. Client-only (guards on window).

import { weeklyFundRequests, currentWeek } from "./weekly-fund-mock";

function csvCell(v: string | number): string {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Build the ledger CSV text (also unit-testable without the DOM). */
export function buildLedgerCsv(): string {
  const header = ["Request ID", "Staff", "District", "Week", "Status", "Requested (UGX)", "Week Start", "Week End"];
  const lines = [header.join(",")];
  for (const r of weeklyFundRequests) {
    lines.push(
      [
        r.id,
        r.staffName,
        r.district ?? "",
        `W${r.period.weekOfMonth}`,
        r.status,
        r.requestedAmount?.amount ?? 0,
        r.period.weekStartIso ?? "",
        r.period.weekEndIso ?? "",
      ].map(csvCell).join(","),
    );
  }
  return lines.join("\n");
}

/** Download the ledger as a .csv file. Returns the row count exported. */
export function exportDisbursementLedger(): number {
  if (typeof window === "undefined") return 0;
  const csv = buildLedgerCsv();
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `disbursement-ledger-${currentWeek.monthIso}-W${currentWeek.weekOfMonth}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return weeklyFundRequests.length;
}
