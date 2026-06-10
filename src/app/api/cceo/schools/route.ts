// GET /api/cceo/schools — the viewer's school directory (uploaded master,
// scoped to their supervision chain) with the SSA→recommendation summary
// folded onto every row. Same engines as /schools: directoryRecords +
// schoolRecommendationSummary. ?fy=/?week=/?month= are accepted but ignored
// (the directory is a current-state read, not a period read).

import { requireCceo, ok, type NextAction } from "../_auth";
import { directoryRecords } from "@/lib/school-directory/directory";
import { schoolRecommendationSummary } from "@/lib/planning/intervention-recommendation";

export const dynamic = "force-dynamic";

export async function GET() {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  const schools = directoryRecords(user.staffId, user.role).map((s) => ({
    ...s,
    recommendation: schoolRecommendationSummary(s.schoolId),
  }));

  const missingSsa = schools.filter((s) => s.ssaStatus !== "SSA Done");
  const nextActions: NextAction[] = missingSsa.slice(0, 3).map((s) => ({
    label: `Schedule SSA — ${s.schoolName}`,
    reason: "No SSA on record — planning stays locked until the first SSA is uploaded.",
    href: "/planning",
  }));

  return ok(
    {
      count: schools.length,
      ssaMissingCount: missingSsa.length,
      schools,
    },
    nextActions,
  );
}
