import { StubPage } from "@/components/shell/StubPage";
import { MyPlanSections } from "@/components/planning/MyPlanSections";
import { MyNextActions } from "@/components/next-action/MyNextActions";
import { getCurrentUser } from "@/lib/auth";
import { activities, fundRequests } from "@/lib/actions/store";
import { fetchMyPlanActivities } from "@/lib/api/surfaces";
import { activeFinancialYear } from "@/lib/fy-engine";
import {
  buildFundingByActivity, fromBeActivity, fromStoreActivity, sectionMyPlan,
  type MyPlanItem,
} from "@/lib/planning/my-plan-sections";

// My Plan — what is ALREADY scheduled for me, sectioned by urgency (spec §10):
// Due Today · Planned This Week · Planned This Month · Waiting on Me ·
// Rescheduled / Needs Attention. Separate from the Planning Tool (which decides
// what still needs scheduling) and from the Completed Log (history) — completed
// and closed work never renders here.
//
// Server-rendered: backend-first (the enforced activity list) with the
// in-memory store as fallback; the cards' action buttons are client islands.
export const dynamic = "force-dynamic";

export default async function MyPlanPage() {
  const user = await getCurrentUser();
  const today = new Date();
  const todayIso = today.toISOString().slice(0, 10);

  // Backend-first read (same seam as /plans); store fallback for mock-id work.
  const be = await fetchMyPlanActivities(user, activeFinancialYear().id);
  let items: MyPlanItem[];
  if (be.live) {
    items = be.data.data
      .map((a) => fromBeActivity(a, todayIso))
      .filter((i): i is MyPlanItem => i !== null);
  } else {
    const funding = buildFundingByActivity(fundRequests());
    items = activities()
      .filter((a) => a.assigneeId === user.staffId)
      .map((a) => fromStoreActivity(a, funding, todayIso))
      .filter((i): i is MyPlanItem => i !== null);
  }

  const sections = sectionMyPlan(items, today);

  return (
    <StubPage
      title="My Plan"
      subtitle="What's already scheduled for you — due today, this week, this month, what's waiting on you, and what keeps slipping."
    >
      <div className="mb-4">
        <MyNextActions assigneeId={user.staffId} heading="Your next best action" />
      </div>
      <MyPlanSections sections={sections} live={be.live} />
    </StubPage>
  );
}
