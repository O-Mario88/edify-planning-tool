/**
 * Edify design tokens for the native app.
 *
 * The values are the existing web app's own `--edify-*` tokens, read from its
 * light and dark themes, so a screen here and the same page on the web are
 * drawn from one palette. Change a colour there first, then here.
 */
import { createContext, createElement, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useColorScheme } from 'react-native';

export interface Palette {
  readonly bg: string;
  readonly surface: string;
  readonly surfaceMuted: string;
  readonly surfaceSelected: string;
  readonly card: string;
  readonly cardBorder: string;
  readonly border: string;
  readonly borderStrong: string;
  readonly text: string;
  readonly textMuted: string;
  readonly textSubtle: string;
  readonly primary: string;
  readonly primaryInk: string;
  readonly primarySoft: string;
  readonly accentText: string;
  readonly eyebrow: string;
  readonly segmentActive: string;
  readonly topbar: string;
  readonly danger: string;
  readonly dangerSoft: string;
  readonly success: string;
  readonly successSoft: string;
  readonly warning: string;
  readonly warningSoft: string;
  readonly info: string;
  readonly infoSoft: string;
  /** Raised surfaces: Home's cards and rows. */
  readonly raised: string;
  readonly raisedBorder: string;
  readonly link: string;
  /** Form fields (selects, text boxes) inside drawers. */
  readonly fieldBorder: string;
  /** Light-blue outline of secondary buttons such as Cancel. */
  readonly outlineBorder: string;
  /** Amber edge of a drawer's confirmation box. */
  readonly confirmBorder: string;
  /** Record tables' header row. */
  readonly tableHead: string;
  /** Charts' first series (--edify-series-1). */
  readonly series1: string;
  readonly heroGradient: readonly [string, string, ...string[]];
  readonly heroRule: string;
}

const light: Palette = {
  bg: '#dbe4eb',
  surface: '#f8fafb',
  surfaceMuted: '#e5eaed',
  surfaceSelected: '#dfe8ed',
  card: '#ffffff',
  cardBorder: '#c7d1d7',
  border: '#c7d1d7',
  borderStrong: '#aebcc4',
  text: '#17232b',
  textMuted: '#233844',
  textSubtle: '#4d6170',
  primary: '#0e5da3',
  primaryInk: '#ffffff',
  primarySoft: '#e4f2fb',
  accentText: '#073962',
  eyebrow: '#0e5da3',
  segmentActive: '#0e5da3',
  topbar: '#ffffff',
  danger: '#be123c',
  dangerSoft: '#fef2f2',
  success: '#065f46',
  successSoft: '#ecfdf5',
  warning: '#92400e',
  warningSoft: '#fffbeb',
  info: '#1872bd',
  infoSoft: '#eef7fd',
  raised: '#ffffff',
  raisedBorder: '#d7dee2',
  link: '#073962',
  fieldBorder: '#858e98',
  outlineBorder: '#8ac6ea',
  confirmBorder: '#fee685',
  tableHead: '#dce6ec',
  series1: '#0e5da3',
  heroGradient: ['#001d39', '#062847', '#0a4d86'],
  heroRule: 'rgba(189, 216, 233, 0.72)',
};

const dark: Palette = {
  bg: '#0e151c',
  surface: '#151f29',
  surfaceMuted: '#121c25',
  surfaceSelected: '#18364b',
  card: '#151f29',
  cardBorder: '#31404d',
  border: '#31404d',
  borderStrong: '#566d7d',
  text: '#edf3f7',
  textMuted: '#bdc9d4',
  textSubtle: '#8fa0ad',
  primary: '#2f78b7',
  primaryInk: '#ffffff',
  primarySoft: 'rgba(83, 145, 194, 0.18)',
  accentText: '#8fbfe3',
  eyebrow: '#a9cee8',
  segmentActive: '#1976d2',
  topbar: '#0b1219',
  danger: '#f18f8a',
  dangerSoft: 'rgba(124, 50, 51, 0.3)',
  success: '#79ca98',
  successSoft: 'rgba(48, 123, 77, 0.22)',
  warning: '#e7b45a',
  warningSoft: 'rgba(137, 92, 24, 0.28)',
  info: '#9bbbd6',
  infoSoft: 'rgba(69, 103, 132, 0.3)',
  raised: '#1a2732',
  raisedBorder: '#283640',
  link: '#a9cee8',
  fieldBorder: '#566d7d',
  outlineBorder: '#3c6f96',
  confirmBorder: 'rgba(231, 180, 90, 0.45)',
  tableHead: '#1d2b36',
  series1: '#4f9ae0',
  heroGradient: ['#0a1118', '#0b141c'],
  heroRule: '#31404d',
};

