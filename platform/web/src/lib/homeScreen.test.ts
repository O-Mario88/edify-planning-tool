import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { GetHomeResponseSchema, HomeFigureSchema } from '@/gen/edify/screens/v1/home_pb';

import { homeFigures, homeHeader, homeTone } from './homeScreen';

const figure = (key: string, over: Partial<{ value: string; tone: string; loading: boolean }> = {}) =>
  create(HomeFigureSchema, { key, label: key.toUpperCase(), url: '/todos', description: `${key} described`, ...over });

describe('homeFigures', () => {
  it('fills a figure still to come with the queue’s value of the same key', () => {
    const strip = homeFigures(
      [figure('waiting_me', { loading: true, tone: 'plain' }), figure('critical', { loading: true, tone: 'plain' })],
      [figure('waiting_me', { value: '4', tone: 'caution' })],
    );
    expect(strip.metrics.map((m) => [m.label, m.value, m.tone, m.href])).toEqual([
      ['WAITING_ME', '4', 'warning', '/todos'],
      ['CRITICAL', '—', '', '/todos'],
    ]);
    expect(strip.metrics[0]?.note).toBe('waiting_me described');
  });

  it('keeps a figure that came with its own value', () => {
    expect(homeFigures([figure('schools', { value: '12', tone: 'good' })], []).metrics[0]?.value).toBe('12');
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
  it('greets the reader by name over the day, the year and the role', () => {
    const header = homeHeader(
      create(GetHomeResponseSchema, { greeting: 'Good evening', firstName: 'Edify', roleTitle: 'Admin', todayLabel: 'Wed, Nov 18', fy: '2027' }),
    );
    expect([header.eyebrow, header.title, header.description]).toEqual(['Wed, Nov 18 · FY 2027', 'Good evening, Edify', 'Admin']);
  });

  it('leaves the name out when the reader has none', () => {
    expect(homeHeader(create(GetHomeResponseSchema, { greeting: 'Good morning' })).title).toBe('Good morning');
  });
});
