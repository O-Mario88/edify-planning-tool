/**
 * A figure strip as separate tiles (owner, 2026-11-16: "the last image of
 * tiles reference is what I want for the entire platform", the Smart Route
 * Planner's figure cards): each tile a tinted icon, the figure, its label and
 * the short line under it, with an info mark where the figure has a note. Two
 * a row on a phone, compact there (owner, 2026-11-20: "Smaller tiles, all
 * shown", then "look at those tiles they are more beautiful"): the tinted
 * icon beside the figure, the label and its line under both at the tile's
 * full width; on a tablet or wider, icon beside figure and label, in even
 * rows of at most five (figureTiles.tileColumns). The strip's title is the tiles' name for a
 * screen reader; a titled strip (My Plan's Plan Breakdown by Period) shows
 * its heading and the line under it over the tiles.
 */
import type { ComponentType } from 'react';
import { Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import {
  Banknote,
  Calendar,
  CalendarCheck,
  ChartColumn,
  Clock,
  GraduationCap,
  Info,
  LayoutGrid,
  Route,
  School,
  TriangleAlert,
  Users,
} from 'lucide-react-native';

import type { PageMetric, PageStrip } from '../../gen/edify/screens/v1/page_pb';
import { fonts, useTheme } from '../../theme';
import type { Palette } from '../../theme';
import { figureIcon, tileColumns } from './figureTiles';
import type { FigureIconName } from './figureTiles';
import { toneColor, usePageLink } from './shared';

type IconComponent = ComponentType<{ size?: number; color?: string }>;

const ICONS: Readonly<Record<FigureIconName, IconComponent>> = {
  school: School,
  cluster: LayoutGrid,
  route: Route,
  clock: Clock,
  calendar: Calendar,
  check: CalendarCheck,
  alert: TriangleAlert,
  money: Banknote,
  people: Users,
  training: GraduationCap,
  chart: ChartColumn,
};

const TILE_SHADOW = '0px 3px 12px 0px rgba(15, 23, 42, 0.06)';
const GAP = 12;
const COMPACT_GAP = 8;
/** Below this width (a phone) tiles are compact: no icon, a smaller figure. */
const COMPACT_BELOW = 768;

/** A tile's tint: its tone where it has one, else what its icon says. */
function tintOf(colors: Palette, metric: PageMetric, icon: FigureIconName): string {
  const toned = toneColor(colors, metric.tone);
  if (toned) return toned;
  if (icon === 'alert') return colors.danger;
  if (icon === 'check') return colors.success;
  return colors.primary;
}

export function PageStripView({ strip }: { readonly strip: PageStrip }) {
  const { colors } = useTheme();
  const { width } = useWindowDimensions();
  const columns = tileColumns(strip.metrics.length, width);
  const compact = width < COMPACT_BELOW;
  const gap = compact ? COMPACT_GAP : GAP;
  const tiles = (
    <View accessibilityLabel={strip.title} style={[styles.grid, { margin: -gap / 2 }]}>
      {strip.metrics.map((metric) => (
        <View key={metric.label} style={{ width: `${100 / columns}%`, padding: gap / 2 }}>
          <Tile metric={metric} compact={compact} />
        </View>
      ))}
    </View>
  );
  if (!strip.subtitle) {
    return tiles;
  }
  return (
    <View style={[styles.titled, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <View style={styles.heading}>
        <Text style={[styles.title, { color: colors.accentText }]} accessibilityRole="header">
          {strip.title}
        </Text>
        <Text style={[styles.subtitle, { color: colors.textSubtle }]}>{strip.subtitle}</Text>
      </View>
      {tiles}
    </View>
  );
}

function Tile({ metric, compact }: { readonly metric: PageMetric; readonly compact: boolean }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const icon = figureIcon(metric.label);
  const tint = tintOf(colors, metric, icon);
  const Icon = ICONS[icon];
  const valueColor = toneColor(colors, metric.tone) ?? colors.text;
  const label = [metric.label, metric.value, metric.helper || metric.note].filter(Boolean).join(', ');
  return (
    <Pressable
      onPress={metric.href ? () => openLink(metric.href) : undefined}
      disabled={!metric.href}
      accessibilityRole={metric.href ? 'link' : 'text'}
      accessibilityLabel={label}
      style={({ pressed }) => [
        styles.tile,
        compact && styles.compact,
        { backgroundColor: pressed ? colors.primarySoft : colors.raised, borderColor: colors.raisedBorder },
      ]}
    >
      {compact ? (
        <>
          <View style={[styles.head, metric.note ? styles.besideInfo : null]}>
            <View style={[styles.icon, styles.iconCompact, { backgroundColor: `${tint}1f` }]}>
              <Icon size={18} color={tint} />
            </View>
            <Text style={[styles.value, styles.valueCompact, { color: valueColor }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>
              {metric.value}
            </Text>
          </View>
          <Text style={[styles.label, styles.small, { color: colors.textMuted }]}>{metric.label}</Text>
          {metric.helper ? <Text style={[styles.helper, styles.small, { color: colors.textMuted }]}>{metric.helper}</Text> : null}
        </>
      ) : (
        <>
          <View style={[styles.icon, { backgroundColor: `${tint}1a` }]}>
            <Icon size={20} color={tint} />
          </View>
          <View style={styles.words}>
            <Text style={[styles.value, { color: valueColor }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>
              {metric.value}
            </Text>
            <Text style={[styles.label, { color: colors.textMuted }]}>{metric.label}</Text>
            {metric.helper ? <Text style={[styles.helper, { color: colors.textMuted }]}>{metric.helper}</Text> : null}
          </View>
        </>
      )}
      {metric.note ? (
        <View style={compact ? styles.infoCorner : undefined}>
          <Info size={compact ? 14 : 16} color={colors.textMuted} />
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
  titled: { borderWidth: 1, borderRadius: 10, padding: 16, gap: 12, boxShadow: TILE_SHADOW },
  heading: { gap: 2 },
  title: { fontFamily: fonts.semibold, fontSize: 15 },
  subtitle: { fontFamily: fonts.bold, fontSize: 12 },
  tile: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    borderWidth: 1,
    borderRadius: 14,
    paddingVertical: 12,
    paddingHorizontal: 12,
    boxShadow: TILE_SHADOW,
  },
  compact: { flexDirection: 'column', alignItems: 'stretch', gap: 6, borderRadius: 14, padding: 12 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  iconCompact: { width: 34, height: 34 },
  infoCorner: { position: 'absolute', top: 12, right: 12 },
  besideInfo: { paddingRight: 20 },
  icon: { width: 40, height: 40, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  words: { flexGrow: 1, flexShrink: 1, minWidth: 0, gap: 1 },
  value: { fontFamily: fonts.bold, fontSize: 20, lineHeight: 24 },
  valueCompact: { fontSize: 18, lineHeight: 22 },
  small: { fontSize: 12, lineHeight: 16 },
  label: { fontFamily: fonts.medium, fontSize: 13 },
  helper: { fontFamily: fonts.medium, fontSize: 12 },
});
