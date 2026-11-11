/**
 * A record table as the web draws it on a phone: a card with its title bar,
 * the table scrolling sideways in its own region (owner, 2026-09-27: tables
 * stay tables), a note under it, or the empty state in place of its rows.
 * The first time a table is wider than the screen, the slim orange "Swipe to
 * view more columns" pill shows over its header and leaves (owner,
 * 2026-10-02: never black, gone after about four seconds).
 */
import { useEffect, useRef, useState } from 'react';
import { Animated, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Check, ChevronDown, ChevronRight, Inbox, Minus } from 'lucide-react-native';

import type { PageAction, PageCell, PageColumn, PagePager, PageRow, PageTable } from '../../gen/edify/screens/v1/page_pb';
import type { Palette } from '../../theme';
import { fonts, useTheme } from '../../theme';
import { PageBlockView } from './PageBlocksView';
import { RowActions } from './RowActions';
import { cardStyles, toneColor, usePageLink, usePicks } from './shared';

/** The Actions column: the menu button, and a row's own button beside it. */
const ACTIONS_WIDTH = 104;
/** The column of a row's open/close chevron (the web's school-plan-table__expander). */
const EXPANDER_WIDTH = 32;
/** The tick-box column of rows the page's bar acts on (school-plan-table__select). */
const PICK_WIDTH = 40;
const ROW_BUTTON_WIDTH = 84;

const HINT_MS = 4000;
const HINT = { fill: '#d85b13', ink: '#17232b' } as const;
/** The hint shows once per session, as the web's does until a swipe. */
let hintSeen = false;

/** A column wide enough for its widest line (the web lays tables out by content). */
function columnWidth(column: PageColumn, cells: readonly PageCell[]): number {
  if (cells.some((cell) => cell.actions.length > 0)) {
    const buttons = Math.max(...cells.map((cell) => cell.actions.filter((action) => action.key === 'button').length));
    return ACTIONS_WIDTH + buttons * ROW_BUTTON_WIDTH;
  }
  const longest = Math.max(
    column.label.length * 8.4 + 32,
    ...cells.map((cell) => cell.text.length * (cell.strong ? 7.6 : 7.2) + 24),
  );
  return Math.round(Math.min(Math.max(longest, 64), 300));
}

interface PageTableViewProps {
  readonly table: PageTable;
  /** Drawn inside another card (a segment): no card of its own. */
  readonly isBare?: boolean;
}

export function PageTableView({ table, isBare = false }: PageTableViewProps) {
  const { colors } = useTheme();
  const hasTitle = table.title !== '' || table.subtitle !== '' || table.count !== '';
  return (
    <View
      style={
        isBare
          ? undefined
          : [cardStyles.card, styles.clip, { backgroundColor: colors.raised, borderColor: colors.border }]
      }
    >
      {hasTitle ? (
        <View style={styles.titlebar}>
          <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
            {table.title}
          </Text>
          {table.subtitle ? <Text style={[styles.subtitle, { color: colors.text }]}>{table.subtitle}</Text> : null}
          {table.count ? (
            <Text style={[styles.count, { color: colors.text }]} accessibilityLabel={`${table.count} listed`}>
              {table.count}
            </Text>
          ) : null}
        </View>
      ) : null}
      {table.rows.length === 0 && table.emptyMessage ? (
        <EmptyState message={table.emptyMessage} action={table.emptyAction} />
      ) : (
        <Grid table={table} />
      )}
      {table.pager ? <Pager pager={table.pager} /> : null}
      {table.footnote ? <Text style={[styles.footnote, { color: colors.textMuted }]}>{table.footnote}</Text> : null}
    </View>
  );
}

