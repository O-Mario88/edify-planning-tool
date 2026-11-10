import { create } from '@bufbuild/protobuf';

import {
  CodeListSchema,
  PlanningDrawerSchema,
  PlanningFollowUpSchema,
  PlanningTrainingSchema,
  PurposeProfileSchema,
  YearReasonsSchema,
} from '../gen/edify/screens/v1/planning_drawer_pb';
import {
  assignValues,
  ceilingFull,
  changeAssignPartner,
  changeAssignPurpose,
  changePurpose,
  chooseAssignTraining,
  chooseTraining,
  fyOf,
  initialState,
  lockFor,
  missingField,
  scheduleBlocked,
  scheduleParts,
  scheduleValues,
  trainingsFor,
} from '../ui/planning/planningLogic';

const ACCOUNTING = create(PlanningTrainingSchema, {
  id: 't-acc',
  label: 'Accounting',
  stableCode: 'ACC',
  category: 'Business Transformation',
  ssaIntervention: 'financial_health',
  staffDeliveryAllowed: true,
  priorityTitles: ['Accountants Training'],
});
const LEADERSHIP = create(PlanningTrainingSchema, {
  id: 't-lead',
  label: 'Leadership',
  stableCode: 'LEAD',
  category: 'Leadership',
  ssaIntervention: '',
  plannerChooses: true,
  staffDeliveryAllowed: true,
});
const UNIVERSAL = create(PlanningTrainingSchema, {
  id: 't-uni',
  label: 'School Improvement',
  stableCode: 'UNI',
  category: 'Universal',
  ssaIntervention: 'leadership',
  universal: true,
  staffDeliveryAllowed: true,
});
const AGENCY_ONLY = create(PlanningTrainingSchema, { id: 't-agency', label: 'Agency', staffDeliveryAllowed: false });

const SCHEDULE = create(PlanningDrawerSchema, {
  kind: 'schedule',
  initialPurpose: 'ssa_support',
  initialTraining: 't-acc',
  defaultCatalogueItem: 'cat-default',
  initialIntervention: 'financial_health',
  activityType: 'school_visit',
  recommendationReason: 'Financial Health is Critical at 4.6/10.',
  ssaPriorities: ['financial_health', 'learning_environment'],
  trainings: [ACCOUNTING, LEADERSHIP, UNIVERSAL, AGENCY_ONLY],
  followUps: [create(PlanningFollowUpSchema, { id: 'a1', label: 'Accounting · 3 Oct', interventionLabel: 'Financial Health' })],
  followUpRequiresTraining: true,
  profiles: {
    donor_visit: create(PurposeProfileSchema, { schedulable: true }),
    social_visit: create(PurposeProfileSchema, { schedulable: false, unavailableReason: 'Not priced.' }),
    in_school_training: create(PurposeProfileSchema, { schedulable: true, requiresParticipants: true }),
  },
  visitLocks: { training_follow_up: create(YearReasonsSchema, { byYear: { '2027': 'Its support visit is used.' } }) },
  purposesLockedEveryYear: [],
  trainingLocks: { '2027': 'Its training is used.' },
  hasJustification: true,
  hidden: { school_id: '1286', require_catalogue: 'yes' },
});

describe('fyOf', () => {
  test('a date from October belongs to the next financial year', () => {
    expect(fyOf('2026-10-01')).toBe('2027');
    expect(fyOf('2027-09-30')).toBe('2027');
    expect(fyOf('')).toBe('');
  });
});

describe('lockFor', () => {
  test("greys a purpose for a date in a year its visit is used, not another year", () => {
    expect(lockFor(SCHEDULE, 'training_follow_up', '2026-11-20')).toBe('Its support visit is used.');
    expect(lockFor(SCHEDULE, 'training_follow_up', '2027-11-20')).toBe('');
  });

  test('without a date, only a purpose used in every open year is greyed', () => {
    expect(lockFor(SCHEDULE, 'training_follow_up', '')).toBe('');
    const everyYear = create(PlanningDrawerSchema, { ...SCHEDULE, purposesLockedEveryYear: ['training_follow_up'] });
    expect(lockFor(everyYear, 'training_follow_up', '')).toBe('Its support visit is used.');
  });
});

