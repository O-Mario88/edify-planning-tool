import { describe, expect, it } from 'vitest';

import {
  choicesFor,
  clearedBy,
  initialValues,
  isDrawerPath,
  isShown,
  missingField,
  safeRedirect,
  schoolDrawerOf,
  ticked,
  valuesToSend,
  withTicked,
} from './drawerLogic';
import type { DrawerJson } from './drawerLogic';

const drawer: DrawerJson = {
  items: [
    { field: { name: 'mode', value: 'visit', required: true, label: 'Mode' } },
    { field: { name: 'district', reloadsPath: '/schools/sub-counties', reloadsTarget: 'sub_county', value: 'd1' } },
    { field: { name: 'sub_county', value: 's1', label: 'Sub-county' } },
    { field: { name: 'parish', groupBy: 'sub_county', value: 'p1' } },
    { field: { name: 'reason', required: true, label: 'Reason', showWhen: [{ field: 'mode', values: ['cancel'] }] } },
    { field: { name: 'locked', required: true, readOnly: true, label: 'Locked' } },
  ],
};

describe('drawer logic', () => {
  it('reads the fields and their values', () => {
    expect(initialValues(drawer).district).toBe('d1');
  });

  it('shows a part only while its condition holds', () => {
    expect(isShown([{ field: 'mode', values: ['cancel'] }], { mode: 'visit' })).toBe(false);
    expect(isShown([{ field: 'mode', values: ['cancel'] }], { mode: 'cancel' })).toBe(true);
    expect(isShown(undefined, {})).toBe(true);
  });

  it('empties what a change reloads, and what hangs from that', () => {
    expect(clearedBy(drawer, 'district')).toEqual(['sub_county', 'parish']);
  });

  it('does not send a hidden field', () => {
    expect(valuesToSend(drawer, { mode: 'visit', reason: 'x' })).not.toHaveProperty('reason');
    expect(valuesToSend(drawer, { mode: 'cancel', reason: 'x' }).reason).toBe('x');
  });

  it('stops on a shown required field left empty, never on a hidden or read-only one', () => {
    expect(missingField(drawer, { mode: 'visit' })).toBe('');
    expect(missingField(drawer, { mode: 'cancel', reason: ' ' })).toBe('Reason');
    expect(missingField(drawer, { mode: '' })).toBe('Mode');
  });

  it('offers only the choices of the field it is grouped by', () => {
    const field = { name: 'parish', groupBy: 'sub_county', options: [{ value: '', label: 'Select' }, { value: 'a', group: 's1' }, { value: 'b', group: 's2' }] };
    expect(choicesFor(field, { sub_county: 's1' }, {}).map((choice) => choice.value)).toEqual(['', 'a']);
    expect(choicesFor(field, { sub_county: 's1' }, { parish: [{ value: 'z' }] }).map((choice) => choice.value)).toEqual(['z']);
  });

  it('keeps a checklist in the list order', () => {
    const choices = [{ value: 'a' }, { value: 'b' }, { value: 'c' }];
    expect(withTicked('c', choices, 'a', true)).toBe('a,c');
    expect(ticked(withTicked('a,c', choices, 'a', false))).toEqual(['c']);
  });

  it('sends a school’s own drawers to their service', () => {
    expect(schoolDrawerOf('/schools/s1/edit-drawer')).toEqual({ schoolId: 's1', kind: 'edit' });
    expect(schoolDrawerOf('/schools/1546/close-drawer')).toEqual({ schoolId: '1546', kind: 'close' });
    expect(schoolDrawerOf('/schools/s1/ssa-entry')).toEqual({ schoolId: 's1', kind: 'ssa-entry' });
    expect(schoolDrawerOf('/clusters/c1/edit-drawer')).toBeNull();
  });

  it('opens only this site’s own paths and redirects only within it', () => {
    expect(isDrawerPath('/schools/s1/edit-drawer')).toBe(true);
    expect(isDrawerPath('/core-schools/assign-partner?school_id=1546')).toBe(true);
    for (const bad of ['//evil.test/x', 'https://evil.test', '/a/../b', 'javascript:alert(1)']) expect(isDrawerPath(bad)).toBe(false);
    expect(safeRedirect('/my-plan')).toBe('/my-plan');
    for (const bad of ['//evil.test', 'https://evil.test', '/\\evil.test']) expect(safeRedirect(bad)).toBe('');
  });
});
