import { create } from '@bufbuild/protobuf';

import {
  DrawerConditionSchema,
  DrawerFieldSchema,
  DrawerItemSchema,
  DrawerOptionSchema,
  PageDrawerSchema,
} from '../gen/edify/screens/v1/drawer_pb';
import { choicesFor, clearedBy, initialValues, isShown, valuesToSend } from '../ui/drawerLogic';

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
