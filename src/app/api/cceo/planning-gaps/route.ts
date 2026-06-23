// GET /api/cceo/planning-gaps — the recommendation-led planning categories
// (spec §9), built from the SAME gap sources the Planning Tool page uses:
// backend school/cluster gaps when the bridge is live, otherwise the
// viewer-scoped mock engines; plus core-package cards and project follow-up
// gaps, folded by buildPlanningCategories. ?fy=/?week=/?month= are ignored —
// a gap is by definition unscheduled, so it carries no period.

import { requireCceo, ok, type NextAction } from "../_auth";
import { toCurrentUser } from "@/lib/auth";
import { onboardedSchoolGaps, scopeGapsToViewer } from "@/lib/planning/onboarded-gaps";
import { backendSchoolGaps } from "@/lib/planning/backend-school-gaps";
import { backendClusterGaps } from "@/lib/planning/backend-cluster-gaps";
import { engineClusterGaps } from "@/lib/planning/engine-cluster-gaps";
import { assignedGapIds } from "@/lib/planning/assignment-overlay";
import { resolveCoreBoardData } from "@/lib/core/core-board";
import { directoryRecords } from "@/lib/school-directory/directory";
import { computeProjectPlanningGaps } from "@/lib/projects/project-planning-gaps";
import { buildPlanningCategories, formatUgx } from "@/lib/planning/planning-categories";
import { loadVisitCostRates, loadGroupActivityRates } from "@/lib/cost-engine/cost-engine-server";

export const dynamic = "force-dynamic";

export async function GET() {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  // School gaps: backend-first, mock fallback (minus rows already assigned).
  const backendGaps = await backendSchoolGaps(user);
  const assigned = assignedGapIds();
  const mockGaps = scopeGapsToViewer(onboardedSchoolGaps(), user.staffId, user.role)
    .filter((x) => !assigned.has(x.id));
  const schoolGaps = backendGaps ?? mockGaps;

  // Cluster gaps: backend-first, engine fallback.
  const beClusterGaps = await backendClusterGaps(user);
  const clusterGaps = beClusterGaps ?? engineClusterGaps();

  // Project follow-up gaps, scoped to the viewer's portfolio schools.
  const scoped: Set<string> | "all" =
    user.role === "CCEO"
      ? new Set(directoryRecords(user.staffId, user.role).map((s) => s.schoolId))
      : "all";
  const projectGaps = computeProjectPlanningGaps(toCurrentUser(user), scoped);

  // Core-package cards (4 visits + 4 trainings slots) — backend when live.
  const coreCards = await resolveCoreBoardData(
    { email: user.email, role: user.role },
    user.staffId,
    user.role,
  );

  const categories = buildPlanningCategories({
    schoolGaps,
    clusterGaps,
    coreCards,
    projectGaps,
    rates: { visit: loadVisitCostRates(), group: loadGroupActivityRates() },
  });

  const totals = {
    openItems: categories.reduce((n, c) => n + c.count, 0),
    redAlerts: categories.reduce((n, c) => n + c.redAlertCount, 0),
    estimatedCostUgx: categories.reduce((n, c) => n + c.estimatedCost, 0),
    liveSchoolGaps: backendGaps !== null,
    liveClusterGaps: beClusterGaps !== null,
  };

  const nextActions: NextAction[] = categories
    .filter((c) => c.priority === "high")
    .slice(0, 3)
    .map((c) => ({
      label: `Plan: ${c.label}`,
      reason: `${c.redAlertCount} red-alert of ${c.count} open — est. ${formatUgx(c.estimatedCost)}.`,
      href: "/planning",
    }));

  return ok({ categories, totals }, nextActions);
}
