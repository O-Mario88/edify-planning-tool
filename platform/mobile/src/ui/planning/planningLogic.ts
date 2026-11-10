/**
 * What the web's planning drawers' scripts do, for the native drawers:
 * Schedule visit (templates/partials/planning/schedule_drawer.html) and
 * Assign to Partner (templates/partials/planning/assign_partner_drawer.html).
 * Which parts show for the purpose chosen, which purposes and trainings grey
 * for the date's financial year, what a change clears, and exactly what a
 * save posts — each rule follows the script's getter or method of the same
 * name. Pure, so it is tested without a device.
 */
import type {
  GetTrainingCapacityResponse,
  PlanningDrawer,
  PlanningTraining,
  PurposeProfile,
} from '../../gen/edify/screens/v1/planning_drawer_pb';

/** The drawer's choices, as the script's own state. */
export interface PlanningState {
  readonly purpose: string;
  /** Assign only. */
  readonly partner: string;
  /** The training (catalogue item) chosen. */
  readonly training: string;
  readonly intervention: string;
  /** The training a Follow Up follows up. */
  readonly source: string;
  readonly date: string;
  readonly participants: string;
  readonly deviation: string;
  readonly facilitator: string;
  readonly goal: string;
  readonly justification: string;
  readonly recommendationReason: string;
  readonly activityType: string;
}

export type Capacity = Pick<GetTrainingCapacityResponse, 'managed' | 'counted' | 'remaining'>;

const TRAINING_PURPOSES = ['in_school_training', 'in_school_training_ssa'];
const FOLLOW_UP = 'training_follow_up';
const SSA_SUPPORT = 'ssa_support';
/** October starts the next financial year. */
const FY_FIRST_MONTH = 10;

/** The script's `fyOf`: "2026-11-20" → "2027". */
export function fyOf(date: string): string {
  if (!date) {
    return '';
  }
  const [year, month] = date.split('-').map(Number);
  return String(month >= FY_FIRST_MONTH ? year + 1 : year);
}

/** Why a purpose is greyed for the date chosen, or ''. */
export function lockFor(drawer: PlanningDrawer, purpose: string, date: string): string {
  const years = drawer.visitLocks[purpose]?.byYear ?? {};
  const year = fyOf(date);
  if (year) {
    return years[year] ?? '';
  }
  return drawer.purposesLockedEveryYear.includes(purpose) ? (Object.values(years)[0] ?? '') : '';
}

/** The trainings the Training list offers. */
export function trainingsFor(drawer: PlanningDrawer, state: PlanningState): readonly PlanningTraining[] {
  if (drawer.kind === 'assign') {
    const codes = drawer.partnerCourses[state.partner]?.codes;
    return codes ? drawer.trainings.filter((training) => codes.includes(training.stableCode)) : drawer.trainings;
  }
  // This drawer schedules staff work (executorType 'staff').
  return drawer.trainings.filter((training) => training.staffDeliveryAllowed);
}

function selectedTraining(drawer: PlanningDrawer, state: PlanningState): PlanningTraining | undefined {
  return trainingsFor(drawer, state).find((training) => training.id === state.training);
}

const NO_PROFILE = { requiresParticipants: false, schedulable: true, unavailableReason: '' };

function profileOf(drawer: PlanningDrawer, purpose: string): Pick<PurposeProfile, keyof typeof NO_PROFILE> {
  return drawer.profiles[purpose] ?? NO_PROFILE;
}

// ── Schedule visit ─────────────────────────────────────────────────────────
/** `onTrainingActivityChange`: a course suggests its intervention and its reason. */
function withTrainingChosen(drawer: PlanningDrawer, state: PlanningState, keepChoice: boolean): PlanningState {
  const selected = selectedTraining(drawer, state);
  const suggested = selected ? selected.ssaIntervention : '';
  const intervention = suggested || !keepChoice || !state.intervention ? suggested : state.intervention;
  if (!selected) {
    return { ...state, intervention };
  }
  const recommendationReason = selected.priorityTitles.length
    ? `Priority activity: ${selected.priorityTitles.join(', ')}`
    : `Governed ${selected.category} training.`;
  return { ...state, intervention, recommendationReason };
}

/** `ensureTrainingActivity`: a training the list no longer offers is dropped. */
function withTrainingKept(drawer: PlanningDrawer, state: PlanningState): PlanningState {
  const isOffered = trainingsFor(drawer, state).some((training) => training.id === state.training);
  return withTrainingChosen(drawer, isOffered ? state : { ...state, training: '' }, true);
}

