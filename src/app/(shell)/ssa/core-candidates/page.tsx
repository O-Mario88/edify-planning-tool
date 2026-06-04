import Link from "next/link";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SsaCoreCandidatesMobileView } from "@/components/mobile/views/SsaCoreCandidatesMobileView";
import { SsaHeader } from "@/components/ssa/SsaHeader";
import { SectionCard } from "@/components/ui/primitives";
import { ArrowRight } from "lucide-react";
import { coreCandidates, coreCandidateSummary } from "@/lib/core/core-candidates";
import { CoreCandidateVerifyCell } from "@/components/core/CoreCandidateVerifyCell";
import type { CoreCandidateStatus } from "@/lib/core/core-types";

const STATUS_TONE: Record<CoreCandidateStatus, string> = {
  "Candidate":               "bg-sky-100    text-sky-700",
  "Verification Pending":    "bg-amber-100  text-amber-700",
  "Verification Submitted":  "bg-amber-100  text-amber-700",
  "Verified Potential Core": "bg-emerald-100 text-emerald-700",
  "Rejected Candidate":      "bg-rose-100   text-rose-700",
  "Onboarding Pending":      "bg-violet-100 text-violet-700",
  "Onboarded as Core":       "bg-violet-100 text-violet-700",
};

export default function CoreCandidateQueuePage() {
  const candidates = coreCandidates();
  const summary = coreCandidateSummary();

  return (
    <ResponsiveDashboard mobile={<SsaCoreCandidatesMobileView />} desktop={
    <>
      <SsaHeader />
      <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
        {/* Summary */}
        <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Kpi label="Potential Candidates" value={summary.total} sub="SSA ≥ 7.5 in directory" tone="bg-sky-50 text-sky-700" />
          <Kpi label="Awaiting Verification" value={summary.candidate} sub="Enter SSA Verification ID" tone="bg-amber-50 text-amber-700" />
          <Kpi label="Verified Potential Core" value={summary.verified} sub="In onboarding queue" tone="bg-emerald-50 text-emerald-700" />
          <Kpi label="Rejected" value={summary.rejected} sub="Not core-ready" tone="bg-rose-50 text-rose-700" />
        </section>

        <SectionCard
          title="Potential Core Candidates"
          subtitle="Derived live from the School Directory — Client schools whose current-FY SSA averages 7.5+ across all areas. Verify the SSA ID to move a school into the Core Onboarding Queue."
          actions={
            summary.verified > 0 ? (
              <Link href="/core-onboarding" className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)]">
                Onboarding Queue ({summary.verified}) <ArrowRight size={12} />
              </Link>
            ) : null
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">School</th>
                  <th scope="col" className="text-left">District · Cluster</th>
                  <th scope="col" className="text-left">Owner</th>
                  <th scope="col" className="text-right">SSA Avg</th>
                  <th scope="col" className="text-left">Weakest areas</th>
                  <th scope="col" className="text-left">Status</th>
                  <th scope="col" className="text-left">Action</th>
                </tr>
              </thead>
              <tbody>
                {candidates.length === 0 && (
                  <tr><td colSpan={7} className="py-8 text-center text-[12px] muted italic">No core candidates — no Client school has a current-FY SSA at 7.5+ yet.</td></tr>
                )}
                {candidates.map((c) => (
                  <tr key={c.schoolId}>
                    <td className="text-[12px]">
                      <Link href={`/schools/${c.schoolId}`} className="font-bold hover:underline">{c.schoolName}</Link>
                      <span className="block text-[10px] muted tabular">ID {c.schoolId}</span>
                    </td>
                    <td className="text-[11.5px] muted">{c.district}{c.cluster ? ` · ${c.cluster}` : ""}</td>
                    <td className="text-[11.5px] muted">{c.accountOwnerName ?? "—"}</td>
                    <td className="text-right tabular font-extrabold">{c.averageScore.toFixed(1)}</td>
                    <td className="text-[11px] muted">{c.weakestInterventions.slice(0, 2).map((w) => w.area).join(", ")}</td>
                    <td>
                      <span className={`inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-bold ${STATUS_TONE[c.candidateStatus]}`}>
                        {c.candidateStatus}
                      </span>
                      {c.verificationId && <span className="block text-[10px] muted tabular mt-0.5">{c.verificationId}</span>}
                    </td>
                    <td>
                      {c.candidateStatus === "Candidate" ? (
                        <CoreCandidateVerifyCell schoolId={c.schoolId} schoolName={c.schoolName} />
                      ) : c.candidateStatus === "Verified Potential Core" ? (
                        <Link href="/core-onboarding" className="text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline">Onboard →</Link>
                      ) : (
                        <span className="text-[11px] muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11px] muted">
            One identity end-to-end: candidate → verification → onboarding → core plan all key on the directory schoolId.
          </div>
        </SectionCard>
      </div>
    </>
    } />
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: number; sub: string; tone: string }) {
  return (
    <div className="card px-3 py-2.5">
      <div className="text-[10.5px] font-semibold muted leading-tight">{label}</div>
      <div className="text-[20px] font-extrabold tabular leading-none mt-1">{value}</div>
      <div className={`inline-block mt-1 px-1.5 py-[1px] rounded text-[9.5px] font-bold ${tone}`}>{sub}</div>
    </div>
  );
}
