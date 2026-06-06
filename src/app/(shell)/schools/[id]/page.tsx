import { notFound } from "next/navigation";
import Link from "next/link";
import {
  Building2,
  MapPin,
  Phone,
  User,
  Users,
  CalendarDays,
  Sparkles,
  ShieldCheck,
  CalendarCheck,
  ChevronLeft,
  TrendingUp,
} from "lucide-react";
import { AppShell } from "@/components/app/AppShell";
import { SectionCard, StatusBadge, ProgressRing } from "@/components/ui/primitives";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { ActionButton } from "@/components/ui/ActionButton";
import { schoolsCatalog, salesforceMatches, validVisitRules, type WorkflowSchoolRow } from "@/lib/workflow-mock";
import { schoolsMock } from "@/lib/schools-mock";
import { resolveSchoolNextAction, type SchoolView } from "@/lib/planning/school-next-action";
import { resolvePlanningCapacity, classifyActivityKind } from "@/lib/planning/planning-capacity";
import { PlanningCapacityBar } from "@/components/planning/PlanningCapacityBar";
import { activities as plannedActivities } from "@/lib/actions/store";

// Per-school planning capacity from the live planned-activity store (the gray-out
// rule): client = 1 visit; core = 4 visits + 4 trainings. Cancelled/returned
// activities don't count against the quota.
function planningCapacityFor(schoolId: string, schoolType: string) {
  const acts = plannedActivities().filter(
    (a) => a.schoolId === schoolId && a.status !== "Cancelled" && a.status !== "Returned",
  );
  const visitsPlanned = acts.filter((a) => classifyActivityKind(a.kind) === "visit").length;
  const trainingsPlanned = acts.filter((a) => classifyActivityKind(a.kind) === "training").length;
  return resolvePlanningCapacity({ schoolType, visitsPlanned, trainingsPlanned });
}
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SchoolDetailMobileView } from "@/components/mobile/views/SchoolDetailMobileView";
import { SchoolPartnerJourney, sampleJourneyForHope } from "@/components/partner/SchoolPartnerJourney";
import { TitleRegister } from "@/components/shell/TitleRegister";
import { School360View, type School360ProjectVM } from "@/components/cluster/School360View";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { projectsForSchool, projectById } from "@/lib/special-projects-mock";
import { activitiesForProjectSchool } from "@/lib/projects/project-activities";
import { ssaForSchool } from "@/lib/projects/project-school-ssa";
import { recommendInterventionsForSchool } from "@/lib/planning/intervention-recommendation";
import { schoolWorkflowState, schoolLinkedActivities } from "@/lib/school-directory/school-state";
import { recommendClustersFor, type ClusterMatch } from "@/lib/cluster/cluster-core";
import { openDuplicateCandidates } from "@/lib/intake/duplicate-candidates-mock";
import type { DirectorySchoolVM, DirectoryClusterMatch } from "@/components/cluster/DirectoryClusterDrawer";

// Adapt a legacy schools-mock row (SCH-### id-space, used by the mobile schools
// intelligence cards) into the WorkflowSchoolRow the 360 render expects — so
// "View School" from those cards opens this profile instead of 404-ing.
function adaptSchoolsMock(sm: (typeof schoolsMock)[number]): WorkflowSchoolRow {
  return {
    id: sm.schoolId, name: sm.schoolName, cluster: "—", district: sm.district,
    ssaScore: sm.ssaScore,
    status: sm.schoolStatus === "Active" ? "Active" : "Inactive",
    segment: sm.segment === "Core" ? "Core" : "Client",
    ssaCompleted: sm.ssaStatus === "Completed",
    weakestIntervention: "—", recommended: String(sm.recommendedNextAction ?? "—"),
    cceo: sm.assignedCceoName, partner: "—", lastVisit: "—",
    noTraining: sm.noTraining, noVisit: sm.noVisit, dataQuality: "Ready for Planning",
  };
}

