/**
 * Home (HomeScreenService: GetHome, GetHomeQueue, GetHomeTodoFigures) as the
 * web draws it. The figures come with GetHome still to be counted; the queue
 * (and, when it says so, the To-Do figures) fills them by key. Nothing is
 * counted here.
 */
import { create } from '@bufbuild/protobuf';

import type { GetHomeResponse, HomeFigure } from '@/gen/edify/screens/v1/home_pb';
import { PageHeaderSchema, PageMetricSchema, PageStripSchema } from '@/gen/edify/screens/v1/page_pb';
import type { PageHeader, PageStrip } from '@/gen/edify/screens/v1/page_pb';

/** Home's tone words (brand | info | plain | caution | alert | good) as the page's. */
const TONES: Readonly<Record<string, string>> = {
  brand: 'info',
  info: 'info',
  caution: 'warning',
  alert: 'danger',
  good: 'success',
};

export function homeTone(tone: string): string {
  return TONES[tone] ?? '';
}

/** The overview tiles: each figure, with the queue's value where it has one. */
export function homeFigures(figures: readonly HomeFigure[], queue: readonly HomeFigure[]): PageStrip {
  const counted = new Map(queue.map((f) => [f.key, f]));
  return create(PageStripSchema, {
    metrics: figures.map((f) => {
      const shown = counted.get(f.key) ?? f;
      const value = shown.value || '—';
      return create(PageMetricSchema, {
        label: f.label,
        value,
        note: f.description,
        href: f.url,
        tone: value === '—' ? '' : homeTone(shown.tone),
      });
    }),
  });
}

/** "Good evening, Edify" over the day, the year and the role. */
export function homeHeader(home: GetHomeResponse): PageHeader {
  const day = [home.todayLabel, home.fy ? `FY ${home.fy}` : ''].filter(Boolean).join(' · ');
  return create(PageHeaderSchema, {
    eyebrow: day,
    title: home.firstName ? `${home.greeting}, ${home.firstName}` : home.greeting,
    description: home.roleTitle,
  });
}