/** The sign-in page is always drawn light, as on the web. */
export const signInPalette = {
  page: '#e7f4fc',
  card: '#ffffff',
  cardBorder: '#d9e3ed',
  title: '#17232b',
  subtitle: '#5b708a',
  label: '#233844',
  inputBg: '#f8fafb',
  inputBorder: '#c7d1d7',
  inputText: '#17232b',
  link: '#0e5da3',
  divider: '#e3eaf0',
  gradient: ['#075397', '#105fa6'] as const,
  barGradient: ['#0a4d86', '#77cff8'] as const,
  danger: '#be123c',
  dangerSoft: '#fef2f2',
} as const;

/** Geist Sans, the web app's typeface, by weight. */
export const fonts = {
  regular: 'Geist_400Regular',
  medium: 'Geist_500Medium',
  semibold: 'Geist_600SemiBold',
  bold: 'Geist_700Bold',
} as const;

/** The web app's type scale (13px text, 20px page titles). */
export const type = {
  small: 12,
  body: 13,
  control: 15,
  title: 20,
  display: 26,
} as const;

export const radius = { xs: 6, sm: 10, md: 12, lg: 16, pill: 999 } as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 28 } as const;

export const sizes = { topbar: 52, bottomNav: 56, control: 44 } as const;

export type ThemeChoice = 'system' | 'light' | 'dark';

export interface Theme {
  readonly colors: Palette;
  readonly isDark: boolean;
  /** Switch between light and dark, as the web app's top-bar control does. */
  readonly toggle: () => void;
}

/** A tone the server names for a tile, mark or tag. */
export interface ToneColors {
  readonly fg: string;
  readonly soft: string;
}

/** The colours of a server tone (brand, info, caution, alert, good, plain). */
export function toneColors(colors: Palette, tone: string): ToneColors {
  switch (tone) {
    case 'brand':
      return { fg: colors.primary, soft: colors.primarySoft };
    case 'info':
      return { fg: colors.info, soft: colors.infoSoft };
    case 'caution':
      return { fg: colors.warning, soft: colors.warningSoft };
    case 'alert':
      return { fg: colors.danger, soft: colors.dangerSoft };
    case 'good':
      return { fg: colors.success, soft: colors.successSoft };
    default:
      return { fg: colors.textMuted, soft: colors.surfaceMuted };
  }
}

const ThemeContext = createContext<{ choice: ThemeChoice; toggle: () => void } | null>(null);

export function ThemeProvider({ children }: { readonly children: ReactNode }) {
  const system = useColorScheme();
  const [choice, setChoice] = useState<ThemeChoice>('system');
  const value = useMemo(
    () => ({
      choice,
      toggle: () =>
        setChoice((current) => {
          const isDarkNow = current === 'system' ? system === 'dark' : current === 'dark';
          return isDarkNow ? 'light' : 'dark';
        }),
    }),
    [choice, system],
  );
  return createElement(ThemeContext.Provider, { value }, children);
}

export function useTheme(): Theme {
  const system = useColorScheme();
  const context = useContext(ThemeContext);
  const choice = context?.choice ?? 'system';
  const isDark = choice === 'system' ? system === 'dark' : choice === 'dark';
  return { colors: isDark ? dark : light, isDark, toggle: context?.toggle ?? (() => undefined) };
}
