import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { ReplicaHeader } from "@/components/core-schools/replica/ReplicaHeader";
import { ReplicaFilterBar } from "@/components/core-schools/replica/ReplicaFilterBar";
import { CoreSchoolShell } from "@/components/core-schools/replica/CoreSchoolShell";
import { replicaBrand } from "@/lib/core-school-replica-mock";
import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";

// Core School Dashboard — executive cockpit replica.
//
// Reading order (matches the design reference 1:1):
//   1. Header — title + subtitle + bell + photo profile
//   2. Filter bar — 10 dropdowns + Filters + Export Report
//   3. 7 KPI tiles (de-duplicated — Package Complete & Potential
//      Champions are surfaced through the funnel below, not the strip)
//   4. Core Service Package Progress (8-stage funnel + minimum support + remaining)
//   5. Analytics row — Intervention bars + District heatmap + YoY
//   6. Tables row — Best Performing + Needing More Attention
//   7. Bottom row — Follow-Up Alerts + Remaining Tasks
//   8. Footer — Data-as-of timestamp + brand line + build label
//   9. Mobile bottom nav — Home · Plan · Create · Core Schools · More
//
// Mobile and tablet render the SAME replica components as desktop —
// each one is tuned via Tailwind responsive classes so phones see a
// clean stack, tablets get tighter pairings, and desktop fans out
// into the wide layout from the reference. The legacy
// `CoreSchoolsMobileView` was retired because it pulled from a
// per-CCEO filtered cohort that left every number at 0 for the demo
// user — directly contradicting an executive dashboard's job.
export default async function CoreSchoolDashboard() {
  // Resolve the signed-in user on the server, then build the role-aware
  // filter scope once per request. The bar is purely a projection of
  // this scope — no client-side fetch, no flicker, deep-link friendly.
  const user = await getCurrentUser();
  const filterScope = getFilterScope({ user });

  const body = (
    <>
      <ReplicaHeader />
      <ReplicaFilterBar scope={filterScope} />

      {/* Subtle page wash — keeps the cards crisp against a tint that's
          a half-step warmer than the global page bg, so the dashboard
          reads as a deliberate surface rather than a list of cards on
          beige paper. */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          backgroundImage:
            "radial-gradient(1200px 600px at 0% 0%, rgba(99,102,241,0.04) 0%, transparent 60%), radial-gradient(900px 500px at 100% 0%, rgba(16,185,129,0.04) 0%, transparent 55%)",
        }}
      />

      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6">
        {/* All dashboard sections live inside the shell so that clicking
            any tile can hide unrelated cards and reveal a focused
            filtered school list with a reset/export header. */}
        <CoreSchoolShell />
      </div>

      {/* Footer strip — data freshness + brand line + build label. On
          phones it stacks vertically so the timestamp never collides
          with the rights line. */}
      <footer className="px-3 sm:px-4 lg:px-6 py-4 mt-2 flex items-center justify-between gap-3 text-caption muted flex-col sm:flex-row sm:flex-wrap">
        <span className="inline-flex items-center gap-1 text-center sm:text-left">
          Data as of: <span className="font-semibold text-slate-600">{replicaBrand.dataAsOf}</span>
        </span>
        <div className="inline-flex items-center gap-3 flex-wrap justify-center">
          <span>{replicaBrand.footerLine}</span>
          <span className="muted hidden sm:inline">·</span>
          <span>All rights reserved</span>
          <span className="muted hidden sm:inline">·</span>
          <span className="font-semibold text-slate-500">{replicaBrand.buildLabel}</span>
        </div>
      </footer>

      {/* Mobile bottom nav — Home · Plan · Create (FAB) · Core Schools
          · More. Self-hidden via `md:hidden`; on tablet/desktop the
          sidebar handles primary navigation. The shell wraps the
          sidebar in `hidden md:flex`, so without this the bottom nav
          would never reach the phone viewport. */}
      <RoleBottomNav />
    </>
  );

  // Mobile and desktop share the same tree — responsive behavior is
  // handled at the component level. ResponsiveDashboard is kept for
  // future divergence (e.g., gesture-driven mobile-only flows).
  return <ResponsiveDashboard mobile={body} desktop={body} />;
}
