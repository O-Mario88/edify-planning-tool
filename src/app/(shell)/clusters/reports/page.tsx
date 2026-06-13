import { PageHeader } from "@/components/ui/PageHeader";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { verifiedClusterImpact } from "@/lib/cluster/cluster-core";
import { clusterAcquisitionMetrics } from "@/lib/cluster/cluster-join-source";

// Cluster donor/impact report — built ONLY from IA-confirmed (verified) cluster
// activities. Every number traces back to a Salesforce TS- id + cluster.
export default async function ClusterReportsPage() {
  const v = verifiedClusterImpact();
  const acq = clusterAcquisitionMetrics();

  return (
    <>
      <PageHeader
        title="Cluster Impact Report"
        subtitle="Donor-ready figures count only IA-confirmed cluster activities. Every row below traces to a Salesforce TS- training id."
        dateLabel="Donor"
        backFallbackHref="/clusters"
      />
      <div className="px-4 sm:px-5 md:px-6 pb-12 space-y-4">
        <MetricStrip
          columns="grid-cols-2 md:grid-cols-4"
          metrics={[
            { key: "meetings", label: "Verified meetings", value: v.verifiedMeetings },
            { key: "teachers", label: "Teachers reached", value: v.teachersReached },
            { key: "leaders", label: "School leaders reached", value: v.schoolLeadersReached },
            { key: "attendance", label: "Total attendance", value: v.attendanceTotal },
            { key: "active", label: "Clusters active", value: v.clustersWithVerified },
            { key: "schools", label: "Schools in clusters", value: v.schoolsInClusters },
            { key: "joined", label: "New schools via cluster", value: acq.schoolsJoined },
            { key: "learners", label: "Learners added via cluster", value: acq.learnersAdded },
          ]}
        />

        <section className="card rounded-2xl overflow-hidden">
          <header className="px-4 pt-3.5 pb-2">
            <h2 className="text-[14px] font-extrabold tracking-tight">Verified activities (traceability)</h2>
            <p className="text-[11.5px] muted mt-0.5">Each IA-confirmed cluster activity contributing to the figures above.</p>
          </header>
          {v.rows.length === 0 ? (
            <p className="px-4 py-6 text-center text-[12px] muted">No IA-confirmed cluster activities yet — verified impact appears once IA confirms completed meetings.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-left muted border-y border-[var(--color-edify-divider)]">
                    <th className="py-2 px-3 font-semibold">Cluster</th>
                    <th className="py-2 px-3 font-semibold">District</th>
                    <th className="py-2 px-3 font-semibold">Activity</th>
                    <th className="py-2 px-3 font-semibold">Date</th>
                    <th className="py-2 px-3 font-semibold">By</th>
                    <th className="py-2 px-3 font-semibold">SF id</th>
                    <th className="py-2 px-3 font-semibold text-right">Teachers</th>
                    <th className="py-2 px-3 font-semibold text-right">Leaders</th>
                    <th className="py-2 px-3 font-semibold text-right">Total</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {v.rows.map((r) => (
                    <tr key={r.id} className="border-b border-[var(--color-edify-divider)] last:border-0">
                      <td className="py-2 px-3 font-semibold text-[var(--color-edify-text)]">{r.clusterName}</td>
                      <td className="py-2 px-3 muted">{r.district}</td>
                      <td className="py-2 px-3">{r.label}</td>
                      <td className="py-2 px-3 muted">{r.date}</td>
                      <td className="py-2 px-3"><span className={r.organizer === "partner" ? "text-violet-700" : "text-sky-700"}>{r.organizer === "partner" ? "Partner" : "Edify"}</span></td>
                      <td className="py-2 px-3"><span className="px-1.5 py-[1px] rounded bg-slate-100 text-slate-600 text-[10px] font-bold">{r.salesforceTrainingId ?? "—"}</span></td>
                      <td className="py-2 px-3 text-right font-extrabold">{r.teachers}</td>
                      <td className="py-2 px-3 text-right font-extrabold">{r.schoolLeaders}</td>
                      <td className="py-2 px-3 text-right font-extrabold">{r.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
