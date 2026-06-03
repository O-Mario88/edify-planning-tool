"use client";

// SchoolGapsBoard — gap-driven school list with SSA gating.
//
// Renders schools in four collapsible sections in the spec's priority
// order: No SSA → No Training → No Visit → No Cluster. Each card
// surfaces the next valid action; intervention-based actions are
// disabled until SSA completes (with a tooltip explaining why).

import { useMemo, useState } from "react";
import {
  AlertOctagon, Footprints, GraduationCap, Users, Building2, MapPin,
  ChevronDown, ChevronRight, ChevronUp, ArrowRight, Eye, User, Phone,
  type LucideIcon, Lock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fullAddressOf, primaryContactOf } from "@/lib/planning/school-address";
import {
  schoolGaps,
  GAP_SORT_ORDER,
  recommendFor,
  type SchoolGap,
  type SchoolGapCategory,
  type SchoolGapAction,
} from "@/lib/planning/planning-gaps-mock";
import {
  PlanningAssignDrawer,
  type AssignOutcome,
  type PlanningAssignContext,
} from "@/components/planning/PlanningAssignDrawer";
import {
  AddToClusterDrawer,
  type AddToClusterOutcome,
  type AddToClusterContext,
} from "@/components/planning/AddToClusterDrawer";
import {
  ScheduleActivityDrawer,
  type ScheduleActivityContext,
  type ScheduleActivityOutcome,
} from "@/components/planning/ScheduleActivityDrawer";
import {
  SsaPerformanceDrawer,
  type SsaPerformanceContext,
} from "@/components/planning/SsaPerformanceDrawer";
import {
  SchoolActivityProfileDrawer,
  type SchoolActivityProfileContext,
} from "@/components/planning/SchoolActivityProfileDrawer";
import { PlanningEmptyState } from "@/components/planning/PlanningEmptyState";
import { RISK_TONE } from "@/lib/planning/status-tokens";

/**
 * Translate a SchoolGap into the unified ScheduleActivityDrawer's
 * context for a school-level training. Centralized so the drawer
 * itself stays generic.
 */
function buildSchoolTrainingContext(s: SchoolGap): ScheduleActivityContext {
  const focus = s.weakestArea?.area ?? "Teaching & Learning";
  return {
    target: { kind: "school", id: s.id, name: s.schoolName },
    activityType:        `${focus} Improvement Training`,
    isTraining:          true,
    defaultParticipants: 25, // sensible default for a single-school training
    defaultProposedBy:   `${s.assignedCceo} (CCEO)`,
    locationLine:        `${s.district}${s.subCounty ? ` · ${s.subCounty}` : ""} · CCEO ${s.assignedCceo}`,
    ssaFocus:            s.weakestArea ? { area: s.weakestArea.area, score: s.weakestArea.score } : undefined,
    noCurrentSsa:        !s.ssaCompleted,
  };
}

const CATEGORY_META: Record<SchoolGapCategory, { label: string; Icon: LucideIcon; tone: "danger" | "warn" | "info"; helper: string }> = {
  no_cluster:  { label: "Unclustered — assign first", Icon: Users, tone: "danger", helper: "Cluster assignment is the required setup step after upload. Planning stays limited until clustered." },
  no_ssa:      { label: "No SSA",      Icon: AlertOctagon, tone: "danger", helper: "Clustered, SSA pending — schedule SIT, assign SSA to a partner, or do it yourself." },
  no_training: { label: "No Training", Icon: GraduationCap, tone: "warn",  helper: "SSA completed — pick School Improvement Training from the weakest area." },
  no_visit:    { label: "No Visit",    Icon: Footprints,   tone: "warn",   helper: "First support visit missing — purpose comes from the weakest SSA area." },
};

const CATEGORY_TONE: Record<"danger" | "warn" | "info", { bg: string; text: string }> = {
  danger: { bg: "bg-rose-50",   text: "text-rose-700"   },
  warn:   { bg: "bg-amber-50",  text: "text-amber-700"  },
  info:   { bg: "bg-blue-50",   text: "text-blue-700"   },
};

const ACTION_LABEL: Record<SchoolGapAction, string> = {
  schedule_ssa:           "Schedule SSA",
  schedule_support_visit: "Schedule Support Visit",
  schedule_training:      "Schedule Training",
  schedule_follow_up:     "Schedule Follow-Up",
  schedule_coaching:      "Schedule Coaching",
  add_to_cluster:         "Add to Cluster",
  assign_partner:         "Assign to Partner",
  view_school:            "View School",
  view_ssa:               "View SSA",
};

