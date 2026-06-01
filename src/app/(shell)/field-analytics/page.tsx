import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { FieldEngineAnalytics } from "@/components/analytics/field-engine/FieldEngineAnalytics";

// Engine-backed analytics (Phase 1 reference surface).
//
// Every number is computed live from the workflow records by
// computeAnalytics, scoped by the shared filter bar, and drillable. The
// server resolves the signed-in user + the role-aware filter scope once;
// the client view owns filter state (URL) and recomputes on change.
export default async function FieldAnalyticsPage() {
  const user = await getCurrentUser();
  const filterScope = getFilterScope({ user });

  return (
    <div className="px-3 sm:px-4 md:px-5 lg:px-6 pt-4 pb-24 space-y-4">
      <header className="min-w-0">
        <h1 className="page-title">Field Analytics</h1>
        <p className="text-body muted">
          Workflow-derived, filter-aware, drillable. Every number traces to the records behind it.
        </p>
      </header>
      <FieldEngineAnalytics filterScope={filterScope} role={user.role} scopeLabel={user.name} />
    </div>
  );
}