function Grid({ table }: { readonly table: PageTable }) {
  const { colors } = useTheme();
  const [viewWidth, setViewWidth] = useState(0);
  const widths = table.columns.map((column, index) =>
    columnWidth(
      column,
      table.rows.map((row) => row.cells[index]).filter((cell): cell is PageCell => cell !== undefined),
    ),
  );
  const opens = table.rows.some((row) => row.details.length > 0 || row.detailsHref !== '');
  const pick = usePicks();
  const pickable = pick.isOn ? table.rows.map((row) => row.pickId).filter((id) => id !== '') : [];
  const ticked = pickable.filter((id) => pick.picked.includes(id)).length;
  const contentWidth =
    widths.reduce((sum, width) => sum + width, 0) + (opens ? EXPANDER_WIDTH : 0) + (pickable.length > 0 ? PICK_WIDTH : 0);
  const isWide = viewWidth > 0 && contentWidth > viewWidth + 2;
  // As the web's table: one row open at a time.
  const [openRow, setOpenRow] = useState<number | null>(null);
  return (
    <View onLayout={(event) => setViewWidth(event.nativeEvent.layout.width)}>
      <ScrollView horizontal showsHorizontalScrollIndicator onScrollBeginDrag={() => (hintSeen = true)}>
        <View>
          {table.columns.length > 0 ? (
            <View style={[styles.row, { backgroundColor: colors.tableHead }]}>
              {pickable.length > 0 ? (
                <Pressable
                  onPress={() => pick.set(pickable, ticked < pickable.length)}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: ticked === pickable.length ? true : ticked > 0 ? 'mixed' : false }}
                  accessibilityLabel="Select all on this page"
                  style={[styles.pickCell, { width: PICK_WIDTH }]}
                >
                  <TickBox isOn={ticked === pickable.length} isPart={ticked > 0 && ticked < pickable.length} />
                </Pressable>
              ) : null}
              {opens ? <View style={{ width: EXPANDER_WIDTH }} /> : null}
              {table.columns.map((column, index) => (
                <Text
                  key={`${column.label}-${index}`}
                  numberOfLines={1}
                  style={[
                    styles.head,
                    { width: widths[index], color: colors.textMuted },
                    column.numeric && styles.numeric,
                  ]}
                >
                  {column.label}
                </Text>
              ))}
            </View>
          ) : null}
          {table.rows.map((row, rowIndex) => (
            <BodyRow
              key={rowIndex}
              row={row}
              table={table}
              widths={widths}
              isFirst={rowIndex === 0}
              opens={opens}
              picks={pickable.length > 0}
              isOpen={openRow === rowIndex}
              onToggle={() => setOpenRow(openRow === rowIndex ? null : rowIndex)}
              detailsWidth={viewWidth}
            />
          ))}
        </View>
      </ScrollView>
      {isWide ? <ScrollHint /> : null}
    </View>
  );
}

interface BodyRowProps {
  readonly row: PageRow;
  readonly table: PageTable;
  readonly widths: readonly number[];
  readonly isFirst: boolean;
  /** The table has rows that open: every row keeps the chevron column. */
  readonly opens: boolean;
  /** The table's rows can be ticked for the page's bar: every row keeps the tick column. */
  readonly picks: boolean;
  readonly isOpen: boolean;
  readonly onToggle: () => void;
  /** The screen's width, which an open row's details fill. */
  readonly detailsWidth: number;
}

/** One record row: its cells, and what opening it shows under it. */
function BodyRow({ row, table, widths, isFirst, opens, picks, isOpen, onToggle, detailsWidth }: BodyRowProps) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const pick = usePicks();
  const isTicked = row.pickId !== '' && pick.picked.includes(row.pickId);
  const canOpen = row.details.length > 0 || row.detailsHref !== '';
  return (
    <View>
      <Pressable
        disabled={!canOpen}
        onPress={onToggle}
        accessibilityState={canOpen ? { expanded: isOpen } : undefined}
        accessibilityHint={canOpen ? `${isOpen ? 'Hides' : 'Shows'} the details of ${rowName(row)}` : undefined}
        style={[
          styles.row,
          { borderTopColor: colors.raisedBorder },
          !isFirst && styles.ruled,
          row.tone === 'done' ? { backgroundColor: colors.successSoft } : null,
          isOpen ? { backgroundColor: colors.primarySoft } : null,
        ]}
      >
        {picks ? (
          <View style={[styles.pickCell, { width: PICK_WIDTH }]}>
            {row.pickId ? (
              <Pressable
                onPress={() => pick.set([row.pickId], !isTicked)}
                accessibilityRole="checkbox"
                accessibilityState={{ checked: isTicked }}
                accessibilityLabel={row.pickLabel || `Select ${rowName(row)}`}
                hitSlop={8}
              >
                <TickBox isOn={isTicked} />
              </Pressable>
            ) : null}
          </View>
        ) : null}
        {opens ? (
          <View style={[styles.expander, { width: EXPANDER_WIDTH }]}>
            {canOpen && isOpen ? <ChevronDown size={14} color={colors.textMuted} /> : null}
            {canOpen && !isOpen ? <ChevronRight size={14} color={colors.textMuted} /> : null}
          </View>
        ) : null}
        {row.cells.map((cell, index) => {
          if (cell.actions.length > 0) {
            return (
              <View key={index} style={[styles.cellBox, { width: widths[index] ?? ACTIONS_WIDTH }]}>
                <RowActions actions={cell.actions} label={rowName(row)} />
              </View>
            );
          }
          const color = rowInk(colors, row) ?? toneColor(colors, cell.tone) ?? (cell.strong ? colors.text : colors.textMuted);
          const text = (
            <Text
              numberOfLines={2}
              style={[
                styles.cell,
                { color, fontFamily: cell.strong ? fonts.bold : fonts.medium },
                table.columns[index]?.numeric && styles.numeric,
              ]}
            >
              {cell.text}
            </Text>
          );
          return cell.href ? (
            <Pressable
              key={index}
              onPress={() => openLink(cell.href)}
              accessibilityRole="link"
              style={[styles.cellBox, { width: widths[index] ?? 120 }]}
            >
              {text}
            </Pressable>
          ) : (
            <View key={index} style={[styles.cellBox, { width: widths[index] ?? 120 }]}>
              {text}
            </View>
          );
        })}
      </Pressable>
      {isOpen ? <RowDetails row={row} width={detailsWidth} /> : null}
    </View>
  );
}

