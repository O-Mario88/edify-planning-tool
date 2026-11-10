/**
 * A bar chart in the platform's cut-out form (static/js/chart-standard.js,
 * owner 2026-10-18): each category's name over one track; every series from
 * zero on the same scale, the longest drawn first so each shorter bar lies on
 * top; the shortest value written inside its bar, the longest after the bar.
 * Each series keeps its shade of the first series' hue (100%, then 33%, ...).
 * A ruled legend names the series; the axis is one rule with its unit under
 * it. "View chart data" opens the same figures as a table.
 */
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { ChevronDown, ChevronRight } from 'lucide-react-native';

import type { PageChart } from '../../gen/edify/screens/v1/page_pb';
import { fonts, useTheme } from '../../theme';
import { cardStyles } from './shared';

/** The share of the first series' hue in each series' shade (chart-standard.js SHADES). */
const SHADES = [100, 33, 78, 10, 55, 89, 44, 22];
/** Room after the longest bar for its value. */
const END_ROOM = 52;
const BAR_HEIGHT = 24;
/** Narrower than this, a bar's number is written after it instead. */
const INSIDE_MIN = 34;
/** The pale whole behind a one-series bar: this share of the series' hue. */
const WHOLE_SHADE = 12;

function mix(hex: string, onto: string, share: number): string {
  const channel = (value: string, at: number) => parseInt(value.slice(at, at + 2), 16);
  const blend = (at: number) =>
    Math.round((channel(hex, at) * share + channel(onto, at) * (100 - share)) / 100)
      .toString(16)
      .padStart(2, '0');
  return `#${blend(1)}${blend(3)}${blend(5)}`;
}

/** A round scale end at or above the largest value, as the web picks it. */
function scaleOf(chart: PageChart): { max: number; step: number } {
  const top = Math.max(0, ...chart.series.flatMap((s) => s.values));
  if (chart.max > 0 && chart.max >= top) {
    return { max: chart.max, step: chart.max / (chart.max % 5 === 0 ? 5 : 4) };
  }
  if (!top) {
    return { max: 1, step: 1 };
  }
  const rough = top / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((m) => m >= rough) ?? rough;
  return { max: Math.ceil(top / step) * step, step };
}

const mark = (value: number) => String(Number(value.toFixed(1)));

