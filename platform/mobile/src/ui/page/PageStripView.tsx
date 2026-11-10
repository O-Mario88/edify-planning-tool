/**
 * A figure strip (components/context_metrics.html) as the web draws it on a
 * phone: one card of tiles two to a row, each its label, its figure and the
 * short line under it, with hairlines between them. The strip's title is not
 * shown on a phone; it is the card's name for a screen reader.
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { PageMetric, PageStrip } from '../../gen/edify/screens/v1/page_pb';
import { fonts, useTheme } from '../../theme';
import { toneColor, usePageLink } from './shared';

const PER_ROW = 2;
const STRIP_SHADOW = '0px 3px 12px 0px rgba(15, 23, 42, 0.06)';

export function PageStripView({ strip }: { readonly strip: PageStrip }) {
  const { colors } = useTheme();
  const rows: PageMetric[][] = [];
  strip.metrics.forEach((metric, index) => {
    if (index % PER_ROW === 0) {
      rows.push([]);
    }
    rows[rows.length - 1].push(metric);
  });
  const grid = (
    <View
      accessibilityLabel={strip.title}
      style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}
    >
      {rows.map((row, rowIndex) => (
        <View
          key={row.map((m) => m.label).join('|')}
          style={[styles.row, rowIndex > 0 && { borderTopWidth: 1, borderTopColor: colors.raisedBorder }]}
        >
          {row.map((metric, index) => (
            <Tile key={metric.label} metric={metric} hasRule={index > 0} />
          ))}
          {row.length < PER_ROW ? <View style={styles.tile} /> : null}
        </View>
      ))}
    </View>
  );
  if (!strip.subtitle) {
    return grid;
  }
  // A titled card of tiles (My Plan's Plan Breakdown by Period): its heading
  // and the line under it, then the tiles in their own box.
  return (
    <View style={[styles.titled, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <View style={styles.heading}>
        <Text style={[styles.title, { color: colors.accentText }]} accessibilityRole="header">
          {strip.title}
        </Text>
        <Text style={[styles.subtitle, { color: colors.textSubtle }]}>{strip.subtitle}</Text>
      </View>
      {grid}
    </View>
  );
}

function Tile({ metric, hasRule }: { readonly metric: PageMetric; readonly hasRule: boolean }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const helperColor = toneColor(colors, metric.tone) ?? colors.textMuted;
  const label = [metric.label, metric.value, metric.helper || metric.note].filter(Boolean).join(', ');
  return (
    <Pressable
      onPress={metric.href ? () => openLink(metric.href) : undefined}
      disabled={!metric.href}
      accessibilityRole={metric.href ? 'link' : 'text'}
      accessibilityLabel={label}
      style={({ pressed }) => [styles.tile, pressed && { backgroundColor: colors.primarySoft }]}
    >
      {hasRule ? <View style={[styles.rule, { backgroundColor: colors.raisedBorder }]} /> : null}
      <Text style={[styles.label, { color: colors.textMuted }]}>{metric.label}</Text>
      <Text style={[styles.value, { color: colors.text }]}>{metric.value}</Text>
      {metric.helper ? <Text style={[styles.helper, { color: helperColor }]}>{metric.helper}</Text> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  titled: { borderWidth: 1, borderRadius: 10, padding: 16, gap: 12, boxShadow: STRIP_SHADOW },
  heading: { gap: 2 },
  title: { fontFamily: fonts.semibold, fontSize: 15 },
  subtitle: { fontFamily: fonts.bold, fontSize: 12 },
  card: { borderWidth: 1, borderRadius: 10, overflow: 'hidden', boxShadow: STRIP_SHADOW },
  row: { flexDirection: 'row' },
  tile: { flex: 1, alignItems: 'center', paddingVertical: 10, paddingHorizontal: 12, gap: 2 },
  rule: { position: 'absolute', left: 0, top: 10, bottom: 10, width: 1 },
  label: { fontFamily: fonts.medium, fontSize: 12, textAlign: 'center' },
  value: { fontFamily: fonts.bold, fontSize: 20, lineHeight: 23, textAlign: 'center' },
  helper: { fontFamily: fonts.medium, fontSize: 12, textAlign: 'center' },
});
