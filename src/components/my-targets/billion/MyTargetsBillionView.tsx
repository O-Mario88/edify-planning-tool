"use client";

import { MyTargetsTopBar } from "./MyTargetsTopBar";
import { TargetCascadeRow } from "./TargetCascadeRow";
import { TargetCategoriesProgressCard } from "./TargetCategoriesProgressCard";
import { PaceForecastCard } from "./PaceForecastCard";
import { TodayFocusCard } from "./TodayFocusCard";
import { NeedsAttentionCard } from "./NeedsAttentionCard";
import { RecoveryActionsCard } from "./RecoveryActionsCard";
import { DailyDebriefCard } from "./DailyDebriefCard";
import { AchievementMomentumCard } from "./AchievementMomentumCard";
import { MyTargetsFooterStrip } from "./MyTargetsFooterStrip";
import { MyPlanCard } from "@/components/planning/MyPlanCard";

// My Targets — Operating View Dashboard. Reading order:
//
//   1. TopBar           — eyebrow + greeting + filter pills + Export
//   2. Hero             — dark gradient + quote + 4 status tiles + CTAs
//   3. TargetCascadeRow — 4 numbered tiles (FY → Quarter → Month → Day)
//   4. Categories       — full-width matrix (FY · Q4 · May · Today)
//   5. Pace Forecast (6) + [Needs Attention / Achievement] (6) —
//      "are we behind?" paired with "what's broken?" and a compressed
//      celebration strip under it
//   6. Recovery Actions — full-width action surface
//   7. Daily Debrief (6) + Today Focus (6) — perfectly aligned twin
//      cards: end-of-day reflection on the left, dense operational
//      rail on the right
//   8. Footer mini-metrics strip
//
// Long-content cards (Categories table, Today Focus) scroll inside
// their cards so the row heights stay aligned at every viewport.
export function MyTargetsBillionView({ firstName }: { firstName?: string }) {
  return (
    <>
      <MyTargetsTopBar firstName={firstName} />
      <div className="px-4 sm:px-5 lg:px-6 pb-12 lg:pb-6 space-y-3 lg:space-y-4">
        {/* MyTargetsHero retired per global hero removal pass. */}

        <TargetCascadeRow />

        {/* My field plan — the plan behind the targets above. Every
            activity is an automatic budget line + Salesforce record. */}
        <MyPlanCard role="cceo" />

        {/* Categories — full-width on its own row so the 7-column
            table can breathe without compressing the chart that
            follows. */}
        <TargetCategoriesProgressCard />

        {/* Pace & Forecast (left column) + a stacked right column
            containing Needs Attention on top and the compressed
            Achievement & Momentum strip directly under it. The chart
            on the left and the diagnosis + celebration on the right
            now read as a single coordinated unit. */}
        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
          <div className="col-span-12 md:col-span-6">
            <PaceForecastCard />
          </div>
          <div className="col-span-12 md:col-span-6 flex flex-col gap-3 lg:gap-4">
            <NeedsAttentionCard />
            <AchievementMomentumCard />
          </div>
        </section>

        {/* Recovery Actions takes its own full-width row so Daily
            Debrief and Today Focus below can sit side-by-side at the
            same height. */}
        <RecoveryActionsCard />

        {/* Daily Debrief + Today Focus — perfectly aligned twin cards.
            items-stretch keeps both ends matched; Daily Debrief
            includes a "Recent debriefs" section that gives it enough
            content weight to match Today Focus's dense rail without
            wasted whitespace. */}
        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
          <div className="col-span-12 md:col-span-6">
            <DailyDebriefCard />
          </div>
          <div className="col-span-12 md:col-span-6">
            <TodayFocusCard />
          </div>
        </section>

        <MyTargetsFooterStrip />
      </div>
    </>
  );
}