export function SchoolGapsBoard({
  assigningUserRole = "CountryProgramLead",
  extraGaps = [],
}: {
  /**
   * Role of the user viewing the planning page. Forwarded to the
   * assign drawer so CCEOs see only the Partner owner option per the
   * operating-model permissions. Defaults to PL.
   */
  assigningUserRole?: "CCEO" | "CountryProgramLead" | "ImpactAssessment" | "CountryDirector" | "Admin";
  /**
   * Onboarded-school gaps computed server-side from uploaded schools + SSA
   * (already scoped to the viewer's supervision chain). Merged in so uploaded
   * data drives the planner alongside the static seed gaps.
   */
  extraGaps?: SchoolGap[];
} = {}) {
  const [collapsed, setCollapsed] = useState<Record<SchoolGapCategory, boolean>>({
    no_cluster: false, no_ssa: false, no_training: false, no_visit: true,
  });
  const [assign, setAssign] = useState<{ school: SchoolGap; action: SchoolGapAction } | null>(null);
  // Add-to-cluster has its own drawer because the inputs are different
  // (no owner picker; pick existing OR create new with district + sub-county).
  // Routed by SchoolRow's onAction handler — add_to_cluster diverts here
  // instead of through PlanningAssignDrawer.
  const [clusterAssign, setClusterAssign] = useState<AddToClusterContext | null>(null);
  // Schedule-training also has its own calendar drawer (date + participants
  // + projected cost + optional partner facilitator). Routed in the same
  // way as add_to_cluster so we never bounce trainings through the owner
  // picker — they're already implicitly owned by the assigned CCEO. We
  // carry the underlying SchoolGap alongside the unified drawer context
  // so the submit handler can dismiss the right school from the list.
  const [scheduleSchoolTraining, setScheduleSchoolTraining] = useState<
    | { context: ScheduleActivityContext; school: SchoolGap }
    | null
  >(null);
  // View SSA opens the performance drawer — adapts based on how many
  // completed SSAs the school has (0 / 1 / 2 / 3+).
  const [ssaPerformance, setSsaPerformance] = useState<SsaPerformanceContext | null>(null);
  // View School opens the activity & investment profile drawer — full
  // school support history, costs, evidence, SSA snapshot, and the
  // next recommended action.
  const [schoolProfile, setSchoolProfile] = useState<SchoolActivityProfileContext | null>(null);
  // Schools that have been confirmed-assigned (to partner / staff /
  // myself) or added to a cluster within this session disappear from
  // the gap list. This is the local-state implementation of the
  // operating-model rule: "Confirm Assignment removes the school from
  // the active CCEO/PL planning gap list." Production swaps this for
  // a backed-by-server dismissal on the gap-list query.
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<string | null>(null);
  // Cluster filter — narrows every bucket to one cluster ("" = all clusters).
  const [clusterFilter, setClusterFilter] = useState<string>("");

  // Distinct clusters present across the current gaps (for the filter select).
  const clusterOptions = useMemo(
    () =>
      [...new Set([...extraGaps, ...schoolGaps].map((s) => s.clusterName).filter(Boolean) as string[])]
        .sort((a, b) => a.localeCompare(b)),
    [extraGaps],
  );

  function dismiss(schoolId: string) {
    setDismissedIds((prev) => {
      const next = new Set(prev);
      next.add(schoolId);
      return next;
    });
  }

  const groups = useMemo(() => {
    const map: Record<SchoolGapCategory, SchoolGap[]> = {
      no_ssa: [], no_training: [], no_visit: [], no_cluster: [],
    };
    // Dismissed schools (just confirmed-assigned in this session) are
    // filtered out so the gap counts and lists reflect "what still
    // needs CCEO/PL action right now", not "what was on the table when
    // the page loaded".
    for (const s of [...extraGaps, ...schoolGaps]) {
      if (dismissedIds.has(s.id)) continue;
      if (clusterFilter && s.clusterName !== clusterFilter) continue;
      map[s.gapCategory].push(s);
    }
    return map;
  }, [dismissedIds, extraGaps, clusterFilter]);

  function handleClusterSubmit(outcome: AddToClusterOutcome) {
    const copy =
      outcome.mode === "existing"
        ? `${outcome.schoolName} added to ${outcome.clusterName}.`
        : `New cluster ${outcome.clusterName} created in ${outcome.district} · ${outcome.subCounty}. ${outcome.schoolName} attached as the first school.`;
    setToast(copy);
    setClusterAssign(null);
    // School is now in a cluster — remove it from the No Cluster gap.
    dismiss(outcome.schoolId);
    setTimeout(() => setToast(null), 4500);
  }

  function handleSchoolTrainingSubmit(outcome: ScheduleActivityOutcome) {
    const pending = scheduleSchoolTraining;
    if (!pending) return;

    const partnerSuffix = outcome.partnerFacilitator
      ? ` Facilitator: ${outcome.partnerFacilitator}.`
      : "";
    const costSuffix = outcome.projectedCostUgx && outcome.projectedCostUgx > 0
      ? ` Projected ${formatUgxShort(outcome.projectedCostUgx)} for ${outcome.participants} participants.`
      : "";
    setToast(
      `${outcome.activityType} scheduled at ${pending.school.schoolName} for ${outcome.date}.${costSuffix}${partnerSuffix}`,
    );
    setScheduleSchoolTraining(null);
    // Training is now on the calendar — remove the school from the
    // No Training gap list. The training will reappear in the owner's
    // scheduled-activity feed (My Plan / Partner Plan / Cluster Plan).
    dismiss(pending.school.id);
    setTimeout(() => setToast(null), 4500);
  }

  function handleAssignSubmit(outcome: AssignOutcome) {
    const ownerCopy =
      outcome.owner === "myself" ? (
        outcome.month && outcome.week
          ? `Scheduled for ${outcome.month} · Week ${outcome.week} — moved to My Plan.`
          : "Activity moved to My Plan."
      ) :
      outcome.owner === "staff" ? `Assigned to ${outcome.staffName}.` :
      outcome.owner === "partner" ? `Sent to ${outcome.partnerName} — awaiting partner planning.` :
      `Facilitator request sent to ${outcome.facilitatorName}.`;
    setToast(ownerCopy);
    // Confirm Assignment removes the school from the active planning
    // gap list per the operating-model contract. The activity will
    // reappear under the owner's queue (My Plan / Partner Planning /
    // staff's planning page) once that next stage lands.
    if (assign?.school?.id) dismiss(assign.school.id);
    setTimeout(() => setToast(null), 3500);
  }

  const drawerContext: PlanningAssignContext | null = assign && (() => {
    const s = assign.school;
    const rec = recommendFor(s);
    return {
      title: ACTION_LABEL[assign.action],
      schoolOrCluster: s.schoolName,
      purpose: rec.purpose,
      // Partner-as-facilitator only makes sense for trainings.
      allowPartnerFacilitator: assign.action === "schedule_training",
      // SSA can be assigned to either a CCEO or a certified Partner —
      // partners deliver the bulk of SSA work in the operating model.
      // The drawer surfaces Myself / Staff / Partner; the partner then
      // picks the delivery date from their scheduling dashboard.
      // SSA Verification (separate purpose) stays staff-only — enforced
      // in plan-cost-calculator's STAFF_ONLY_PURPOSES, not here.
      allowPartnerOwnership: true,
      assigningUserRole,
    };
  })();

  return (
    <section className="card p-3.5">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[16px] font-extrabold tracking-tight">Client school gaps</h2>
          <p className="text-[12px] muted mt-0.5">
            Schools listed by gap, urgent first. No-SSA schools only show the SSA action — intervention buttons unlock once SSA completes.
          </p>
        </div>
        {clusterOptions.length > 0 && (
          <label className="shrink-0 inline-flex items-center gap-1.5 text-[11px] font-semibold muted">
            <Users size={12} className="text-[var(--color-edify-primary)]" />
            <select
              value={clusterFilter}
              onChange={(e) => setClusterFilter(e.target.value)}
              aria-label="Filter by cluster"
              className={cn(
                "h-8 px-2 rounded-lg border text-[11.5px] bg-white",
                clusterFilter
                  ? "border-[var(--color-edify-primary)] text-[var(--color-edify-primary)] font-semibold"
                  : "border-[var(--color-edify-border)] text-[var(--color-edify-text)]",
              )}
            >
              <option value="">All clusters</option>
              {clusterOptions.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
        )}
      </header>

      <div className="space-y-3">
        {GAP_SORT_ORDER.map((cat) => {
          const list = groups[cat];
          const isCollapsed = collapsed[cat];
          const meta = CATEGORY_META[cat];
          const tone = CATEGORY_TONE[meta.tone];
          return (
            <div key={cat} className="rounded-xl border border-[var(--color-edify-divider)] bg-white">
              <button
                type="button"
                onClick={() => setCollapsed((c) => ({ ...c, [cat]: !c[cat] }))}
                className="w-full flex items-center gap-3 px-3.5 py-2.5 hover:bg-[var(--color-edify-soft)]/40 transition-colors text-left"
              >
                <span className={cn("grid place-items-center h-8 w-8 rounded-md", tone.bg, tone.text)}>
                  <meta.Icon size={14} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[12px] font-extrabold tracking-tight">{meta.label}</div>
                  <div className="text-[11px] muted">{meta.helper}</div>
                </div>
                <span className="text-[12px] font-extrabold tabular text-[var(--color-edify-text)]">
                  {list.length}
                </span>
                <span className="text-[var(--color-edify-muted)]">
                  {isCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </span>
              </button>
              {!isCollapsed && (
                list.length === 0 ? (
                  <div className="px-4 py-4 border-t border-[var(--color-edify-divider)]">
                    <PlanningEmptyState
                      variant="good"
                      size="sm"
                      eyebrow="Bucket clear"
                      title={`No schools currently in "${meta.label}".`}
                      body="Schools land here when the gap is detected during the nightly SSA + activity sync."
                    />
                  </div>
                ) : (
                  <ul className="divide-y divide-[var(--color-edify-divider)] border-t border-[var(--color-edify-divider)]">
                    {list.map((s) => (
                      <SchoolRow
                        key={s.id}
                        school={s}
                        onAction={(action) => {
                          // Cluster assignment has its own dedicated drawer with
                          // existing-vs-create-new modes.
                          if (action === "add_to_cluster") {
                            setClusterAssign({
                              schoolId:   s.id,
                              schoolName: s.schoolName,
                              cceoName:   s.assignedCceo,
                            });
                            return;
                          }
                          // Schedule training opens the unified calendar
                          // drawer (date + participants + projected cost)
                          // rather than bouncing through the owner picker
                          // — the owner is implicitly the assigned CCEO.
                          if (action === "schedule_training") {
                            setScheduleSchoolTraining({
                              school:  s,
                              context: buildSchoolTrainingContext(s),
                            });
                            return;
                          }
                          // View SSA opens the performance drawer, not
                          // the owner picker. Adapts to the school's SSA
                          // history (locked / single / yearly comparison
                          // / 3-year trend).
                          if (action === "view_ssa") {
                            setSsaPerformance({ school: s });
                            return;
                          }
                          // View School opens the activity & investment
                          // profile drawer (full history, costs,
                          // evidence, contributors, next action).
                          if (action === "view_school") {
                            setSchoolProfile({ school: s });
                            return;
                          }
                          // Every other action continues through the generic
                          // owner picker.
                          setAssign({ school: s, action });
                        }}
                      />
                    ))}
                  </ul>
                )
              )}
            </div>
          );
        })}
      </div>

      <PlanningAssignDrawer
        open={!!assign}
        context={drawerContext}
        onClose={() => setAssign(null)}
        onSubmit={handleAssignSubmit}
      />

      <AddToClusterDrawer
        open={!!clusterAssign}
        context={clusterAssign}
        onClose={() => setClusterAssign(null)}
        onSubmit={handleClusterSubmit}
      />

      <ScheduleActivityDrawer
        open={!!scheduleSchoolTraining}
        context={scheduleSchoolTraining?.context ?? null}
        onClose={() => setScheduleSchoolTraining(null)}
        onSubmit={handleSchoolTrainingSubmit}
      />

      <SsaPerformanceDrawer
        open={!!ssaPerformance}
        context={ssaPerformance}
        onClose={() => setSsaPerformance(null)}
        // Recommended-action CTAs route back through the existing
        // gap-action machinery: Schedule SSA → owner picker; Schedule
        // Training → activity drawer; Schedule Support Visit → owner
        // picker. Close the performance drawer first so the next
        // drawer doesn't stack underneath it.
        onAction={(action, school) => {
          setSsaPerformance(null);
          if (action === "schedule_training") {
            setScheduleSchoolTraining({
              school,
              context: buildSchoolTrainingContext(school),
            });
            return;
          }
          setAssign({ school, action });
        }}
      />

      <SchoolActivityProfileDrawer
        open={!!schoolProfile}
        context={schoolProfile}
        onClose={() => setSchoolProfile(null)}
        // Cross-drawer hand-off: clicking "View SSA graph" inside the
        // school profile drawer closes it and opens the full SSA
        // performance drawer so the two surfaces stay in sync.
        onViewSsa={(school) => {
          setSchoolProfile(null);
          setSsaPerformance({ school });
        }}
        // Recommended-action CTAs go through the same machinery as
        // the SSA drawer's, so the parent's routing logic is one
        // single source of truth.
        onAction={(action, school) => {
          setSchoolProfile(null);
          if (action === "schedule_training") {
            setScheduleSchoolTraining({
              school,
              context: buildSchoolTrainingContext(school),
            });
            return;
          }
          if (action === "view_ssa") {
            setSsaPerformance({ school });
            return;
          }
          setAssign({ school, action });
        }}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-[12px] font-semibold px-4 py-3 max-w-[400px]">
          {toast}
        </div>
      )}
    </section>
  );
}

