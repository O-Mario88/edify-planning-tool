import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { LeaveMobileView } from "@/components/mobile/views/LeaveMobileView";
import { LeaveHeader } from "@/components/leave/LeaveHeader";
import { LeaveTodaySnapshot } from "@/components/leave/LeaveTodaySnapshot";
import { LeaveKpiRow } from "@/components/leave/LeaveKpiRow";
import { PlanningCalendar } from "@/components/leave/PlanningCalendar";
import { AutomaticPlanningRulesPanel } from "@/components/leave/AutomaticPlanningRulesPanel";
import { UpcomingLeaveScheduleTable } from "@/components/leave/UpcomingLeaveScheduleTable";
import { HolidayBlackoutDatesTable } from "@/components/leave/HolidayBlackoutDatesTable";
import { AutoBlockedConflictsCard } from "@/components/leave/AutoBlockedConflictsCard";
import { TeamAvailabilityHeatmap } from "@/components/leave/TeamAvailabilityHeatmap";
import { PlanningEngineActiveBar } from "@/components/leave/PlanningEngineActiveBar";
import { LeaveLive } from "@/components/leave/LeaveLive";

// Leave & Holiday Planning Dashboard — premium redesign.
//
// Reading order matches the planner's decision tree:
//   1. Header (chrome)
//   2. Today's Snapshot — what's happening NOW + primary action
//   3. KPI stat bar — quick context (compact, not competing with hero)
//   4. Main row: Planning Calendar (lg col 8) + Planning Rules (col 4)
//   5. Conflicts strip — full-width alert band with actions per row
//   6. Coming up + Team Availability — combined feed + heatmap (col 7 + 5)
//   7. Planning Engine Active footer
//
// All availability decisions still resolve through
// getPlanningAvailability() in lib/leave-mock.ts — single source of
// truth across the planning tool, CCEO dashboard, and CPL dashboard.
export default function LeaveHolidayPlanningDashboard() {
  return (
    <ResponsiveDashboard mobile={<LeaveMobileView />} desktop={
    <>
      <LeaveHeader />
        <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
          {/* 1. Today's plan hero — the answer-this-first surface. */}
          <LeaveTodaySnapshot />

          {/* 2. Compact KPI stat bar. */}
          <LeaveKpiRow />

          {/* Live, backend-backed leave workflow — request + approve/reject. */}
          <LeaveLive />

          {/* 3. Conflicts band — elevated above the calendar so the
                 planner sees what needs review before they start
                 scrolling the month grid. */}
          <section id="conflicts">
            <AutoBlockedConflictsCard />
          </section>

          {/* 4. Calendar + Planning rules.
                 Calendar gets the visual weight (col 8); rules card
                 sits in the right rail at col 4. */}
          <section id="planning-calendar" className="grid grid-cols-12 gap-4 items-start">
            <div className="col-span-12 lg:col-span-8">
              <PlanningCalendar initialYear={2025} initialMonth0={6} />
            </div>
            <div className="col-span-12 lg:col-span-4" id="planning-rules">
              <AutomaticPlanningRulesPanel role="CCEO" />
            </div>
          </section>

          {/* 5. Coming up + Team availability.
                 Upcoming leave + holidays sit side-by-side as a
                 combined timeline (col 7), team coverage heatmap
                 anchors the right (col 5). `items-stretch` keeps all
                 three cards at the same height; each card scrolls
                 internally so a long table never breaks the row. */}
          <section className="grid grid-cols-12 gap-4 items-stretch">
            <div className="col-span-12 lg:col-span-7 grid grid-cols-1 md:grid-cols-2 gap-4 items-stretch">
              <UpcomingLeaveScheduleTable />
              <HolidayBlackoutDatesTable />
            </div>
            <div className="col-span-12 lg:col-span-5">
              <TeamAvailabilityHeatmap />
            </div>
          </section>

          {/* 6. Footer — engine status reassurance. */}
          <PlanningEngineActiveBar />
        </div>
      </>
    } />
  );
}
