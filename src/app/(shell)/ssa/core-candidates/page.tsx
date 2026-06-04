import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SsaCoreCandidatesMobileView } from "@/components/mobile/views/SsaCoreCandidatesMobileView";
import { SsaHeader } from "@/components/ssa/SsaHeader";
import { CoreCandidateSummaryCards } from "@/components/ssa/CoreCandidateSummaryCards";
import { CoreCandidateTable } from "@/components/ssa/CoreCandidateTable";
import { SectionCard } from "@/components/ui/primitives";
import { ssaVerificationTodos } from "@/lib/ssa-mock";
import { ssaTodoCompletionFor } from "@/lib/ssa/verification-todos";
import { SsaTodoCompleteCell } from "@/components/ssa/SsaTodoCompleteCell";

export default function CoreCandidateQueuePage() {
  return (
    <ResponsiveDashboard mobile={<SsaCoreCandidatesMobileView />} desktop={
    <>
      <SsaHeader />
        <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
          <CoreCandidateSummaryCards />

          <CoreCandidateTable />

          <SectionCard
            title="SSA Verification Required (Staff Todos)"
            subtitle="Auto-created by the recommendation engine for Client schools at SSA 7.5+ across all 8 interventions."
          >
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Todo</th>
                  <th scope="col" className="text-left">School</th>
                  <th scope="col" className="text-left">Assigned Staff</th>
                  <th scope="col" className="text-left">Status</th>
                  <th scope="col" className="text-left">SSA ID</th>
                  <th scope="col" className="text-left">Due</th>
                  <th scope="col" className="text-left">Action</th>
                </tr>
              </thead>
              <tbody>
                {ssaVerificationTodos.map((t) => {
                  const done = ssaTodoCompletionFor(t.todoId);
                  return (
                    <tr key={t.todoId}>
                      <td className="text-body font-semibold whitespace-nowrap">
                        Verify SSA for Potential Core School Review
                      </td>
                      <td className="text-[12px]">{t.schoolName}</td>
                      <td className="text-[12px] muted">{t.assignedStaffId}</td>
                      <td>
                        {done ? (
                          <span className="inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-bold bg-emerald-100 text-emerald-700">
                            {done.newStatus} · {done.flag}
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-bold bg-amber-100 text-amber-700">
                            {t.status}
                          </span>
                        )}
                      </td>
                      <td className="text-[11.5px] tabular muted">
                        {done ? (
                          /* ID-consistency: show the EXACT entered verification id. */
                          <span title="Verification ID entered by staff">
                            <b className="text-[var(--color-edify-text)]">{done.ssaVerificationId}</b>
                            <span className="block text-[10px] muted">was {t.originalSsaId}</span>
                          </span>
                        ) : (
                          t.originalSsaId
                        )}
                      </td>
                      <td className="text-[12px] muted">{t.dueDate ?? "—"}</td>
                      <td>
                        {done ? (
                          <span className="text-[11px] muted">Verified by {done.completedByName}</span>
                        ) : (
                          <SsaTodoCompleteCell todoId={t.todoId} schoolName={t.schoolName} />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11px] muted">
              Duplicate todos are prevented per (school, originalSsaId). Marking done requires
              the new SSA Verification ID — the queue then shows that exact ID back.
            </div>
          </SectionCard>
        </div>
      </>
    } />
  );
}
