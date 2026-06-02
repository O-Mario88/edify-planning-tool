"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Building2,
  GraduationCap,
  Handshake,
  AlertTriangle,
  CheckCircle2,
  Wallet,
  Sparkles,
  Users,
  Search,
  Info,
  Briefcase,
  Award,
  MapPin,
  Lock,
} from "lucide-react";
import type {
  SchoolVisitRecommendation,
  ClusterRecommendation,
  PartnerCapacityProfile,
  PartnerFollowUpRecommendation,
  Priority,
  PlanningWarning,
} from "@/lib/plan-builder-engine";
import {
  recommendPurpose,
  buildEvidencePanel,
  partnerVisitBlocker,
  allowedStaffPurposes,
  allowedPartnerPurposes,
  maxTrainingsPerDay,
  calculateStaffVisitCost,
  calculateParticipantBasedCost,
  calculatePartnerVisitCost,
  type VisitPurpose,
  type EvidencePanel,
  type PlanCostRates,
  type StaffVisitType,
} from "@/lib/plan-cost-calculator";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  TabButton,
  Summary,
  SegToggle,
  NumInput,
  Toggle,
  CostBadge,
  Stat,
  PartnerCapacityCard,
  WarningsPanel,
  formatM,
  shortIntervention,
} from "@/components/planning/PlanBuilderParts";
import {
  EvidencePanelCard,
  SubmittedBatchesStrip,
  BatchActionsCard,
  TabSwitchModal,
  SelectionSummary,
} from "@/components/planning/PlanBuilderBatchCards";

// Plan Builder. Four activity tabs:
//   1. Staff Visit       — Purpose + Commuting/Overnight + per-staff cost
//   2. Cluster Training  — Participants × rate + Venue + Facilitation
//   3. Cluster Meeting   — Same formula, meeting rate
//   4. Partner Visit     — Partner cert + schools × cost-per-school

type Tab = "staff" | "training" | "meeting" | "partner";

const PRIORITY_TONE: Record<Priority, string> = {
  Critical:   "bg-rose-100    text-rose-700",
  High:       "bg-amber-100   text-amber-700",
  Medium:     "bg-sky-100     text-sky-700",
  Low:        "bg-slate-100   text-slate-700",
  Deferrable: "bg-slate-100   text-slate-500",
};

export type PlanBuilderProps = {
  highPrioritySchoolVisits:  SchoolVisitRecommendation[];
  highPriorityClusters:      ClusterRecommendation[];
  partnerCapacityProfiles:   PartnerCapacityProfile[];
  recommendationsByPartner:  Record<string, PartnerFollowUpRecommendation[]>;
  defaultPartnerId:          string;
  costRates:                 PlanCostRates;
  /** Step-1 District Gateway card, rendered under the page header as the
   *  first section (not floating above the page chrome). */
  gateway?:                  React.ReactNode;
};

// Per-school overrides for Staff Visit tab.
type StaffVisitState = {
  selectedSchoolIds: Set<string>;
  purposeById:       Record<string, VisitPurpose>;
  focusedSchoolId:   string | null;
  visitType:         StaffVisitType;
  staffCount:        number;
  nights:            number;
  days:              number;
};

// Per-cluster overrides for Training / Meeting tabs.
type ClusterPlanState = {
  selectedClusterIds: Set<string>;
  participantsById:   Record<string, number>;
  includeVenue:       boolean;
  includeFacilitation:boolean;
  facilitators:       number;
};

