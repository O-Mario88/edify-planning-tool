/**
 * A profile's insight rail (partials/profiles/_rail.html): under the page's
 * blocks on a phone, a card of parts — SSA Performance (the figure and a
 * meter for each intervention) and Needs Attention (amber-dotted links).
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { PageMeter, PageRail, PageRailPart } from '../../gen/edify/screens/v1/page_pb';
import { fonts, useTheme } from '../../theme';
import { cardStyles, usePageLink } from './shared';

const AMBER = '#f59e0b';

export function PageRailView({ rail }: { readonly rail: PageRail }) {
  const { colors } = useTheme();
  return (
    <View style={[cardStyles.card, cardStyles.padded, styles.gap, { backgroundColor: colors.raised, borderColor: colors.border }]}>
      <View>
        <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
          {rail.title}
        </Text>
        {rail.subtitle ? <Text style={[styles.small, { color: colors.textMuted }]}>{rail.subtitle}</Text> : null}
      </View>
      {rail.parts.map((part) => (
        <Part key={part.key || part.title} part={part} />
      ))}
    </View>
  );
}

function Part({ part }: { readonly part: PageRailPart }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  return (
    <View style={[styles.part, { borderColor: colors.border, backgroundColor: colors.surfaceMuted }]}>
      <Text style={[styles.partTitle, { color: colors.text }]} accessibilityRole="header">
        {part.title}
      </Text>
      {part.figure ? (
        <View style={styles.figureLine}>
          <Text
            onPress={part.figureHref ? () => openLink(part.figureHref) : undefined}
            accessibilityRole={part.figureHref ? 'link' : 'text'}
            style={[styles.figure, { color: colors.text }]}
          >
            {part.figure}
          </Text>
          {part.figureNote ? <Text style={[styles.small, { color: colors.textMuted }]}>{part.figureNote}</Text> : null}
        </View>
      ) : null}
      {part.meters.map((meter) => (
        <MeterLine key={meter.label} meter={meter} />
      ))}
      {part.note ? <Text style={[styles.small, styles.note, { color: colors.textMuted }]}>{part.note}</Text> : null}
      {part.links.map((link) => (
        <Pressable
          key={link.text}
          onPress={() => openLink(link.href)}
          accessibilityRole="link"
          style={[styles.linkRow, { borderBottomColor: colors.border }]}
        >
          <View style={[styles.dot, { backgroundColor: AMBER }]} />
          <Text style={[styles.linkText, { color: colors.text }]}>{link.text}</Text>
          <Text style={[styles.chevron, { color: colors.text }]}>›</Text>
        </Pressable>
      ))}
    </View>
  );
}

function MeterLine({ meter }: { readonly meter: PageMeter }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  return (
    <Pressable
      onPress={meter.href ? () => openLink(meter.href) : undefined}
      disabled={!meter.href}
      accessibilityRole={meter.href ? 'link' : 'text'}
      accessibilityLabel={`${meter.label} ${meter.value}`}
      style={[styles.meterRow, { borderBottomColor: colors.border }]}
    >
      <Text style={[styles.meterName, { color: colors.text }]}>{meter.label}</Text>
      <View style={[styles.track, { backgroundColor: colors.border }]}>
        <View style={[styles.fill, { width: `${Math.min(100, meter.fraction * 100)}%`, backgroundColor: colors.primary }]} />
      </View>
      <Text style={[styles.meterValue, { color: colors.text }]}>{meter.value}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  gap: { gap: 12 },
  title: { fontFamily: fonts.bold, fontSize: 15 },
  small: { fontFamily: fonts.medium, fontSize: 12 },
  part: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 14, paddingTop: 12, paddingBottom: 10, gap: 4 },
  partTitle: { fontFamily: fonts.bold, fontSize: 14, marginBottom: 2 },
  figureLine: { gap: 2, marginBottom: 4 },
  figure: { fontFamily: fonts.bold, fontSize: 20 },
  meterRow: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 38, borderBottomWidth: 1 },
  meterName: { flex: 1, fontFamily: fonts.medium, fontSize: 13 },
  track: { width: 72, height: 6, borderRadius: 999, overflow: 'hidden' },
  fill: { height: 6 },
  meterValue: { width: 36, textAlign: 'right', fontFamily: fonts.semibold, fontSize: 13 },
  note: { marginTop: 6 },
  linkRow: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 42, borderBottomWidth: 1 },
  dot: { width: 7, height: 7, borderRadius: 4 },
  linkText: { flex: 1, fontFamily: fonts.semibold, fontSize: 13 },
  chevron: { fontFamily: fonts.semibold, fontSize: 16 },
});
