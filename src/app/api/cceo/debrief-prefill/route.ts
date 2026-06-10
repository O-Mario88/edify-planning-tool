// GET /api/cceo/debrief-prefill — everything the Daily Debrief drawer needs
// before the user types: role-shaped prompts, categories, priorities, the
// default routing recipients, and today's already-submitted state (via the
// same backend surface /api/debriefs reads). The form copy lives in
// src/lib/debrief/* — this is a thin server wrapper, not duplicated logic.
// ?fy=/?week=/?month= are ignored (a debrief is always "today").

import { requireCceo, ok, type NextAction } from "../_auth";
import { promptsForRole, titleForRole, subtitleForRole } from "@/lib/debrief/prompts";
import { categoriesForRole } from "@/lib/debrief/categories";
import { PRIORITIES } from "@/lib/debrief/priorities";
import { routeRecipients, labelForRecipient } from "@/lib/debrief/routing";
import { submitterRoleFor } from "@/lib/debrief/types";
import { fetchDebriefsToday } from "@/lib/api/surfaces";

export const dynamic = "force-dynamic";

export async function GET() {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  // Admin previews the CCEO form (no submitter role of its own).
  const submitter = submitterRoleFor(user.role) ?? "CCEO";

  const today = await fetchDebriefsToday(user);

  const defaultRecipients = routeRecipients(submitter, [], "Normal").map((r) => ({
    role: r,
    label: labelForRecipient(r),
  }));

  const nextActions: NextAction[] = today.live
    ? [] // the drawer reads the live state to decide; no recommendation needed
    : [
        {
          label: "Submit today's debrief",
          reason: "No live debrief state available — the drawer will treat today as unsubmitted.",
          href: "/debriefs",
        },
      ];

  return ok(
    {
      submitterRole: submitter,
      title: titleForRole(submitter),
      subtitle: subtitleForRole(submitter),
      prompts: promptsForRole(submitter),
      categories: categoriesForRole(submitter),
      priorities: PRIORITIES,
      defaultRecipients,
      today: today.live ? { live: true, ...today.data } : { live: false, error: today.error },
    },
    nextActions,
  );
}
