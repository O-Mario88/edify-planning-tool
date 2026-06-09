"use client";

// View SSA — LIVE, for ONE selected school (not a general grid). Fetches that
// school's SSA history from the backend (/api/ssa/school/:schoolId): the latest
// record's 8 intervention scores, the two weakest, verification status, and FY
// history. This is the "View SSA" drawer content. No mock.

import { useEffect, useState } from "react";
import { Grid3x3, AlertTriangle } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeSchoolSsaRecord } from "@/lib/api/surfaces";

const LABEL: Record<string, string> = {
  christlike_behaviour: "Christ-like Behaviour", exposure_to_word_of_god: "Exposure to the Word of God",
  leadership: "Leadership Best Practice", teaching_and_learning: "Teaching Environment",
  learning_environment: "Learning Environment", government_requirements: "Government Requirements",
  financial_health: "Fees / Budget / Accounts", education_technology: "Education Technology", enrollment: "Enrollment",
};
const tone = (v: number) => (v >= 8 ? "bg-emerald-500 text-white" : v >= 7 ? "bg-emerald-100 text-emerald-700" : v >= 5 ? "bg-amber-100 text-amber-700" : "bg-rose-100 text-rose-700");

export function SchoolSsaLive({ schoolId }: { schoolId: string }) {
  const [records, setRecords] = useState<BeSchoolSsaRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true); setError(null);
    fetch(`/api/ssa/school/${encodeURIComponent(schoolId)}`, { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setRecords(j.records as BeSchoolSsaRecord[]); else setError(j.error || "Could not load SSA"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, [schoolId]);

  if (loading) return <LoadingState compact />;
  if (error) return <ErrorState compact message={error} onRetry={load} />;
  if (!records || records.length === 0) return <EmptyState compact title="No SSA yet" message="This school has no SSA on record. Schedule an SSA to unlock planning." />;

  const latest = records[0];
  const scores = [...latest.scores].sort((a, b) => a.score - b.score);
  const twoWorst = scores.slice(0, 2);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-[13px] font-extrabold inline-flex items-center gap-1.5"><Grid3x3 size={14} /> SSA · FY{latest.fy}</h3>
        <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold border",
          latest.verificationStatus === "confirmed" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-amber-50 text-amber-700 border-amber-200")}>
          {latest.verificationStatus === "confirmed" ? "Verified" : "Awaiting verification"}
        </span>
      </div>

      {/* Two weakest = the recommendation drivers */}
      <div className="rounded-lg border border-rose-200 bg-rose-50/50 p-2.5">
        <div className="text-[10px] font-bold uppercase tracking-wide text-rose-700 mb-1 inline-flex items-center gap-1"><AlertTriangle size={11} /> Two weakest — plan these</div>
        {twoWorst.map((s) => (
          <div key={s.intervention} className="flex items-center justify-between text-[11.5px] py-0.5">
            <span className="font-semibold">{LABEL[s.intervention] ?? s.intervention}</span>
            <span className="font-extrabold tabular">{s.score}/10</span>
          </div>
        ))}
      </div>

      {/* All 8 */}
      <div className="grid grid-cols-2 gap-1.5">
        {scores.map((s) => (
          <div key={s.intervention} className="flex items-center justify-between gap-1.5 text-[11px]">
            <span className="muted truncate">{LABEL[s.intervention] ?? s.intervention}</span>
            <span className={cn("px-1.5 py-0.5 rounded text-[10.5px] font-extrabold tabular shrink-0", tone(s.score))}>{s.score}</span>
          </div>
        ))}
      </div>

      {records.length > 1 && (
        <div className="border-t border-[var(--color-edify-divider)] pt-2 text-[10.5px] muted">
          History: {records.map((r) => `FY${r.fy} (${r.averageScore ?? "—"})`).join(" · ")}
        </div>
      )}
    </div>
  );
}
