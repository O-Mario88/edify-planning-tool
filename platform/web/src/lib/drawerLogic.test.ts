import { describe, expect, it } from 'vitest';

import {
  addToProjectDrawer,
  addToProjectOf,
  choicesFor,
  clearedBy,
  drawerLinksOf,
  initialValues,
  isDrawerPath,
  isShown,
  missingField,
  planningDrawerOf,
  safeRedirect,
  schoolDrawerOf,
  ticked,
  valuesToSend,
  withHiddenReset,
  withTicked,
} from './drawerLogic';
import type { DrawerJson } from './drawerLogic';

describe('planningDrawerOf', () => {
  it('reads the school and the kind from a planning drawer path', () => {
    expect(planningDrawerOf('/planning/schedule-modal?school_id=1000')).toEqual({ school: '1000', kind: 'schedule' });
    expect(planningDrawerOf('/planning/assign-partner-modal?school_id=1546')).toEqual({ school: '1546', kind: 'assign' });
  });

  it('is nothing for any other path, or one with no school', () => {
    expect(planningDrawerOf('/planning/schedule-modal')).toBeNull();
    expect(planningDrawerOf('/core-schools/assign-partner?school_id=1546')).toBeNull();
  });
});

describe('addToProjectOf', () => {
  it('reads the school from an Add to Project path', () => {
    expect(addToProjectOf('/schools/cmw9/assign-to-project')).toBe('cmw9');
  });

  it('is nothing for another school action', () => {
    expect(addToProjectOf('/schools/cmw9/edit-drawer')).toBeNull();
    expect(addToProjectOf('/schools/cmw9/assign-to-project/extra')).toBeNull();
  });
});

describe('addToProjectDrawer', () => {
  const form = {
    title: 'Assign Hill Primary to project',
    projects: [
      { value: 'p1', label: 'Alumni' },
      { value: 'p2', label: 'Full Project', reason: 'This project has no places left.' },
    ],
    supportTypes: [{ value: 'staff', label: 'Staff-led support' }],
    coordinators: [{ value: 'u1', label: 'A Coordinator' }],
    focusAreas: [{ value: 'leadership', label: 'Leadership' }],
  };

  it('asks for a project and offers the form the gateway answered', () => {
    const out = addToProjectDrawer(form);
    expect(out.title).toBe('Assign Hill Primary to project');
    expect(out.submitLabel).toBe('Assign to project');
    expect(out.canSubmit).toBe(true);
    const names = (out.items ?? []).flatMap((item) => (item.field?.name ? [item.field.name] : []));
    expect(names).toEqual(['project_id', 'project_type', 'participation_type', 'coordinator_id', 'support_area', 'start_date', 'notes']);
    expect(out.items?.find((item) => item.field?.name === 'project_id')?.field?.required).toBe(true);
  });

  it('keeps a full project on the list, greyed with its reason', () => {
    const project = addToProjectDrawer(form).items?.find((item) => item.field?.name === 'project_id')?.field;
    const full = project?.options?.find((option) => option.value === 'p2');
    expect(full?.disabled).toBe(true);
    expect(full?.label).toContain('This project has no places left.');
  });

  it('cannot be submitted when no project can be chosen, and says why', () => {
    const out = addToProjectDrawer({ ...form, projects: [], emptyNotice: 'No project is open for enrolment.' });
    expect(out.canSubmit).toBe(false);
    expect(out.items?.[0]?.note?.text).toBe('No project is open for enrolment.');
  });
});

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

  it('puts a field back to how the form opened once it is hidden', () => {
    const conditional: DrawerJson = {
      items: [
        { field: { name: 'purpose', kind: 'select', value: '' } },
        { field: { name: 'course', kind: 'select', value: '', showWhen: [{ field: 'purpose', values: ['training'] }] } },
        { field: { name: 'focus', kind: 'select', value: 'leadership', showWhen: [{ field: 'purpose', values: ['donor'] }] } },
        { field: { name: 'topic', kind: 'select', value: '', showWhen: [{ field: 'course', values: ['c1'] }] } },
      ],
    };
    expect(withHiddenReset(conditional, { purpose: 'donor', course: 'c1', focus: 'enrolment', topic: 'x' })).toEqual({
      purpose: 'donor',
      course: '',
      focus: 'enrolment',
      topic: '',
    });
    expect(withHiddenReset(conditional, { purpose: 'training', course: 'c1', focus: 'enrolment', topic: 'x' })).toEqual({
      purpose: 'training',
      course: 'c1',
      focus: 'leadership',
      topic: 'x',
    });
  });

  it('reads the links a drawer offers, and a choice that cannot be taken', () => {
    const links = drawerLinksOf({
      block: { panel: { items: [{ links: { links: [{ text: 'Schedule', caption: 'Core visit', href: '/core-schools/schedule-visit?school_id=1', drawer: true }, { text: 'Schedule', caption: 'complete' }] } }] } },
    });
    expect(links).toHaveLength(2);
    expect(links[0]?.href).toBe('/core-schools/schedule-visit?school_id=1');
    expect(links[1]?.href).toBeUndefined();
    expect(drawerLinksOf({ text: 'plain' })).toEqual([]);
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
