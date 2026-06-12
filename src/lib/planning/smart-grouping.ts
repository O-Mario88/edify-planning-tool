// Smart Grouping for Planning (spec layer #7).
//
// When staff plan, the system proposes efficient batches instead of one-school-
// at-a-time scheduling: "5 schools in Nansana need Teaching & Learning → schedule
// them the same week" (geographic) and "8 schools are weak on Financial Health →
// run a Financial Management cluster training this month" (thematic). Saves
// transport, improves coverage, helps staff hit targets.
//
// server-only: reads the unified activity model to find what's still unscheduled.

import "server-only";

import { intakeSchools } from "@/lib/intake/intake-mock";
import { schoolWorkflowState } from "@/lib/school-directory/school-state";
import { allUnifiedActivities } from "@/lib/activity/unified-activity-source";
import { schoolRecommendationSummary } from "@/lib/planning/intervention-recommendation";
import { deliveryFor } from "@/lib/planning/intervention-recommendation";
import type { SsaInterventionArea } from "@/lib/planning/planning-gaps-mock";

export type GroupingSuggestion = {
  id: string;
  kind: "geographic" | "thematic";
  title: string;
  recommendation: string;
  area: SsaInterventionArea;
  subCounty?: string;
  schoolIds: string[];
  count: number;
};

const MIN_GROUP = 2;

export function smartGroupingSuggestions(opts: { assignedCceo?: string } = {}): GroupingSuggestion[] {
  // Schools that are ready to plan but have nothing scheduled yet.
  const scheduled = new Set(
    allUnifiedActivities()
      .filter((a) => a.stage === "planned" || a.stage === "in_progress")
      .map((a) => a.schoolId)
      .filter(Boolean) as string[],
  );

  const candidates = intakeSchools
    .filter((s) => !opts.assignedCceo || s.assignedCceo === opts.assignedCceo)
    .filter((s) => schoolWorkflowState(s).stage === "planning_ready")
    .filter((s) => !scheduled.has(s.schoolId))
    .map((s) => ({ school: s, weak: schoolRecommendationSummary(s.schoolId).weakestArea }))
    .filter((x): x is { school: typeof x.school; weak: SsaInterventionArea } => !!x.weak);

  const suggestions: GroupingSuggestion[] = [];

  // ── Geographic: same sub-county + same weak area ──
  const geoKey = (subCounty: string, area: SsaInterventionArea) => `${subCounty}::${area}`;
  const geoGroups = new Map<string, { subCounty: string; area: SsaInterventionArea; schoolIds: string[] }>();
  for (const { school, weak } of candidates) {
    const sc = school.subCounty?.trim();
    if (!sc) continue;
    const k = geoKey(sc, weak);
    const g = geoGroups.get(k) ?? { subCounty: sc, area: weak, schoolIds: [] };
    g.schoolIds.push(school.schoolId);
    geoGroups.set(k, g);
  }
  for (const [k, g] of geoGroups) {
    if (g.schoolIds.length < MIN_GROUP) continue;
    const mode = deliveryFor(g.area) === "partner" ? "partner training" : "coaching visits";
    suggestions.push({
      id: `geo-${k}`,
      kind: "geographic",
      title: `${g.schoolIds.length} schools in ${g.subCounty} need ${g.area}`,
      recommendation: `Schedule them in the same week as ${mode} to share transport.`,
      area: g.area,
      subCounty: g.subCounty,
      schoolIds: g.schoolIds,
      count: g.schoolIds.length,
    });
  }

  // ── Thematic: a weak area shared across many schools → one cluster training ──
  const themeGroups = new Map<SsaInterventionArea, string[]>();
  for (const { school, weak } of candidates) {
    themeGroups.set(weak, [...(themeGroups.get(weak) ?? []), school.schoolId]);
  }
  for (const [area, schoolIds] of themeGroups) {
    if (schoolIds.length < 3) continue; // a cluster training needs critical mass
    suggestions.push({
      id: `theme-${area}`,
      kind: "thematic",
      title: `${schoolIds.length} schools are weak on ${area}`,
      recommendation: `Run a ${area} cluster training this month instead of separate visits.`,
      area,
      schoolIds,
      count: schoolIds.length,
    });
  }

  // Biggest, highest-leverage batches first.
  return suggestions.sort((a, b) => b.count - a.count);
}
