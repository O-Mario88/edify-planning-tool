/**
 * The parts the loan referral screens are drawn with: a status pill in its
 * colour, a figure tile, a label-and-value line, and sharing a link or a
 * CSV file the way the platform allows (the share sheet on a phone, the
 * clipboard or a download in a browser).
 */
import type { ReactNode } from 'react';
import { Platform, Pressable, Share, StyleSheet, Text, View } from 'react-native';

import { fonts, radius, toneColors, useTheme } from '../../theme';
import { loanStatusTone } from './loanRoutes';

export function StatusPill({ status, label }: { readonly status: string; readonly label: string }) {
  const { colors } = useTheme();
  const tone = toneColors(colors, loanStatusTone(status));
  return (
    <View style={[styles.pill, { backgroundColor: tone.soft }]} accessibilityLabel={`Status: ${label}`}>
      <Text style={[styles.pillText, { color: tone.fg }]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

interface TileProps {
  readonly label: string;
  readonly value: string;
  readonly tone?: 'good' | 'alert' | 'caution' | 'info' | 'plain';
  readonly onPress?: () => void;
}

/** One figure of the dashboard; pressing it filters the list to what it counts. */
export function Tile({ label, value, tone = 'plain', onPress }: TileProps) {
  const { colors } = useTheme();
  const accent = tone === 'plain' ? colors.text : toneColors(colors, tone).fg;
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : 'summary'}
      accessibilityLabel={`${label}: ${value}`}
      style={({ pressed }) => [
        styles.tile,
        { backgroundColor: colors.raised, borderColor: colors.raisedBorder, opacity: pressed ? 0.85 : 1 },
      ]}
    >
      <Text style={[styles.tileValue, { color: accent }]} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </Text>
      <Text style={[styles.tileLabel, { color: colors.textMuted }]} numberOfLines={2}>
        {label}
      </Text>
    </Pressable>
  );
}

export function TileGrid({ children }: { readonly children: ReactNode }) {
  return <View style={styles.grid}>{children}</View>;
}

interface LineProps {
  readonly label: string;
  readonly value: string;
  readonly isStrong?: boolean;
  /** The first line of a card with no title above it: no rule over it. */
  readonly isFirst?: boolean;
}

/** A label and its value on one line, the value right-aligned. */
export function Line({ label, value, isStrong, isFirst }: LineProps) {
  const { colors } = useTheme();
  if (!value) {
    return null;
  }
  return (
    <View style={[styles.line, { borderTopColor: colors.border }, isFirst && styles.firstLine]}>
      <Text style={[styles.lineLabel, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.lineValue, { color: colors.text, fontFamily: isStrong ? fonts.bold : fonts.semibold }]} selectable>
        {value}
      </Text>
    </View>
  );
}

/** Shares a link: the share sheet on a phone, the clipboard in a browser. */
export async function shareLink(url: string, title: string): Promise<string> {
  if (Platform.OS === 'web') {
    const clipboard = (globalThis as { navigator?: { clipboard?: { writeText(text: string): Promise<void> } } }).navigator?.clipboard;
    if (clipboard) {
      await clipboard.writeText(url);
      return 'Link copied.';
    }
    return url;
  }
  await Share.share({ message: url, title });
  return '';
}

/** Hands over a CSV file: a download in a browser, the share sheet on a phone. */
export async function shareCsv(fileName: string, csv: string): Promise<void> {
  if (Platform.OS === 'web') {
    const scope = globalThis as unknown as {
      document?: { createElement(tag: string): { href: string; download: string; click(): void } };
      URL?: { createObjectURL(blob: unknown): string; revokeObjectURL(url: string): void };
      Blob?: new (parts: string[], options: { type: string }) => unknown;
    };
    if (scope.document && scope.URL && scope.Blob) {
      const href = scope.URL.createObjectURL(new scope.Blob([csv], { type: 'text/csv;charset=utf-8' }));
      const anchor = scope.document.createElement('a');
      anchor.href = href;
      anchor.download = fileName;
      anchor.click();
      scope.URL.revokeObjectURL(href);
      return;
    }
  }
  await Share.share({ message: csv, title: fileName });
}

const styles = StyleSheet.create({
  pill: { alignSelf: 'flex-start', borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 3 },
  pillText: { fontFamily: fonts.bold, fontSize: 12 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tile: { flexGrow: 1, flexBasis: '30%', minWidth: 100, borderWidth: 1, borderRadius: radius.md, paddingVertical: 12, paddingHorizontal: 12, gap: 2 },
  tileValue: { fontFamily: fonts.bold, fontSize: 20, fontVariant: ['tabular-nums'] },
  tileLabel: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 16 },
  line: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, paddingVertical: 9, borderTopWidth: StyleSheet.hairlineWidth },
  firstLine: { borderTopWidth: 0, paddingTop: 0 },
  lineLabel: { fontFamily: fonts.medium, fontSize: 13, flexShrink: 0, maxWidth: '45%' },
  lineValue: { fontSize: 13, flex: 1, textAlign: 'right', fontVariant: ['tabular-nums'] },
});
