// CountryAnalyticsLive — backend-driven program snapshot for leadership
// dashboards (CD / RVP / IA). Server component: calls the analytics surfaces
// directly (the same ones /analytics uses), so the KPIs + activity pipeline are
// real backend numbers, role-scoped. Renders nothing when the backend is off.

import { Network } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchAnalyticsDashboard, fetchActivityPipeline, type GeoFilterParams } from "@/lib/api/surfaces";
import { MetricStrip } from "@/components/ui/MetricStrip";

const STATUS_LABEL: Record<string, string> = {
  planned: "Planned", assigned_to_partner: "With partner", completed: "Completed",
  awaiting_ia: "Awaiting IA", ia_confirmed: "IA confirmed", paid: "Paid", closed: "Closed", cancelled: "Cancelled",
};

export async function CountryAnalyticsLive({ geo }: { geo?: GeoFilterParams } = {}) {
  const user = await getCurrentUser();
  const [dash, pipe] = await Promise.all([fetchAnalyticsDashboard(user, geo), fetchActivityPipeline(user, geo)]);
  if (!dash.live) return null; // backend off → render nothing (page keeps its own content)
  const d = dash.data;

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Network size={14} /> Program snapshot</h3>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>

      <MetricStrip
        bare
        columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6"
        metrics={[
          { key: "schools", label: "Schools in scope", value: d.schools },
          { key: "core", label: "Core schools", value: d.coreSchools },
          { key: "client", label: "Client schools", value: d.clientSchools },
          { key: "ready", label: "Planning-ready", value: d.planningReady },
          { key: "unclustered", label: "Unclustered", value: d.unclustered, tone: d.unclustered > 0 ? "alert" : "default" },
          { key: "ssa", label: "SSA complete", value: d.ssaDone },
        ]}
      />

      {pipe.live && pipe.data.total > 0 && (
        <div className="mt-3">
          <div className="text-[10px] uppercase tracking-wider font-bold muted mb-1.5">Activity pipeline · {pipe.data.total} total</div>
          <div className="flex flex-wrap gap-1.5">
            {pipe.data.byStatus.map((s) => (
              <span key={s.status} className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md bg-[var(--color-edify-soft)]/60 text-[11px] font-semibold">
                {STATUS_LABEL[s.status] ?? s.status} <span className="tabular font-extrabold text-[var(--color-edify-primary)]">{s.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
