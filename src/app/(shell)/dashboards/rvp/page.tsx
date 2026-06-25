// /dashboards/rvp — Regional VP cockpit.
//
// ─────────────────────────────────────────────────────────────────────
// Every dashboard in this app must answer FOUR questions in this order.
// If you can't point to where each one is answered, the page is a box
// of widgets, not a cockpit. See /partner/today for the canonical
// expression of this discipline.
//
//   1. WHAT TO DO NOW         → CommandStack (top, single most important block)
//   2. WHAT'S HAPPENING       → KPI tiles (region-weighted scale + funds)
//   3. WHAT CHANGED / RISKY   → InsightStrip + Country Comparison + Burn-risk rail
//   4. WHAT'S NEXT (CONTEXT)  → Cycle/Impact/Performers context (deferred below)
//
// Reading order is enforced by section order — no callouts between the
// KPI row and the comparison table. Regional context (BestPerformers,
// AnnualCycle, LeadershipImpact, TeamTargets, Special Projects, SF
// compliance) lives below the fold; it's reference material, not the
// daily working surface.
// ─────────────────────────────────────────────────────────────────────

import { Globe, Wallet, Target, Sparkles, TrendingUp, AlertTriangle } from "lucide-react";
import { CommandStack } from "@/components/actions/CommandStack";
import { RecruitmentIntelligenceCard } from "@/components/analytics/RecruitmentIntelligenceCard";
import { ClientVerificationCard } from "@/components/ssa/ClientVerificationCard";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DashboardGreetingHero } from "@/components/dashboards/DashboardGreetingHero";
import { CountryAnalyticsLive } from "@/components/analytics/CountryAnalyticsLive";
import { DecisionEngineEmbed } from "@/components/leadership/DecisionEngineEmbed";
import { SectionBoundary } from "@/components/ui/SectionBoundary";
import { SectionCard, StatusBadge, ProgressRing } from "@/components/ui/primitives";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { countryRollups, specialProjects } from "@/lib/workflow-mock";
import { TeamTargetsCallout } from "@/components/team-targets/TeamTargetsCallout";
import { LeadershipImpactSnapshot } from "@/components/impact/LeadershipImpactSnapshot";
import { AnnualCycleCallout } from "@/components/fy/AnnualCycleCallout";
import { InsightStrip } from "@/components/insights/InsightCard";
import { insightsForRvp } from "@/lib/insights";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { RvpMobileView } from "@/components/mobile/views/RvpMobileView";
import { DonorImpactReachCard } from "@/components/director/DonorImpactReachCard";
import { getDonorMetricSnapshot } from "@/lib/donor-metrics";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { redirect } from "next/navigation";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { LeadershipKpiStrip } from "@/components/director/LeadershipKpiStrip";
import { fetchLeadershipSummary } from "@/lib/api/surfaces";
import { selectionFromSearchParams, geoParamsFromSelection } from "@/lib/filters/apply-filters";

