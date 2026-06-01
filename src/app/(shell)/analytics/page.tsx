import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { getDonorMetricSnapshot } from "@/lib/donor-metrics";
import type { DonorRoleScope, DonorReportingFilters } from "@/lib/donor-metrics-types";
import { FieldEngineAnalytics } from "@/components/analytics/field-engine/FieldEngineAnalytics";
import { computeAnalytics } from "@/lib/analytics/compute-analytics";
import { buildDateRangeFromFilters } from "@/lib/filters/apply-filters";
import { selectedFyId } from "@/lib/analytics/scope";
import { ALL_SENTINEL, type FilterSelection } from "@/lib/filters/types";

// Field Performance & School Improvement Analytics — the truth layer.
//
// Every number is computed live by the analytics engine from the workflow
// records (computeAnalytics), scoped by the shared filter bar, and drillable.
// The Donor Reporting section is fed filter-aware reach values from the same
// engine (overrides) + the active filters, so it responds to FY/region/district
// exactly like the rest of the page.

// URL query keys (mirror hooks/use-active-filters + use-filter-bar).
const URL_KEYS: Record<keyof FilterSelection, string> = {
  fy: "fy", quarter: "q", region: "region", district: "district", cluster: "cluster",
  cceo: "cceo", partner: "partner", package: "pkg", ssa: "ssa", champion: "champ",
};

function isReal(v: string): boolean {
  return !!v && v !== ALL_SENTINEL;
}

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const user = await getCurrentUser();
  const filterScope = getFilterScope({ user });

  // Resolve the active filter selection from the URL.
  const sp = await searchParams;
  const get = (k: keyof FilterSelection): string => {
    const v = sp[URL_KEYS[k]];
    return (Array.isArray(v) ? v[0] : v) ?? ALL_SENTINEL;
  };
  const selection = Object.fromEntries(
    (Object.keys(URL_KEYS) as (keyof FilterSelection)[]).map((k) => [k, get(k)]),
  ) as FilterSelection;

  // Filter-aware engine values → donor overrides (record-derived, not fabricated).
  const engine = computeAnalytics({ selection, role: user.role, scopeLabel: user.name });
  const v = (key: string) => engine.metrics.find((m) => m.key === key)?.value ?? 0;
  const overrides: Record<string, number> = {
    schoolsReached: v("schoolsReached"),
    studentsImpacted: v("learnersImpacted"),
    teachersTrained: v("teachersTrained"),
    schoolLeadersTrained: v("schoolLeadersTrained"),
    districtsCovered: v("districtsCovered"),
  };

  // Donor filters reflect the real selection (period + geography).
  const range = buildDateRangeFromFilters(selection);
  const fyId = selectedFyId(selection);
  const filters: DonorReportingFilters = {
    operationalCycleLabel: `FY ${fyId}${isReal(selection.quarter) ? ` · ${selection.quarter}` : ""}`,
    dateRangeStart: range.startDate,
    dateRangeEnd: range.endDate,
    schoolType: "all",
    deliveredBy: "all",
    ...(isReal(selection.region) ? { region: selection.region } : {}),
    ...(isReal(selection.district) ? { district: selection.district } : {}),
    ...(isReal(selection.cluster) ? { cluster: selection.cluster } : {}),
  };

  const donorSnapshot = getDonorMetricSnapshot({
    role: donorScopeForRole(user.role),
    userName: user.name,
    generatedBy: user.name,
    filters,
    overrides,
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