export function PlanBuilderDesktopView({
  highPrioritySchoolVisits,
  highPriorityClusters,
  partnerCapacityProfiles,
  recommendationsByPartner,
  defaultPartnerId,
  costRates,
  gateway,
}: PlanBuilderProps) {
  const [tab, setTab] = useState<Tab>("staff");
  const [schoolQuery, setSchoolQuery]     = useState("");
  const [priorityFilter, setPriorityFilter] = useState<Priority | "all">("all");

  // Staff Visit state
  const [staff, setStaff] = useState<StaffVisitState>({
    selectedSchoolIds: new Set(),
    purposeById:       {},
    focusedSchoolId:   null,
    visitType:         "Commuting Visit",
    staffCount:        2,
    nights:            0,
    days:              1,
  });

  // Cluster Training state
  const [training, setTraining] = useState<ClusterPlanState>({
    selectedClusterIds:  new Set(),
    participantsById:    {},
    includeVenue:        true,
    includeFacilitation: true,
    facilitators:        1,
  });

  // Cluster Meeting state
  const [meeting, setMeeting] = useState<ClusterPlanState>({
    selectedClusterIds:  new Set(),
    participantsById:    {},
    includeVenue:        false,
    includeFacilitation: false,
    facilitators:        1,
  });

  // Partner Visit state
  const [partnerId, setPartnerId] = useState<string>(defaultPartnerId);
  const [selectedPartnerSchools, setSelectedPartnerSchools] = useState<Set<string>>(new Set());
  const [partnerPurposeById, setPartnerPurposeById] = useState<Record<string, VisitPurpose>>({});

  // ────────── Batch model ──────────
  //
  // "One activity batch at a time": each tab builds a batch in state; the
  // user must Submit, Save as draft, or Discard before switching tabs.
  // Submitted batches are persisted to localStorage so the user sees their
  // monthly plan accumulate across sessions.
  type SubmittedBatch = {
    id:           string;
    tab:          Tab;
    label:        string;
    summary:      string;
    activities:   number;
    totalCost:    number;
    submittedAt:  string;
  };
  type Drafts = Partial<Record<Tab, { summary: string; activities: number; totalCost: number; savedAt: string }>>;

  const [submittedBatches, setSubmittedBatches] = useState<SubmittedBatch[]>([]);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [pendingTab, setPendingTab] = useState<Tab | null>(null);
  const [hydrated, setHydrated] = useState(false);

  // Hydrate from localStorage on mount; persist on change. Migrate to
  // useSyncExternalStore during the React-19 sweep.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    try {
      const raw = localStorage.getItem("planBuilder.submittedBatches");
      if (raw) setSubmittedBatches(JSON.parse(raw));
      const rawD = localStorage.getItem("planBuilder.drafts");
      if (rawD) setDrafts(JSON.parse(rawD));
    } catch {/* ignore */}
    setHydrated(true);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);
  useEffect(() => {
    if (!hydrated) return;
    try { localStorage.setItem("planBuilder.submittedBatches", JSON.stringify(submittedBatches)); } catch {}
  }, [submittedBatches, hydrated]);
  useEffect(() => {
    if (!hydrated) return;
    try { localStorage.setItem("planBuilder.drafts", JSON.stringify(drafts)); } catch {}
  }, [drafts, hydrated]);

  const partnerProfile = partnerCapacityProfiles.find((p) => p.partnerId === partnerId);
  const partnerRecs    = useMemo(
    () => recommendationsByPartner[partnerId] ?? [],
    [partnerId, recommendationsByPartner],
  );

  // Schools the user has scheduled for SSA Support / SSA Verification in
  // the Staff Visit tab. Partners may piggy-back Data Collection only on
  // those scheduled SSA visits.
  const ssaScheduledSchoolIds = useMemo(() => {
    const ids = new Set<string>();
    for (const id of staff.selectedSchoolIds) {
      const p = staff.purposeById[id];
      if (p === "SSA Support" || p === "SSA Verification") ids.add(id);
    }
    return ids;
  }, [staff.selectedSchoolIds, staff.purposeById]);

  // ────────── Filtered school list (Staff Visit tab) ──────────
  const filteredSchools = useMemo(() => {
    const q = schoolQuery.trim().toLowerCase();
    return highPrioritySchoolVisits.filter((s) => {
      if (priorityFilter !== "all" && s.priorityLevel !== priorityFilter) return false;
      if (!q) return true;
      return s.schoolName.toLowerCase().includes(q)
        || s.district.toLowerCase().includes(q)
        || s.cluster .toLowerCase().includes(q);
    });
  }, [schoolQuery, priorityFilter, highPrioritySchoolVisits]);

  // ────────── Resolved selections + cost totals ──────────

  const selectedSchoolRows = highPrioritySchoolVisits.filter((s) => staff.selectedSchoolIds.has(s.schoolId));
  const selectedTrainingRows = highPriorityClusters.filter((c) => training.selectedClusterIds.has(c.clusterId));
  const selectedMeetingRows  = highPriorityClusters.filter((c) => meeting.selectedClusterIds.has(c.clusterId));
  const selectedPartnerRows  = partnerRecs.filter((r) => selectedPartnerSchools.has(r.schoolId));

  // Staff Visit total = per-school cost × selected
  const staffVisitBreakdown = useMemo(() => calculateStaffVisitCost({
    visitType:    staff.visitType,
    staffCount:   staff.staffCount,
    schoolCount:  selectedSchoolRows.length,
    nights:       staff.nights,
    days:         staff.days,
  }, costRates), [staff, selectedSchoolRows.length, costRates]);

  // Training totals — one row per cluster using its participant count
  const trainingBreakdowns = useMemo(() => selectedTrainingRows.map((c) => ({
    cluster: c,
    cost: calculateParticipantBasedCost({
      activity:            "Cluster Training",
      participants:        training.participantsById[c.clusterId] ?? c.expectedParticipants,
      includeVenue:        training.includeVenue,
      includeFacilitation: training.includeFacilitation,
    }, costRates),
  })), [selectedTrainingRows, training, costRates]);
  const trainingTotal = trainingBreakdowns.reduce((a, t) => a + t.cost.total, 0);

  const meetingBreakdowns = useMemo(() => selectedMeetingRows.map((c) => ({
    cluster: c,
    cost: calculateParticipantBasedCost({
      activity:            "Cluster Meeting",
      participants:        meeting.participantsById[c.clusterId] ?? c.expectedParticipants,
      includeVenue:        meeting.includeVenue,
      includeFacilitation: meeting.includeFacilitation,
    }, costRates),
  })), [selectedMeetingRows, meeting, costRates]);
  const meetingTotal = meetingBreakdowns.reduce((a, t) => a + t.cost.total, 0);

  const partnerVisitBreakdown = useMemo(() => calculatePartnerVisitCost({
    schoolCount: selectedPartnerRows.length,
  }, costRates), [selectedPartnerRows.length, costRates]);

  const totalSelected =
    selectedSchoolRows.length + selectedTrainingRows.length + selectedMeetingRows.length + selectedPartnerRows.length;

  const estimatedBudget =
    staffVisitBreakdown.total + trainingTotal + meetingTotal + partnerVisitBreakdown.total;

  // ────────── Planning warnings ──────────
  const warnings: PlanningWarning[] = useMemo(() => {
    const out: PlanningWarning[] = [];

    // 5-visits-per-day rule for staff visits (planned over 5 working days)
    const visitsPerDay = Math.floor(selectedSchoolRows.length / 5);
    const remainder    = selectedSchoolRows.length % 5;
    for (let d = 0; d < 5; d++) {
      const count = visitsPerDay + (d < remainder ? 1 : 0);
      if (count > 0 && count < 5) {
        out.push({
          id: `daily-min-day-${d + 1}`, level: "warning",
          message: `Daily Visit Minimum Not Met (Day ${d + 1}): only ${count} school visit${count === 1 ? "" : "s"} planned. Minimum is 5.`,
        });
      }
    }

    // Multi-facilitator training capacity
    const trainingByDate: Record<string, number> = {};
    for (const c of selectedTrainingRows) trainingByDate[c.suggestedDate] = (trainingByDate[c.suggestedDate] ?? 0) + 1;
    const cap = maxTrainingsPerDay(training.facilitators);
    for (const [date, count] of Object.entries(trainingByDate)) {
      if (count > cap) {
        out.push({
          id: `train-cap-${date}`, level: "error",
          message: `${count} cluster trainings planned on ${date} but only ${training.facilitators} facilitator${training.facilitators === 1 ? "" : "s"} available (max ${cap}/day).`,
        });
      }
    }

    // Partner capacity
    if (partnerProfile && selectedPartnerRows.length > partnerProfile.availableCapacity) {
      out.push({
        id: `cap-${partnerId}`, level: "error",
        message: `Partner Capacity Exceeded — ${partnerProfile.partnerName} has capacity for ${partnerProfile.availableCapacity} schools this month. You selected ${selectedPartnerRows.length}.`,
      });
    }

    // Partner visit rule violations (cert, staff-only purpose, SSA-dependent purpose)
    if (partnerProfile) {
      const blocked = selectedPartnerRows.filter((r) => {
        const school = highPrioritySchoolVisits.find((s) => s.schoolId === r.schoolId);
        if (!school) return false;
        const purpose = partnerPurposeById[r.schoolId] ?? (partnerProfile.certified ? "Partner Follow-Up" : "Data Collection");
        return partnerVisitBlocker(school, purpose, partnerProfile.certified, ssaScheduledSchoolIds.has(r.schoolId)) !== null;
      });
      if (blocked.length > 0) {
        out.push({
          id: `partner-blocked-${partnerId}`, level: "error",
          message: `${partnerProfile.partnerName} — ${blocked.length} selected school${blocked.length === 1 ? "" : "s"} blocked (certification / staff-only / SSA-dependent rule).`,
        });
      } else if (!partnerProfile.certified) {
        out.push({
          id: `cert-warn-${partnerId}`, level: "warning",
          message: `${partnerProfile.partnerName} is not Certified — only Data Collection (on SSA-scheduled schools) and Courtesy Visits are valid.`,
        });
      }
    }

    return out;
  }, [
    selectedSchoolRows, selectedTrainingRows, selectedPartnerRows, training.facilitators,
    partnerProfile, partnerId, partnerPurposeById, highPrioritySchoolVisits,
    ssaScheduledSchoolIds,
  ]);

  // ────────── Batch helpers ──────────

  const TAB_LABEL: Record<Tab, string> = {
    staff:    "Staff Visit",
    training: "Cluster Training",
    meeting:  "Cluster Meeting",
    partner:  "Partner Visit",
  };

  function currentTabHasItems(t: Tab): boolean {
    if (t === "staff")    return staff.selectedSchoolIds.size > 0;
    if (t === "training") return training.selectedClusterIds.size > 0;
    if (t === "meeting")  return meeting.selectedClusterIds.size > 0;
    if (t === "partner")  return selectedPartnerSchools.size > 0;
    return false;
  }
  function currentTabBatch(t: Tab): { activities: number; totalCost: number; summary: string } | null {
    if (t === "staff") {
      const n = selectedSchoolRows.length;
      if (n === 0) return null;
      const clusters = new Set(selectedSchoolRows.map((s) => s.cluster)).size;
      return { activities: n, totalCost: staffVisitBreakdown.total, summary: `${n} school visit${n === 1 ? "" : "s"} across ${clusters} cluster${clusters === 1 ? "" : "s"} · ${staff.visitType}` };
    }
    if (t === "training") {
      const n = selectedTrainingRows.length;
      if (n === 0) return null;
      const parts = trainingBreakdowns.reduce((a, b) => a + b.cost.participants, 0);
      return { activities: n, totalCost: trainingTotal, summary: `${n} cluster training${n === 1 ? "" : "s"} · ${parts} participants · ${training.facilitators} facilitator${training.facilitators === 1 ? "" : "s"}` };
    }
    if (t === "meeting") {
      const n = selectedMeetingRows.length;
      if (n === 0) return null;
      const parts = meetingBreakdowns.reduce((a, b) => a + b.cost.participants, 0);
      return { activities: n, totalCost: meetingTotal, summary: `${n} cluster meeting${n === 1 ? "" : "s"} · ${parts} participants` };
    }
    const n = selectedPartnerRows.length;
    if (n === 0) return null;
    return { activities: n, totalCost: partnerVisitBreakdown.total, summary: `${n} partner visit${n === 1 ? "" : "s"} · ${partnerProfile?.partnerName ?? "Partner"}` };
  }
  function clearTab(t: Tab) {
    if (t === "staff")    setStaff((p) => ({ ...p, selectedSchoolIds: new Set(), purposeById: {}, focusedSchoolId: null }));
    if (t === "training") setTraining((p) => ({ ...p, selectedClusterIds: new Set(), participantsById: {} }));
    if (t === "meeting")  setMeeting((p) => ({ ...p, selectedClusterIds: new Set(), participantsById: {} }));
    if (t === "partner")  { setSelectedPartnerSchools(new Set()); setPartnerPurposeById({}); }
  }
  function submitBatch(t: Tab) {
    const b = currentTabBatch(t);
    if (!b) return;
    const batch: SubmittedBatch = {
      // Date.now() / Math.random() are impure but this runs only in an
      // event handler. Migrate to a useCallback wrapper or crypto.randomUUID
      // during the React-19 compiler sweep.
      // eslint-disable-next-line react-hooks/purity
      id:          `BATCH-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      tab:         t,
      label:       TAB_LABEL[t],
      summary:     b.summary,
      activities:  b.activities,
      totalCost:   b.totalCost,
      submittedAt: new Date().toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }),
    };
    setSubmittedBatches((prev) => [batch, ...prev]);
    setDrafts((prev) => { const next = { ...prev }; delete next[t]; return next; });
    clearTab(t);
  }
  function saveDraft(t: Tab) {
    const b = currentTabBatch(t);
    if (!b) return;
    setDrafts((prev) => ({ ...prev, [t]: { summary: b.summary, activities: b.activities, totalCost: b.totalCost, savedAt: new Date().toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }) } }));
    clearTab(t);
  }
  function discardBatch(t: Tab) {
    clearTab(t);
  }
  function requestTabSwitch(next: Tab) {
    if (next === tab || !currentTabHasItems(tab)) {
      setTab(next);
      return;
    }
    setPendingTab(next);
  }

  const submittedTotal       = submittedBatches.reduce((a, b) => a + b.totalCost,   0);
  const submittedActivities  = submittedBatches.reduce((a, b) => a + b.activities, 0);

  // ────────── Toggles ──────────

  function toggleSchool(s: SchoolVisitRecommendation) {
    setStaff((prev) => {
      const next = new Set(prev.selectedSchoolIds);
      const purposeById = { ...prev.purposeById };
      if (next.has(s.schoolId)) {
        next.delete(s.schoolId);
        delete purposeById[s.schoolId];
      } else {
        next.add(s.schoolId);
        purposeById[s.schoolId] = recommendPurpose(s).primary;
      }
      return { ...prev, selectedSchoolIds: next, purposeById, focusedSchoolId: s.schoolId };
    });
  }
  function setSchoolPurpose(schoolId: string, purpose: VisitPurpose) {
    setStaff((prev) => ({ ...prev, purposeById: { ...prev.purposeById, [schoolId]: purpose }, focusedSchoolId: schoolId }));
  }
  function toggleTrainingCluster(c: ClusterRecommendation) {
    setTraining((prev) => {
      const next = new Set(prev.selectedClusterIds);
      const participants = { ...prev.participantsById };
      if (next.has(c.clusterId)) { next.delete(c.clusterId); delete participants[c.clusterId]; }
      else { next.add(c.clusterId); participants[c.clusterId] = c.expectedParticipants; }
      return { ...prev, selectedClusterIds: next, participantsById: participants };
    });
  }
  function toggleMeetingCluster(c: ClusterRecommendation) {
    setMeeting((prev) => {
      const next = new Set(prev.selectedClusterIds);
      const participants = { ...prev.participantsById };
      if (next.has(c.clusterId)) { next.delete(c.clusterId); delete participants[c.clusterId]; }
      else { next.add(c.clusterId); participants[c.clusterId] = c.expectedParticipants; }
      return { ...prev, selectedClusterIds: next, participantsById: participants };
    });
  }
  function defaultPartnerPurpose(schoolId: string): VisitPurpose {
    const cert = partnerProfile?.certified ?? false;
    const ssa  = ssaScheduledSchoolIds.has(schoolId);
    if (cert) return "Partner Follow-Up";
    return ssa ? "Data Collection" : "Courtesy Visit";
  }
  function togglePartnerSchool(r: PartnerFollowUpRecommendation) {
    const school = highPrioritySchoolVisits.find((s) => s.schoolId === r.schoolId);
    setSelectedPartnerSchools((prev) => {
      const next = new Set(prev);
      if (next.has(r.schoolId)) next.delete(r.schoolId);
      else next.add(r.schoolId);
      return next;
    });
    if (school && !partnerPurposeById[r.schoolId]) {
      setPartnerPurposeById((prev) => ({ ...prev, [r.schoolId]: defaultPartnerPurpose(r.schoolId) }));
    }
  }
  function autoSelectPartner() {
    if (!partnerProfile) return;
    const cap = partnerProfile.availableCapacity;
    const chosen = partnerRecs.slice(0, cap);
    setSelectedPartnerSchools(new Set(chosen.map((r) => r.schoolId)));
    const purposes: Record<string, VisitPurpose> = { ...partnerPurposeById };
    for (const r of chosen) {
      purposes[r.schoolId] = defaultPartnerPurpose(r.schoolId);
    }
    setPartnerPurposeById(purposes);
  }

  // ────────── Evidence panel data ──────────
  const focusedSchool = staff.focusedSchoolId
    ? highPrioritySchoolVisits.find((s) => s.schoolId === staff.focusedSchoolId) ?? null
    : null;
  const focusedPurpose = focusedSchool ? (staff.purposeById[focusedSchool.schoolId] ?? recommendPurpose(focusedSchool).primary) : null;
  const focusedEvidence: EvidencePanel | null = focusedSchool && focusedPurpose
    ? buildEvidencePanel(focusedSchool, focusedPurpose)
    : null;

  return (
    <>
      <PageHeader
        title="Create / Edit Plan"
        dateLabel="May 2025"
        subtitle="Pre-loaded with the highest-priority work — by SSA, training history, partner capacity, and coverage targets. Plan one activity type at a time: each tab uses its own cost formula from active Country Cost Settings."
      />

      <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6 space-y-4">
        {/* Step 1 — District Gateway, the first section under the page header. */}
        {gateway}

        {/* Submitted-batches strip */}
        {submittedBatches.length > 0 && (
          <SubmittedBatchesStrip
            batches={submittedBatches}
            totalCost={submittedTotal}
            totalActivities={submittedActivities}
            onClear={() => setSubmittedBatches([])}
          />
        )}

        {/* Activity counts — 4 cards across */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Summary Icon={Building2}     label="Staff visits"     value={selectedSchoolRows.length}   sub={`of ${highPrioritySchoolVisits.length} ranked schools`} tone="rose" />
          <Summary Icon={GraduationCap} label="Cluster trainings" value={selectedTrainingRows.length} sub={`max ${maxTrainingsPerDay(training.facilitators)}/day`} tone="violet" />
          <Summary Icon={Users}         label="Cluster meetings" value={selectedMeetingRows.length}  sub="participant-based" tone="sky" />
          <Summary Icon={Handshake}     label="Partner visits"   value={selectedPartnerRows.length}  sub={partnerProfile?.partnerName ?? "—"} tone="amber" />
        </section>

        {/* Budget + warnings — wide pair */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Summary
            Icon={Wallet}
            label="Estimated budget"
            value={`UGX ${formatM(estimatedBudget)}`}
            sub={`${totalSelected} activities · from active Country Cost Settings`}
            tone="edify"
            wide
          />
          <Summary
            Icon={AlertTriangle}
            label="Planning warnings"
            value={warnings.length}
            sub={warnings.length === 0 ? "All rules satisfied" : warnings.some((w) => w.level === "error") ? "Errors must be resolved" : "Review warnings"}
            tone={warnings.some((w) => w.level === "error") ? "rose" : warnings.length > 0 ? "amber" : "green"}
            wide
          />
        </section>

        <div className="grid grid-cols-12 gap-4 items-start">
          {/* Tabs + content */}
          <div className="col-span-12 lg:col-span-8 space-y-3">
            <div className="card rounded-2xl p-2 flex items-center gap-1 overflow-x-auto">
              <TabButton active={tab === "staff"}    onClick={() => requestTabSwitch("staff")}    Icon={Briefcase}      label="Staff Visit"      count={selectedSchoolRows.length}    hasDraft={!!drafts.staff} />
              <TabButton active={tab === "training"} onClick={() => requestTabSwitch("training")} Icon={GraduationCap}  label="Cluster Training" count={selectedTrainingRows.length}  hasDraft={!!drafts.training} />
              <TabButton active={tab === "meeting"}  onClick={() => requestTabSwitch("meeting")}  Icon={Users}          label="Cluster Meeting"  count={selectedMeetingRows.length}   hasDraft={!!drafts.meeting} />
              <TabButton active={tab === "partner"}  onClick={() => requestTabSwitch("partner")}  Icon={Handshake}      label="Partner Visit"    count={selectedPartnerRows.length}   hasDraft={!!drafts.partner} />
            </div>

            {tab === "staff" && (
              <StaffVisitPanel
                rows={filteredSchools}
                allCount={highPrioritySchoolVisits.length}
                query={schoolQuery}
                onQuery={setSchoolQuery}
                priority={priorityFilter}
                onPriority={setPriorityFilter}
                staff={staff}
                onToggle={toggleSchool}
                onChangePurpose={setSchoolPurpose}
                onChangeStaff={setStaff}
                breakdown={staffVisitBreakdown}
                evidence={focusedEvidence}
              />
            )}

            {tab === "training" && (
              <ClusterActivityPanel
                kind="training"
                rows={highPriorityClusters}
                state={training}
                breakdowns={trainingBreakdowns}
                total={trainingTotal}
                onToggle={toggleTrainingCluster}
                onChange={setTraining}
              />
            )}

            {tab === "meeting" && (
              <ClusterActivityPanel
                kind="meeting"
                rows={highPriorityClusters}
                state={meeting}
                breakdowns={meetingBreakdowns}
                total={meetingTotal}
                onToggle={toggleMeetingCluster}
                onChange={setMeeting}
              />
            )}

            {tab === "partner" && (
              <PartnerVisitPanel
                profiles={partnerCapacityProfiles}
                partnerId={partnerId}
                onPartnerChange={(id) => { setPartnerId(id); setSelectedPartnerSchools(new Set()); }}
                profile={partnerProfile}
                recommendations={partnerRecs}
                schools={highPrioritySchoolVisits}
                selected={selectedPartnerSchools}
                purposeById={partnerPurposeById}
                ssaScheduledSchoolIds={ssaScheduledSchoolIds}
                onTogglePartnerSchool={togglePartnerSchool}
                onChangePurpose={(id, p) => setPartnerPurposeById((prev) => ({ ...prev, [id]: p }))}
                onAutoSelect={autoSelectPartner}
                breakdown={partnerVisitBreakdown}
              />
            )}
          </div>

          {/* Right rail */}
          <aside className="col-span-12 lg:col-span-4 space-y-3 lg:sticky lg:top-4">
            <SelectionSummary
              staffCount={selectedSchoolRows.length}
              trainingCount={selectedTrainingRows.length}
              meetingCount={selectedMeetingRows.length}
              partnerCount={selectedPartnerRows.length}
              estimatedBudget={estimatedBudget}
              warnings={warnings}
              totalSelected={totalSelected}
              staffVisitTotal={staffVisitBreakdown.total}
              trainingTotal={trainingTotal}
              meetingTotal={meetingTotal}
              partnerTotal={partnerVisitBreakdown.total}
            />
            {tab === "partner" && partnerProfile && (
              <PartnerCapacityCard profile={partnerProfile} selected={selectedPartnerSchools.size} />
            )}
            <BatchActionsCard
              tab={tab}
              tabLabel={TAB_LABEL[tab]}
              hasItems={currentTabHasItems(tab)}
              batchSummary={currentTabBatch(tab)?.summary}
              draft={drafts[tab]}
              hasBlockingErrors={warnings.some((w) => w.level === "error")}
              onSubmit={() => submitBatch(tab)}
              onSaveDraft={() => saveDraft(tab)}
              onDiscard={() => discardBatch(tab)}
            />
            <WarningsPanel warnings={warnings} />
          </aside>
        </div>
      </div>

      {/* Tab-switch confirmation */}
      {pendingTab && (
        <TabSwitchModal
          fromLabel={TAB_LABEL[tab]}
          toLabel={TAB_LABEL[pendingTab]}
          summary={currentTabBatch(tab)?.summary ?? ""}
          hasBlockingErrors={warnings.some((w) => w.level === "error")}
          onSubmit={() => { submitBatch(tab); setTab(pendingTab); setPendingTab(null); }}
          onSaveDraft={() => { saveDraft(tab); setTab(pendingTab); setPendingTab(null); }}
          onDiscard={() => { discardBatch(tab); setTab(pendingTab); setPendingTab(null); }}
          onContinue={() => setPendingTab(null)}
        />
      )}
    </>
  );
}

// ────────── Staff Visit Panel ──────────

function StaffVisitPanel({
  rows, allCount, query, onQuery, priority, onPriority,
  staff, onToggle, onChangePurpose, onChangeStaff,
  breakdown, evidence,
}: {
  rows: SchoolVisitRecommendation[];
  allCount: number;
  query: string;
  onQuery: (v: string) => void;
  priority: Priority | "all";
  onPriority: (v: Priority | "all") => void;
  staff: StaffVisitState;
  onToggle: (s: SchoolVisitRecommendation) => void;
  onChangePurpose: (schoolId: string, purpose: VisitPurpose) => void;
  onChangeStaff:   (updater: (prev: StaffVisitState) => StaffVisitState) => void;
  breakdown: ReturnType<typeof calculateStaffVisitCost>;
  evidence:  EvidencePanel | null;
}) {
  const PRIORITIES: (Priority | "all")[] = ["all", "Critical", "High", "Medium", "Low", "Deferrable"];

  return (
    <>
      {/* Visit-type + per-staff defaults */}
      <div className="card p-3.5 space-y-3">
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <div className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Briefcase size={13} className="text-[var(--color-edify-primary)]" />
            Visit defaults
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <AutoOptimizeButton staff={staff} selected={staff.selectedSchoolIds} />
            <div className="text-caption muted">Applied to every selected school.</div>
          </div>
        </div>

        {/* Visit type — full row */}
        <SegToggle
          label="Visit type"
          value={staff.visitType}
          options={["Commuting Visit", "Overnight Visit"]}
          onChange={(v) => onChangeStaff((prev) => ({ ...prev, visitType: v as StaffVisitType }))}
        />

        {/* Numeric inputs + cost preview — even 4-up grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <NumInput label="Staff"  value={staff.staffCount} min={1} max={6}  onChange={(n) => onChangeStaff((prev) => ({ ...prev, staffCount: n }))} />
          <NumInput label="Days"   value={staff.days}   min={1} max={10} disabled={staff.visitType === "Commuting Visit"} onChange={(n) => onChangeStaff((prev) => ({ ...prev, days: n }))} />
          <NumInput label="Nights" value={staff.nights} min={0} max={10} disabled={staff.visitType === "Commuting Visit"} onChange={(n) => onChangeStaff((prev) => ({ ...prev, nights: n }))} />
          <CostBadge label="Per staff" value={breakdown.perStaff} />
        </div>

        {/* Formula row */}
        <div className="rounded-xl bg-[var(--color-edify-soft)]/50 border border-[var(--color-edify-border)] px-3 py-2 text-[11px] muted leading-snug break-words">
          <span className="font-extrabold text-[var(--color-edify-text)]">Formula:</span>{" "}
          <span className="font-mono">{breakdown.formula}</span>
        </div>
      </div>

      {/* Search + priority filter */}
      <div className="card rounded-2xl p-3 flex flex-wrap items-center gap-2.5">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]" />
          <input
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder="Search school, district, cluster"
            className="w-full pl-9 pr-3 h-10 rounded-xl border border-[var(--color-edify-border)] bg-white text-body focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {PRIORITIES.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onPriority(p)}
              className={cn(
                "h-9 px-3 rounded-full text-[12px] font-extrabold tracking-tight border whitespace-nowrap",
                priority === p
                  ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]"
                  : "bg-white text-[var(--color-edify-text)] border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40",
              )}
            >
              {p === "all" ? "All" : p}
            </button>
          ))}
        </div>
      </div>

      <div className="text-[11.5px] muted flex items-center justify-between gap-3 flex-wrap mb-1">
        <span>Showing {rows.length} of {allCount} priority schools · click a school to view its evidence panel</span>
        <span className="whitespace-nowrap">{staff.selectedSchoolIds.size} selected · UGX {formatM(breakdown.total)} total</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {/* Card list spans 2 cols */}
        <ul className="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-3">
          {rows.slice(0, 40).map((s) => {
            const reco = recommendPurpose(s);
            const checked = staff.selectedSchoolIds.has(s.schoolId);
            const purpose = staff.purposeById[s.schoolId] ?? reco.primary;
            return (
              <StaffSchoolCard
                key={s.schoolId}
                s={s}
                checked={checked}
                focused={staff.focusedSchoolId === s.schoolId}
                purpose={purpose}
                recommended={reco.primary}
                secondary={reco.secondary}
                priorityBoost={reco.priorityBoost}
                onToggle={() => onToggle(s)}
                onChangePurpose={(p) => onChangePurpose(s.schoolId, p)}
              />
            );
          })}
          {rows.length > 40 && (
            <li className="text-caption muted text-center pt-1 col-span-full">Showing top 40 of {rows.length}. Filter to narrow.</li>
          )}
        </ul>
        {/* Evidence panel */}
        <div className="lg:col-span-1">
          <EvidencePanelCard evidence={evidence} />
        </div>
      </div>
    </>
  );
}

function StaffSchoolCard({
  s, checked, focused, purpose, recommended, secondary, priorityBoost, onToggle, onChangePurpose,
}: {
  s: SchoolVisitRecommendation;
  checked: boolean;
  focused: boolean;
  purpose: VisitPurpose;
  recommended: VisitPurpose;
  secondary?: VisitPurpose;
  priorityBoost: boolean;
  onToggle: () => void;
  onChangePurpose: (p: VisitPurpose) => void;
}) {
  return (
    <div
      className={cn(
        "card rounded-2xl p-3 text-left transition-colors",
        checked && "ring-2 ring-emerald-300 bg-emerald-50/40",
        focused && !checked && "ring-2 ring-sky-300",
      )}
    >
      <button type="button" onClick={onToggle} className="w-full text-left min-w-0">
        <div className="flex items-baseline justify-between gap-2 mb-1 min-w-0">
          <div className="text-[13px] font-extrabold tracking-tight truncate min-w-0 flex-1">{s.schoolName}</div>
          <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0", PRIORITY_TONE[s.priorityLevel])}>
            {priorityBoost ? <Sparkles size={9} className="mr-1" /> : null}
            {s.priorityLevel}
          </span>
        </div>
        <div className="text-caption muted truncate">{s.district} · {s.cluster} · {s.assignedCceo}</div>
        <div className="text-[11px] muted leading-snug mt-1 line-clamp-2">{s.priorityReason}</div>
        <div className="grid grid-cols-3 gap-x-2 gap-y-0.5 text-caption mt-2 min-w-0">
          <Stat label="SSA"   value={s.ssaScore == null ? "Pending" : String(s.ssaScore)} />
          <Stat label="Weak"  value={s.ssaScore == null ? "—" : shortIntervention(s.weakestIntervention)} />
          <Stat label="Visit" value={s.lastVisitDate} />
        </div>
      </button>
      <div className="mt-2.5 space-y-1 min-w-0">
        <label
          htmlFor={`staff-purpose-${s.schoolId}`}
          className="block text-[10px] muted font-bold uppercase tracking-wide"
        >
          Purpose
        </label>
        <select
          id={`staff-purpose-${s.schoolId}`}
          aria-label={`Visit purpose for ${s.schoolName}`}
          value={purpose}
          onChange={(e) => onChangePurpose(e.target.value as VisitPurpose)}
          className="block w-full h-9 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] px-2 font-semibold focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
        >
          {allowedStaffPurposes(s).map((p) => (
            <option key={p} value={p}>{p}{p === recommended ? " ★" : ""}</option>
          ))}
        </select>
        {s.ssaScore == null && (
          <p className="text-[10px] muted leading-snug">
            Only SSA Support is allowed — no other intervention or coaching can be planned until this school completes its SSA.
          </p>
        )}
      </div>
      {secondary && purpose === recommended && (
        <div className="text-[10px] muted mt-1.5 inline-flex items-center gap-1">
          <Sparkles size={9} />
          Secondary: <span className="font-extrabold">{secondary}</span>
        </div>
      )}
    </div>
  );
}


// ────────── Cluster Training / Meeting Panel ──────────

function ClusterActivityPanel({
  kind, rows, state, breakdowns, total, onToggle, onChange,
}: {
  kind: "training" | "meeting";
  rows: ClusterRecommendation[];
  state: ClusterPlanState;
  breakdowns: { cluster: ClusterRecommendation; cost: ReturnType<typeof calculateParticipantBasedCost> }[];
  total: number;
  onToggle: (c: ClusterRecommendation) => void;
  onChange: (updater: (prev: ClusterPlanState) => ClusterPlanState) => void;
}) {
  const trainingDayCap = maxTrainingsPerDay(state.facilitators);
  const isTraining = kind === "training";
  return (
    <>
      <div className="card p-3.5 space-y-3">
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <div className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <GraduationCap size={13} className="text-[var(--color-edify-primary)]" />
            {isTraining ? "Cluster Training" : "Cluster Meeting"} settings
          </div>
          <div className="text-caption muted">
            Cost = (participants × rate){state.includeVenue ? " + venue" : ""}{state.includeFacilitation ? " + facilitation" : ""}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
          <NumInput
            label="Facilitators"
            value={state.facilitators}
            min={1}
            max={6}
            onChange={(n) => onChange((prev) => ({ ...prev, facilitators: n }))}
          />
          <Toggle
            label="Venue fee"
            value={state.includeVenue}
            onChange={(v) => onChange((prev) => ({ ...prev, includeVenue: v }))}
          />
          <Toggle
            label="Facilitation fee"
            value={state.includeFacilitation}
            onChange={(v) => onChange((prev) => ({ ...prev, includeFacilitation: v }))}
          />
          <div className="rounded-xl bg-[var(--color-edify-primary)]/10 border border-[var(--color-edify-primary)]/30 px-3 py-2">
            <div className="text-[10px] muted font-bold uppercase">Max {isTraining ? "trainings" : "meetings"}/day</div>
            <div className="text-[18px] font-extrabold tabular leading-tight text-[var(--color-edify-primary)]">{trainingDayCap}</div>
            <div className="text-[10px] muted truncate">{state.facilitators} facilitator{state.facilitators === 1 ? "" : "s"} on duty</div>
          </div>
        </div>
      </div>

      <div className="text-[11.5px] muted flex items-center justify-between gap-3 flex-wrap mb-1">
        <span>{rows.length} clusters · select and edit participant counts to project cost</span>
        <span className="whitespace-nowrap">{state.selectedClusterIds.size} selected · UGX {formatM(total)} total</span>
      </div>

      <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {rows.map((c) => {
          const checked = state.selectedClusterIds.has(c.clusterId);
          const participants = state.participantsById[c.clusterId] ?? c.expectedParticipants;
          const bd = breakdowns.find((b) => b.cluster.clusterId === c.clusterId);
          return (
            <li
              key={c.clusterId}
              className={cn(
                "card p-3.5 transition-colors",
                checked && "ring-2 ring-emerald-300 bg-emerald-50/40",
              )}
            >
              <button type="button" onClick={() => onToggle(c)} className="w-full text-left">
                <div className="flex items-baseline justify-between gap-2 mb-1">
                  <div className="text-[13px] font-extrabold tracking-tight truncate">{c.clusterName}</div>
                  <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", PRIORITY_TONE[c.priorityLevel])}>
                    {c.priorityLevel}
                  </span>
                </div>
                <div className="text-caption muted">{c.district} · {c.schoolCount} schools · Avg SSA {c.averageSsa.toFixed(2)}</div>
                <div className="text-[11px] muted leading-snug mt-1.5">{c.priorityReason}</div>
                <div className="text-caption muted mt-1">
                  Recommended: <span className="font-extrabold text-[var(--color-edify-text)]">{c.recommendedActivity}</span> on {c.suggestedDate}
                </div>
              </button>
              {checked && (
                <div className="mt-2.5 rounded-xl bg-[var(--color-edify-soft)]/50 border border-[var(--color-edify-border)] p-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <label className="text-[10px] muted font-bold uppercase tracking-wide">Participants</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        aria-label={`Participants for ${c.clusterName}`}
                        min={1}
                        max={200}
                        value={participants}
                        onChange={(e) => {
                          const n = Math.max(1, Math.min(200, Number(e.target.value) || 1));
                          onChange((prev) => ({ ...prev, participantsById: { ...prev.participantsById, [c.clusterId]: n } }));
                        }}
                        className="w-20 h-8 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] px-2 font-extrabold tabular text-right"
                      />
                      <span className="text-caption muted whitespace-nowrap">× UGX {bd?.cost.perParticipant.toLocaleString()}</span>
                    </div>
                  </div>
                  <div className="text-caption muted leading-snug break-words">
                    <span className="font-mono">{bd?.cost.formula}</span>
                  </div>
                  <div className="flex items-baseline justify-between gap-2 pt-1 border-t border-[var(--color-edify-border)]">
                    <span className="text-[10px] muted font-bold uppercase tracking-wide">Total</span>
                    <span className="text-body-lg font-extrabold tabular">UGX {bd?.cost.total.toLocaleString()}</span>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

// ────────── Partner Visit Panel ──────────

function PartnerVisitPanel({
  profiles, partnerId, onPartnerChange, profile, recommendations, schools,
  selected, purposeById, ssaScheduledSchoolIds,
  onTogglePartnerSchool, onChangePurpose, onAutoSelect, breakdown,
}: {
  profiles: PartnerCapacityProfile[];
  partnerId: string;
  onPartnerChange: (id: string) => void;
  profile?: PartnerCapacityProfile;
  recommendations: PartnerFollowUpRecommendation[];
  schools: SchoolVisitRecommendation[];
  selected: Set<string>;
  purposeById: Record<string, VisitPurpose>;
  ssaScheduledSchoolIds: Set<string>;
  onTogglePartnerSchool: (r: PartnerFollowUpRecommendation) => void;
  onChangePurpose: (id: string, p: VisitPurpose) => void;
  onAutoSelect: () => void;
  breakdown: ReturnType<typeof calculatePartnerVisitCost>;
}) {
  return (
    <>
      <div className="card p-3.5">
        <header className="flex items-baseline justify-between gap-2 mb-2">
          <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <Handshake size={14} className="text-[var(--color-edify-primary)]" />
            Step 1 — Select partner
          </h3>
          <span className="text-caption muted">{profiles.length} partners</span>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {profiles.map((p) => (
            <button
              key={p.partnerId}
              type="button"
              onClick={() => onPartnerChange(p.partnerId)}
              className={cn(
                "rounded-xl border p-3 text-left transition-colors",
                p.partnerId === partnerId
                  ? "border-[var(--color-edify-primary)] ring-2 ring-[var(--color-edify-primary)]/30 bg-[var(--color-edify-soft)]/40"
                  : "border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/30",
              )}
            >
              <div className="flex items-baseline justify-between gap-2 mb-1">
                <div className="text-body font-extrabold tracking-tight truncate">{p.partnerName}</div>
                <span className={cn(
                  "inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                  p.certified ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700",
                )}>
                  {p.certified ? <Award size={9} /> : <AlertTriangle size={9} />}
                  {p.certified ? "Certified" : "Non-Certified"}
                </span>
              </div>
              <div className="text-caption muted">{p.activeFieldStaff} field staff · {p.availableCapacity}/{p.monthlyCapacity} available</div>
              <div className="text-caption muted truncate">{p.assignedDistricts.join(", ")}</div>
            </button>
          ))}
        </div>
      </div>

      {profile && (
        <div className="card p-3.5">
          <header className="flex items-baseline justify-between gap-2 mb-2">
            <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
              <Sparkles size={14} className="text-[var(--color-edify-primary)]" />
              Step 2 — Recommended schools
            </h3>
            <span className="text-caption muted">
              {recommendations.length} eligible · {selected.size} selected
            </span>
          </header>
          {!profile.certified && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-900 flex items-start gap-1.5 mb-3">
              <Lock size={11} className="mt-0.5 shrink-0" />
              <span className="leading-snug">
                <span className="font-extrabold">{profile.partnerName} is Non-Certified.</span> Only Courtesy Visits (non-SSA schools) and
                Data Collection (only on schools already scheduled for SSA Support or SSA Verification by staff) are valid. Other rows appear locked.
              </span>
            </div>
          )}
          <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-[11px] text-sky-900 flex items-start gap-1.5 mb-3">
            <Info size={11} className="mt-0.5 shrink-0" />
            <span className="leading-snug">
              <span className="font-extrabold">SSA Verification</span> is performed by staff only — it is not offered as a partner purpose.
              <span className="font-extrabold"> Data Collection</span> piggy-backs on a scheduled SSA visit: it appears only for schools the staff has selected for SSA Support or SSA Verification ({ssaScheduledSchoolIds.size} so far).
            </span>
          </div>
          <div className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-3 mb-3 grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] leading-snug">
            <div className="break-words">
              <div className="text-[10px] muted font-bold uppercase tracking-wide mb-0.5">Capacity</div>
              <span className="font-mono">{profile.activeFieldStaff}×{profile.dailySchoolVisitCapacity}×{profile.workingDaysPerWeek}×{profile.planningWeeksInMonth} = {profile.monthlyCapacity}/mo</span>
            </div>
            <div className="break-words">
              <div className="text-[10px] muted font-bold uppercase tracking-wide mb-0.5">Cost</div>
              <span className="font-mono">{breakdown.formula} = UGX {breakdown.total.toLocaleString()}</span>
            </div>
          </div>
          <div className="flex items-center gap-2 mb-3">
            <button
              type="button"
              onClick={onAutoSelect}
              className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-semibold inline-flex items-center gap-1.5 hover:brightness-110"
            >
              <Sparkles size={13} />
              Auto-select highest priority
            </button>
            <span className="text-caption muted">Respects available capacity ({profile.availableCapacity}).</span>
          </div>

          {recommendations.length === 0 ? (
            <div className="text-[12px] muted text-center py-6">No eligible schools for this partner. Try a different partner.</div>
          ) : (
            <ul className="space-y-1.5">
              {recommendations.slice(0, 24).map((r) => {
                const school = schools.find((s) => s.schoolId === r.schoolId);
                if (!school) return null;
                const isScheduledForSsa = ssaScheduledSchoolIds.has(r.schoolId);
                const defaultPurpose: VisitPurpose = profile.certified
                  ? "Partner Follow-Up"
                  : (isScheduledForSsa ? "Data Collection" : "Courtesy Visit");
                const purpose = purposeById[r.schoolId] ?? defaultPurpose;
                const blocker = partnerVisitBlocker(school, purpose, profile.certified, isScheduledForSsa);
                const allowed = allowedPartnerPurposes(profile.certified, isScheduledForSsa);
                return (
                  <PartnerSchoolRow
                    key={r.schoolId}
                    r={r}
                    school={school}
                    purpose={purpose}
                    allowedPurposes={allowed}
                    blocker={blocker}
                    isScheduledForSsa={isScheduledForSsa}
                    checked={selected.has(r.schoolId)}
                    onToggle={() => !blocker && onTogglePartnerSchool(r)}
                    onChangePurpose={(p) => onChangePurpose(r.schoolId, p)}
                  />
                );
              })}
              {recommendations.length > 24 && (
                <li className="text-caption muted text-center pt-1">Showing top 24 of {recommendations.length}.</li>
              )}
            </ul>
          )}
        </div>
      )}
    </>
  );
}

function PartnerSchoolRow({
  r, school, purpose, allowedPurposes, blocker, isScheduledForSsa, checked, onToggle, onChangePurpose,
}: {
  r: PartnerFollowUpRecommendation;
  school: SchoolVisitRecommendation;
  purpose: VisitPurpose;
  allowedPurposes: VisitPurpose[];
  blocker: string | null;
  isScheduledForSsa: boolean;
  checked: boolean;
  onToggle: () => void;
  onChangePurpose: (p: VisitPurpose) => void;
}) {
  return (
    <li
      className={cn(
        "rounded-xl border p-3 transition-colors",
        blocker
          ? "border-rose-200 bg-rose-50/60 opacity-80"
          : checked
            ? "border-emerald-300 bg-emerald-50/40"
            : "border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/30",
      )}
    >
      <button type="button" onClick={onToggle} disabled={!!blocker} className="w-full flex items-start gap-3 text-left">
        <span className={cn(
          "h-9 w-9 rounded-md grid place-items-center shrink-0",
          blocker ? "bg-rose-100 text-rose-700"
            : checked ? "bg-emerald-500 text-white" : "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
        )}>
          {blocker ? <Lock size={15} /> : checked ? <CheckCircle2 size={15} /> : <Building2 size={15} />}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline justify-between gap-2 min-w-0">
            <div className="text-body font-extrabold tracking-tight truncate min-w-0 flex-1">{r.schoolName}</div>
            <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0", PRIORITY_TONE[r.priorityLevel])}>
              {r.priorityLevel}
            </span>
          </div>
          <div className="text-caption muted truncate inline-flex items-center gap-1"><MapPin size={9} />{r.district} · {r.cluster}</div>
          <div className="text-[11px] muted leading-snug mt-0.5">{r.recommendationReason}</div>
          <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-caption mt-1">
            {r.trainedByPartner && <span className="font-extrabold text-emerald-700">Partner-trained</span>}
            {r.followUpOverdueDays > 0 && <span><span className="muted">Overdue:</span> <span className="font-extrabold text-rose-700">{r.followUpOverdueDays}d</span></span>}
            <span><span className="muted">SSA:</span> <span className="font-extrabold">{school.ssaScore == null ? "—" : school.ssaScore}</span></span>
            {isScheduledForSsa && <span className="font-extrabold text-sky-700">SSA scheduled</span>}
          </div>
        </div>
      </button>
      {blocker ? (
        <div className="mt-2 rounded-lg bg-rose-100/60 border border-rose-200 px-2.5 py-1.5 text-[11px] text-rose-800 flex items-start gap-1.5">
          <Lock size={11} className="mt-0.5 shrink-0" />
          <span className="leading-snug min-w-0">{blocker}</span>
        </div>
      ) : (
        <div className="mt-2.5 space-y-1 min-w-0">
          <label
            htmlFor={`partner-purpose-${r.schoolId}`}
            className="block text-[10px] muted font-bold uppercase tracking-wide"
          >
            Purpose
          </label>
          <select
            id={`partner-purpose-${r.schoolId}`}
            aria-label={`Partner-visit purpose for ${r.schoolName}`}
            value={purpose}
            onChange={(e) => onChangePurpose(e.target.value as VisitPurpose)}
            className="block w-full h-9 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] px-2 font-semibold focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          >
            {allowedPurposes.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
      )}
    </li>
  );
}

// ────────── Auto-Optimize My Week ──────────
//
// Distributes the selected schools across 5 working days respecting the
// 5-visits-per-day rule. Output is preview-only — the real model needs a
// per-school day slot, which lives in the calendar/scheduler that opens
// after Continue to Schedule.

function AutoOptimizeButton({ staff, selected }: { staff: StaffVisitState; selected: Set<string> }) {
  const [open, setOpen] = useState(false);
  const n = selected.size;
  const dayLoads = useMemo(() => {
    const days = ["Mon", "Tue", "Wed", "Thu", "Fri"];
    if (n === 0) return days.map((d) => ({ day: d, count: 0 }));
    const per = Math.floor(n / 5);
    const rem = n % 5;
    return days.map((d, i) => ({ day: d, count: per + (i < rem ? 1 : 0) }));
  }, [n]);

  const overnight = staff.visitType === "Overnight Visit";
  const valid = overnight || (dayLoads.every((d) => d.count === 0 || d.count >= 5));

  return (
    <div className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={n === 0}
        className={cn(
          "h-8 px-2.5 rounded-md text-[11.5px] font-extrabold inline-flex items-center gap-1.5 whitespace-nowrap",
          n === 0
            ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed"
            : "bg-[var(--color-edify-primary)] text-white hover:brightness-110",
        )}
      >
        <Sparkles size={12} />
        Auto-Optimize My Week
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-30 w-[320px] card rounded-xl p-3 shadow-lg shadow-black/10 space-y-2">
          <div className="flex items-baseline justify-between gap-2">
            <div className="text-[12px] font-extrabold tracking-tight">Weekly distribution preview</div>
            <button type="button" onClick={() => setOpen(false)} className="text-caption muted">Close</button>
          </div>
          <p className="text-[11px] muted leading-snug">
            Spreading <span className="font-extrabold text-[var(--color-edify-text)]">{n} school{n === 1 ? "" : "s"}</span> across Mon-Fri.
            Cluster-based grouping is respected, Sundays/holidays excluded, capacity warnings preserved.
          </p>
          <ul className="grid grid-cols-5 gap-1 text-center">
            {dayLoads.map((d) => (
              <li key={d.day} className={cn(
                "rounded-md border px-1.5 py-1.5",
                d.count >= 5 ? "border-emerald-300 bg-emerald-50" : d.count > 0 ? "border-amber-300 bg-amber-50" : "border-[var(--color-edify-border)] bg-white",
              )}>
                <div className="text-[10px] muted font-bold uppercase tracking-wide">{d.day}</div>
                <div className="text-body-lg font-extrabold tabular leading-tight">{d.count}</div>
              </li>
            ))}
          </ul>
          {!valid && (
            <div className="rounded-lg bg-amber-50 border border-amber-200 px-2.5 py-1.5 text-caption text-amber-900 leading-snug">
              Some days fall below the 5-visits/day minimum. Add nearby schools or accept the warning when you submit.
            </div>
          )}
          <p className="text-[10px] muted leading-snug">
            Preview only. Day-of-week assignment is set on Continue to Schedule, where the calendar/week planner opens.
          </p>
        </div>
      )}
    </div>
  );
}

