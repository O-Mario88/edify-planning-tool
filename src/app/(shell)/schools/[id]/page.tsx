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
import { SectionCard, StatusBadge, ProgressRing } from "@/components/ui/primitives";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { ActionButton } from "@/components/ui/ActionButton";
import { schoolsCatalog, salesforceMatches, validVisitRules, type WorkflowSchoolRow } from "@/lib/workflow-mock";
import { schoolsMock } from "@/lib/schools-mock";
import { resolveSchoolNextAction, type SchoolView } from "@/lib/planning/school-next-action";
import { resolvePlanningCapacity, classifyActivityKind } from "@/lib/planning/planning-capacity";
import { PlanningCapacityBar, type AssignmentVM } from "@/components/planning/PlanningCapacityBar";
import { activities as plannedActivities } from "@/lib/actions/store";
import { getCurrentUser } from "@/lib/auth";
import { computeStaffCapacity, staffAlreadySupportsSchool, getAssignmentOptions } from "@/lib/planning/assignment-policy";
import { cceosSupervisedBy } from "@/lib/org/supervision";
import { isBackendEnabled } from "@/lib/api/backend";
import { isMockAllowed } from "@/lib/mock-policy";
import { fetchSchoolDetail, fetchAssignmentOptions, fetchSchoolWorkflow, fetchActivities, type BeAssignmentOptions } from "@/lib/api/surfaces";
import type { School360Activity } from "@/components/cluster/School360View";
import { SchoolWorkflowJourney } from "@/components/schools/SchoolWorkflowJourney";
import { SchoolSsaLive } from "@/components/ssa/SchoolSsaLive";
import { SchoolDetailErrorState } from "@/components/schools/SchoolDetailErrorState";
import { resolveSchoolNextAction as resolveNextAction } from "@/lib/planning/school-next-action";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { Database } from "lucide-react";

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

// Assignment options for the current user on this school (role rules + staff
// support capacity). Drives the Assign-to-Myself / Assign-to-Partner buttons.
async function assignmentFor(schoolId: string, ownerName: string | undefined, canPlanVisit: boolean): Promise<AssignmentVM> {
  const user = await getCurrentUser();
  const staffCap = computeStaffCapacity(user.staffId);
  const isDirectOwner = !!ownerName && ownerName === user.name;
  const supervised = user.role === "CountryProgramLead"
    ? cceosSupervisedBy(user.staffId).map((c) => ({ staffId: c.staffId, name: c.name }))
    : [];
  // The relevant team assignee is the school's OWNER, if they're a supervised CCEO.
  const ownerCceo = !isDirectOwner ? supervised.find((c) => c.name === ownerName) : undefined;
  const isSupervisedSchool = !!ownerCceo;
  const already = staffAlreadySupportsSchool(user.staffId, schoolId);
  const opts = getAssignmentOptions({
    role: user.role, isDirectOwner, isSupervisedSchool,
    schoolAlreadySupported: already, capacity: staffCap, partnerAvailable: true,
    supervisedCceos: ownerCceo ? [ownerCceo] : [],
  });
  const self = opts.find((o) => o.type === "self");
  const partner = opts.find((o) => o.type === "partner");
  return {
    staffUsed: staffCap.used, staffMax: staffCap.max, staffAtLimit: staffCap.atLimit, staffNearLimit: staffCap.nearLimit,
    showSelf: !!self,
    selfEnabled: !!self?.enabled && canPlanVisit,
    selfReason: self && !self.enabled ? self.reason : (!canPlanVisit ? "Visit quota for this school is full." : undefined),
    partnerEnabled: !!partner?.enabled,
    partnerReason: partner && !partner.enabled ? partner.reason : undefined,
    team: opts.filter((o) => o.type === "staff").map((t) => {
      const name = t.label.replace("Assign to ", "");
      const tc = t.staffId ? computeStaffCapacity(t.staffId) : null;
      const tAlready = t.staffId ? staffAlreadySupportsSchool(t.staffId, schoolId) : false;
      const enabled = !!tc && (tAlready || tc.remaining > 0);
      return { name, staffId: t.staffId ?? "", enabled, reason: enabled ? undefined : `${name} is at their direct support limit (${tc?.max ?? 0}).` };
    }),
  };
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
import { schoolWorkflowState, schoolLinkedActivities } from "@/lib/school-directory/school-state";
import { SchoolTimeline } from "@/components/schools/SchoolTimeline";
import { QualityGateNotices } from "@/components/gates/QualityGateNotices";
import { schoolQualityGates } from "@/lib/gates/quality-gates";
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

  // Write-path migration: when the backend is on and this is a backend school,
  // render the backend-backed profile so scheduling writes to the API (enforced).
  // A real backend error surfaces an error state (with retry) instead of silently
  // rendering mock data — "Backend failure = error. Never fake data." A 404 means
  // the id is not a backend school, so we fall through to the legacy id-space
  // lookups below (so old SCH-### / sch-N links never dead-end).
  if (isBackendEnabled()) {
    const user = await getCurrentUser();
    const be = await fetchSchoolDetail(user, id);
    if (be.live) return <BackendSchool360 school={be.data} />;
    const notFoundOnBackend = be.error == null || /\b404\b/.test(be.error);
    if (!notFoundOnBackend) {
      return <SchoolDetailErrorState message={`Could not load this school from the backend (${be.error}).`} />;
    }
  }

  // Source of truth: an uploaded School Directory record. Render the School 360
  // for it; fall back to the legacy catalogue (sch-N) and the mobile schools-mock
  // set (SCH-###) for old ids so a school action button never dead-ends.
  // Legacy mock id-spaces exist only in dev (mock enabled); in production a
  // non-backend school id 404s rather than rendering fabricated data.
  if (!isMockAllowed()) return notFound();
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
  const assignment = await assignmentFor(s.id, s.cceo, capacity.canPlanVisit);

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
    // Canonical in-shell page chrome (CorePageHeader) — replaces the
    // legacy AppShell/AppTopHeader, which rendered a parallel header with
    // dead FY/month/region filter pills + a dead search on top of the
    // app's real shell. Mirrors BackendSchool360 below.
    <>
      <CorePageHeader
        icon="schools"
        title="School 360"
        subtitle="Operational profile, SSA history, planned vs completed activities, and verification trail."
      />
      <div className="px-3 sm:px-4 md:px-6 pb-24 lg:pb-6 space-y-3 pt-3">
      <div>
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

      {/* Planning capacity — visit/training quota + gray-out + assignment */}
      <PlanningCapacityBar schoolId={s.id} schoolName={s.name} capacity={capacity} assignment={assignment} />

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
      </div>
    </>
    } />
  );
}

