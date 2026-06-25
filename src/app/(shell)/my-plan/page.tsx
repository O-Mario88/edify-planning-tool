import { Suspense } from "react";
import { StubPage } from "@/components/shell/StubPage";
import { MyPlanSections } from "@/components/planning/MyPlanSections";
import { PartnerPlannedSections } from "@/components/planning/PartnerPlannedSections";
import { coreOwnershipRows } from "@/lib/core/core-board";
import { MyPlanBriefingHero } from "@/components/planning/MyPlanBriefingHero";
import { MyPlanSnapshotStrip } from "@/components/planning/MyPlanSnapshotStrip";
import { MyPlanPeriodSwitcher } from "@/components/planning/MyPlanPeriodSwitcher";
import { getCurrentUser } from "@/lib/auth";
import { fetchMyPlanGrouped, fetchFundRequests, type BeMyPlanPeriod } from "@/lib/api/surfaces";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { activeFinancialYear } from "@/lib/fy-engine";
import {
  buildFundingByPeriod, fromBeActivity, sectionMyPlan,
  type MyPlanItem,
} from "@/lib/planning/my-plan-sections";
import { dailyBrief, snapshotChips } from "@/lib/planning/my-plan-brief";

// My Plan — planned work by week, month, quarter, and fiscal year (spec §11).
// Backend is the source of truth; mock store fallback only when explicitly allowed.
export const dynamic = "force-dynamic";

export default async function MyPlanPage({
  searchParams,
}: {
  searchParams: Promise<{ period?: string }>;
}) {
  const user = await getCurrentUser();
  const params = await searchParams;
  const period = (params.period ?? "month") as BeMyPlanPeriod;
  const today = new Date();
  const todayIso = today.toISOString().slice(0, 10);
  const fy = activeFinancialYear().id;

  const be = await fetchMyPlanGrouped(user, period, fy);

  if (!be.live && !isMockAllowed()) {
    return (
      <StubPage title="My Plan" subtitle="Your scheduled work, ordered by urgency.">
        <InsufficientData surface="My Plan" />
      </StubPage>
    );
  }

  let items: MyPlanItem[] = [];
  if (be.live) {
    const fr = await fetchFundRequests(user);
    const fundingByPeriod = buildFundingByPeriod(
      fr.live ? fr.data.filter((r) => r.isOwn ?? true).map((r) => ({ periodKey: r.periodKey, status: r.status })) : [],
    );
    items = be.data.items
      .map((a) => fromBeActivity(a, todayIso, fundingByPeriod))
      .filter((i): i is MyPlanItem => i !== null);
  } else if (isMockAllowed()) {
    const { activities, fundRequests } = await import("@/lib/actions/store");
    const { buildFundingByActivity, fromStoreActivity } = await import("@/lib/planning/my-plan-sections");
    const { clusterMeetingsForStaff } = await import("@/lib/cluster/cluster-core");
    const { fromClusterMeeting } = await import("@/lib/planning/my-plan-sections");
    const funding = buildFundingByActivity(fundRequests());
    items = activities()
      .filter((a) => a.assigneeId === user.staffId)
      .map((a) => fromStoreActivity(a, funding, todayIso))
      .filter((i): i is MyPlanItem => i !== null);
    const clusterItems = clusterMeetingsForStaff(user.name)
      .map((m) => fromClusterMeeting(m, todayIso))
      .filter((i): i is MyPlanItem => i !== null);
    const existingIds = new Set(items.map((i) => i.id));
    items = [...items, ...clusterItems.filter((i) => !existingIds.has(i.id))];
  }

  const sections = sectionMyPlan(items, today);
  const brief = dailyBrief({ name: user.name, now: today, sections });
  const chips = snapshotChips(sections, today);

  // Partner-owned core activities the user is monitoring — rendered as a
  // dedicated "Planned by Partner" card below the personal lanes (organized by
  // Week / Month). Lives on /my-plan because it's already-planned work; the
  // gap-focused Planning page no longer carries these monitoring cards.
  const coreOwnership = coreOwnershipRows(user.staffId, user.role);

  return (
    <StubPage
      title="My Plan"
      subtitle="Your scheduled work — switch between week, month, quarter, and fiscal year."
    >
      <div className="space-y-4">
        <Suspense fallback={null}>
          <MyPlanPeriodSwitcher />
        </Suspense>
        <MyPlanBriefingHero brief={brief} />
        <MyPlanSnapshotStrip chips={chips} />
        <MyPlanSections sections={sections} live={be.live} />
        <PartnerPlannedSections rows={coreOwnership.assignedToPartner} now={today} />
      </div>
    </StubPage>
  );
}