export default async function School360({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const spv = (await searchParams).view;
  const view = (Array.isArray(spv) ? spv[0] : spv) as SchoolView | undefined;

  // Source of truth: an uploaded School Directory record. Render the School 360
  // for it; fall back to the legacy catalogue (sch-N) and the mobile schools-mock
  // set (SCH-###) for old ids so a school action button never dead-ends.
  const intake = intakeSchools.find((x) => x.schoolId === id);
  if (intake) return <IntakeSchool360 schoolId={id} view={view} />;

  const sm = schoolsMock.find((x) => x.schoolId === id);
  const s = schoolsCatalog.find((x) => x.id === id) ?? (sm ? adaptSchoolsMock(sm) : null);
  if (!s) return notFound();

  // School-specific next action (spec §4/§5) — surfaced when the user arrived via
  // a "Plan Action" / "View SSA" button (?view=...), so the action that brought
  // them here is front-and-centre instead of a generic page.
  const nextAction = resolveSchoolNextAction({
    clusterStatus: s.cluster && s.cluster !== "—" ? "clustered" : "unclustered",
    currentFySsaStatus: s.ssaCompleted ? "done" : "not_done",
    schoolType: s.segment === "Core" ? "core" : "client",
  });
  const capacity = planningCapacityFor(s.id, s.segment === "Core" ? "core" : "client");

  // Stub history derived from the school
  const ssaHistory = [
    { period: "2024 Q3", score: Math.max(10, s.ssaScore - 14) },
    { period: "2024 Q4", score: Math.max(10, s.ssaScore - 8) },
    { period: "2025 Q1", score: Math.max(10, s.ssaScore - 3) },
    { period: "2025 Q2", score: s.ssaScore },
  ];

  const planned = [
    { kind: "In-School Coaching", window: "May / Wk 1", status: "Active Todo" as const },
    { kind: "SSA Follow-Up",      window: "May / Wk 2", status: "Scheduled" as const },
    { kind: "Cluster Training",   window: "May 06",     status: "Approved" as const },
  ];
  const completed = [
    { kind: "School Visit",        window: "Apr 24", sfId: "SFA-002711", validVisit: "Yes" as const },
    { kind: "In-School Coaching",  window: "Apr 17", sfId: "SFA-002702", validVisit: "Yes" as const },
    { kind: "SSA Support",         window: "Apr 10", sfId: "SFA-002692", validVisit: "No"  as const },
  ];

  return (
    <ResponsiveDashboard mobile={<SchoolDetailMobileView school={s} />} desktop={
    <AppShell
      role="CCEO"
      title="School 360"
      subtitle="Operational profile, SSA history, planned vs completed activities, and verification trail."
      filters={["financialYear", "month", "region"]}
    >
      <div className="-mt-2">
        <Link
          href="/schools"
          className="inline-flex items-center gap-1 text-[12px] muted hover:text-[var(--color-edify-text)]"
        >
          <ChevronLeft size={12} />
          Back to Schools
        </Link>
      </div>

      {/* School-specific next action — shown when arriving from a View SSA /
          Plan Action button so the resolved workflow for THIS school leads. */}
      {view && (
        <div className={`rounded-xl border px-3.5 py-2.5 flex items-start gap-2.5 ${nextAction.blockingGate ? "bg-amber-50 border-amber-200 text-amber-800" : "bg-emerald-50 border-emerald-200 text-emerald-800"}`}>
          <Sparkles size={15} className="shrink-0 mt-0.5" />
          <div className="min-w-0">
            <div className="text-[12.5px] font-extrabold">Next action · {nextAction.label}</div>
            <div className="text-[11.5px] opacity-90 leading-snug">{nextAction.reason}</div>
          </div>
        </div>
      )}

      {/* Planning capacity — visit/training quota + gray-out */}
      <PlanningCapacityBar schoolId={s.id} capacity={capacity} />

      {/* Identity card */}
      <SectionCard
        title={s.name}
        subtitle={`${s.cluster} · ${s.district} District`}
        icon={<Building2 size={13} />}
        actions={
          <div className="flex items-center gap-2">
            <ActionButton
              label="Update Visit"
              className="btn btn-sm"
              toast={{
                tone: "info",
                title: `Visit log opened — ${s.name}`,
                body: "Capture date, evidence, and Salesforce ID to complete the visit.",
              }}
            />
            <ActionButton
              label="Schedule Activity"
              className="btn btn-sm btn-primary"
              toast={{
                tone: "success",
                title: `Activity scheduler opened`,
                body: `Pick a week and activity type for ${s.name}.`,
              }}
            />
          </div>
        }
      >
        <div className="grid grid-cols-12 gap-3">
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Status</div>
            <div className="mt-1 flex items-center gap-2">
              <StatusBadge tone={s.status === "Active" ? "green" : s.status === "Becoming Inactive" ? "amber" : "red"}>
                {s.status}
              </StatusBadge>
              <StatusBadge tone={s.segment === "Core" ? "edify" : "blue"}>{s.segment}</StatusBadge>
            </div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Assigned CCEO</div>
            <div className="text-[13px] font-bold mt-0.5 flex items-center gap-1.5">
              <User size={12} />
              {s.cceo}
            </div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Assigned Partner</div>
            <div className="text-[13px] font-bold mt-0.5 flex items-center gap-1.5">
              <Users size={12} />
              {s.partner}
            </div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Contact</div>
            <div className="text-[13px] font-bold mt-0.5 flex items-center gap-1.5">
              <Phone size={12} />
              +254 712 345 678
            </div>
          </div>

          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Gateway Status</div>
            <div className="text-body font-bold mt-0.5">Onboarded · 12 Mar 2024</div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Coordinates</div>
            <div className="text-body font-bold mt-0.5 flex items-center gap-1.5">
              <MapPin size={12} />
              {s.dataQuality === "Needs Coordinates" ? "Missing — needs update" : "0.3398° N, 32.5817° E"}
            </div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Risk Level</div>
            <div className="text-body font-bold mt-0.5">
              <StatusBadge tone={s.ssaScore < 35 ? "red" : s.ssaScore < 55 ? "amber" : "green"}>
                {s.ssaScore < 35 ? "High" : s.ssaScore < 55 ? "Medium" : "Low"}
              </StatusBadge>
            </div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Special Projects</div>
            <div className="text-body font-bold mt-0.5 flex items-center gap-1.5">
              <Sparkles size={12} />
              EdTech · CCSEL
            </div>
          </div>
        </div>
      </SectionCard>

      {/* KPI strip */}
      <MetricStrip
        columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6"
        metrics={[
          { key: "ssa",       label: "SSA Score",        value: `${s.ssaScore}%`, caption: "Latest", tone: s.ssaScore < 35 ? "alert" : s.ssaScore >= 55 ? "good" : "default" },
          { key: "visits",    label: "Valid Visits YTD", value: "6",              caption: "Counts toward target", tone: "good" },
          { key: "trainings", label: "Trainings YTD",    value: "2",              caption: "Cluster + In-School" },
          { key: "lastvisit", label: "Last Visit",       value: s.lastVisit,      caption: "On record" },
          { key: "msc",       label: "MSC Stories",      value: "3",              caption: "Most Significant Change" },
          { key: "enrolment", label: "Enrolment",        value: "412",            caption: "Latest update" },
        ]}
      />

      {/* Partner support journey — closes the workflow loop:
          every partner activity for this school is threaded into the
          school's own timeline so the work is understood as school
          improvement, not just partner payment. */}
      <SchoolPartnerJourney {...sampleJourneyForHope()} />

      {/* SSA history + planned/completed */}
      <section className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-5">
          <SectionCard icon={<TrendingUp size={13} />} title="SSA History" subtitle="Recommendations always start from SSA performance.">
            <div className="space-y-2">
              {ssaHistory.map((h) => (
                <div key={h.period} className="flex items-center gap-3">
                  <div className="text-[12px] font-semibold w-[80px]">{h.period}</div>
                  <div className="flex-1">
                    <div className="pill-row">
                      <span style={{ width: `${h.score}%`, background: h.score < 35 ? "var(--color-danger)" : h.score < 55 ? "var(--color-edify-orange)" : "var(--color-success)" }} />
                    </div>
                  </div>
                  <div className="text-body tabular font-extrabold w-[40px] text-right">{h.score}%</div>
                </div>
              ))}
            </div>
            <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[12px]">
              <div className="muted">Weakest intervention</div>
              <div className="font-bold mt-0.5">{s.weakestIntervention}</div>
              <div className="muted mt-2">Recommended next</div>
              <div className="font-bold mt-0.5">{s.recommended}</div>
            </div>
          </SectionCard>
        </div>

        <div className="col-span-12 md:col-span-7 space-y-4">
          <SectionCard icon={<CalendarDays size={13} />} title="Planned Activities" subtitle="Active todos and approved/scheduled work.">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Activity</th>
                  <th scope="col" className="text-left">Window</th>
                  <th scope="col" className="text-left">Status</th>
                  <th scope="col" className="text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {planned.map((p, i) => (
                  <tr key={i}>
                    <td className="text-body font-semibold">{p.kind}</td>
                    <td className="text-[12px] muted">{p.window}</td>
                    <td>
                      <StatusBadge tone={p.status === "Approved" ? "green" : "blue"}>{p.status}</StatusBadge>
                    </td>
                    <td className="text-right">
                      <ActionButton
                        label="Open"
                        ariaLabel={`Open ${p.kind} (${p.window})`}
                        className="btn btn-sm"
                        toast={{
                          tone: "info",
                          title: `Opening ${p.kind}`,
                          body: `${p.window} · ${p.status}`,
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </SectionCard>

          <SectionCard icon={<ShieldCheck size={13} />} title="Completed Activities · Verification Trail" subtitle="Salesforce IDs and valid-visit outcomes.">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Activity</th>
                  <th scope="col" className="text-left">Window</th>
                  <th scope="col" className="text-left">SFA ID</th>
                  <th scope="col" className="text-left">Valid Visit</th>
                </tr>
              </thead>
              <tbody>
                {completed.map((c, i) => (
                  <tr key={i}>
                    <td className="text-body font-semibold">{c.kind}</td>
                    <td className="text-[12px] muted">{c.window}</td>
                    <td className="text-[12px] tabular">{c.sfId}</td>
                    <td>
                      <StatusBadge tone={c.validVisit === "Yes" ? "green" : "red"}>{c.validVisit}</StatusBadge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </SectionCard>
        </div>
      </section>

      {/* Salesforce + Valid visit + Health rings */}
      <section className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-7">
          <SectionCard icon={<CalendarCheck size={13} />} title="Salesforce Activity for this School" subtitle="Smart match against planned windows.">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Activity</th>
                  <th scope="col" className="text-left">Match</th>
                  <th scope="col" className="text-left">SFA ID</th>
                  <th scope="col" className="text-right">Days Open</th>
                </tr>
              </thead>
              <tbody>
                {salesforceMatches.slice(0, 4).map((r) => (
                  <tr key={r.id}>
                    <td className="text-body font-semibold">{r.activity}</td>
                    <td>
                      <StatusBadge tone={r.matchState === "Strong match" ? "green" : r.matchState === "No match" ? "red" : "amber"}>
                        {r.matchState}
                      </StatusBadge>
                    </td>
                    <td className="text-[12px] tabular">{r.sfId ?? "—"}</td>
                    <td className="text-right tabular text-[12px]">{r.daysOpen}d</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </SectionCard>
        </div>
        <div className="col-span-12 md:col-span-5">
          <SectionCard icon={<ShieldCheck size={13} />} title="Visit Quality" subtitle="Why visits count or do not count for this school.">
            <ul className="space-y-1.5">
              {validVisitRules.map((r) => (
                <li
                  key={r.kind}
                  className="flex items-center gap-2 text-[12px] py-1 px-1.5 rounded-md hover:bg-[var(--color-edify-soft)]/50"
                >
                  <span
                    className={`w-2.5 h-2.5 rounded-full ${r.counts ? "bg-[var(--color-success)]" : "bg-[var(--color-danger)]"}`}
                  />
                  <span className="font-semibold">{r.kind}</span>
                  <span className="ml-auto muted">{r.counts ? "Counts" : "Does not count"}</span>
                </li>
              ))}
            </ul>
            <div className="mt-3 pt-3 border-t border-[#eef2f4] grid grid-cols-3 gap-2 text-center">
              {[
                { l: "Verified", v: 92 },
                { l: "Logged", v: 88 },
                { l: "Evidence", v: 84 },
              ].map((x) => (
                <div key={x.l}>
                  <ProgressRing pct={x.v} size={56} stroke={5} label={`${x.v}%`} />
                  <div className="text-caption muted mt-1 font-semibold">{x.l}</div>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>
      </section>
    </AppShell>
    } />
  );
}

// ── School 360 for an uploaded (intake) school — the source-of-truth record ──
async function IntakeSchool360({ schoolId, view }: { schoolId: string; view?: SchoolView }) {
  const s = intakeSchools.find((x) => x.schoolId === schoolId)!;
  const state = schoolWorkflowState(s);
  const nextAction = resolveSchoolNextAction({
    clusterStatus: state.clusterId ? "clustered" : "unclustered",
    currentFySsaStatus: state.ssaDone ? "done" : "not_done",
    schoolType: s.schoolType,
  });
  const capacity = planningCapacityFor(s.schoolId, s.schoolType);
  const activities = schoolLinkedActivities(s);
  const dupe = openDuplicateCandidates().some((d) => d.schoolId === s.schoolId);

  // Special-project participation (separate from SSA interventions).
  const projectVMs: School360ProjectVM[] = projectsForSchool(s.schoolId)
    .map((tag) => projectById(tag.projectId))
    .filter((p): p is NonNullable<typeof p> => Boolean(p))
    .map((p) => {
      const acts = activitiesForProjectSchool(p.projectId, s.schoolId);
      const ssa = ssaForSchool(s.schoolId);
      const change = ssa
        ? Math.round((ssa.current[p.primaryInterventionId] - ssa.baseline[p.primaryInterventionId]) * 10) / 10
        : undefined;
      return {
        projectId: p.projectId,
        projectShortName: p.projectShortName,
        projectType: p.projectType,
        primaryInterventionId: p.primaryInterventionId,
        status: p.status,
        partnerName: p.assignedPartnerName,
        trainings: acts.filter((a) => a.activityType === "Project Training").length,
        followUps: acts.filter((a) => a.activityType === "Project Follow-Up Visit").length,
        interventionChange: change,
      };
    });

  // Recommendations so "Add to Cluster" works straight from the 360.
  const g = recommendClustersFor(s);
  const toVM = (m: ClusterMatch): DirectoryClusterMatch => ({
    id: m.cluster.id, name: m.cluster.name, district: m.cluster.district,
    subCounties: m.cluster.subCounties ?? [], schoolCount: m.schoolCount,
    ssaRate: m.ssaRate, tier: m.tier, leaderName: m.cluster.clusterLeaderName,
  });
  const addToClusterVM: DirectorySchoolVM | null = state.stage === "unclustered" ? {
    schoolId: s.schoolId, schoolName: s.schoolName, schoolType: s.schoolType,
    region: s.region, district: s.district, subCounty: s.subCounty, parish: s.parish,
    assignedCceo: s.assignedCceo, ssaStatus: s.ssaStatus, duplicate: dupe,
    clusterStatus: "unclustered",
    matches: { strong: g.strong.map(toVM), district: g.district.map(toVM), region: g.region.map(toVM) },
  } : null;

  return (
    <>
      <TitleRegister title={s.schoolName} dateLabel="School 360" />
      {view && (
        <div className={`mx-3 sm:mx-4 md:mx-6 mb-3 rounded-xl border px-3.5 py-2.5 flex items-start gap-2.5 ${nextAction.blockingGate ? "bg-amber-50 border-amber-200 text-amber-800" : "bg-emerald-50 border-emerald-200 text-emerald-800"}`}>
          <Sparkles size={15} className="shrink-0 mt-0.5" />
          <div className="min-w-0">
            <div className="text-[12.5px] font-extrabold">Next action · {nextAction.label}</div>
            <div className="text-[11.5px] opacity-90 leading-snug">{nextAction.reason}</div>
          </div>
        </div>
      )}
      <div className="mx-3 sm:mx-4 md:mx-6 mb-3">
        <PlanningCapacityBar schoolId={s.schoolId} capacity={capacity} />
      </div>
      <School360View
        record={{
          schoolId: s.schoolId, schoolName: s.schoolName, schoolType: s.schoolType,
          region: s.region, district: s.district, subCounty: s.subCounty, parish: s.parish,
          assignedCceo: s.assignedCceo, enrollment: s.enrollment, phone: s.phone,
          primaryContact: s.primaryContact, shippingAddress: s.shippingAddress,
          dateAdded: s.dateAdded, addedBy: s.addedBy,
        }}
        state={{
          stage: state.stage, stageLabel: state.stageLabel, blocker: state.blocker,
          flags: state.flags, clusterId: state.clusterId, clusterName: state.clusterName,
          ssaDone: state.ssaDone, nextActions: state.nextActions,
        }}
        activities={activities}
        addToClusterVM={addToClusterVM}
        projects={projectVMs}
        ssa={recommendInterventionsForSchool(s.schoolId)}
      />
    </>
  );
}
