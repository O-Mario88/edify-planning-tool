"use client";

import Link from "next/link";
import { MobileSubpageShell } from "@/components/mobile/views/MobileSubpageShell";
import { CoreCandidateVerifyCell } from "@/components/core/CoreCandidateVerifyCell";
import type { CoreCandidate, CoreCandidateStatus } from "@/lib/core/core-types";

const STATUS_TONE: Record<CoreCandidateStatus, string> = {
  "Candidate":               "bg-sky-100 text-sky-700",
  "Verification Pending":    "bg-amber-100 text-amber-700",
  "Verification Submitted":  "bg-amber-100 text-amber-700",
  "Verified Potential Core": "bg-emerald-100 text-emerald-700",
  "Rejected Candidate":      "bg-rose-100 text-rose-700",
  "Onboarding Pending":      "bg-violet-100 text-violet-700",
  "Onboarded as Core":       "bg-violet-100 text-violet-700",
};

export function SsaCoreCandidatesMobileView({
  candidates = [],
  summary = { total: 0, candidate: 0, verified: 0, rejected: 0 },
}: {
  candidates?: CoreCandidate[];
  summary?: { total: number; candidate: number; verified: number; rejected: number };
}) {
  return (
    <MobileSubpageShell
      title="Core Candidates"
      subtitle="Directory schools with SSA ≥ 7.5 — verify to onboard."
    >
      <div className="grid grid-cols-3 gap-2 px-3">
        <Kpi label="Candidates" value={summary.total} />
        <Kpi label="To verify" value={summary.candidate} />
        <Kpi label="Verified" value={summary.verified} />
      </div>

      {summary.verified > 0 && (
        <div className="px-3">
          <Link href="/core-onboarding" className="block text-center rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold py-2">
            Onboarding Queue ({summary.verified}) →
          </Link>
        </div>
      )}

      <div className="px-3 flex flex-col gap-2 pb-4">
        {candidates.length === 0 && (
          <p className="text-center text-[12px] muted italic py-6">No core candidates yet.</p>
        )}
        {candidates.map((c) => (
          <div key={c.schoolId} className="card p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[13px] font-extrabold tracking-tight truncate">{c.schoolName}</div>
                <div className="text-[11px] muted truncate">{c.district} · {c.accountOwnerName ?? "—"} · SSA {c.averageScore.toFixed(1)}</div>
              </div>
              <span className={`inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-bold whitespace-nowrap ${STATUS_TONE[c.candidateStatus]}`}>
                {c.candidateStatus}
              </span>
            </div>
            <div className="mt-2 flex items-center justify-between gap-2">
              <span className="text-[10.5px] muted truncate">Weakest: {c.weakestInterventions.slice(0, 2).map((w) => w.area).join(", ")}</span>
              {c.candidateStatus === "Candidate" ? (
                <CoreCandidateVerifyCell schoolId={c.schoolId} schoolName={c.schoolName} />
              ) : c.candidateStatus === "Verified Potential Core" ? (
                <Link href="/core-onboarding" className="text-[11px] font-bold text-[var(--color-edify-primary)]">Onboard →</Link>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </MobileSubpageShell>
  );
}

function Kpi({ label, value }: { label: string; value: number }) {
  return (
    <div className="card px-2.5 py-2 text-center">
      <div className="text-[16px] font-extrabold tabular leading-none">{value}</div>
      <div className="text-[9.5px] muted mt-0.5">{label}</div>
    </div>
  );
}