describe('schedule drawer', () => {
  test('opens on the recommended purpose with the recommended training kept for the post', () => {
    const state = initialState(SCHEDULE);

    expect(state.purpose).toBe('ssa_support');
    expect(state.training).toBe('t-acc');
    expect(state.intervention).toBe('financial_health');
  });

  test('SSA Support shows Data Gathering and posts the default catalogue item, no intervention', () => {
    const state = changePurpose(SCHEDULE, initialState(SCHEDULE), 'ssa_support');
    const parts = scheduleParts(SCHEDULE, state, undefined);

    expect(parts.showSsaDataGathering).toBe(true);
    expect(parts.showManualIntervention).toBe(false);
    expect(parts.ssaDeviation).toBe(false);
    const sent = scheduleValues(SCHEDULE, { ...state, date: '2026-11-20' }, parts);
    expect(sent.catalogue_item_id).toBe('cat-default');
    expect(sent).not.toHaveProperty('focus_intervention');
    expect(sent.scheduled_date).toBe('2026-11-20');
    expect(sent.executor_type).toBe('staff');
    expect(sent.delivery_type).toBe('staff');
  });

  test('In-school Training lists only staff-delivered trainings and takes the intervention from the course', () => {
    let state = changePurpose(SCHEDULE, initialState(SCHEDULE), 'in_school_training');
    state = chooseTraining(SCHEDULE, state, 't-acc');
    const parts = scheduleParts(SCHEDULE, state, undefined);

    expect(trainingsFor(SCHEDULE, state).map((t) => t.id)).toEqual(['t-acc', 't-lead', 't-uni']);
    expect(parts.showLinkedIntervention).toBe(true);
    expect(parts.showManualIntervention).toBe(false);
    expect(parts.showParticipants).toBe(true);
    expect(state.recommendationReason).toBe('Priority activity: Accountants Training');
    const sent = scheduleValues(SCHEDULE, state, parts);
    expect(sent.catalogue_item_id).toBe('t-acc');
    expect(sent).not.toHaveProperty('focus_intervention');
    expect(sent).toHaveProperty('facilitating_partner_id', '');
  });

  test('a training the catalogue leaves open lets the planner name the intervention', () => {
    let state = changePurpose(SCHEDULE, initialState(SCHEDULE), 'in_school_training');
    state = chooseTraining(SCHEDULE, state, 't-lead');
    const parts = scheduleParts(SCHEDULE, state, undefined);

    expect(parts.showManualIntervention).toBe(true);
    expect(state.intervention).toBe('');
    expect(state.recommendationReason).toBe('Governed Leadership training.');
    expect(parts.ssaDeviation).toBe(true);
  });

  test("after the year's training is used only the universal training can be scheduled", () => {
    let state = changePurpose(SCHEDULE, { ...initialState(SCHEDULE), date: '2026-11-20' }, 'in_school_training');
    state = chooseTraining(SCHEDULE, state, 't-acc');
    const parts = scheduleParts(SCHEDULE, state, undefined);

    expect(parts.trainingLockReason).toBe('Its training is used.');
    expect(parts.heldTrainings).toEqual(['t-acc', 't-lead']);
    expect(scheduleBlocked(parts)).toBe(true);
    const universal = chooseTraining(SCHEDULE, state, 't-uni');
    expect(scheduleBlocked(scheduleParts(SCHEDULE, universal, undefined))).toBe(false);
  });

  test('a Follow Up for a date in a used year is blocked, and its training is required', () => {
    const state = changePurpose(SCHEDULE, { ...initialState(SCHEDULE), date: '2026-11-20' }, 'training_follow_up');
    const parts = scheduleParts(SCHEDULE, state, undefined);

    expect(state.intervention).toBe('');
    expect(state.training).toBe('');
    expect(parts.showFollowUp).toBe(true);
    expect(parts.followUpBlocked).toBe(true);
    expect(scheduleBlocked(parts)).toBe(true);
    expect(parts.showManualIntervention).toBe(false);
  });

  test('a purpose that cannot be priced says why', () => {
    const state = changePurpose(SCHEDULE, initialState(SCHEDULE), 'social_visit');

    expect(scheduleParts(SCHEDULE, state, undefined).unavailableReason).toBe('Not priced.');
  });

  test('a focus outside the SSA priorities asks why, and only then is the reason sent', () => {
    const base = changePurpose(SCHEDULE, initialState(SCHEDULE), 'donor_visit');
    const aligned = { ...base, intervention: 'financial_health', deviation: 'typed earlier' };
    const departing = { ...base, intervention: 'enrolment', deviation: 'Donor asked.' };

    expect(scheduleValues(SCHEDULE, aligned, scheduleParts(SCHEDULE, aligned, undefined))).not.toHaveProperty(
      'ssa_deviation_reason',
    );
    expect(scheduleValues(SCHEDULE, departing, scheduleParts(SCHEDULE, departing, undefined))).toHaveProperty(
      'ssa_deviation_reason',
      'Donor asked.',
    );
  });

  test('the ceiling is full only for a counted, managed training with no place left', () => {
    const state = chooseTraining(SCHEDULE, changePurpose(SCHEDULE, initialState(SCHEDULE), 'in_school_training'), 't-uni');

    expect(ceilingFull(SCHEDULE, state, { managed: true, counted: false, remaining: 0 })).toBe(true);
    expect(ceilingFull(SCHEDULE, state, { managed: true, counted: true, remaining: 0 })).toBe(false);
    expect(ceilingFull(SCHEDULE, state, { managed: false, counted: false, remaining: 0 })).toBe(false);
  });

  test('the justification is sent when the drawer asks for it', () => {
    const state = { ...initialState(SCHEDULE), justification: 'I am nearby.' };

    expect(scheduleValues(SCHEDULE, state, scheduleParts(SCHEDULE, state, undefined)).visit_justification).toBe(
      'I am nearby.',
    );
  });
});