export function PageChartView({ chart }: { readonly chart: PageChart }) {
  const { colors } = useTheme();
  const [width, setWidth] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const scale = scaleOf(chart);
  const trackWidth = Math.max(0, width - END_ROOM);
  const share = (value: number) => Math.min(1, value / scale.max) * trackWidth;
  const fillOf = (index: number) => {
    const shade = SHADES[index % SHADES.length];
    return shade === 100 ? colors.series1 : mix(colors.series1, colors.raised, shade);
  };
  const ticks: number[] = [];
  for (let tick = 0; tick <= scale.max + scale.step / 1000; tick += scale.step) {
    ticks.push(Number(tick.toFixed(6)));
  }

  return (
    <View style={[cardStyles.card, cardStyles.padded, styles.gap, { backgroundColor: colors.raised, borderColor: colors.border }]}>
      <View>
        <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
          {chart.title}
        </Text>
        {chart.subtitle ? <Text style={[styles.subtitle, { color: colors.textMuted }]}>{chart.subtitle}</Text> : null}
      </View>
      {chart.series.length > 1 ? (
        <View style={[styles.legend, { borderColor: colors.borderStrong }]}>
          {chart.series.map((series, index) => (
            <View key={series.name} style={styles.legendItem}>
              <View style={[styles.key, { backgroundColor: fillOf(index) }]} />
              <Text style={[styles.legendText, { color: colors.textMuted }]}>{series.name}</Text>
            </View>
          ))}
        </View>
      ) : null}
      <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)} style={styles.rows}>
        {width > 0
          ? chart.categories.map((category, row) => {
              const bars = chart.series
                .map((series, index) => ({ index, value: series.values[row] ?? 0 }))
                .sort((a, b) => b.value - a.value || b.index - a.index);
              const longest = bars[0];
              const shortest = bars.length > 1 ? bars[bars.length - 1] : undefined;
              const fitsInside = shortest !== undefined && share(shortest.value) >= INSIDE_MIN;
              const after =
                shortest && !fitsInside
                  ? bars.map((bar) => `${mark(bar.value)} ${chart.series[bar.index].name}`).join(', ')
                  : longest
                    ? mark(longest.value)
                    : '';
              return (
                <View key={category} accessible accessibilityLabel={`${category}: ${bars.map((b) => `${mark(b.value)} ${chart.series[b.index].name}`).join(', ')}`}>
                  <Text style={[styles.name, { color: colors.text }]}>{category}</Text>
                  <View style={styles.track}>
                    {chart.series.length === 1 ? (
                      // One series: its bar is the dark part of the pale whole
                      // (the scale's end), so a zero still reads as measured.
                      <View style={[styles.whole, { width: trackWidth, backgroundColor: mix(colors.series1, colors.raised, WHOLE_SHADE) }]} />
                    ) : null}
                    {bars.map((bar) => (
                      <View key={bar.index} style={[styles.bar, { width: share(bar.value), backgroundColor: fillOf(bar.index) }]}>
                        {fitsInside && shortest?.index === bar.index ? (
                          <Text
                            style={[
                              styles.inside,
                              { color: SHADES[bar.index % SHADES.length] >= 60 ? '#ffffff' : colors.text },
                            ]}
                          >
                            {mark(bar.value)}
                          </Text>
                        ) : null}
                      </View>
                    ))}
                    <Text style={[styles.end, { left: longest ? share(longest.value) : 0, color: colors.textMuted }]}>{after}</Text>
                  </View>
                </View>
              );
            })
          : null}
      </View>
      <View style={[styles.axis, { width: trackWidth, borderTopColor: colors.textMuted }]}>
        {ticks.map((tick) => (
          <Text key={tick} style={[styles.tick, { left: share(tick) - 12, color: colors.textMuted }]}>
            {mark(tick)}
          </Text>
        ))}
      </View>
      {chart.axisTitle ? (
        <Text style={[styles.unit, { width: trackWidth, color: colors.textMuted }]}>{chart.axisTitle}</Text>
      ) : null}
      <Pressable onPress={() => setIsOpen((open) => !open)} accessibilityRole="button" accessibilityState={{ expanded: isOpen }} style={styles.toggle}>
        {isOpen ? <ChevronDown size={14} color={colors.textMuted} /> : <ChevronRight size={14} color={colors.textMuted} />}
        <Text style={[styles.toggleText, { color: colors.textMuted }]}>View chart data</Text>
      </Pressable>
      {isOpen ? (
        <View style={[styles.data, { borderColor: colors.border }]}>
          {chart.categories.map((category, row) => (
            <View key={category} style={[styles.dataRow, { borderTopColor: colors.raisedBorder }, row > 0 && styles.ruled]}>
              <Text style={[styles.dataName, { color: colors.text }]}>{category}</Text>
              <Text style={[styles.dataValues, { color: colors.textMuted }]}>
                {chart.series.map((series) => `${series.name}: ${mark(series.values[row] ?? 0)}`).join(' · ')}
              </Text>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  gap: { gap: 12 },
  title: { fontFamily: fonts.bold, fontSize: 15 },
  subtitle: { fontFamily: fonts.medium, fontSize: 13, marginTop: 2 },
  legend: { flexDirection: 'row', flexWrap: 'wrap', alignSelf: 'center', columnGap: 16, rowGap: 4, borderWidth: 1, paddingHorizontal: 10, paddingVertical: 6 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  key: { width: 12, height: 12 },
  legendText: { fontFamily: fonts.medium, fontSize: 12 },
  rows: { gap: 10 },
  name: { fontFamily: fonts.medium, fontSize: 13, marginBottom: 2 },
  track: { height: BAR_HEIGHT },
  bar: { position: 'absolute', left: 0, top: 0, height: BAR_HEIGHT, justifyContent: 'center', alignItems: 'flex-end' },
  whole: { position: 'absolute', left: 0, top: 0, height: BAR_HEIGHT },
  inside: { fontFamily: fonts.bold, fontSize: 13, paddingRight: 6 },
  end: { position: 'absolute', top: 3, paddingLeft: 8, fontFamily: fonts.medium, fontSize: 13 },
  axis: { height: 22, borderTopWidth: 1.5 },
  tick: { position: 'absolute', top: 4, width: 24, textAlign: 'center', fontFamily: fonts.medium, fontSize: 12 },
  unit: { fontFamily: fonts.medium, fontStyle: 'italic', fontSize: 13, textAlign: 'center' },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 32 },
  toggleText: { fontFamily: fonts.semibold, fontSize: 13 },
  data: { borderWidth: 1, borderRadius: 8 },
  dataRow: { paddingHorizontal: 12, paddingVertical: 8, gap: 2 },
  ruled: { borderTopWidth: 1 },
  dataName: { fontFamily: fonts.semibold, fontSize: 13 },
  dataValues: { fontFamily: fonts.medium, fontSize: 12 },
});
