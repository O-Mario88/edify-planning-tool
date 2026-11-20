/**
 * A page's blocks, in the order the page draws them. Each kind is drawn the
 * way the web draws that component on a phone; a kind the app does not know
 * yet is left out, never guessed at.
 */
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import type { PageBlock, PageFacts, PagePanel, PageSegments } from '../../gen/edify/screens/v1/page_pb';
import { fonts, useTheme } from '../../theme';
import { PageChartView } from './PageChartView';
import { PageFilterBar } from './PageFilterBar';
import { PageFormView } from './PageFormView';
import { PageLinkTabsView } from './PageLinkTabsView';
import { PageListView } from './PageListView';
import { PageCalendarView } from './PageCalendarView';
import { PageChipsView } from './PageChipsView';
import { PagePanelView } from './PagePanelView';
import { PageRailView } from './PageRailView';
import { PageRecordView } from './PageRecordView';
import { PageStripView } from './PageStripView';
import { EmptyState, Explanation, PageTableView, Pager } from './PageTableView';
import { ChipContext, cardStyles, usePageLink } from './shared';
import { liftHeroes } from './heroStrip';
import { headingOnly, tableNote } from './tableNote';

/** A table's note on a card of its own, folded under its chevron. */
function NoteCard({ text }: { readonly text: string }) {
  const { colors } = useTheme();
  return (
    <View style={[cardStyles.card, { backgroundColor: colors.raised, borderColor: colors.border, overflow: 'hidden' }]}>
      <Explanation text={text} isBare />
    </View>
  );
}

interface PageBlocksViewProps {
  readonly blocks: readonly PageBlock[];
  /** A filter changed: the page's query parameter, its new value and the
   * hidden values the filter form sends with it. */
  readonly onFilter: (name: string, value: string, hidden: Readonly<Record<string, string>>) => void;
  /** Filters on the card colour (a profile) rather than the field colour. */
  readonly isRaised?: boolean;
  /** The page's web path, which names its hero figures (heroStrip). */
  readonly pagePath?: string;
}

export function PageBlocksView({ blocks, onFilter, isRaised = true, pagePath = '' }: PageBlocksViewProps) {
  const lifted = useMemo(() => liftHeroes(blocks, pagePath), [blocks, pagePath]);
  // The page's chip filters start on the values its script starts them on.
  const opening = useMemo(
    () =>
      Object.fromEntries(
        blocks.flatMap((block) => (block.kind.case === 'chips' ? [[block.kind.value.name, block.kind.value.value]] : [])),
      ),
    [blocks],
  );
  const [chosen, setChosen] = useState<Record<string, string>>(opening);
  // The page filter form's hidden values (the Calendar's year, month and tab).
  const hidden = useMemo(() => {
    const filters = blocks.find((block) => block.kind.case === 'filters');
    return filters?.kind.case === 'filters' ? filters.kind.value.hidden : {};
  }, [blocks]);
  const chips = useMemo(
    () => ({ chosen: { ...opening, ...chosen }, choose: (name: string, value: string) => setChosen((now) => ({ ...now, [name]: value })) }),
    [chosen, opening],
  );
  return (
    <ChipContext.Provider value={chips}>
      <View style={styles.stack}>
        {lifted.blocks.map((block, index) => {
          const blocks = lifted.blocks;
          const next = blocks[index + 1];
          // The page's hero figures lead it, larger (heroStrip, owner 2026-11-20).
          if (index === lifted.heroAt && block.kind.case === 'strip') {
            return <PageStripView key={index} strip={block.kind.value} isHero />;
          }
          // The calendar's month block stands in for the event-type segments
          // before it, which carry the same month as text (docs/migration/54.5).
          if (block.kind.case === 'segments' && next?.kind.case === 'calendar') {
            return null;
          }
          if (block.kind.case === 'calendar') {
            const before = blocks[index - 1];
            return (
              <PageCalendarView
                key={index}
                calendar={block.kind.value}
                panels={before?.kind.case === 'segments' ? segmentPanels(before.kind.value) : []}
                hidden={hidden}
                onFilter={onFilter}
              />
            );
          }
          // A table's note sent as its own block folds as a footnote does (2026-11-20).
          const note = tableNote(blocks, index);
          if (note) {
            return <NoteCard key={index} text={note} />;
          }
          // A panel that is only a title heads the block after it (2026-11-20).
          const heading = headingOnly(block);
          if (heading) {
            return <Block key={index} block={{ ...block, kind: { case: 'section', value: heading.title } } as PageBlock} onFilter={onFilter} isRaised={isRaised} />;
          }
          return <Block key={index} block={block} onFilter={onFilter} isRaised={isRaised} />;
        })}
      </View>
    </ChipContext.Provider>
  );
}