const ASSIGN = create(PlanningDrawerSchema, {
  kind: 'assign',
  trainings: [ACCOUNTING, LEADERSHIP],
  partnerCourses: { p1: create(CodeListSchema, { codes: ['LEAD'] }) },
  followUps: [],
});

describe('assign drawer', () => {
  test("a partner's recorded courses narrow the training list", () => {
    const state = { ...initialState(ASSIGN), partner: 'p1', purpose: 'in_school_training' };

    expect(trainingsFor(ASSIGN, state).map((t) => t.id)).toEqual(['t-lead']);
    expect(trainingsFor(ASSIGN, { ...state, partner: 'p2' }).map((t) => t.id)).toEqual(['t-acc', 't-lead']);
  });

  test('choosing a training fills the hidden catalogue item, activity type and intervention', () => {
    let state = changeAssignPurpose({ ...initialState(ASSIGN), partner: 'p2' }, 'in_school_training');
    state = chooseAssignTraining(ASSIGN, state, 't-acc');

    expect(assignValues(state)).toEqual({
      partner_id: 'p2',
      purpose_of_visit: 'in_school_training',
      catalogue_item_id: 't-acc',
      activity_type: 'in_school_training',
      focus_intervention: 'financial_health',
    });
  });

  test("switching to a partner that does not deliver the chosen training clears it", () => {
    let state = changeAssignPurpose({ ...initialState(ASSIGN), partner: 'p2' }, 'in_school_training');
    state = chooseAssignTraining(ASSIGN, state, 't-acc');
    state = changeAssignPartner(ASSIGN, state, 'p1');

    expect(state.training).toBe('');
    expect(state.activityType).toBe('');
  });

  test('changing the reason clears what the last one chose; a Follow Up sends its training', () => {
    let state = chooseAssignTraining(ASSIGN, { ...initialState(ASSIGN), purpose: 'in_school_training' }, 't-acc');
    state = changeAssignPurpose(state, 'training_follow_up');
    state = { ...state, source: 'a1' };

    expect(assignValues(state)).toEqual({
      partner_id: '',
      purpose_of_visit: 'training_follow_up',
      catalogue_item_id: '',
      activity_type: '',
      focus_intervention: '',
      source_activity_id: 'a1',
    });
  });
});

describe('missingField', () => {
  test("names the first required field left empty, as the browser stops the form", () => {
    const assign = { ...initialState(ASSIGN) };

    expect(missingField(ASSIGN, assign, undefined)).toBe('partner');
    expect(missingField(ASSIGN, { ...assign, partner: 'p2' }, undefined)).toBe('purpose');
    expect(missingField(ASSIGN, { ...assign, partner: 'p2', purpose: 'in_school_training' }, undefined)).toBe('training');
    expect(missingField(ASSIGN, { ...assign, partner: 'p2', purpose: 'ssa_support' }, undefined)).toBe('');
  });

  test('a schedule needs a purpose, a real date and the justification it asks for', () => {
    const state = { ...changePurpose(SCHEDULE, initialState(SCHEDULE), 'donor_visit'), justification: 'Nearby.' };
    const parts = (next: typeof state) => scheduleParts(SCHEDULE, next, undefined);

    expect(missingField(SCHEDULE, state, parts(state))).toBe('date');
    const badDate = { ...state, date: '2026-02-30' };
    expect(missingField(SCHEDULE, badDate, parts(badDate))).toBe('date');
    const ready = { ...state, date: '2026-11-24' };
    expect(missingField(SCHEDULE, ready, parts(ready))).toBe('');
    const noReason = { ...ready, justification: ' ' };
    expect(missingField(SCHEDULE, noReason, parts(noReason))).toBe('justification');
  });

  test('a Follow Up needs its training only when the drawer requires one', () => {
    const state = { ...changePurpose(SCHEDULE, initialState(SCHEDULE), 'training_follow_up'), date: '2027-11-24', justification: 'x' };

    expect(missingField(SCHEDULE, state, scheduleParts(SCHEDULE, state, undefined))).toBe('source');
  });
});