/** What an open row shows under it, as wide as the screen: the record's
 * "Label: value" facts and the link to its own page. */
function RowDetails({ row, width }: { readonly row: PageRow; readonly width: number }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  return (
    <View style={[styles.details, { width: width || undefined, borderTopColor: colors.raisedBorder, backgroundColor: colors.surface }]}>
      {row.detailsHref ? (
        <Text onPress={() => openLink(row.detailsHref)} accessibilityRole="link" style={[styles.detailsLink, { color: colors.link }]}>
          Open {rowName(row)} profile
        </Text>
      ) : null}
      <View style={styles.detailFacts}>
        {row.details.map((fact) => (
          <Text key={fact.label} style={[styles.detailLabel, { color: colors.textMuted }]}>
            {fact.label}:{' '}
            <Text
              onPress={fact.href ? () => openLink(fact.href) : undefined}
              accessibilityRole={fact.href ? 'link' : undefined}
              style={[styles.detailValue, { color: toneColor(colors, fact.tone) ?? colors.link }]}
            >
              {fact.value}
            </Text>
          </Text>
        ))}
      </View>
      {row.detailBlocks.map((block, index) => (
        <PageBlockView key={index} block={block} />
      ))}
    </View>
  );
}

/** The tick a row or record card shows for the page's bar; part-filled when
 * some of a table's rows are ticked. */
export function TickBox({ isOn, isPart = false }: { readonly isOn: boolean; readonly isPart?: boolean }) {
  const { colors } = useTheme();
  const isFilled = isOn || isPart;
  return (
    <View
      style={[
        styles.tick,
        { borderColor: isFilled ? colors.primary : colors.borderStrong, backgroundColor: isFilled ? colors.primary : colors.raised },
      ]}
    >
      {isOn ? <Check size={12} color={colors.primaryInk} /> : isPart ? <Minus size={12} color={colors.primaryInk} /> : null}
    </View>
  );
}

function ScrollHint() {
  const [isShown, setIsShown] = useState(!hintSeen);
  const fade = useRef(new Animated.Value(1)).current;
  const nudge = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!isShown) {
      return undefined;
    }
    hintSeen = true;
    const step = (to: number) => Animated.timing(nudge, { toValue: to, duration: 400, useNativeDriver: true });
    Animated.sequence([Animated.delay(400), step(-6), step(0), step(-6), step(0)]).start();
    const timer = setTimeout(() => {
      Animated.timing(fade, { toValue: 0, duration: 300, useNativeDriver: true }).start(() => setIsShown(false));
    }, HINT_MS);
    return () => clearTimeout(timer);
  }, [fade, isShown, nudge]);
  if (!isShown) {
    return null;
  }
  return (
    <Animated.View
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[styles.hint, { opacity: fade, transform: [{ translateX: nudge }] }]}
    >
      <Text style={styles.hintText}>Swipe to view more columns</Text>
    </Animated.View>
  );
}

/** A finished row is green and an overdue one red, in every cell but its
 * actions (row-state.css). */
function rowInk(colors: Palette, row: PageRow): string | undefined {
  if (row.tone === 'done') {
    return colors.success;
  }
  return row.tone === 'overdue' ? colors.danger : undefined;
}

/** What a row is called in its menu's label: the record it links to (a
 * school's name), else its first cell. */
function rowName(row: PageRow): string {
  const linked = row.cells.find((cell) => cell.href && cell.text);
  return linked?.text || row.cells.find((cell) => cell.text)?.text || 'this row';
}

