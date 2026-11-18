/**
 * Home (HomeScreenService: GetHome, GetHomeQueue, GetHomeTodoFigures) as the
 * existing Home draws it (templates/pages/home/index.html). The figures come
 * with GetHome still to be counted; the queue (and, when it says so, the
 * To-Do figures) fills them by key. Nothing is counted here.
 */
import type { GetHomeResponse, HomeFigure } from '@/gen/edify/screens/v1/home_pb';

/** Home's tone words (brand | info | plain | caution | alert | good) as the page's badge tones. */
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

/** A figure as the overview draws it: its value and tone, or still loading. */
export interface HomeFigureCard {
  readonly key: string;
  readonly label: string;
  readonly url: string;
  readonly iconSvg: string;
  readonly description: string;
  readonly value: string;
  /** Home's own tone word: the figure's class (edify-home__figure--{tone}). */
  readonly tone: string;
  readonly loading: boolean;
}

/** Each overview figure, with the queue's value and tone where it counted one. */
export function homeFigures(figures: readonly HomeFigure[], queue: readonly HomeFigure[]): HomeFigureCard[] {
  const counted = new Map(queue.map((f) => [f.key, f]));
  return figures.map((f) => {
    const shown = counted.get(f.key);
    const loading = f.loading && !shown;
    return {
      key: f.key,
      label: f.label,
      url: f.url,
      iconSvg: f.iconSvg,
      description: f.description,
      value: (shown ?? f).value,
      tone: (shown ?? f).tone || 'plain',
      loading,
    };
  });
}

/** The desk header's words: "Home · Admin", the greeting by name. */
export function homeHeader(home: GetHomeResponse): { eyebrow: string; title: string; description: string } {
  return {
    eyebrow: home.roleTitle ? `Home · ${home.roleTitle}` : 'Home',
    title: home.firstName ? `${home.greeting}, ${home.firstName}` : home.greeting,
    description: 'What needs you now, what is coming up, and where to go next.',
  };
}

/** The overview's date: "Thu, Nov 19 · FY2027". */
export function homeDate(home: GetHomeResponse): string {
  return [home.todayLabel, home.fy ? `FY${home.fy}` : ''].filter(Boolean).join(' · ');
}
