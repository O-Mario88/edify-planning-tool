import { redirect } from "next/navigation";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SsaMobileView } from "@/components/mobile/views/SsaMobileView";
import { SsaHeader } from "@/components/ssa/SsaHeader";
import { InterventionPerformanceCard } from "@/components/ssa/InterventionPerformanceCard";
import { DistrictSsaPerformanceTable } from "@/components/ssa/DistrictSsaPerformanceTable";
import { DistrictHeatPanel } from "@/components/ssa/DistrictHeatPanel";
import { PriorityInterventionGapsCard } from "@/components/ssa/PriorityInterventionGapsCard";
import { UrgentInterventionSchoolsCard } from "@/components/ssa/UrgentInterventionSchoolsCard";
import { SsaTrendCard } from "@/components/ui/lazy-charts";
import { ActionInsightsPanel } from "@/components/ssa/ActionInsightsPanel";

// SSA Performance — intelligence cockpit.
//
// Layout rule: paired rows hold cards of MATCHED natural height (so no
// card leaves dead space beside a shorter one); wide tables get the
// full 12 columns (so no column cramps and no text wraps).
//
//   1. Hero band — headline Average SSA Score + status tiles.
//   2. Intervention scoreboard  +  Insights & Recommendations  (paired)
//   3. District performance table                              (full)
//   4. 6-year Trend  +  District heat panel                    (paired)
//   5. Priority intervention gaps heatmap                       (full)
//   6. Schools requiring urgent attention                       (full)
// This is the AGGREGATE SSA cockpit. A school-specific "View SSA" must never land
// here — if a schoolId is passed, send it to that school's profile (SSA section).
export default async function SsaPerformancePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const sid = Array.isArray(sp.schoolId) ? sp.schoolId[0] : sp.schoolId;
  if (sid) redirect(`/schools/${encodeURIComponent(sid)}?view=ssa`);
  return (
    <ResponsiveDashboard mobile={<SsaMobileView />} desktop={
    <>
      <SsaHeader />

      {/* Subtle page wash so cards sit on a deliberate surface. */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          backgroundImage:
            "radial-gradient(1100px 560px at 6% 0%, rgba(82,112,131,0.06) 0%, transparent 55%), radial-gradient(900px 480px at 100% 6%, rgba(44,125,128,0.05) 0%, transparent 50%)",
        }}
      />

      <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 pt-3 md:pt-4 space-y-3 md:space-y-4">
        {/* SsaHero retired per global hero removal pass. */}

        {/* 2 — Intervention scoreboard + recommendations.
            Matched height (~8 ranked rows vs ~4 insight cards), so they
            sit level. Scoreboard takes 7/12 so its labels never wrap. */}
        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch" id="interventions">
          <div className="col-span-12 xl:col-span-7">
            <InterventionPerformanceCard />
          </div>
          <div className="col-span-12 xl:col-span-5" id="alerts">
            <ActionInsightsPanel />
          </div>
        </section>

        {/* 3 — District performance — full width. An 8-column table
            needs the room; half-width cramps every cell. */}
        <section id="districts">
          <DistrictSsaPerformanceTable />
        </section>

        {/* 4 — Trend + district heat. Both compact, matched height. */}
        <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
          <div className="col-span-12 md:col-span-6">
            <SsaTrendCard />
          </div>
          <div className="col-span-12 md:col-span-6">
            <DistrictHeatPanel />
          </div>
        </section>

        {/* 5 — Intervention gaps heatmap — full width (6 districts ×
            8 interventions; the cells need horizontal room). */}
        <section id="heatmap">
          <PriorityInterventionGapsCard />
        </section>

        {/* 6 — Schools requiring urgent attention — full width. */}
        <section id="urgent">
          <UrgentInterventionSchoolsCard />
        </section>
      </div>
    </>
    } />
  );
}