/** One page block on its own (a drawer's table or tabbed part). */
export function PageBlockView({ block }: { readonly block: PageBlock }) {
  return <Block block={block} onFilter={() => undefined} isRaised />;
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
    case 'section':
      // A heading between the page's sections: a title over what follows,
      // ruled off from the part above it, never a card.
      return (
        <View style={[styles.section, { borderTopColor: colors.border }]}>
          <Text style={[styles.sectionText, { color: colors.text }]} accessibilityRole="header">
            {kind.value}
          </Text>
        </View>
      );
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
    case 'record':
      return <PageRecordView record={kind.value} />;
    case 'form':
      return <PageFormView form={kind.value} />;
    case 'pager':
      return (
        <View style={[cardStyles.card, styles.clip, { backgroundColor: colors.raised, borderColor: colors.border }]}>
          <Pager pager={kind.value} isAlone />
        </View>
      );
    case 'empty':
      return <EmptyState message={kind.value} />;
    default:
      return null;
  }
}

/** The panels of a segments card's first part (the Calendar's phone month and month card). */
function segmentPanels(segments: PageSegments): readonly PagePanel[] {
  return (segments.segments[0]?.blocks ?? []).flatMap((block) => (block.kind.case === 'panel' ? [block.kind.value] : []));
}

/** The profile's identity card: its facts, "Label: value". */
const WIDE_FACTS = 768;

function FactsCard({ facts }: { readonly facts: PageFacts }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  // One to a line on a phone; side by side from a tablet up, as the web's
  // profile header flows them.
  const isWide = useWindowDimensions().width >= WIDE_FACTS;
  return (
    <View
      accessibilityLabel="Profile details"
      style={[cardStyles.card, cardStyles.padded, styles.facts, { backgroundColor: colors.raised, borderColor: colors.border }]}
    >
      {facts.facts.map((fact) => (
        <View key={fact.label} style={isWide ? styles.factWide : styles.fact}>
          {/* Owner 2026-11-12: a fact reads "Label: value" on one line, the value in blue. */}
          <Text style={[styles.factLabel, { color: colors.textMuted }]}>
            {fact.label}:{' '}
            <Text
              onPress={fact.href ? () => openLink(fact.href) : undefined}
              accessibilityRole={fact.href ? 'link' : 'text'}
              style={[styles.factValue, { color: colors.link }]}
            >
              {fact.value}
            </Text>
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
      {segments.title || segments.subtitle ? (
        <View style={styles.titlebar}>
          <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
            {segments.title}
          </Text>
          {segments.subtitle ? <Text style={[styles.subtitle, { color: colors.text }]}>{segments.subtitle}</Text> : null}
        </View>
      ) : null}
      <View style={[styles.switchArea, !(segments.title || segments.subtitle) && styles.switchAlone]}>
        {/* Owner 2026-10-02: a long strip scrolls sideways rather than clip. */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.switchScroll}>
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
        </ScrollView>
        {segments.caption ? <Text style={[styles.caption, { color: colors.textMuted }]}>{segments.caption}</Text> : null}
      </View>
      {shown?.blocks.map((block, index) => {
        if (block.kind.case === 'table') {
          return <PageTableView key={index} table={block.kind.value} isBare />;
        }
        const note = tableNote(shown.blocks, index);
        if (note) {
          return <Explanation key={index} text={note} />;
        }
        return <Block key={index} block={block} onFilter={onFilter} />;
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 16 },
  scope: { fontFamily: fonts.medium, fontSize: 13 },
  section: { borderTopWidth: 1, paddingTop: 14, marginTop: 6 },
  sectionText: { fontFamily: fonts.bold, fontSize: 17, letterSpacing: -0.2 },
  facts: { flexDirection: 'row', flexWrap: 'wrap', rowGap: 8 },
  fact: { width: '100%' },
  factWide: { marginRight: 32 },
  factLabel: { fontFamily: fonts.semibold, fontSize: 13 },
  factValue: { fontFamily: fonts.semibold, fontSize: 13 },
  clip: { overflow: 'hidden' },
  titlebar: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 12, rowGap: 4, paddingHorizontal: 16, paddingVertical: 12 },
  title: { fontFamily: fonts.bold, fontSize: 15 },
  subtitle: { fontFamily: fonts.medium, fontSize: 13 },
  switchArea: { paddingHorizontal: 16, paddingBottom: 12, gap: 8 },
  switchAlone: { paddingTop: 12 },
  switchScroll: { flexGrow: 0 },
  switch: { flexDirection: 'row', alignSelf: 'flex-start', borderRadius: 10 },
  segment: { flexDirection: 'row', alignItems: 'center', gap: 8, height: 32, paddingHorizontal: 14 },
  first: { borderTopLeftRadius: 8, borderBottomLeftRadius: 8 },
  segmentText: { fontFamily: fonts.semibold, fontSize: 13 },
  count: { borderRadius: 999, paddingHorizontal: 7, paddingVertical: 1 },
  countText: { fontFamily: fonts.semibold, fontSize: 12 },
  caption: { fontFamily: fonts.medium, fontSize: 12 },
});
