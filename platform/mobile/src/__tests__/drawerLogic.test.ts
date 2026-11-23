import { create } from '@bufbuild/protobuf';

import { DrawerItemSchema, PageDrawerSchema } from '../gen/edify/screens/v1/drawer_pb';
import { DrawerConditionSchema, DrawerFieldSchema, DrawerOptionSchema } from '../gen/edify/screens/v1/form_pb';
import { PageFormItemSchema, PageFormSchema } from '../gen/edify/screens/v1/page_pb';
import {
  choicesFor,
  clearedBy,
  initialValues,
  isShown,
  asDrawer,
  missingField,
  ticked,
  withHiddenReset,
  withTicked,
  valuesToSend,
} from '../ui/drawerLogic';

const option = (value: string, label: string, group = '') => create(DrawerOptionSchema, { value, label, group });
const when = (field: string, ...values: string[]) => create(DrawerConditionSchema, { field, values });

const TYPE = create(DrawerFieldSchema, {
  name: 'school_type',
  kind: 'select',
  value: 'client',
  options: [option('client', 'Client'), option('core', 'Core')],
});
const COHORT = create(DrawerFieldSchema, {
  name: 'core_cohort_number',
  kind: 'number',
  value: '',
  showWhen: [when('school_type', 'core')],
});
const DISTRICT = create(DrawerFieldSchema, {
  name: 'district_id',
  kind: 'select',
  value: 'd1',
  reloadsPath: '/schools/sub-counties',
  reloadsTarget: 'sub_county_id',
});
const SUB_COUNTY = create(DrawerFieldSchema, {
  name: 'sub_county_id',
  kind: 'select',
  value: 'sc1',
  reloadsPath: '/schools/parishes',
  reloadsTarget: 'parish_id',
});
const PARISH = create(DrawerFieldSchema, {
  name: 'parish_id',
  kind: 'select',
  value: 'p1',
  groupBy: 'sub_county_id',
  options: [option('', 'Select a parish'), option('p1', 'Ddundu', 'sc1'), option('p2', 'Kiyunga', 'sc2')],
});

const DRAWER = create(PageDrawerSchema, {
  items: [TYPE, COHORT, DISTRICT, SUB_COUNTY, PARISH].map((field) =>
    create(DrawerItemSchema, { kind: { case: 'field', value: field } }),
  ),
});

describe('withHiddenReset', () => {
  it('puts a hidden field back to how the form opened', () => {
    const purpose = create(DrawerFieldSchema, { name: 'purpose', kind: 'select', value: '' });
    const course = create(DrawerFieldSchema, { name: 'course', kind: 'select', value: '', showWhen: [when('purpose', 'training')] });
    const focus = create(DrawerFieldSchema, { name: 'focus', kind: 'select', value: 'leadership', showWhen: [when('purpose', 'donor')] });
    const topic = create(DrawerFieldSchema, { name: 'topic', kind: 'select', value: '', showWhen: [when('course', 'c1')] });
    const drawer = create(PageDrawerSchema, {
      items: [purpose, course, focus, topic].map((field) => create(DrawerItemSchema, { kind: { case: 'field', value: field } })),
    });
    expect(withHiddenReset(drawer, { purpose: 'donor', course: 'c1', focus: 'enrolment', topic: 'x' })).toEqual({
      purpose: 'donor',
      course: '',
      focus: 'enrolment',
      topic: '',
    });
    expect(withHiddenReset(drawer, { purpose: 'training', course: 'c1', focus: 'enrolment', topic: 'x' })).toEqual({
      purpose: 'training',
      course: 'c1',
      focus: 'leadership',
      topic: 'x',
    });
  });
});

describe('isShown', () => {
  test('shows an item with no condition', () => {
    expect(isShown([], {})).toBe(true);
  });

  test('shows an item only while its field holds one of the values', () => {
    expect(isShown(COHORT.showWhen, { school_type: 'client' })).toBe(false);
    expect(isShown(COHORT.showWhen, { school_type: 'core' })).toBe(true);
  });
});

describe('choicesFor', () => {
  test("keeps only the choices that belong to the other field's value", () => {
    expect(choicesFor(PARISH, { sub_county_id: 'sc2' }, {}).map((o) => o.value)).toEqual(['', 'p2']);
  });

  test('takes reloaded choices over the ones the drawer opened with', () => {
    const reloaded = { parish_id: [option('', 'Select a parish'), option('p9', 'New Parish', 'sc9')] };

    expect(choicesFor(PARISH, { sub_county_id: 'sc9' }, reloaded).map((o) => o.label)).toEqual([
      'Select a parish',
      'New Parish',
    ]);
  });
});