export default async function RVPDashboard({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  // Defense-in-depth: middleware already gates /dashboards/rvp, but the
  // page re-checks so a guard gap can't expose the regional cockpit.
  const rawUser = await getCurrentUser();
  if (!["RVP", "Admin"].includes(rawUser.role)) {
    redirect(ROLE_REDIRECT[rawUser.role]);
  }
  const currentUser = toCurrentUser(rawUser);
  // Geography filter from the header bar — narrows the whole cockpit server-side.
  const geo = geoParamsFromSelection(selectionFromSearchParams(await searchParams));
  // Production: a clean LIVE regional cockpit — real KPIs from the backend plus
  // the live program-analytics band. (The fabricated "4-country comparison" body
  // below only renders in dev mock mode for design reference.)
  const leadership = await fetchLeadershipSummary(rawUser, geo);
  if (!isMockAllowed()) {
    return (
      <>
        <DashboardPageHeader role="RVP" />
        <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 pt-4 space-y-4 md:space-y-5">
          <DashboardGreetingHero user={rawUser} />
          <section className="space-y-3">
            <SectionHeader tier="strategic" eyebrow="Region" title="Regional performance at a glance" description="Live school counts, SSA health, activity pipeline and finance across the schools in your scope." />
            <SectionBoundary label="regional KPIs">
              {leadership.live ? <LeadershipKpiStrip s={leadership.data} scopeLabel="region" /> : <InsufficientData surface="regional KPIs" />}
            </SectionBoundary>
          </section>
          <SectionBoundary label="the program snapshot">
            <CountryAnalyticsLive geo={geo} />
          </SectionBoundary>
        </div>
      </>
    );
  }

  // Regional donor-reporting rollup — same builder as /donor-reporting,
  // scoped to RVP so the readiness snapshot and the full report agree.
  const donorSnapshot = getDonorMetricSnapshot({
    role: "RVP",
    userName: rawUser.name,
    generatedBy: rawUser.name,
  });

  const totalSchools = countryRollups.reduce((a, c) => a + c.schools, 0);
  const totalCommitted = countryRollups.reduce((a, c) => a + c.fundsCommittedUgxM, 0);
  const totalDisbursed = countryRollups.reduce((a, c) => a + c.fundsDisbursedUgxM, 0);
  const avg = (key: keyof typeof countryRollups[number]) =>
    Math.round(
      countryRollups.reduce((a, c) => a + (c[key] as number), 0) / countryRollups.length,
    );

  return (
    <ResponsiveDashboard
      mobile={
        <>
          <DashboardPageHeader role="RVP" />
          <RvpMobileView />
        </>
      }
      desktop={
    <>
      <DashboardPageHeader role="RVP" />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 pt-4 space-y-4 md:space-y-5">

      {/* GREETING HERO — system-wide layout rule: header → hero → stats → work. */}
      <DashboardGreetingHero user={rawUser} />

      {/* Live program snapshot (backend analytics). */}
      <SectionBoundary label="the program snapshot">
        <CountryAnalyticsLive geo={geo} />
      </SectionBoundary>

      {/* Leadership Decision Engine — region/country advisory boards, computed from live data. */}
      <SectionBoundary label="leadership decisions">
        <DecisionEngineEmbed />
      </SectionBoundary>

      {/* REGIONAL SIGNALS — the statistics snapshot, directly below the
          hero: region-weighted KPIs, system insights, training coverage. */}
      <section className="space-y-3">
        <SectionHeader
          tier="strategic"
          eyebrow="Regional signals"
          title="What's happening across the region"
          description="Region-weighted scale numbers and what the system is noticing this period."
        />
      <MetricStrip
        metrics={[
          { key: "schools",   label: "Schools in Region", value: totalSchools, caption: `${countryRollups.length} countries` },
          { key: "target",    label: "Avg Monthly Target", value: `${avg("monthlyTargetPct")}%`, caption: "Region-weighted" },
          { key: "visit",     label: "Avg Valid Visit",    value: `${avg("validVisitPct")}%`, caption: "Verified portion" },
          { key: "ssa",       label: "Avg SSA Done",       value: `${avg("ssaCompletedPct")}%`, caption: "Region" },
          { key: "committed", label: "Funds Committed",    value: `UGX ${totalCommitted.toLocaleString()}M`, caption: "From approved plans" },
          { key: "disbursed", label: "Funds Disbursed",    value: `UGX ${totalDisbursed.toLocaleString()}M`, caption: "Across countries" },
        ]}
        columns="grid-cols-2 sm:grid-cols-3 xl:grid-cols-6"
      />

      <InsightStrip insights={insightsForRvp()} />
      </section>

      {/* TODAY — the work stack. */}
      <CommandStack user={rawUser} hideMission />

      {/* Recruitment intelligence — regional expansion-readiness summary. */}
      <RecruitmentIntelligenceCard />

      {/* Client SSA verification — 10% portfolio quota (PL/CD/IA/RVP). */}
      <ClientVerificationCard />

      {/* COUNTRIES & RISK — comparison table and burn-rate rail. */}
      <section className="space-y-3">
        <SectionHeader
          tier="strategic"
          eyebrow="Countries & risk"
          title="Where the region is healthy and where money is parked"
          description="Country-by-country performance side-by-side and the burn-rate rail showing which pipelines may slip the cycle."
        />
      <section
        aria-label="Country comparison and burn risk"
        className="grid grid-cols-12 gap-4 items-start"
        id="compare"
      >
        <div className="col-span-12 md:col-span-8">
          <SectionCard
            icon={<Globe size={13} />}
            title="Country Comparison"
            subtitle="Targets, valid visits, SSA completion, and disbursement progress side-by-side."
          >
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Country</th>
                  <th scope="col" className="text-left">Director</th>
                  <th scope="col" className="text-right">Schools</th>
                  <th scope="col" className="text-right">SSA Done</th>
                  <th scope="col" className="text-right">Valid Visit</th>
                  <th scope="col" className="text-right">Target</th>
                  <th scope="col" className="text-right">Funds (Committed / Disbursed)</th>
                  <th scope="col" className="text-right">Special Projects</th>
                </tr>
              </thead>
              <tbody>
                {countryRollups.map((c) => {
                  const tone = c.monthlyTargetPct >= 80 ? "green" : c.monthlyTargetPct >= 72 ? "amber" : "red";
                  return (
                    <tr key={c.country}>
                      <td className="text-body font-semibold">{c.country}</td>
                      <td className="text-[12px] muted">{c.director}</td>
                      <td className="text-right tabular text-body font-semibold">{c.schools}</td>
                      <td className="text-right tabular text-[12px]">{c.ssaCompletedPct}%</td>
                      <td className="text-right tabular text-[12px]">{c.validVisitPct}%</td>
                      <td className="text-right">
                        <StatusBadge tone={tone}>{c.monthlyTargetPct}%</StatusBadge>
                      </td>
                      <td className="text-right tabular text-[12px]">
                        {c.fundsCommittedUgxM}M / {c.fundsDisbursedUgxM}M
                      </td>
                      <td className="text-right tabular text-body font-semibold">{c.specialProjects}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </SectionCard>
        </div>
        <div className="col-span-12 md:col-span-4">
          <SectionCard
            icon={<AlertTriangle size={13} />}
            title="Burn-rate Risk"
            subtitle="Where pipeline disbursement may slip the cycle. Red = below 65%, amber = 65–80%, green ≥ 80%."
          >
            <div className="space-y-3">
              {countryRollups.map((c) => {
                const burn = Math.round((c.fundsDisbursedUgxM / c.fundsCommittedUgxM) * 100);
                const tone = burn >= 80 ? "green" : burn >= 65 ? "amber" : "red";
                return (
                  <div key={c.country} className="flex items-center gap-3">
                    <div className="text-[12px] font-semibold w-[80px]">{c.country}</div>
                    <div className="flex-1">
                      <div className="pill-row">
                        <span
                          style={{
                            width: `${burn}%`,
                            background:
                              tone === "green"
                                ? "var(--color-success)"
                                : tone === "amber"
                                  ? "var(--color-edify-orange)"
                                  : "var(--color-danger)",
                          }}
                        />
                      </div>
                    </div>
                    <div className="text-[11.5px] tabular font-semibold w-[42px] text-right">{burn}%</div>
                    <StatusBadge tone={tone}>burn</StatusBadge>
                  </div>
                );
              })}
            </div>
          </SectionCard>
        </div>
      </section>

      </section>

      {/* DISCIPLINE — Salesforce logging compliance + special projects. */}
      <section className="space-y-3">
        <SectionHeader
          tier="strategic"
          eyebrow="Discipline"
          title="Logging discipline and special-project progress"
          description="Salesforce logging compliance by country and the special-project portfolio that sits outside SSA recommendations."
        />
      <section
        aria-label="Regional discipline"
        className="grid grid-cols-12 gap-4 items-start"
      >
        <div className="col-span-12 md:col-span-7">
          <SectionCard
            icon={<TrendingUp size={13} />}
            title="Regional Salesforce Compliance"
            subtitle="Logging discipline by country. Drives verified targets."
          >
            <div className="grid grid-cols-4 gap-3">
              {countryRollups.map((c, i) => {
                const pct = [92, 84, 96, 78][i] ?? 80;
                return (
                  <div
                    key={c.country}
                    className="rounded-xl border border-[var(--color-edify-border)] p-3 flex flex-col items-center text-center"
                  >
                    <div className="text-[11px] muted font-semibold">{c.country}</div>
                    <div className="my-1.5">
                      <ProgressRing pct={pct} size={68} stroke={6} label={`${pct}%`} />
                    </div>
                    <div className="text-caption muted">Logged ≤ 5 days</div>
                  </div>
                );
              })}
            </div>
          </SectionCard>
        </div>
        <div className="col-span-12 md:col-span-5">
          <SectionCard
            icon={<Sparkles size={13} />}
            title="Special Projects · Region"
            subtitle="Excluded from SSA recommendations to avoid double-counting."
          >
            <div className="space-y-2">
              {specialProjects.map((p) => (
                <div
                  key={p.key}
                  className="rounded-lg border border-[var(--color-edify-border)] p-2.5 flex items-center gap-3"
                >
                  <span className="icon-tile icon-tile-violet" style={{ width: 28, height: 28 }}>
                    <Sparkles size={13} />
                  </span>
                  <div className="leading-tight flex-1 min-w-0">
                    <div className="text-body font-bold truncate">{p.name}</div>
                    <div className="text-[11px] muted truncate">
                      {p.cohort} · {p.schoolsImpacted} schools
                    </div>
                  </div>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-14 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden inline-block">
                      <span className="block h-full bg-[var(--color-edify-primary)]" style={{ width: `${p.progressPct}%` }} />
                    </span>
                    <span className="text-[11.5px] tabular font-semibold">{p.progressPct}%</span>
                  </span>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>
      </section>

      </section>

      {/* IMPACT — donor-reporting readiness for the region. */}
      <section className="space-y-3">
        <SectionHeader
          tier="strategic"
          eyebrow="Impact"
          title="Donor-reporting readiness across the region"
          description="Reach, training, and improvement figures the region can report — deduplicated, scoped to RVP, verified or confirmed only. Each tile opens the full report."
        />
        <DonorImpactReachCard snapshot={donorSnapshot} />
      </section>

      {/* CONTEXT — cycle/impact/recognition. The activity-plan horizon
          card was removed: the RVP monitors via analytics, not planning. */}
      <section className="space-y-3">
        <SectionHeader
          tier="strategic"
          eyebrow="Context"
          title="What's working across the region"
          description="The annual cycle, leadership-impact snapshot, top performers, and team-target rollups."
        />
        <AnnualCycleCallout variant="rvp" />
        <LeadershipImpactSnapshot variant="rvp" />
        <TeamTargetsCallout variant="rvp" user={currentUser} />
      </section>
      </div>
    </>
      }
    />
  );
}
