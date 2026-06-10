// GET /api/cceo/salesforce-queue — the "Salesforce ID Required" slice of the
// evidence queues (spec §16): completed work with evidence but no SVE-/TS-
// completion ID, the gate before IA verification + payment. Same engine as
// /api/cceo/evidence-queue (buildEvidenceQueues), narrowed to this gate.
// ?fy=/?week=/?month= are ignored (current-state queue).

import { requireCceo, ok, type NextAction } from "../_auth";
import { buildEvidenceQueues } from "@/lib/cceo/evidence-queues";
import { SALESFORCE_QUEUE_HREF } from "@/lib/cceo/partner-work";

export const dynamic = "force-dynamic";

export async function GET() {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  const queues = buildEvidenceQueues({ staffId: user.staffId });

  const nextActions: NextAction[] = queues.sfIdRequired.slice(0, 3).map((item) => ({
    label: `Enter ${item.expectedPrefix} ID — ${item.schoolOrCluster}`,
    reason: item.blockedReason,
    href: item.href,
  }));

  return ok(
    {
      count: queues.counts.salesforce,
      items: queues.sfIdRequired,
      queueHref: SALESFORCE_QUEUE_HREF,
    },
    nextActions,
  );
}