export function initialState(drawer: PlanningDrawer): PlanningState {
  const state: PlanningState = {
    purpose: drawer.initialPurpose,
    partner: '',
    training: drawer.kind === 'schedule' ? drawer.initialTraining : '',
    intervention: drawer.kind === 'schedule' ? drawer.initialIntervention : '',
    source: '',
    date: '',
    participants: '',
    deviation: '',
    facilitator: '',
    goal: '',
    justification: '',
    recommendationReason: drawer.recommendationReason,
    activityType: drawer.kind === 'schedule' ? drawer.activityType : '',
  };
  // The schedule drawer's x-init runs ensureTrainingActivity() once.
  return drawer.kind === 'schedule' ? withTrainingKept(drawer, state) : state;
}

/** `onPurposeChange`: what no longer has a field is cleared. */
export function changePurpose(drawer: PlanningDrawer, state: PlanningState, purpose: string): PlanningState {
  let next: PlanningState = { ...state, purpose };
  if (!profileOf(drawer, purpose).requiresParticipants) {
    next = { ...next, participants: '' };
  }
  next = TRAINING_PURPOSES.includes(purpose) ? withTrainingKept(drawer, next) : { ...next, training: '' };
  if (purpose !== FOLLOW_UP) {
    next = { ...next, source: '' };
  }
  if (purpose === SSA_SUPPORT || (purpose === FOLLOW_UP && drawer.followUpRequiresTraining)) {
    next = { ...next, intervention: '' };
  }
  return next;
}

/** A training picked from the list: a fresh course is a fresh suggestion. */
export function chooseTraining(drawer: PlanningDrawer, state: PlanningState, training: string): PlanningState {
  return withTrainingChosen(drawer, { ...state, training }, false);
}

/** What the drawer shows for the choices made. */
export interface ScheduleParts {
  readonly showTrainingPicker: boolean;
  readonly showFollowUp: boolean;
  readonly showSsaDataGathering: boolean;
  readonly showLinkedIntervention: boolean;
  readonly showManualIntervention: boolean;
  readonly showParticipants: boolean;
  readonly ssaDeviation: boolean;
  readonly selected: PlanningTraining | undefined;
  readonly selectedFollowUpLabel: string;
  /** Why the purpose cannot be priced, or ''. */
  readonly unavailableReason: string;
  /** Each greyed purpose's reason for the date, said under the list. */
  readonly visitLockReasons: readonly string[];
  readonly followUpBlocked: boolean;
  readonly trainingLockReason: string;
  /** The trainings greyed in the list. */
  readonly heldTrainings: readonly string[];
  readonly universalTrainingNames: string;
  readonly trainingBlocked: boolean;
  readonly trainingCeilingFull: boolean;
}

/** `trainingCeilingFull`. */
export function ceilingFull(drawer: PlanningDrawer, state: PlanningState, capacity: Capacity | undefined): boolean {
  return (
    TRAINING_PURPOSES.includes(state.purpose) &&
    Boolean(state.training) &&
    capacity !== undefined &&
    capacity.managed &&
    !capacity.counted &&
    (capacity.remaining ?? 0) <= 0
  );
}

export function scheduleParts(drawer: PlanningDrawer, state: PlanningState, capacity: Capacity | undefined): ScheduleParts {
  const showTrainingPicker = TRAINING_PURPOSES.includes(state.purpose);
  const showFollowUp = state.purpose === FOLLOW_UP;
  const showSsaDataGathering = state.purpose === SSA_SUPPORT;
  const followUpWithoutSource = showFollowUp && !drawer.followUpRequiresTraining && !state.source;
  const selected = selectedTraining(drawer, state);
  const showLinkedIntervention = showTrainingPicker && !(selected && selected.plannerChooses);
  const priorities = drawer.ssaPriorities;
  const year = fyOf(state.date);
  const trainingLockReason = !showTrainingPicker
    ? ''
    : year
      ? (drawer.trainingLocks[year] ?? '')
      : drawer.trainingLockedEveryYear
        ? (Object.values(drawer.trainingLocks)[0] ?? '')
        : '';
  const offered = trainingsFor(drawer, state);
  const profile = profileOf(drawer, state.purpose);
  return {
    showTrainingPicker,
    showFollowUp,
    showSsaDataGathering,
    showLinkedIntervention,
    showManualIntervention:
      !showSsaDataGathering && (!showFollowUp || followUpWithoutSource) && !showLinkedIntervention,
    showParticipants: profile.requiresParticipants === true,
    ssaDeviation:
      priorities.length > 0 &&
      !showSsaDataGathering &&
      !(showFollowUp && state.source) &&
      (!state.intervention || !priorities.includes(state.intervention)),
    selected,
    selectedFollowUpLabel: drawer.followUps.find((item) => item.id === state.source)?.interventionLabel ?? '',
    unavailableReason: state.purpose && profile.schedulable === false ? profile.unavailableReason : '',
    visitLockReasons: [
      ...new Set(Object.keys(drawer.visitLocks).map((purpose) => lockFor(drawer, purpose, state.date)).filter(Boolean)),
    ],
    followUpBlocked: Boolean(lockFor(drawer, state.purpose, state.date)),
    trainingLockReason,
    heldTrainings: trainingLockReason ? offered.filter((training) => !training.universal).map((training) => training.id) : [],
    universalTrainingNames: offered
      .filter((training) => training.universal)
      .map((training) => training.label)
      .join(', '),
    trainingBlocked: Boolean(trainingLockReason) && selected !== undefined && !selected.universal,
    trainingCeilingFull: ceilingFull(drawer, state, capacity),
  };
}