function SchoolRow({
  school: s, onAction,
}: {
  school: SchoolGap;
  onAction: (action: SchoolGapAction) => void;
}) {
  const rec = recommendFor(s);
  // Cluster-first gate takes precedence over the SSA gate: an unclustered
  // school can only be assigned to a cluster (or viewed) until it is clustered.
  const clusterBlocked = s.gapCategory === "no_cluster" || !s.inCluster;
  const ssaBlocked = !clusterBlocked && !s.ssaCompleted;
  const [open, setOpen] = useState(false);
  const contact = primaryContactOf(s);

  // The action buttons surfaced per row. Order: primary first.
  const buttons: SchoolGapAction[] = clusterBlocked
    ? ["add_to_cluster", "view_school"]
    : ssaBlocked
      ? ["schedule_ssa", "view_school"]
      : rec.allowedActions;

  return (
    <li className={cn(open && "bg-[var(--color-edify-soft)]/30 transition-colors")}>
      {/* Collapsed header — click to expand. Shows identity + risk pill +
          the 4 status chips so the planner can scan urgency without
          opening every row. Everything else (weak areas, contact details,
          recommended action, action buttons) lives in the expanded body. */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={`school-${s.id}-detail`}
        className="w-full px-3.5 py-3 flex items-start gap-3 text-left hover:bg-[var(--color-edify-soft)]/40 transition-colors"
      >
        <span className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0 mt-0.5">
          <Building2 size={13} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-[12px] font-extrabold tracking-tight truncate">{s.schoolName}</h3>
            <span className={cn(
              "ml-auto inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide",
              RISK_TONE[s.riskLevel].bg,
              RISK_TONE[s.riskLevel].text,
            )}>
              {s.riskLevel}
            </span>
          </div>
          <p className="text-[11px] muted leading-tight inline-flex items-center gap-1 mt-0.5">
            <MapPin size={9} className="text-[var(--color-edify-primary)]" />
            {fullAddressOf(s)}
          </p>
          {/* Status chips — kept on the collapsed header so urgency reads
              at a glance without expanding the row. */}
          <div className="flex items-center gap-1.5 flex-wrap mt-2">
            <StatusChip ok={s.ssaCompleted} label={s.ssaCompleted ? "SSA Complete" : "No SSA"} />
            <StatusChip ok={s.lastVisitLabel != null && s.lastVisitLabel !== "Never"} label={s.lastVisitLabel === "Never" || !s.lastVisitLabel ? "No Visit" : `Last visit ${s.lastVisitLabel}`} />
            <StatusChip ok={s.lastTrainingLabel != null && s.lastTrainingLabel !== "Never"} label={s.lastTrainingLabel === "Never" || !s.lastTrainingLabel ? "No Training" : `Last training ${s.lastTrainingLabel}`} />
            <StatusChip ok={s.inCluster} label={s.inCluster ? `In ${s.clusterName ?? "cluster"}` : "No Cluster"} />
          </div>
        </div>
        <ChevronRight
          size={14}
          className={cn(
            "text-[var(--color-edify-muted)] shrink-0 mt-1 transition-transform",
            open && "rotate-90",
          )}
        />
      </button>

      {open && (
        <div id={`school-${s.id}-detail`} className="px-3.5 pb-3 -mt-1 space-y-2.5">
          {/* Contact + weak areas + assigned ownership — laid out as a
              compact facts grid that mirrors the /plans accordion. */}
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 rounded-xl bg-white border border-[var(--color-edify-border)] p-3">
            <Fact icon={<User size={10} />}  label="Primary contact" value={
              <span className="inline-flex items-center gap-1.5">
                <span>{contact.name}</span>
                <span className="opacity-50">·</span>
                <a href={`tel:${contact.phone.replace(/\s+/g, "")}`} className="tabular hover:underline inline-flex items-center gap-1">
                  <Phone size={9} className="text-[var(--color-edify-primary)]" />
                  {contact.phone}
                </a>
              </span>
            } fullWidth />
            {s.weakestArea && (
              <Fact label="Weakest SSA" value={`${s.weakestArea.area} ${s.weakestArea.score}/10`} />
            )}
            {s.secondWeakArea && (
              <Fact label="Also weak" value={`${s.secondWeakArea.area} ${s.secondWeakArea.score}/10`} />
            )}
            <Fact label="CCEO"    value={s.assignedCceo} />
            <Fact label="Partner" value={s.assignedPartner ?? "Not assigned"} />
          </dl>

          {/* Recommendation — unified callout surface: bordered, no fill */}
          <div className="rounded-md border border-[var(--color-edify-divider)] px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wider font-bold muted">Recommended next action</div>
            <p className="text-[12px] font-extrabold text-[var(--color-edify-text)] mt-0.5">{rec.headline}</p>
            <p className="text-[11px] muted leading-snug mt-1">{rec.purpose}</p>
          </div>

          {/* Action buttons. Primary first, then a 2-col grid of secondary
              actions. SSA-blocked schools only show the SSA action +
              view-school until SSA completes. */}
          <div className="space-y-2">
            <ActionButton
              primary
              action={rec.primaryAction}
              label={rec.primaryLabel}
              onClick={() => onAction(rec.primaryAction)}
              disabled={false}
            />
            {(clusterBlocked || ssaBlocked) && rec.disabledReason && (
              <div className="text-[11px] muted leading-snug flex items-start gap-1.5 px-1">
                <Lock size={10} className="mt-0.5 text-rose-500 shrink-0" />
                <span>{rec.disabledReason}</span>
              </div>
            )}
            <div className="grid grid-cols-2 gap-1.5">
              {buttons
                .filter((a) => a !== rec.primaryAction)
                .map((action) => {
                  const disabled = clusterBlocked
                    ? action !== "add_to_cluster" && action !== "view_school"
                    : ssaBlocked &&
                      action !== "schedule_ssa" &&
                      action !== "view_school";
                  return (
                    <ActionButton
                      key={action}
                      action={action}
                      label={ACTION_LABEL[action]}
                      onClick={() => onAction(action)}
                      disabled={disabled}
                      lockReason={rec.disabledReason}
                    />
                  );
                })}
            </div>
          </div>
        </div>
      )}
    </li>
  );
}

// Shared label-value primitive used in the expanded body. Local copy of
// the helper used in the /plans and Core Schools accordions; kept
// inline rather than promoted to a shared module so the file stays
// self-contained.
function Fact({
  icon,
  label,
  value,
  fullWidth = false,
}: {
  icon?: React.ReactNode;
  label: string;
  value: React.ReactNode;
  fullWidth?: boolean;
}) {
  return (
    <div className={cn("min-w-0", fullWidth && "sm:col-span-2")}>
      <dt className="text-[10px] muted font-semibold uppercase tracking-wide flex items-center gap-1">
        {icon && <span className="text-[var(--color-edify-muted)]">{icon}</span>}
        {label}
      </dt>
      <dd className="text-[12px] font-extrabold tracking-tight mt-0.5">{value}</dd>
    </div>
  );
}

function formatUgxShort(amount: number): string {
  if (amount >= 1_000_000) return `UGX ${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000)     return `UGX ${(amount / 1_000).toFixed(0)}K`;
  return `UGX ${amount}`;
}

function StatusChip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={cn(
      "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-bold",
      ok ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700",
    )}>
      {label}
    </span>
  );
}

function ActionButton({
  action, label, primary, onClick, disabled, lockReason,
}: {
  action: SchoolGapAction;
  label: string;
  primary?: boolean;
  onClick: () => void;
  disabled?: boolean;
  lockReason?: string;
}) {
  void action;
  const isView = label.startsWith("View");
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={disabled ? (lockReason ?? "Complete the required setup step first.") : undefined}
      className={cn(
        "inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md text-[11px] font-semibold transition-colors whitespace-nowrap",
        disabled
          ? "bg-slate-100 text-slate-400 cursor-not-allowed"
          : primary
            ? "bg-[var(--color-edify-primary)] text-white font-extrabold hover:bg-[var(--color-edify-dark)]"
            : "border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
      )}
    >
      {isView ? <Eye size={11} /> : null}
      {label}
      {primary && !disabled ? <ArrowRight size={11} /> : null}
    </button>
  );
}
