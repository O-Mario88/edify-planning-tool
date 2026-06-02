"use client";

// ExportButton — one-click client-side CSV export.
//
// Replaces the scattered disabled "Export — coming soon" buttons. Takes the rows
// already on screen + a filename, builds a CSV in the browser, and triggers a
// download. No server round-trip, no dependency. Year-2 can add server-side
// XLSX/PDF behind the same button.

import { useState } from "react";
import { Download, Check } from "lucide-react";
import { cn } from "@/lib/utils";

function toCsv(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return "";
  const headers = Array.from(
    rows.reduce<Set<string>>((acc, r) => { Object.keys(r).forEach((k) => acc.add(k)); return acc; }, new Set()),
  );
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [headers.join(",")];
  for (const r of rows) lines.push(headers.map((h) => esc(r[h])).join(","));
  return lines.join("\n");
}

export function ExportButton({
  rows,
  filename = "export",
  label = "Export",
  className,
  size = "sm",
  iconOnly = false,
  ariaLabel,
}: {
  /** Plain objects — keys become CSV columns. */
  rows: Record<string, unknown>[];
  filename?: string;
  label?: string;
  className?: string;
  size?: "sm" | "md";
  /** Render just the download icon (square button) — for dense rows. */
  iconOnly?: boolean;
  ariaLabel?: string;
}) {
  const [done, setDone] = useState(false);

  function download() {
    const csv = toCsv(rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setDone(true);
    setTimeout(() => setDone(false), 1800);
  }

  const h = iconOnly
    ? "h-8 w-8 grid place-items-center"
    : size === "md" ? "h-9 px-3.5 text-[12.5px]" : "h-8 px-3 text-[12px]";
  return (
    <button
      type="button"
      onClick={download}
      disabled={rows.length === 0}
      aria-label={ariaLabel ?? (iconOnly ? `${label} (CSV)` : undefined)}
      title={rows.length === 0 ? "Nothing to export" : `Export ${rows.length} row${rows.length === 1 ? "" : "s"} to CSV`}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-edify-border)] font-semibold transition-colors",
        "hover:bg-[var(--color-edify-soft)]/60 disabled:opacity-50 disabled:cursor-not-allowed",
        h, className,
      )}
    >
      {done ? <Check size={13} className="text-emerald-600" /> : <Download size={13} className={iconOnly ? "text-[var(--color-edify-muted)]" : ""} />}
      {!iconOnly && (done ? "Downloaded" : label)}
    </button>
  );
}
