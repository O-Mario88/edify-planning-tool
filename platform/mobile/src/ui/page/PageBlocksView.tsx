/**
 * A page's blocks, in the order the page draws them. Each kind is drawn the
 * way the web draws that component on a phone; a kind the app does not know
 * yet is left out, never guessed at.
 */
import { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { PageBlock, PageFacts, PageSegments } from '../../gen/edify/screens/v1/page_pb';
import { fonts, useTheme } from '../../theme';
import { PageChartView } from './PageChartView';
import { PageFilterBar } from './PageFilterBar';
import { PageLinkTabsView } from './PageLinkTabsView';
import { PageListView } from './PageListView';
import { PageChipsView } from './PageChipsView';
import { PagePanelView } from './PagePanelView';
import { PageRailView } from './PageRailView';
import { PageStripView } from './PageStripView';
import { EmptyState, PageTableView } from './PageTableView';
import { ChipContext, cardStyles, usePageLink } from './shared';

interface PageBlocksViewProps {
  readonly blocks: readonly PageBlock[];
  /** A filter changed: the page's query parameter, its new value and the
   * hidden values the filter form sends with it. */
  readonly onFilter: (name: string, value: string, hidden: Readonly<Record<string, string>>) => void;
  /** Filters on the card colour (a profile) rather than the field colour. */
  readonly isRaised?: boolean;
}

export function PageBlocksView({ blocks, onFilter, isRaised = true }: PageBlocksViewProps) {
  // The page's chip filters start on the values its script starts them on.
  const opening = useMemo(
    () =>
      Object.fromEntries(
        blocks.flatMap((block) => (block.kind.case === 'chips' ? [[block.kind.value.name, block.kind.value.value]] : [])),
      ),
    [blocks],
  );
  const [chosen, setChosen] = useState<Record<string, string>>(opening);
  const chips = useMemo(
    () => ({ chosen: { ...opening, ...chosen }, choose: (name: string, value: string) => setChosen((now) => ({ ...now, [name]: value })) }),
    [chosen, opening],
  );
  return (
    <ChipContext.Provider value={chips}>
      <View style={styles.stack}>
        {blocks.map((block, index) => (
          <Block key={index} block={block} onFilter={onFilter} isRaised={isRaised} />
        ))}
      </View>
    </ChipContext.Provider>
  );
}

interface BlockProps {
  readonly block: PageBlock;
  readonly onFilter: PageBlocksViewProps['onFilter'];
  readonly isRaised?: boolean;
}

function Block({ block, onFilter, isRaised = true }: BlockProps) {
  const { colors } = useTheme();
  const kind = block.kind;
  switch (kind.case) {
    case 'scopeLine':
      return <Text style={[styles.scope, { color: colors.textMuted }]}>{kind.value}</Text>;
    case 'facts':
      return <FactsCard facts={kind.value} />;
    case 'filters':
      return <PageFilterBar filters={kind.value} onFilter={onFilter} isRaised={isRaised} />;
    case 'linkTabs':
      return <PageLinkTabsView tabs={kind.value} />;
    case 'list':
      return <PageListView list={kind.value} />;
    case 'chips':
      return <PageChipsView chips={kind.value} />;
    case 'strip':
      return <PageStripView strip={kind.value} />;
    case 'table':
      return <PageTableView table={kind.value} />;
    case 'rail':
      return <PageRailView rail={kind.value} />;
    case 'chart':
      return <PageChartView chart={kind.value} />;
    case 'panel':
      return <PagePanelView panel={kind.value} />;
    case 'segments':
      return <SegmentsCard segments={kind.value} onFilter={onFilter} />;
    case 'empty':
      return <EmptyState message={kind.value} />;
    default:
      return null;
  }
}

/** The profile's identity card: its facts two to a row. */
function FactsCard({ facts }: { readonly facts: PageFacts }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  return (
    <View
      accessibilityLabel="Profile details"
      style={[cardStyles.card, cardStyles.padded, styles.facts, { backgroundColor: colors.raised, borderColor: colors.border }]}
    >
      {facts.facts.map((fact) => (
        <View key={fact.label} style={styles.fact}>
          <Text style={[styles.factLabel, { color: colors.textMuted }]}>{fact.label}</Text>
          <Text
            onPress={fact.href ? () => openLink(fact.href) : undefined}
            accessibilityRole={fact.href ? 'link' : 'text'}
            style={[styles.factValue, { color: colors.text, fontFamily: fact.href ? fonts.medium : fonts.semibold }]}
          >
            {fact.value}
          </Text>
        </View>
      ))}
    </View>
  );
}

/** A card that switches between parts of itself (Participation's Planned and
 * Completed), drawn in the page's segment shape. */
function SegmentsCard({ segments, onFilter }: { readonly segments: PageSegments; readonly onFilter: PageBlocksViewProps['onFilter'] }) {
  const { colors } = useTheme();
  const opening = Math.max(0, segments.segments.findIndex((segment) => segment.active));
  const [open, setOpen] = useState(opening);
  const shown = segments.segments[open];
  return (
    <View style={[cardStyles.card, styles.clip, { backgroundColor: colors.raised, borderColor: colors.border }]}>
      <View style={styles.titlebar}>
        <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
          {segments.title}
        </Text>
        {segments.subtitle ? <Text style={[styles.subtitle, { color: colors.text }]}>{segments.subtitle}</Text> : null}
      </View>
      <View style={styles.switchArea}>
        <View style={[styles.switch, { backgroundColor: colors.surface }]} accessibilityRole="tablist">
          {segments.segments.map((segment, index) => {
            const isOn = index === open;
            return (
              <Pressable
                key={segment.label}
                onPress={() => setOpen(index)}
                accessibilityRole="tab"
                accessibilityState={{ selected: isOn }}
                style={[styles.segment, isOn && { backgroundColor: colors.segmentActive }, index === 0 && styles.first]}
              >
                <Text style={[styles.segmentText, { color: isOn ? '#ffffff' : colors.textMuted }]}>{segment.label}</Text>
                {segment.count ? (
                  <View style={[styles.count, { backgroundColor: isOn ? 'rgba(255,255,255,0.22)' : colors.border }]}>
                    <Text style={[styles.countText, { color: isOn ? '#ffffff' : colors.text }]}>{segment.count}</Text>
                  </View>
                ) : null}
              </Pressable>
            );
          })}
        </View>
        {segments.caption ? <Text style={[styles.caption, { color: colors.textMuted }]}>{segments.caption}</Text> : null}
      </View>
      {shown?.blocks.map((block, index) => {
        if (block.kind.case === 'table') {
          return <PageTableView key={index} table={block.kind.value} isBare />;
        }
        return <Block key={index} block={block} onFilter={onFilter} />;
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 16 },
  scope: { fontFamily: fonts.medium, fontSize: 13 },
  facts: { flexDirection: 'row', flexWrap: 'wrap', rowGap: 12 },
  fact: { width: '50%', paddingRight: 8, gap: 2 },
  factLabel: { fontFamily: fonts.semibold, fontSize: 12 },
  factValue: { fontSize: 13 },
  clip: { overflow: 'hidden' },
  titlebar: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 12, rowGap: 4, paddingHorizontal: 16, paddingVertical: 12 },
  title: { fontFamily: fonts.bold, fontSize: 15 },
  subtitle: { fontFamily: fonts.medium, fontSize: 13 },
  switchArea: { paddingHorizontal: 16, paddingBottom: 12, gap: 8 },
  switch: { flexDirection: 'row', alignSelf: 'flex-start', borderRadius: 10 },
  segment: { flexDirection: 'row', alignItems: 'center', gap: 8, height: 32, paddingHorizontal: 14 },
  first: { borderTopLeftRadius: 8, borderBottomLeftRadius: 8 },
  segmentText: { fontFamily: fonts.semibold, fontSize: 13 },
  count: { borderRadius: 999, paddingHorizontal: 7, paddingVertical: 1 },
  countText: { fontFamily: fonts.semibold, fontSize: 12 },
  caption: { fontFamily: fonts.medium, fontSize: 12 },
});
