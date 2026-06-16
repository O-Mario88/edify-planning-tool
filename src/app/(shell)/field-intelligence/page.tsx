import { Brain } from "lucide-react";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { FieldIntelligenceMobileView } from "@/components/mobile/views/FieldIntelligenceMobileView";
import { ExecutiveHeader } from "@/components/director/ExecutiveHeader";
import { FieldIntelKpiRowV2 } from "@/components/field-intelligence/FieldIntelKpiRowV2";
import { TodaysFieldDebriefCard } from "@/components/field-intelligence/TodaysFieldDebriefCard";
import { WeeklyReflectionPanel } from "@/components/field-intelligence/WeeklyReflectionPanel";
import {
  autoFillDailyDebrief,
  generateWeeklyStaffSummary,
  calculateRawAchievement,
  calculateContextAdjustedAchievement,
  dailyDebriefs,
} from "@/lib/field-intelligence-mock";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Daily Field Debrief — capture the field reality of today, see the
// weekly reflection rolled up on the right. Aggregates flow up to
// Program Lead → Country Director → RVP / HR via the same engine.
export default async function FieldIntelligencePage() {
  const currentUser = toCurrentUser(await getCurrentUser());
  // The 6 KPIs + weekly reflection come from hardcoded mock debriefs (dated
  // 2025-11-12), not the live DailyDebrief backend. Withhold in production.
  if (!isMockAllowed()) return <InsufficientData surface="field intelligence" />;
  const auto = autoFillDailyDebrief(currentUser.staffId);
  const todaysDebrief = dailyDebriefs.find(
    (d) => d.staffId === currentUser.staffId && d.date === "2025-11-12",
  );

  const raw = calculateRawAchievement(auto);
  const ctx = todaysDebrief
    ? calculateContextAdjustedAchievement({
        plannedActivities: auto.plannedActivities,
        verifiedActivities: auto.verifiedActivities,
        barrierCategories: todaysDebrief.barrierCategories,
      })
    : raw;

  const weekly = generateWeeklyStaffSummary(currentUser.staffId);

  return (
    <ResponsiveDashboard mobile={<FieldIntelligenceMobileView />} desktop={
    <>
      <ExecutiveHeader
        title="Field Intelligence"
        subtitle="Daily field debriefs and the weekly reflection, rolled up from the field."
        breadcrumb={["Home", "Field Intelligence"]}
      />
        <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
          {/* Page title — Field Intelligence Engine */}
          <header className="flex items-start gap-3">
            <span className="h-9 w-9 rounded-xl bg-emerald-100 text-emerald-700 grid place-items-center shrink-0 mt-0.5">
              <Brain size={18} />
            </span>
            <div className="min-w-0">
              <h1 className="page-title">
                Field Intelligence Engine
              </h1>
              <p className="text-body muted">
                Transform daily field debriefs into leadership decisions. Capture reality,
                classify performance, and drive action that improves outcomes.
              </p>
            </div>
          </header>

          {/* 6 KPI tiles */}
          <FieldIntelKpiRowV2
            planned={auto.plannedActivities}
            completed={auto.completedActivities}
            verified={auto.verifiedActivities}
            incomplete={auto.incompleteActivities}
            rawAchievementPct={raw}
            contextAdjustedPct={ctx}
          />

          {/* Two-column work area: Today's Debrief (8) + Weekly Reflection (4) */}
          <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
            <div className="col-span-12 lg:col-span-8">
              <TodaysFieldDebriefCard
                staffName={currentUser.name}
                planned={auto.plannedActivities}
                completed={auto.completedActivities}
                verified={auto.verifiedActivities}
                incomplete={auto.incompleteActivities}
                rawAchievementPct={raw}
                contextAdjustedPct={ctx}
              />
            </div>
            <div className="col-span-12 lg:col-span-4">
              {weekly && (
                <WeeklyReflectionPanel summary={weekly} staffName={currentUser.name} />
              )}
            </div>
          </section>
        </div>
      </>
    } />
  );
}
