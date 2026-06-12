import { StubPage } from "@/components/shell/StubPage";
import { MyPlanSections } from "@/components/planning/MyPlanSections";
import { MyPlanBriefingHero } from "@/components/planning/MyPlanBriefingHero";
import { MyPlanSnapshotStrip } from "@/components/planning/MyPlanSnapshotStrip";
import { getCurrentUser } from "@/lib/auth";
import { activities, fundRequests } from "@/lib/actions/store";
import { fetchMyPlanActivities } from "@/lib/api/surfaces";
import { activeFinancialYear } from "@/lib/fy-engine";
import {
  buildFundingByActivity, fromBeActivity, fromStoreActivity, fromClusterMeeting, sectionMyPlan,
  type MyPlanItem,
} from "@/lib/planning/my-plan-sections";
import { clusterMeetingsForStaff } from "@/lib/cluster/cluster-core";
import { dailyBrief, snapshotChips } from "@/lib/planning/my-plan-brief";

// My Plan — the CCEO / Program Lead daily field cockpit (spec §10).
//
// Page shape:
//   1. Header (StubPage)               — who, where, plan-as-list framing
//   2. Daily Field Briefing hero       — greeting + one smart sentence + verdict
//   3. Personal Execution snapshot     — 5 urgency chips that scroll to the lane
//   4. Five urgency lanes              — Waiting · Attention · Today · Week · Month
//
// Backend-first: fetchMyPlanActivities reads the enforced list when the
// backend is on; the in-memory store is the dev fallback. The brief and
// the snapshot derive purely from the same sectioned items the lanes
// render, so the numbers are guaranteed to match.
export const dynamic = "force-dynamic";

export default async function MyPlanPage() {
  const user = await getCurrentUser();
  const today = new Date();
  const todayIso = today.toISOString().slice(0, 10);

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

  // Cluster meetings are stored separately from school activities. Merge them
  // in so scheduled meetings (SIT, 1st/2nd/3rd cluster meetings) appear in
  // the correct urgency lane without a backend round-trip.
  if (!be.live) {
    const clusterItems = clusterMeetingsForStaff(user.name)
      .map((m) => fromClusterMeeting(m, todayIso))
      .filter((i): i is MyPlanItem => i !== null);
    // De-duplicate by id in case the same meeting somehow lands in both.
    const existingIds = new Set(items.map((i) => i.id));
    items = [...items, ...clusterItems.filter((i) => !existingIds.has(i.id))];
  }

  const sections = sectionMyPlan(items, today);
  const brief = dailyBrief({ name: user.name, now: today, sections });
  const chips = snapshotChips(sections, today);

  return (
    <StubPage
      title="My Plan"
      subtitle="Your scheduled work, ordered by urgency."
    >
      <div className="space-y-4">
        <MyPlanBriefingHero brief={brief} />
        <MyPlanSnapshotStrip chips={chips} />
        <MyPlanSections sections={sections} live={be.live} />
      </div>
    </StubPage>
  );
}