describe('clearedBy', () => {
  test('a change clears the field it reloads and the fields tied to that one', () => {
    expect(clearedBy(DRAWER, 'district_id').sort()).toEqual(['parish_id', 'sub_county_id']);
    expect(clearedBy(DRAWER, 'sub_county_id')).toEqual(['parish_id']);
    expect(clearedBy(DRAWER, 'school_type')).toEqual([]);
  });
});

describe('valuesToSend', () => {
  test('sends the shown fields only, as the browser does with a hidden one', () => {
    const values = { ...initialValues(DRAWER), core_cohort_number: '3' };

    expect(valuesToSend(DRAWER, values)).toEqual({
      school_type: 'client',
      district_id: 'd1',
      sub_county_id: 'sc1',
      parish_id: 'p1',
    });
    expect(valuesToSend(DRAWER, { ...values, school_type: 'core' })).toHaveProperty('core_cohort_number', '3');
  });
});

const SUB_COUNTIES = create(DrawerFieldSchema, {
  name: 'sub_county_ids',
  label: 'Sub-counties',
  kind: 'checklist',
  value: '',
  required: true,
  groupBy: 'district_id',
  options: [option('s1', 'Goma', 'd1'), option('s2', 'Nama', 'd1'), option('s3', 'Kira', 'd2')],
});
const CLUSTER = create(PageDrawerSchema, {
  items: [DISTRICT, SUB_COUNTIES].map((field) => create(DrawerItemSchema, { kind: { case: 'field', value: field } })),
});

describe('checklists', () => {
  test('reads the ticked choices from the joined value', () => {
    expect(ticked('s1,s2')).toEqual(['s1', 's2']);
    expect(ticked('')).toEqual([]);
  });

  test('ticks and unticks one choice, keeping the order of the choices', () => {
    const choices = SUB_COUNTIES.options;
    expect(withTicked('s2', choices, ['s1'], true)).toBe('s1,s2');
    expect(withTicked('s1,s2', choices, ['s1'], false)).toBe('s2');
  });

  test('Select all ticks every choice that applies, and clears them', () => {
    const shown = choicesFor(SUB_COUNTIES, { district_id: 'd1' }, {});
    expect(withTicked('', shown, shown.map((choice) => choice.value), true)).toBe('s1,s2');
    expect(withTicked('s1,s2', shown, shown.map((choice) => choice.value), false)).toBe('');
  });

  test("a district's change clears its sub-counties", () => {
    expect(clearedBy(CLUSTER, 'district_id')).toContain('sub_county_ids');
  });
});

describe('missingField', () => {
  test('names a shown required field left empty, as the browser stops the save', () => {
    expect(missingField(CLUSTER, { district_id: 'd1', sub_county_ids: '' })).toBe('Sub-counties');
  });

  test('lets the save through once every required field holds a value', () => {
    expect(missingField(CLUSTER, { district_id: 'd1', sub_county_ids: 's1' })).toBe('');
  });

  test('does not ask for a required field that is hidden', () => {
    const hidden = create(DrawerFieldSchema, {
      name: 'core_cohort_number',
      label: 'Core cohort',
      kind: 'number',
      required: true,
      showWhen: [when('school_type', 'core')],
    });
    const drawer = create(PageDrawerSchema, {
      items: [TYPE, hidden].map((field) => create(DrawerItemSchema, { kind: { case: 'field', value: field } })),
    });
    expect(missingField(drawer, { school_type: 'client', core_cohort_number: '' })).toBe('');
    expect(missingField(drawer, { school_type: 'core', core_cohort_number: '' })).toBe('Core cohort');
  });
});

describe('asDrawer', () => {
  test("a page's own form is read as a drawer: its values, its required stop", () => {
    const subject = create(DrawerFieldSchema, { name: 'subject', label: 'Subject', kind: 'text', required: true });
    const form = create(PageFormSchema, {
      title: 'Escalate',
      submitLabel: 'Send',
      key: 'raise',
      items: [
        create(PageFormItemSchema, { kind: { case: 'heading', value: 'What needs deciding' } }),
        create(PageFormItemSchema, { kind: { case: 'field', value: subject } }),
      ],
    });

    const drawer = asDrawer(form);

    expect(drawer.submitLabel).toBe('Send');
    expect(drawer.canSubmit).toBe(true);
    expect(initialValues(drawer)).toEqual({ subject: '' });
    expect(missingField(drawer, { subject: '' })).toBe('Subject');
    expect(valuesToSend(drawer, { subject: 'Funding gap' })).toEqual({ subject: 'Funding gap' });
  });
});
