import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { getDonorMetricSnapshot } from "@/lib/donor-metrics";
import type { DonorRoleScope } from "@/lib/donor-metrics-types";
import { FieldEngineAnalytics } from "@/components/analytics/field-engine/FieldEngineAnalytics";

// Field Performance & School Improvement Analytics — the truth layer.
//
// Every number is computed live by the analytics engine from the workflow
// records (computeAnalytics), scoped by the shared filter bar, and drillable to
// the exact records behind it — consistent across every role. The role-scoped
// Donor Reporting Impact section (evidence-gated, computed server-side) renders
// below. Replaces the previous hand-typed per-role consoles.
export default async function AnalyticsPage() {
  const user = await getCurrentUser();
  const filterScope = getFilterScope({ user });
  const donorSnapshot = getDonorMetricSnapshot({
    role: donorScopeForRole(user.role),
    userName: user.name,
    generatedBy: user.name,
  });

  return (
    <div className="px-3 sm:px-4 md:px-5 lg:px-6 pt-4 pb-24 space-y-4">
      <header className="min-w-0">
        <h1 className="page-title">Analytics</h1>
        <p className="text-body muted">
          Workflow-derived, filter-aware, drillable. Every number traces to the records behind it.
        </p>
      </header>
      <FieldEngineAnalytics
        filterScope={filterScope}
        role={user.role}
        scopeLabel={user.name}
        donorSnapshot={donorSnapshot}
      />
    </div>
  );
}

function donorScopeForRole(role: string): DonorRoleScope {
  switch (role) {
    case "CCEO":               return "CCEO";
    case "CountryProgramLead": return "ProgramLead";
    case "ImpactAssessment":   return "ImpactAssessment";
    case "CountryDirector":    return "CountryDirector";
    case "RVP":                return "RVP";
    default:                   return "ProgramLead";
  }
}
