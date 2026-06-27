import { Database, CloudOff } from "lucide-react";

// Shared backend-status chips. Used by every surface wired to edify-api so the
// "where is this data from" signal looks identical everywhere.

/** Green pill — the data on this surface is live from the backend database. */
export function LiveBadge({ fy, label }: { fy?: string; label?: string }) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 text-emerald-700 px-2.5 py-1 text-[11px] font-bold border border-emerald-200">
      <Database size={12} /> {label ?? "Live · backend API"}{fy ? ` · FY${fy}` : ""}
    </div>
  );
}

/** Amber pill — backend is disabled or unreachable; surfaces should render
 *  honest empty/error states instead of local mock data. */
export function BackendOfflineBanner({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 text-amber-700 px-2.5 py-1 text-[11px] font-bold border border-amber-200">
      <CloudOff size={12} /> Backend unavailable — showing no local mock data ({error})
    </div>
  );
}