/** The submit button's `:disabled`. */
export function scheduleBlocked(parts: ScheduleParts): boolean {
  return parts.followUpBlocked || parts.trainingBlocked || parts.trainingCeilingFull;
}

/** Exactly what the schedule form posts besides its rendered hidden values:
 * a field the script has removed (x-if) or disabled is not sent. */
export function scheduleValues(drawer: PlanningDrawer, state: PlanningState, parts: ScheduleParts): Record<string, string> {
  const sent: Record<string, string> = {
    purpose_of_visit: state.purpose,
    activity_type: state.activityType,
    recommendation_reason: state.recommendationReason,
    scheduled_date: state.date,
    executor_type: 'staff',
    delivery_type: 'staff',
    activity_purpose_text: state.goal,
  };
  if (parts.showTrainingPicker) {
    sent.catalogue_item_id = state.training;
    sent.facilitating_partner_id = state.facilitator;
  } else if (drawer.defaultCatalogueItem) {
    sent.catalogue_item_id = drawer.defaultCatalogueItem;
  }
  if (parts.showManualIntervention) {
    sent.focus_intervention = state.intervention;
  }
  if (parts.ssaDeviation) {
    sent.ssa_deviation_reason = state.deviation;
  }
  if (parts.showFollowUp) {
    sent.source_activity_id = state.source;
  }
  if (parts.showParticipants) {
    sent.expected_participants = state.participants;
  }
  if (drawer.hasJustification) {
    sent.visit_justification = state.justification;
  }
  return sent;
}

// ── Assign to Partner ──────────────────────────────────────────────────────
/** `onPurposeChange`: a new reason starts its own choices afresh. */
export function changeAssignPurpose(state: PlanningState, purpose: string): PlanningState {
  return { ...state, purpose, training: '', activityType: '', intervention: '', source: '' };
}

/** `onPartnerChange`: a training the new partner does not deliver is dropped. */
export function changeAssignPartner(drawer: PlanningDrawer, state: PlanningState, partner: string): PlanningState {
  const next = { ...state, partner };
  if (next.purpose === 'in_school_training' && !selectedTraining(drawer, next)) {
    return { ...next, training: '', activityType: '' };
  }
  return next;
}

/** `selectTraining`: the training fills the hidden catalogue item, activity
 * type and intervention. */
export function chooseAssignTraining(drawer: PlanningDrawer, state: PlanningState, training: string): PlanningState {
  const item = drawer.trainings.find((option) => option.id === training);
  return {
    ...state,
    training,
    activityType: item ? 'in_school_training' : '',
    intervention: item ? item.ssaIntervention : '',
  };
}

export function assignValues(state: PlanningState): Record<string, string> {
  const sent: Record<string, string> = {
    partner_id: state.partner,
    purpose_of_visit: state.purpose,
    catalogue_item_id: state.training,
    activity_type: state.activityType,
    focus_intervention: state.intervention,
  };
  if (state.purpose === FOLLOW_UP) {
    sent.source_activity_id = state.source;
  }
  return sent;
}

// ── The browser's own check before a post ─────────────────────────────────
/** A field a required control names: the browser refuses to post the form
 * while one is empty, and points at the first. */
export type RequiredField = 'partner' | 'purpose' | 'training' | 'source' | 'date' | 'justification';

/** A real calendar day written as the date field writes it. */
function isDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }
  const day = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(day.getTime()) && day.toISOString().slice(0, 10) === value;
}

/** The first required field left empty, in the form's order, or ''. */
export function missingField(
  drawer: PlanningDrawer,
  state: PlanningState,
  parts: ScheduleParts | undefined,
): RequiredField | '' {
  if (drawer.kind === 'assign') {
    if (!state.partner) return 'partner';
    if (!state.purpose) return 'purpose';
    if (state.purpose === 'in_school_training' && !state.training) return 'training';
    if (state.purpose === FOLLOW_UP && drawer.followUpRequiresTraining && !state.source) return 'source';
    return '';
  }
  if (!state.purpose) return 'purpose';
  if (parts?.showTrainingPicker && !state.training) return 'training';
  if (parts?.showFollowUp && drawer.followUpRequiresTraining && !state.source) return 'source';
  if (!isDay(state.date)) return 'date';
  if (drawer.hasJustification && !state.justification.trim()) return 'justification';
  return '';
}