// This school's REAL activities from the backend, mapped to the 360 shape.
// Returns null when the backend is off (caller falls back to the mock).
const VISIT_KINDS = new Set(["school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit"]);
const tcase = (x: string) => x.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
async function liveSchoolActivities(schoolId: string): Promise<School360Activity[] | null> {
  if (!isBackendEnabled()) return null;
  const user = await getCurrentUser();
  const r = await fetchActivities(user, `?schoolId=${encodeURIComponent(schoolId)}&pageSize=50`);
  if (!r.live) return null;
  return r.data.data.map((a) => ({
    kind: VISIT_KINDS.has(a.activityType) ? "visit" : a.activityType.includes("ssa") ? "ssa_upload" : "training",
    label: tcase(a.activityType),
    date: a.scheduledDate ? new Date(a.scheduledDate).toLocaleDateString() : `${a.fy ?? ""} ${a.quarter ?? ""}`.trim(),
    status: tcase(a.status),
    ref: a.salesforceActivityId ?? undefined,
  }));
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
  const assignment = await assignmentFor(s.schoolId, s.assignedCceo, capacity.canPlanVisit);
  // Linked activities — LIVE from the backend (this school's real activities),
  // falling back to the mock only when the backend is disabled.
  const activities = (await liveSchoolActivities(s.schoolId)) ?? schoolLinkedActivities(s);
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
        <QualityGateNotices evaluation={schoolQualityGates({ schoolId: s.schoolId, ssaDone: state.ssaDone })} />
        <PlanningCapacityBar schoolId={s.schoolId} schoolName={s.schoolName} capacity={capacity} assignment={assignment} />
      </div>
      {/* View SSA — this school's REAL SSA from the backend (not a general grid). */}
      <div className="mx-3 sm:mx-4 md:mx-6 mb-3 card p-3.5">
        <SchoolSsaLive schoolId={s.schoolId} />
      </div>
      {/* Operational timeline — the school's full story, upload → verified impact. */}
      <div className="mx-3 sm:mx-4 md:mx-6 mb-3">
        <SchoolTimeline schoolId={s.schoolId} />
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
        /* SSA now shown live above via <SchoolSsaLive> — suppress the mock
           recommendation section so the page has one source of SSA truth. */
        addToClusterVM={addToClusterVM}
        projects={projectVMs}
        ssa={undefined}
      />
    </>
  );
}

