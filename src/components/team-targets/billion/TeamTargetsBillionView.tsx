"use client";

import { TeamTargetsTopBar } from "./TeamTargetsTopBar";
import { TeamCascadeRow } from "./TeamCascadeRow";
import { TeamKeyTargetsProgressCard } from "./TeamKeyTargetsProgressCard";
import { TeamPaceForecastCard } from "./TeamPaceForecastCard";
import { StaffNeedsSupportCard } from "./StaffNeedsSupportCard";
import { TopTeamPerformerCard } from "./TopTeamPerformerCard";
import { TeamRecoveryActionsCard } from "./TeamRecoveryActionsCard";
import { TeamStatusDistributionCard } from "./TeamStatusDistributionCard";
import { TeamFooterStrip } from "./TeamFooterStrip";

// Team Targets — Operating View Dashboard. Reading order mirrors the
// my-targets billion view but at TEAM scale:
//
//   1. TopBar              — eyebrow + greeting + filter pills + Export
//   2. Hero                — gradient + leadership quote + 4 team status tiles + CTAs
//   3. TeamCascadeRow      — 4 tiles (FY → Quarter → Month → This Week)
//   4. Key Team Targets    — full-width matrix (7 activity categories × 4 horizons)
//   5. Team Pace (6) + [Staff Needs Support / Top Performer] (6)
//   6. Team Recovery Actions (6) + Team Status Distribution (6)
//   7. Footer mini-metrics strip
//
// Surfaces the entire program-lead workflow: where is the team, what's
// broken, who do I support today, what wins do I celebrate, where do I
// intervene, and how is the cohort distributed.
export function TeamTargetsBillionView({ firstName }: { firstName?: string }) {
  return (
    <>
      <TeamTargetsTopBar firstName={firstName} />
      <div className="px-4 sm:px-5 lg:px-6 pb-12 lg:pb-6 space-y-3 lg:space-y-4">
        {/* TeamTargetsHero retired per global hero removal pass. */}

        <TeamCascadeRow />

        <TeamKeyTargetsProgressCard />

        {/* Team Pace + (Staff Needs Support / Top Performer stacked) */}
        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
          <div className="col-span-12 md:col-span-6">
            <TeamPaceForecastCard />
          </div>
          <div className="col-span-12 md:col-span-6 flex flex-col gap-3 lg:gap-4">
            <StaffNeedsSupportCard />
            <TopTeamPerformerCard />
          </div>
        </section>

        {/* Team Recovery Actions + Team Status Distribution */}
        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
          <div className="col-span-12 md:col-span-6">
            <TeamRecoveryActionsCard />
          </div>
          <div className="col-span-12 md:col-span-6">
            <TeamStatusDistributionCard />
          </div>
        </section>

        <TeamFooterStrip />
      </div>
    </>
  );
}
