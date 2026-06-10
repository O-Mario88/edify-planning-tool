// GET /api/cceo/partner-work — the CCEO's partner-monitoring view (spec §15):
// six workflow buckets (not scheduled → payment pipeline), the most urgent
// rows, and the payment-pipeline summary. One engine call — buildPartnerWork —
// scoped by the viewer's identity (their assigned partner activities).
// ?fy=/?week=/?month= are ignored (the monitor is current-state).

import { requireCceo, ok, type NextAction } from "../_auth";
import { buildPartnerWork } from "@/lib/cceo/partner-work";

export const dynamic = "force-dynamic";

export async function GET() {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  const work = buildPartnerWork({
    name: user.name,
    role: user.role,
    staffId: user.staffId,
  });

  const nextActions: NextAction[] = work.urgent.slice(0, 3).map((row) => ({
    label: `${row.actionLabel} — ${row.school}`,
    reason: `${row.reason} (${row.partner} · ${row.due}).`,
    href: row.actionHref,
  }));

  return ok(work, nextActions);
}
