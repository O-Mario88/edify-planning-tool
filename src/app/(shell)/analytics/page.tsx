import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { fetchAnalyticsDashboard, fetchAnalyticsSsa, fetchActivityPipeline, fetchContributionSummary, type ContributionLens, type ContributionSummary } from "@/lib/api/surfaces";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { LiveBadge, BackendOfflineBanner } from "@/components/ui/BackendStatus";
import { MyContribution } from "@/components/analytics/MyContribution";
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

  // Live backend band — scoped counts straight from edify-api (Postgres). Sits
  // above the workflow engine so the two truth layers are visible side by side;
  // renders only when the backend is enabled and reachable.
  const [beDash, beSsa, bePipe] = await Promise.all([
    fetchAnalyticsDashboard(user),
    fetchAnalyticsSsa(user),
    fetchActivityPipeline(user),
  ]);
  const liveBand = buildLiveBand(beDash, beSsa, bePipe);
  const liveError = !beDash.live ? beDash.error : null;

  // Scope-enforced contribution lens. PL gets own / team / combined (team = the
  // CCEOs they supervise); CCEO gets own-schools only; country roles get a
  // country aggregate. Backend enforces — a CCEO asking for team is a 403.
  const contributionLenses = await loadContributionLenses(user, fyId);
  const contributionTitle = contributionTitleFor(user.role);

  return (
    <div className="px-3 sm:px-4 md:px-5 lg:px-6 pt-4 pb-24 space-y-4">
      <header className="min-w-0">
        <h1 className="page-title">Analytics</h1>
        <p className="text-body muted">
          Workflow-derived, filter-aware, drillable. Every number traces to the records behind it.
        </p>
      </header>
      {contributionLenses && (
        <MyContribution title={contributionTitle} fy={fyId} lenses={contributionLenses} />
      )}
      {liveBand && (
        <div className="space-y-2">
          <LiveBadge label="Live · backend API · scoped counts" />
          <MetricStrip
            title="Directory & activity — live from edify-api"
            metrics={liveBand}
            columns="grid-cols-2 sm:grid-cols-3 md:grid-cols-5 xl:grid-cols-9"
          />
        </div>
      )}
      <BackendOfflineBanner error={liveError} />
      <FieldEngineAnalytics
        filterScope={filterScope}
        role={user.role}
        scopeLabel={user.name}
        donorSnapshot={donorSnapshot}
      />
    </div>
  );
}

// Build the live KPI band from the three scoped backend analytics endpoints.
// Returns null when the dashboard summary isn't live (backend off/unreachable),
// so the band simply doesn't render.
function buildLiveBand(
  dash: Awaited<ReturnType<typeof fetchAnalyticsDashboard>>,
  ssa: Awaited<ReturnType<typeof fetchAnalyticsSsa>>,
  pipe: Awaited<ReturnType<typeof fetchActivityPipeline>>,
): MetricCell[] | null {
  if (!dash.live) return null;
  const d = dash.data;
  const cells: MetricCell[] = [
    { key: "schools", label: "Schools in scope", value: d.schools },
    { key: "core", label: "Core", value: d.coreSchools },
    { key: "client", label: "Client", value: d.clientSchools },
    { key: "ready", label: "Planning Ready", value: d.planningReady, tone: d.planningReady ? "good" : "default" },
    { key: "unclustered", label: "Unclustered", value: d.unclustered, tone: d.unclustered ? "alert" : "default" },
    { key: "ssa_done", label: "SSA Complete", value: d.ssaDone, tone: d.ssaDone ? "good" : "default" },
  ];
  if (ssa.live) {
    cells.push(
      { key: "ssa_schools", label: "Schools w/ SSA", value: ssa.data.schoolsWithSsa },
      { key: "ssa_avg", label: "Avg SSA Score", value: ssa.data.overallAverage, unit: "/10" },
    );
  }
  if (pipe.live) {
    cells.push({ key: "activities", label: "Activities", value: pipe.data.total });
  }
  return cells;
}

// Roles that get a school-improvement contribution lens. Partner/HR have a
// different contribution model (assigned work / staff performance) — later phase.
const CONTRIBUTION_ROLES = ["CCEO", "CountryProgramLead", "CountryDirector", "RVP", "ImpactAssessment", "ProgramAccountant", "Admin"];

async function loadContributionLenses(
  user: Awaited<ReturnType<typeof getCurrentUser>>,
  fy: string,
): Promise<Partial<Record<ContributionLens, ContributionSummary>> | null> {
  if (!CONTRIBUTION_ROLES.includes(user.role)) return null;
  const own = await fetchContributionSummary(user, { lens: "own", fy });
  if (!own.live) return null; // backend off/unreachable → don't render the lens
  const lenses: Partial<Record<ContributionLens, ContributionSummary>> = { own: own.data };
  // Only PL has a genuine own-vs-team split worth tabbing; country roles' lenses
  // all resolve to the same country aggregate, so a single lens reads cleaner.
  if (user.role === "CountryProgramLead" && own.data.canViewTeam) {
    const [team, combined] = await Promise.all([
      fetchContributionSummary(user, { lens: "team", fy }),
      fetchContributionSummary(user, { lens: "combined", fy }),
    ]);
    if (team.live) lenses.team = team.data;
    if (combined.live) lenses.combined = combined.data;
  }
  return lenses;
}

function contributionTitleFor(role: string): string {
  switch (role) {
    case "CCEO": return "My Contribution to School Improvement";
    case "CountryProgramLead": return "My Contribution & Team Impact";
    case "CountryDirector": return "Country Impact";
    case "RVP": return "Regional / Country Impact (summary)";
    case "ImpactAssessment": return "Verification & Impact Contribution";
    case "ProgramAccountant": return "Accountability Contribution";
    default: return "My Contribution";
  }
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
