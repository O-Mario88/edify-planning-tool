/** The Route Planner's outline drawings (24px grid, as the shell's). */
import type { SVGProps } from 'react';

const PATHS = {
  pin: 'M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21zm0-9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
  school: 'M3 21h18M5 21V10m4 11V10m6 11V10m4 11V10M2 10h20L12 3 2 10z',
  route: 'M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm12-10a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 15V9a4 4 0 0 1 4-4h4m-4 14h4a4 4 0 0 0 4-4V9',
  car: 'M5 17h14M5 17a2 2 0 1 0 4 0m-4 0H3v-5l2-5h14l2 5v5h-2m-14 0h4m6 0a2 2 0 1 0 4 0m-4 0h4M3 12h18',
  clock: 'M12 7v5l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0z',
  calendarCheck: 'M8 3v4m8-4v4M3 9h18M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm4 9 2 2 4-4',
  calendar: 'M8 3v4m8-4v4M3 9h18M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z',
  info: 'M12 16v-4m0-4h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z',
  map: 'M9 20 3 17V4l6 3m0 13 6-3m-6 3V7m6 10 6 3V7l-6-3m0 13V4M9 7l6-3',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  filter: 'M3 4h18l-7 8v6l-4 2v-8L3 4z',
  trophy: 'M8 21h8m-4-4v4m-5-17h10v5a5 5 0 0 1-10 0V4zM7 6H4a3 3 0 0 0 3 4m10-4h3a3 3 0 0 1-3 4',
  check: 'M5 13l4 4L19 7',
  optimize: 'M7 16V4m0 0L3 8m4-4 4 4m6 0v12m0 0 4-4m-4 4-4-4',
  navigate: 'M3 11 21 3l-8 18-2-8-8-2z',
  bulb: 'M9 18h6m-5 3h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z',
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
  locate: 'M12 2v3m0 14v3M2 12h3m14 0h3m-10 6a6 6 0 1 0 0-12 6 6 0 0 0 0 12zm0-4a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  save: 'M5 3h11l3 3v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V3zm3 0v5h7V3M8 21v-7h8v7',
  hourglass: 'M6 3h12M6 21h12M7 3c0 5 5 6 5 9s-5 4-5 9m10-18c0 5-5 6-5 9s5 4 5 9',
  road: 'M8 3 4 21m12-18 4 18M12 5v3m0 4v3m0 4v2',
  arrowRight: 'M5 12h14m-6-6 6 6-6 6',
  lock: 'M7 11V8a5 5 0 0 1 10 0v3M6 11h12v10H6V11z',
  alert: 'M12 9v4m0 4h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  external: 'M14 4h6v6m0-6-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5',
  chevronDown: 'M6 9l6 6 6-6',
} as const;

export type RouteIconName = keyof typeof PATHS;

export function RouteIcon({ name, strokeWidth = 1.9, ...props }: { name: RouteIconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} aria-hidden="true" {...props}>
      <path strokeLinecap="round" strokeLinejoin="round" d={PATHS[name]} />
    </svg>
  );
}