/** The shared table pager: "Showing 1–50 of 51" and the page buttons. */
export function Pager({ pager, isAlone = false }: { readonly pager: PagePager; readonly isAlone?: boolean }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  return (
    <View
      style={[styles.pager, isAlone ? styles.pagerAlone : { borderTopColor: colors.raisedBorder }]}
      accessibilityRole="toolbar"
    >
      <Text style={[styles.pagerSummary, { color: colors.textSubtle }]}>{pager.summary}</Text>
      <View style={styles.pagerControls}>
        {pager.pages.map((page, index) =>
          page.href && !page.current ? (
            <Pressable
              key={`${page.label}-${index}`}
              onPress={() => openLink(page.href)}
              accessibilityRole="button"
              accessibilityLabel={/^\d+$/.test(page.label) ? `Page ${page.label}` : page.label}
              style={[styles.pageButton, { borderColor: colors.border, backgroundColor: colors.raised }]}
            >
              <Text style={[styles.pageText, { color: colors.text }]}>{page.label}</Text>
            </Pressable>
          ) : (
            <View
              key={`${page.label}-${index}`}
              accessibilityState={{ selected: page.current }}
              style={[styles.pageButton, page.current ? { backgroundColor: colors.primary, borderColor: colors.primary } : styles.pageGap]}
            >
              <Text style={[styles.pageText, { color: page.current ? colors.primaryInk : colors.textSubtle }]}>{page.label}</Text>
            </View>
          ),
        )}
      </View>
    </View>
  );
}

/** The platform empty state; with a way out (My Plan's "Open Planning"), the
 * web draws it as one line with the link under the sentence. */
export function EmptyState({ message, action }: { readonly message: string; readonly action?: PageAction }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  if (action) {
    return (
      <View style={styles.emptyLine}>
        <Text style={[styles.emptyLineText, { color: colors.textMuted }]}>{message}</Text>
        <Text
          onPress={() => openLink(action.href)}
          accessibilityRole="link"
          style={[styles.emptyLink, { color: colors.link }]}
        >
          {action.label} →
        </Text>
      </View>
    );
  }
  return (
    <View style={styles.empty}>
      <View style={[styles.emptyMark, { backgroundColor: colors.surfaceMuted }]}>
        <Inbox size={18} color={colors.textSubtle} />
      </View>
      <Text style={[styles.emptyText, { color: colors.textMuted }]}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  clip: { overflow: 'hidden' },
  expander: { alignItems: 'center', justifyContent: 'center', alignSelf: 'stretch' },
  pickCell: { alignItems: 'center', justifyContent: 'center', alignSelf: 'stretch' },
  tick: { width: 16, height: 16, borderWidth: 1, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  details: { borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 12, gap: 8 },
  detailsLink: { fontFamily: fonts.semibold, fontSize: 12 },
  detailFacts: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 18, rowGap: 6 },
  detailLabel: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 17 },
  detailValue: { fontFamily: fonts.bold, fontSize: 12 },
  titlebar: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'baseline',
    columnGap: 12,
    rowGap: 4,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  title: { flexShrink: 1, fontFamily: fonts.bold, fontSize: 15 },
  subtitle: { fontFamily: fonts.medium, fontSize: 13 },
  count: { marginLeft: 'auto', fontFamily: fonts.semibold, fontSize: 13 },
  emptyLine: { paddingHorizontal: 16, paddingVertical: 14, gap: 2 },
  emptyLineText: { fontFamily: fonts.medium, fontSize: 13 },
  emptyLink: { alignSelf: 'flex-start', fontFamily: fonts.semibold, fontSize: 13, textDecorationLine: 'underline' },
  pager: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12, borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 12 },
  pagerSummary: { fontFamily: fonts.semibold, fontSize: 12 },
  pagerAlone: { borderTopWidth: 0 },
  pagerControls: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  pageButton: { minWidth: 44, minHeight: 44, borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, alignItems: 'center', justifyContent: 'center' },
  pageGap: { borderColor: 'transparent' },
  pageText: { fontFamily: fonts.bold, fontSize: 12 },
  row: { flexDirection: 'row' },
  ruled: { borderTopWidth: 1 },
  head: {
    fontFamily: fonts.bold,
    fontSize: 14,
    lineHeight: 32,
    paddingHorizontal: 12,
    textTransform: 'capitalize',
  },
  cellBox: { minHeight: 32, justifyContent: 'center', paddingHorizontal: 12, paddingVertical: 6 },
  cell: { fontSize: 13 },
  numeric: { textAlign: 'right' },
  footnote: { fontFamily: fonts.semibold, fontSize: 13, lineHeight: 18, paddingHorizontal: 16, paddingVertical: 10 },
  empty: { alignItems: 'center', gap: 8, paddingHorizontal: 16, paddingVertical: 20 },
  emptyMark: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  emptyText: { fontFamily: fonts.medium, fontSize: 13, textAlign: 'center' },
  hint: {
    position: 'absolute',
    top: 7,
    right: 20,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 2,
    backgroundColor: HINT.fill,
  },
  hintText: { fontFamily: fonts.semibold, fontSize: 12, color: HINT.ink },
});
