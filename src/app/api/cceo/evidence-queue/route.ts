// GET /api/cceo/evidence-queue — the CCEO's guided "what is blocking my
// completed work" queues (spec §16): Evidence Required · Salesforce ID
// Required · IA Returned · Accountability Pending. One engine call —
// buildEvidenceQueues — scoped by the signed-in staffId.
// ?fy=/?week=/?month= are ignored (the queues are current-state).

import { requireCceo, ok, type NextAction } from "../_auth";
import { buildEvidenceQueues } from "@/lib/cceo/evidence-queues";

export const dynamic = "force-dynamic";

export async function GET() {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  const queues = buildEvidenceQueues({ staffId: user.staffId });

  const nextActions: NextAction[] = [];
  const firstEvidence = queues.evidenceRequired[0];
  if (firstEvidence) {
    nextActions.push({
      label: `Capture evidence — ${firstEvidence.schoolOrCluster}`,
      reason: firstEvidence.blockedReason,
      href: firstEvidence.href,
    });
  }
  const firstReturned = queues.iaReturned[0];
  if (firstReturned) {
    nextActions.push({
      label: `Fix IA return — ${firstReturned.schoolOrCluster}`,
      reason: firstReturned.blockedReason,
      href: firstReturned.href,
    });
  }
  const firstAcct = queues.accountabilityPending[0];
  if (firstAcct) {
    nextActions.push({
      label: `Close accountability — ${firstAcct.weekLabel}`,
      reason: firstAcct.blockedReason,
      href: firstAcct.href,
    });
  }

  return ok(queues, nextActions);
}
