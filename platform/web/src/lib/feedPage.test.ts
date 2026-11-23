import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { PageActionSchema, PageColumnSchema, PageRowSchema } from '@/gen/edify/screens/v1/page_pb';

import { actionHref,
  drawerFromHash, drawerPageHref, isHeadingRow, pageQuery, queryString, resolveHref, splitActions } from './feedPage';

describe('pageQuery', () => {
  it('keeps the first value of each key and drops empty values and path', () => {
    expect(pageQuery({ tab: ['core', 'client'], q: '', path: '/admin', fy: '2027', missing: undefined })).toEqual({ tab: 'core', fy: '2027' });
  });

  it('bounds long values and refuses overlong keys', () => {
    const query = pageQuery({ q: 'x'.repeat(2000), ['k'.repeat(65)]: '1' });
    expect(query.q).toHaveLength(512);
    expect(Object.keys(query)).toEqual(['q']);
  });
});

describe('resolveHref', () => {
  it('puts a bare query on the page’s own path', () => {
    expect(resolveHref('/my-plan', '?period=week')).toBe('/my-plan?period=week');
  });

  it('keeps web paths and fragments', () => {
    expect(resolveHref('/planning', '/schools/abc')).toBe('/schools/abc');
    expect(resolveHref('/my-plan', '?list=staff_queue#plan-list')).toBe('/my-plan?list=staff_queue#plan-list');
    expect(resolveHref('/my-plan', '#plan-list')).toBe('#plan-list');
  });

  it('refuses anything that leaves the site', () => {
    for (const href of ['https://evil.example', '//evil.example', '/\\evil', 'javascript:alert(1)', '']) {
      expect(resolveHref('/planning', href)).toBe('');
    }
  });
});

describe('links to the existing web', () => {
  it('opens a drawer on the same page of the existing web, with the page’s query', () => {
    expect(drawerPageHref('http://localhost:8185', '/planning', { tab: 'core', fy: '2027' })).toBe('http://localhost:8185/planning?tab=core&fy=2027');
    expect(queryString({})).toBe('');
  });

  it('sends a drawer action there and a plain link to its page here', () => {
    const drawer = create(PageActionSchema, { label: 'Schedule', href: '/planning/schedule-modal?school_id=1650', drawer: true, enabled: true });
    const link = create(PageActionSchema, { label: 'Open Calendar', href: '/calendar', enabled: true });
    const href = actionHref(drawer, '/planning', 'http://x/planning');
    expect(href).toBe('http://x/planning#drawer=%2Fplanning%2Fschedule-modal%3Fschool_id%3D1650');
    expect(drawerFromHash(href)).toEqual({ path: '/planning/schedule-modal?school_id=1650', fallback: 'http://x/planning' });
    expect(drawerFromHash('/planning#drawer=%2Fplanning%2Fx')).toEqual({ path: '/planning/x', fallback: '' });
    expect(drawerFromHash('/planning#drawer=https%3A%2F%2Fevil.test')).toBeNull();
    expect(actionHref(link, '/my-plan', 'http://x/my-plan')).toBe('/calendar');
  });
});

describe('rows', () => {
  const columns = ['ID', 'School Name', 'Cluster'].map((label) => create(PageColumnSchema, { label }));

  it('reads a one-cell row in a wider table as a group heading', () => {
    expect(isHeadingRow(create(PageRowSchema, { cells: [{ text: 'Program Lead 1 · Paul N. 75 schools' }] }), columns)).toBe(true);
  });

  it('does not read a school row or a tickable row as a heading', () => {
    expect(isHeadingRow(create(PageRowSchema, { cells: [{ text: '1650' }, { text: 'Kasawo' }] }), columns)).toBe(false);
    expect(isHeadingRow(create(PageRowSchema, { cells: [{ text: 'x' }], pickId: '1650' }), columns)).toBe(false);
    expect(isHeadingRow(create(PageRowSchema, { cells: [{ text: 'Your visits' }] }), [columns[0]!])).toBe(false);
  });

  it('splits a row’s buttons from its menu items', () => {
    const actions = ['button', 'menu', 'danger'].map((key) => create(PageActionSchema, { key, label: key }));
    const { buttons, menu } = splitActions(actions);
    expect(buttons.map((a) => a.key)).toEqual(['button']);
    expect(menu.map((a) => a.key)).toEqual(['menu', 'danger']);
  });
});
