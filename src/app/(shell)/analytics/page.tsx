import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { fetchAnalyticsDashboard, fetchAnalyticsSsa, fetchActivityPipeline, fetchContributionSummary, liveDistrictNamesFor, type ContributionLens, type ContributionSummary } from "@/lib/api/surfaces";
import { PageHeader } from "@/components/ui/PageHeader";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { LiveBadge, BackendOfflineBanner } from "@/components/ui/BackendStatus";
import { MyContribution } from "@/components/analytics/MyContribution";
import { FieldEngineAnalytics } from "@/components/analytics/field-engine/FieldEngineAnalytics";
import { selectedFyId } from "@/lib/analytics/scope";
import { ALL_SENTINEL, type FilterSelection } from "@/lib/filters/types";
import { geoParamsFromSelection } from "@/lib/filters/apply-filters";

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

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const user = await getCurrentUser();
  // Build the geography dropdowns from the LIVE backend district universe when
  // the backend is on, so the bar offers exactly the districts that have data.
  const liveDistrictNames = await liveDistrictNamesFor(user);
  const filterScope = getFilterScope({ user, liveDistrictNames });

  // Resolve the active filter selection from the URL.
  const sp = await searchParams;
  const get = (k: keyof FilterSelection): string => {
    const v = sp[URL_KEYS[k]];
    return (Array.isArray(v) ? v[0] : v) ?? ALL_SENTINEL;
  };
  const selection = Object.fromEntries(
    (Object.keys(URL_KEYS) as (keyof FilterSelection)[]).map((k) => [k, get(k)]),
  ) as FilterSelection;

  const fyId = selectedFyId(selection);
  // Geography filter → narrows the live band server-side so it tracks the SSA
  // tables below (which already honor the filter), instead of staying national.
  const geo = geoParamsFromSelection(selection);

  // Live backend band — scoped counts straight from edify-api (Postgres). Sits
  // above the workflow engine so the two truth layers are visible side by side;
  // renders only when the backend is enabled and reachable.
  const [beDash, beSsa, bePipe] = await Promise.all([
    fetchAnalyticsDashboard(user, geo),
    fetchAnalyticsSsa(user, geo),
    fetchActivityPipeline(user, geo),
  ]);
  const liveBand = buildLiveBand(beDash, beSsa, bePipe);
  const liveError = !beDash.live ? beDash.error : null;

  // Scope-enforced contribution lens. PL gets own / team / combined (team = the
  // CCEOs they supervise); CCEO gets own-schools only; country roles get a
  // country aggregate. Backend enforces — a CCEO asking for team is a 403.
  const contributionLenses = await loadContributionLenses(user, fyId, geo);
  const contributionTitle = contributionTitleFor(user.role);

  // CCEO (spec §22): the page reads as PERSONAL portfolio analytics — the
  // engine narrows every record set to the viewer's own schools and the
  // surface leads with a personal metric strip (country-wide sections hidden).
  const personal = user.role === "CCEO";

  return (
    <>
      <PageHeader
        title={personal ? "My Analytics" : "Analytics"}
        subtitle={
          personal
            ? "Your portfolio only — schools reached, gaps, target pace and pipeline. Every number traces to your own records."
            : "Workflow-derived, filter-aware, drillable. Every number traces to the records behind it."
        }
        filterBar={<HeaderFilterBar scope={filterScope} />}
        backFallbackHref="/dashboard"
      />
      <div className="px-3 sm:px-4 md:px-5 lg:px-6 pt-2 pb-24 space-y-4">
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
        <FieldEngineAnalytics role={user.role} scopeLabel={user.name} personal={personal} />
      </div>
    </>
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
  geo: ReturnType<typeof geoParamsFromSelection>,
): Promise<Partial<Record<ContributionLens, ContributionSummary>> | null> {
  if (!CONTRIBUTION_ROLES.includes(user.role)) return null;
  const own = await fetchContributionSummary(user, { lens: "own", fy, ...geo });
  if (!own.live) return null; // backend off/unreachable → don't render the lens
  const lenses: Partial<Record<ContributionLens, ContributionSummary>> = { own: own.data };
  // Only PL has a genuine own-vs-team split worth tabbing; country roles' lenses
  // all resolve to the same country aggregate, so a single lens reads cleaner.
  if (user.role === "CountryProgramLead" && own.data.canViewTeam) {
    const [team, combined] = await Promise.all([
      fetchContributionSummary(user, { lens: "team", fy, ...geo }),
      fetchContributionSummary(user, { lens: "combined", fy, ...geo }),
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
