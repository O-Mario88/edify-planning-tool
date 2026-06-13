// /partner/today — Today To-Do.
//
// Default partner landing page. Answers one question: what must our
// partner team do today, in what order, for which schools, and what
// evidence must be submitted before the day is complete?
//
// Reading order (deliberate):
//   1. Today's Partner Work — calm header + people line
//   2. 5 summary cards
//   3. Priority to-do list (heart of the page)
//   4. Evidence Required Today
//   5. Corrections Due Today
//   6. Payment Blockers Today
//   7. Done for Today closure card
//
// No analytics. No charts. By design.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerTodayTaskList } from "@/components/partner/PartnerTodayTaskList";
import { PartnerTodayBottomSections } from "@/components/partner/PartnerTodayBottomSections";
import { DoneForTodayPartner } from "@/components/partner/DoneForTodayPartner";
import { PartnerClustersSummaryCard } from "@/components/cluster/PartnerClustersSummaryCard";
import { PartnerWorkQueueLive } from "@/components/partner/PartnerWorkQueueLive";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerTodayPage({
  searchParams,
}: {
  searchParams: Promise<{ preview?: string }>;
}) {
  const user = await getCurrentUser();
  const params = await searchParams;
  const previewMode = process.env.NODE_ENV !== "production" && params.preview === "1";
  if (!previewMode && !ALLOWED.has(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  return (
    <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
      {/* Live, backend-driven: activities routed to this partner org. */}
      <PartnerWorkQueueLive />
      <PartnerTodayTaskList />
      <PartnerClustersSummaryCard />
      <PartnerTodayBottomSections />
      <DoneForTodayPartner />
    </div>
  );
}
