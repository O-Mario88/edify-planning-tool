import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { GetHomeResponseSchema, HomeFigureSchema } from '@/gen/edify/screens/v1/home_pb';

import { heroFirst, homeDate, homeFigures, homeHeader, homeTone } from './homeScreen';

const figure = (key: string, over: Partial<{ value: string; tone: string; loading: boolean }> = {}) =>
  create(HomeFigureSchema, { key, label: key.toUpperCase(), url: '/todos', description: `${key} described`, ...over });

describe('homeFigures', () => {
  it('fills a figure still to come with the queue’s value and tone, by key', () => {
    const cards = homeFigures(
      [figure('waiting_me', { loading: true, tone: 'plain' }), figure('critical', { loading: true, tone: 'plain' })],
      [figure('waiting_me', { value: '4', tone: 'caution' })],
    );
    expect(cards.map((c) => [c.key, c.value, c.tone, c.loading, c.url])).toEqual([
      ['waiting_me', '4', 'caution', false, '/todos'],
      ['critical', '', 'plain', true, '/todos'],
    ]);
    expect(cards[0]?.description).toBe('waiting_me described');
  });

  it('keeps a figure that came with its own value', () => {
    expect(homeFigures([figure('schools', { value: '12', tone: 'good' })], [])[0]).toMatchObject({ value: '12', tone: 'good', loading: false });
  });
});

describe('heroFirst', () => {
  const cards = homeFigures([figure('upcoming'), figure('under_way'), figure('overdue'), figure('waiting_me')], []);

  it('puts a CCEO’s two hero figures, Overdue and Waiting on you, first and marks them (owner, 2026-11-20)', () => {
    const shown = heroFirst(cards, 'CCEO');
    expect(shown.map((c) => [c.key, c.hero])).toEqual([
      ['overdue', true],
      ['waiting_me', true],
      ['upcoming', false],
      ['under_way', false],
    ]);
  });

  it('gives every role with its own plan the same two, Overdue and To-Do (the partners)', () => {
    expect(heroFirst(cards, 'Partner').map((c) => [c.key, c.hero])).toEqual([
      ['overdue', true],
      ['waiting_me', true],
      ['upcoming', false],
      ['under_way', false],
    ]);
  });

  it('leads a desk role with Critical and To-Do (the Country Director, IA, the Accountant)', () => {
    const desk = homeFigures([figure('waiting_me'), figure('due_today'), figure('critical')], []);
    expect(heroFirst(desk, 'Country Director').map((c) => [c.key, c.hero])).toEqual([
      ['critical', true],
      ['waiting_me', true],
      ['due_today', false],
    ]);
  });

  it('leaves figures with neither as they come, none a hero', () => {
    const other = homeFigures([figure('due_today'), figure('upcoming')], []);
    expect(heroFirst(other, 'Admin').map((c) => [c.key, c.hero])).toEqual([
      ['due_today', false],
      ['upcoming', false],
    ]);
  });
});

describe('homeTone', () => {
  it('reads Home’s tone words as the page’s', () => {
    expect(['brand', 'info', 'plain', 'caution', 'alert', 'good', 'other'].map(homeTone)).toEqual([
      'info', 'info', '', 'warning', 'danger', 'success', '',
    ]);
  });
});

describe('homeHeader', () => {
  it('heads Home with the role and greets the reader by name', () => {
    const home = create(GetHomeResponseSchema, { greeting: 'Good evening', firstName: 'Edify', roleTitle: 'Admin', todayLabel: 'Wed, Nov 18', fy: '2027' });
    expect(homeHeader(home)).toEqual({
      eyebrow: 'Home · Admin',
      title: 'Good evening, Edify',
      description: 'What needs you now, what is coming up, and where to go next.',
    });
    expect(homeDate(home)).toBe('Wed, Nov 18 · FY2027');
  });

  it('leaves the name out when the reader has none', () => {
    expect(homeHeader(create(GetHomeResponseSchema, { greeting: 'Good morning' })).title).toBe('Good morning');
  });
});
