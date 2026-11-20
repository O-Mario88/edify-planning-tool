/**
 * A page while it loads, shaped like the page it will be (a figure strip,
 * then a card of rows), as Home's queue loads: one loading style across the
 * app instead of a lone spinner (2026-11-20 review). Still, so a reader who
 * asked for reduced motion sees nothing move.
 */
import { StyleSheet, View } from 'react-native';

import { radius, useTheme } from '../../theme';

const TILES = 4;
const ROWS = 4;

export function PageSkeleton() {
  const { colors } = useTheme();
  const bar = { backgroundColor: colors.surfaceMuted };
  return (
    <View accessible accessibilityLabel="Loading" accessibilityRole="progressbar" style={styles.page}>
      <View style={styles.tiles}>
        {Array.from({ length: TILES }, (_, i) => (
          <View key={i} style={styles.tileBox}>
            <View style={[styles.tile, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
              <View style={[styles.figure, bar]} />
              <View style={[styles.line, styles.short, bar]} />
            </View>
          </View>
        ))}
      </View>
      <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
        <View style={[styles.line, styles.title, bar]} />
        {Array.from({ length: ROWS }, (_, i) => (
          <View key={i} style={[styles.row, { borderTopColor: colors.raisedBorder }]}>
            <View style={[styles.line, bar]} />
            <View style={[styles.line, styles.short, bar]} />
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { gap: 16 },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', margin: -4 },
  tileBox: { width: '50%', padding: 4 },
  tile: { borderWidth: 1, borderRadius: 10, paddingVertical: 12, paddingHorizontal: 12, gap: 8 },
  figure: { width: 36, height: 18, borderRadius: radius.sm },
  card: { borderWidth: 1, borderRadius: 10, overflow: 'hidden' },
  title: { width: '45%', margin: 16 },
  row: { borderTopWidth: StyleSheet.hairlineWidth, paddingVertical: 14, paddingHorizontal: 16, gap: 8 },
  line: { height: 10, borderRadius: radius.sm, width: '80%' },
  short: { width: '50%' },
});