// ── Backend-backed school profile (write-path migration) ────────────
// Identity + assignment/capacity from the backend (/schools/:id, /assignment/
// options). Scheduling here writes to the API (capacity-enforced) because the
// schoolId is a real backend id.
function assignmentVmFromBackend(d: BeAssignmentOptions, canPlanVisit: boolean): AssignmentVM {
  const self = d.options.find((o) => o.type === "self");
  const partner = d.options.find((o) => o.type === "partner");
  return {
    staffUsed: d.capacity.used, staffMax: d.capacity.max, staffAtLimit: d.capacity.atLimit, staffNearLimit: d.capacity.nearLimit,
    showSelf: !!self,
    selfEnabled: !!self?.enabled && canPlanVisit,
    selfReason: self && !self.enabled ? self.reason : (!canPlanVisit ? "Visit quota for this school is full." : undefined),
    partnerEnabled: !!partner?.enabled,
    partnerReason: partner && !partner.enabled ? partner.reason : undefined,
    team: d.options.filter((o) => o.type === "staff").map((t) => ({ name: t.label.replace("Assign to ", ""), staffId: t.staffId ?? "", enabled: t.enabled, reason: t.reason })),
  };
}

async function BackendSchool360({ school }: { school: import("@/lib/api/surfaces").BeSchoolDetail }) {
  const user = await getCurrentUser();
  const [opts, wf] = await Promise.all([
    fetchAssignmentOptions(user, school.schoolId),
    fetchSchoolWorkflow(user, school.schoolId),
  ]);
  const capacity = resolvePlanningCapacity({ schoolType: school.schoolType, visitsPlanned: 0, trainingsPlanned: 0 });
  const assignment = opts.live ? assignmentVmFromBackend(opts.data, capacity.canPlanVisit) : undefined;
  const nextAction = resolveNextAction({
    clusterStatus: school.clusterStatus === "clustered" ? "clustered" : "unclustered",
    currentFySsaStatus: school.currentFySsaStatus === "done" ? "done" : "not_done",
    schoolType: school.schoolType === "core" ? "core" : "client",
  });
  const latestSsa = (school.ssaRecords ?? []).slice().sort((a, b) => (b.dateOfSsa > a.dateOfSsa ? 1 : -1))[0];

  return (
    <>
      <CorePageHeader icon="schools" title={school.name} subtitle={`${school.schoolType} school · ${school.district?.name ?? "—"}${school.cluster?.name ? ` · ${school.cluster.name}` : ""}`} />
      <div className="px-3 sm:px-4 md:px-6 pb-24 lg:pb-6 space-y-3 pt-3">
        <div className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 text-emerald-700 px-2.5 py-1 text-[11px] font-bold border border-emerald-200">
          <Database size={12} /> Live from the backend database (edify-api)
        </div>

        {wf.live ? (
          <SchoolWorkflowJourney wf={wf.data} />
        ) : (
          <div className="card p-3 flex items-start gap-2.5">
            <div className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-primary)] text-white shrink-0">→</div>
            <div className="min-w-0">
              <div className="text-[12.5px] font-extrabold">Next action · {nextAction.label}</div>
              <div className="text-[11.5px] muted leading-snug">{nextAction.reason}</div>
            </div>
          </div>
        )}

        <PlanningCapacityBar schoolId={school.schoolId} schoolName={school.name} capacity={capacity} assignment={assignment} />

        <section className="card p-3.5">
          <h2 className="text-[12px] font-extrabold uppercase tracking-wide muted mb-2">School bio</h2>
          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1.5 text-[12px]">
            <Fact label="School ID" value={school.schoolId} />
            <Fact label="Type" value={school.schoolType} />
            <Fact label="Region" value={school.region?.name ?? "—"} />
            <Fact label="District" value={school.district?.name ?? "—"} />
            <Fact label="Cluster" value={school.cluster?.name ?? "Unclustered"} />
            <Fact label="Account owner" value={school.accountOwner?.user?.name ?? school.accountOwnerNameRaw ?? "—"} />
            <Fact label="Enrollment" value={school.enrollment != null ? String(school.enrollment) : "—"} />
            <Fact label="SSA status" value={school.currentFySsaStatus} />
            <Fact label="Planning" value={school.planningReadiness} />
          </dl>
        </section>

        <section className="card p-3.5">
          <h2 className="text-[12px] font-extrabold uppercase tracking-wide muted mb-2">SSA history</h2>
          {school.ssaRecords && school.ssaRecords.length > 0 ? (
            <ul className="divide-y divide-[var(--color-edify-divider)] text-[12px]">
              {school.ssaRecords.slice().sort((a, b) => (b.dateOfSsa > a.dateOfSsa ? 1 : -1)).map((r) => (
                <li key={r.id} className="py-1.5 flex items-center justify-between">
                  <span className="muted">{r.fy} · {new Date(r.dateOfSsa).toLocaleDateString()}</span>
                  <span className="font-extrabold tabular">{r.averageScore != null ? `${r.averageScore.toFixed(1)}/10` : "—"}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px] muted italic">No SSA on record for this school yet.</p>
          )}
          {latestSsa && <p className="text-[10.5px] muted mt-2">Latest: {latestSsa.fy}</p>}
        </section>
      </div>
      <RoleBottomNav />
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide muted font-bold">{label}</dt>
      <dd className="font-semibold capitalize">{value}</dd>
    </div>
  );
}
