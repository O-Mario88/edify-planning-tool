/**
 * What every page block shares: the web's card, the tones its status words
 * use, and where a link goes. A block never decides where a link leads; the
 * screen that draws it does (PageLinkContext).
 */
import { createContext, useContext } from 'react';
import { StyleSheet } from 'react-native';

import type { Palette } from '../../theme';

/** Opens a web path the page links to: natively when the app has it. */
export type OpenLink = (href: string) => void;
export const PageLinkContext = createContext<OpenLink>(() => undefined);

export function usePageLink(): OpenLink {
  return useContext(PageLinkContext);
}

/** The page's chips: the value each chip filter is on, and how to change it. */
export interface ChipState {
  readonly chosen: Readonly<Record<string, string>>;
  readonly choose: (name: string, value: string) => void;
}
export const ChipContext = createContext<ChipState>({ chosen: {}, choose: () => undefined });

export function useChips(): ChipState {
  return useContext(ChipContext);
}

/** The web's card shadow (.card, .edify-surface). */
export const CARD_SHADOW =
  '0px 5px 20px -12px rgba(23, 48, 66, 0.23), 0px 1px 3px 0px rgba(23, 48, 66, 0.07)';

/** The colour of a status word in the page's tone, or undefined for plain text. */
export function toneColor(colors: Palette, tone: string): string | undefined {
  switch (tone) {
    case 'success':
    case 'good':
    case 'positive':
    case 'green':
      return colors.success;
    case 'danger':
    case 'alert':
    case 'negative':
    case 'red':
    case 'rose':
      return colors.danger;
    case 'warning':
    case 'caution':
    case 'attention':
    case 'amber':
      return colors.warning;
    case 'info':
    case 'primary':
    case 'lime':
    case 'blue':
      return colors.link;
    default:
      return undefined;
  }
}

export const cardStyles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 10, boxShadow: CARD_SHADOW },
  padded: { padding: 16 },
});
