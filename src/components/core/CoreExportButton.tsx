"use client";

// Client-side CSV export. Receives already-scoped rows from the server page and
// downloads them — no extra fetch, respects whatever the user is allowed to see.

import { Download } from "lucide-react";

export type ExportRow = Record<string, string | number | null | undefined>;

function toCsv(rows: ExportRow[]): string {
  if (rows.length === 0) return "";
  const headers = Object.keys(rows[0]);
  const escape = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [headers.join(","), ...rows.map((r) => headers.map((h) => escape(r[h])).join(","))].join("\n");
}

export function CoreExportButton({ rows, filename, label = "Export CSV" }: { rows: ExportRow[]; filename: string; label?: string }) {
  function download() {
    const csv = toCsv(rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <button type="button" onClick={download} disabled={rows.length === 0}
      className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)] disabled:opacity-40">
      <Download size={12} /> {label}
    </button>
  );
}
