import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { GetHomeResponseSchema, HomeFigureSchema } from '@/gen/edify/screens/v1/home_pb';

import { homeDate, homeFigures, homeHeader, homeTone } from './homeScreen';

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
