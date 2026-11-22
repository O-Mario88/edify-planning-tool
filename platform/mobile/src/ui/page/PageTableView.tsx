/**
 * A record table as the web draws it on a phone: a card with its title bar,
 * its rows as cards on a phone (owner, 2026-11-19: "Rows on phones", which
 * replaced 2026-09-27's tables stay tables; rowCard.ts picks each card's
 * title, ID, status and facts, the rest under "All details"; a long table,
 * 16 rows or more, a compact list whose rows open their card in a sheet), the table
 * scrolling sideways in its own region on a tablet, a note under it, or the
 * empty state in place of its rows.
 * The first time a table is wider than the screen, the slim orange "Swipe to
 * view more columns" pill shows over its header and leaves (owner,
 * 2026-10-02: never black, gone after about four seconds).
 */
import { useEffect, useRef, useState } from 'react';
import { Animated, Modal, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Check, ChevronDown, ChevronRight, Inbox, Minus, X } from 'lucide-react-native';

import type { PageAction, PageCell, PageColumn, PagePager, PageRow, PageTable } from '../../gen/edify/screens/v1/page_pb';
import type { Palette } from '../../theme';
import { fonts, useTheme } from '../../theme';
import { PageBlockView } from './PageBlocksView';
import { RowActions } from './RowActions';
import { asList, rowCard, summaryOf } from './rowCard';
import { titleCase } from './titleCase';
import type { RowCard, RowFact } from './rowCard';
import { cardStyles, toneColor, usePageLink, usePicks } from './shared';

/** The Actions column: the menu button, and a row's own button beside it. */
const ACTIONS_WIDTH = 104;
/** The column of a row's open/close chevron (the web's school-plan-table__expander). */
const EXPANDER_WIDTH = 32;
/** The tick-box column of rows the page's bar acts on (school-plan-table__select). */
const PICK_WIDTH = 40;
const ROW_BUTTON_WIDTH = 84;

const HINT_MS = 4000;
// White on the orange reads 4.84:1; the dark ink read 4.13:1 (axe, 2026-11-20).
const HINT = { fill: '#d85b13', ink: '#ffffff' } as const;
/** The hint shows once per session, as the web's does until a swipe. */
let hintSeen = false;
/** A phone's tables as row cards (owner, 2026-11-19), reversed for the spreadsheet on every screen (2026-11-20). */
const ROWS_ON_PHONES = false;
/** From this width (a tablet) a table is drawn as a table. */
const TABLE_FROM = 768;
/** A cell's own side padding, and the first and last columns' outer one: the
 *  card's 16pt content line (owner, 2026-11-20: "just make them look more
 *  premium", as the web's phone grid). */
const CELL_SIDE = 14;
const EDGE_SIDE = 16;
/** What an empty cell shows: a quiet dash, so an empty column reads as none. */
const NOTHING = '\u2014';

/** The outer padding of a column at the table's edge, if it is one. */
function edgePad(index: number, count: number, isLead: boolean): { paddingLeft?: number; paddingRight?: number } {
  return {
    ...(index === 0 && isLead ? { paddingLeft: EDGE_SIDE } : null),
    ...(index === count - 1 ? { paddingRight: EDGE_SIDE } : null),
  };
}

/** A column wide enough for its widest line (the web lays tables out by content). */
function columnWidth(column: PageColumn, cells: readonly PageCell[]): number {
  if (cells.some((cell) => cell.actions.length > 0)) {
    const buttons = Math.max(...cells.map((cell) => cell.actions.filter((action) => action.key === 'button').length));
    return ACTIONS_WIDTH + buttons * ROW_BUTTON_WIDTH;
  }
  const longest = Math.max(
    column.label.length * 8.4 + 32,
    ...cells.map((cell) => cell.text.length * (cell.strong || cell.href ? 7.6 : 7.2) + CELL_SIDE * 2),
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
  const { width } = useWindowDimensions();
  const asCards = ROWS_ON_PHONES && width < TABLE_FROM;
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
      ) : asCards && asList(table.rows.length) ? (
        <ListRows table={table} />
      ) : asCards ? (
        <Cards table={table} />
      ) : (
        <Grid table={table} />
      )}
      {table.pager ? <Pager pager={table.pager} /> : null}
      {table.footnote ? <Explanation text={table.footnote} /> : null}
    </View>
  );
}

/** Stable identifier for a row so filtering, sorting or paging cannot attach details to a different record. */
function stableRowKey(row: PageRow, fallbackIndex: number): string {
  if (row.pickId) return `pick:${row.pickId}`;
  if (row.detailsHref) return `detail:${row.detailsHref}`;
  const linked = row.cells.find((cell) => cell.href);
  if (linked?.href) return `href:${linked.href}:${row.cells[0]?.text ?? ''}`;
  const signature = row.cells
    .map((cell) => cell.text.trim())
    .filter(Boolean)
    .slice(0, 3)
    .join('|');
  return signature ? `sig:${signature}` : `row:${fallbackIndex}`;
}

function Grid({ table }: { readonly table: PageTable }) {
  const { colors } = useTheme();
  const [viewWidth, setViewWidth] = useState(0);
  const pick = usePicks();
  const pickable = pick.isOn ? table.rows.map((row) => row.pickId).filter((id) => id !== '') : [];
  // The first column leads the row when no tick box comes before it.
  const isLead = pickable.length === 0;
  const widths = table.columns.map((column, index) => {
    const edges = (index === 0 && isLead ? EDGE_SIDE - CELL_SIDE : 0) + (index === table.columns.length - 1 ? EDGE_SIDE - CELL_SIDE : 0);
    return (
      columnWidth(
        column,
        table.rows.map((row) => row.cells[index]).filter((cell): cell is PageCell => cell !== undefined),
      ) + edges
    );
  });
  const ticked = pickable.filter((id) => pick.picked.includes(id)).length;
  const contentWidth = widths.reduce((sum, width) => sum + width, 0) + (pickable.length > 0 ? PICK_WIDTH : 0);
  const isWide = viewWidth > 0 && contentWidth > viewWidth + 2;
  // As the web's table: one row open at a time, keyed by stable record ID.
  const [openRowKey, setOpenRowKey] = useState<string | null>(null);
  return (
    <View onLayout={(event) => setViewWidth(event.nativeEvent.layout.width)}>
      <ScrollView horizontal showsHorizontalScrollIndicator onScrollBeginDrag={() => (hintSeen = true)}>
        <View>
          {table.columns.length > 0 ? (
            <View style={[styles.row, styles.headRow, { backgroundColor: colors.tableHead, borderBottomColor: colors.borderStrong }]}>
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
              {table.columns.map((column, index) => (
                <Text
                  key={`${column.label}-${index}`}
                  numberOfLines={1}
                  style={[
                    styles.head,
                    { width: widths[index], color: colors.textMuted },
                    edgePad(index, table.columns.length, isLead),
                    column.numeric && styles.numeric,
                  ]}
                >
                  {titleCase(column.label)}
                </Text>
              ))}
            </View>
          ) : null}
          {table.rows.map((row, rowIndex) => {
            const rowKey = stableRowKey(row, rowIndex);
            return (
              <BodyRow
                key={rowKey}
                row={row}
                table={table}
                widths={widths}
                isFirst={rowIndex === 0}
                isLead={isLead}
                picks={pickable.length > 0}
                isOpen={openRowKey === rowKey}
                onToggle={() => setOpenRowKey(openRowKey === rowKey ? null : rowKey)}
                detailsWidth={viewWidth}
              />
            );
          })}
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
  /** The first column is the row's first cell (no tick box before it). */
  readonly isLead: boolean;
  /** The table's rows can be ticked for the page's bar: every row keeps the tick column. */
  readonly picks: boolean;
  readonly isOpen: boolean;
  readonly onToggle: () => void;
  /** The screen's width, which an open row's details fill. */
  readonly detailsWidth: number;
}

/** What a table's folded explanation says while it is closed. */
export const EXPLANATION_LABEL = 'Explanation';

/** A table's explanation (its footnote) folded under a chevron, closed until
 * tapped (owner, 2026-11-20: "they should by default be hidden and only
 * opened by tapping the unhide icon/chevron"), as the web's
 * (components/page/Explanation.tsx). */
export function Explanation({ text, isBare = false }: { readonly text: string; readonly isBare?: boolean }) {
  const { colors } = useTheme();
  const [isOpen, setOpen] = useState(false);
  return (
    <View style={isBare ? null : [styles.explain, { borderTopColor: colors.tableLine }]}>
      <Pressable
        onPress={() => setOpen(!isOpen)}
        accessibilityRole="button"
        accessibilityState={{ expanded: isOpen }}
        accessibilityLabel={EXPLANATION_LABEL}
        hitSlop={4}
        style={styles.explainToggle}
      >
        <View style={isOpen ? styles.explainOpen : null}>
          <ChevronDown size={16} color={colors.tableLink} />
        </View>
        <Text style={[styles.explainLabel, { color: colors.tableLink }]}>{EXPLANATION_LABEL}</Text>
      </Pressable>
      {isOpen ? <Text style={[styles.footnote, styles.explainText, { color: colors.textMuted }]}>{text}</Text> : null}
    </View>
  );
}

/** One record row: its cells, and what opening it shows under it. */
function BodyRow({ row, table, widths, isFirst, isLead, picks, isOpen, onToggle, detailsWidth }: BodyRowProps) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const pick = usePicks();
  const isTicked = row.pickId !== '' && pick.picked.includes(row.pickId);
  const canOpen = row.details.length > 0 || row.detailBlocks.length > 0 || row.detailsHref !== '';
  const primaryHref = row.detailsHref || row.cells.find((cell) => cell.href)?.href || '';
  return (
    <View>
      <Pressable
        disabled={!canOpen}
        onPress={onToggle}
        accessibilityState={canOpen ? { expanded: isOpen } : undefined}
        accessibilityHint={canOpen ? `${isOpen ? 'Hides' : 'Shows'} the details of ${rowName(row)}` : undefined}
        accessibilityActions={[
          ...(canOpen ? [{ name: 'activate', label: `${isOpen ? 'Hide' : 'Show'} details for ${rowName(row)}` }] : []),
          ...(primaryHref ? [{ name: 'openProfile', label: `Open ${rowName(row)} profile` }] : []),
        ]}
        onAccessibilityAction={(event) => {
          if (event.nativeEvent.actionName === 'openProfile' && primaryHref) {
            openLink(primaryHref);
          } else if (canOpen) {
            onToggle();
          }
        }}
        style={[
          styles.row,
          { borderTopColor: colors.tableLine },
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
        {row.cells.map((cell, index) => {
          if (cell.actions.length > 0) {
            return (
              <View key={index} style={[styles.cellBox, { width: widths[index] ?? ACTIONS_WIDTH }, edgePad(index, row.cells.length, isLead)]}>
                <RowActions actions={cell.actions} label={rowName(row)} />
              </View>
            );
          }
          const isEmpty = cell.text.trim() === '';
          const isLink = cell.href !== '' && !isEmpty;
          // A linked name is link blue, as on the web (2026-11-20); a row's or a cell's tone still wins.
          const color =
            rowInk(colors, row) ??
            toneColor(colors, cell.tone) ??
            (isEmpty ? colors.textSubtle : isLink ? colors.tableLink : cell.strong ? colors.text : colors.textMuted);
          const edge = edgePad(index, row.cells.length, isLead);
          return (
            <View key={index} style={[styles.cellBox, { width: widths[index] ?? 120, alignItems: table.columns[index]?.numeric ? 'flex-end' : 'flex-start' }, edge]}>
              <Text
                onPress={isLink ? () => openLink(cell.href) : undefined}
                accessibilityRole={isLink ? 'link' : undefined}
                style={[
                  styles.cell,
                  { color, fontFamily: cell.strong ? fonts.bold : isLink ? fonts.semibold : fonts.medium },
                  isEmpty && styles.nothing,
                  table.columns[index]?.numeric && styles.numeric,
                ]}
              >
                {isEmpty ? NOTHING : cell.text}
              </Text>
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
/** The soft fill behind a status word in its tone. */
function toneSoft(colors: Palette, tone: string): string {
  const ink = toneColor(colors, tone);
  if (ink === colors.success) return colors.successSoft;
  if (ink === colors.danger) return colors.dangerSoft;
  if (ink === colors.warning) return colors.warningSoft;
  if (ink === colors.link) return colors.infoSoft;
  return colors.surfaceMuted;
}

function Cards({ table }: { readonly table: PageTable }) {
  const { colors } = useTheme();
  const pick = usePicks();
  const pickable = pick.isOn ? table.rows.map((row) => row.pickId).filter((id) => id !== '') : [];
  const ticked = pickable.filter((id) => pick.picked.includes(id)).length;
  // As the table: one row open at a time.
  const [openRow, setOpenRow] = useState<number | null>(null);
  return (
    <View>
      {pickable.length > 0 ? (
        <Pressable
          onPress={() => pick.set(pickable, ticked < pickable.length)}
          accessibilityRole="checkbox"
          accessibilityState={{ checked: ticked === pickable.length ? true : ticked > 0 ? 'mixed' : false }}
          style={[styles.cardsAll, { borderTopColor: colors.raisedBorder }]}
        >
          <TickBox isOn={ticked === pickable.length} isPart={ticked > 0 && ticked < pickable.length} />
          <Text style={[styles.cardsAllText, { color: colors.textMuted }]}>Select all on this page</Text>
        </Pressable>
      ) : null}
      {table.rows.map((row, index) => (
        <RowCardView
          key={index}
          table={table}
          row={row}
          isOpen={openRow === index}
          onToggle={() => setOpenRow(openRow === index ? null : index)}
        />
      ))}
    </View>
  );
}

function FactGrid({ facts }: { readonly facts: readonly RowFact[] }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  return (
    <View style={styles.cardFacts}>
      {facts.map((fact, index) => (
        <View key={`${fact.label}-${index}`} style={styles.cardFact}>
          <Text style={[styles.cardFactLabel, { color: colors.textMuted }]}>{fact.label}</Text>
          <Text
            onPress={fact.cell.href ? () => openLink(fact.cell.href) : undefined}
            accessibilityRole={fact.cell.href ? 'link' : undefined}
            style={[styles.cardFactValue, { color: fact.cell.href ? colors.link : (toneColor(colors, fact.cell.tone) ?? colors.text) }]}
          >
            {fact.cell.text}
          </Text>
        </View>
      ))}
    </View>
  );
}

interface RowCardViewProps {
  readonly table: PageTable;
  readonly row: PageRow;
  readonly isOpen: boolean;
  readonly onToggle: () => void;
}

function RowCardView({ table, row, isOpen, onToggle }: RowCardViewProps) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const pick = usePicks();
  const card = rowCard(table.columns, row);
  const name = rowName(row);
  const isTicked = row.pickId !== '' && pick.picked.includes(row.pickId);
  const more = card.rest.length > 0 || row.details.length > 0 || row.detailsHref !== '' || row.detailBlocks.length > 0;
  const statusInk = card.status ? (toneColor(colors, card.status.tone) ?? colors.text) : colors.text;
  return (
    <View
      style={[
        styles.card,
        { borderTopColor: colors.raisedBorder },
        row.tone === 'overdue' ? { borderLeftWidth: 3, borderLeftColor: colors.danger } : null,
        row.tone === 'done' ? { backgroundColor: colors.successSoft } : null,
      ]}
    >
      <View style={styles.cardHead}>
        {pick.isOn && row.pickId ? (
          <Pressable
            onPress={() => pick.set([row.pickId], !isTicked)}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: isTicked }}
            accessibilityLabel={row.pickLabel || `Select ${name}`}
            hitSlop={10}
            style={styles.cardTick}
          >
            <TickBox isOn={isTicked} />
          </Pressable>
        ) : null}
        <View style={styles.cardName}>
          <Text
            onPress={card.title?.href ? () => openLink(card.title?.href ?? '') : undefined}
            accessibilityRole={card.title?.href ? 'link' : 'header'}
            style={[styles.cardTitle, { color: card.title?.href ? colors.link : colors.text }]}
          >
            {card.title?.text ?? name}
          </Text>
          {card.id ? (
            <Text style={[styles.cardId, { color: colors.textMuted }]}>
              {card.id.label} {card.id.cell.text}
            </Text>
          ) : null}
        </View>
        {card.status ? (
          <View style={[styles.cardStatus, { backgroundColor: toneSoft(colors, card.status.tone) }]}>
            <Text style={[styles.cardStatusText, { color: statusInk }]}>{card.status.text}</Text>
          </View>
        ) : null}
      </View>
      {card.lead.length > 0 ? <FactGrid facts={card.lead} /> : null}
      {more || card.actions ? (
        <View style={styles.cardFoot}>
          {more ? (
            <Pressable
              onPress={onToggle}
              accessibilityRole="button"
              accessibilityState={{ expanded: isOpen }}
              accessibilityLabel={`${isOpen ? 'Hide' : 'All'} details of ${name}`}
              hitSlop={8}
              style={styles.cardMore}
            >
              <Text style={[styles.cardMoreText, { color: colors.link }]}>{isOpen ? 'Hide details' : 'All details'}</Text>
              {isOpen ? <ChevronDown size={14} color={colors.link} /> : <ChevronRight size={14} color={colors.link} />}
            </Pressable>
          ) : (
            <View />
          )}
          {card.actions ? <RowActions actions={card.actions.actions} label={name} /> : null}
        </View>
      ) : null}
      {isOpen ? (
        <View style={[styles.cardDetails, { backgroundColor: colors.surface }]}>
          {card.rest.length > 0 ? <FactGrid facts={card.rest} /> : null}
          {row.details.length > 0 || row.detailsHref || row.detailBlocks.length > 0 ? <RowDetails row={row} width={0} /> : null}
        </View>
      ) : null}
    </View>
  );
}

interface SheetContentProps {
  readonly card: RowCard;
  readonly row: PageRow;
  readonly onClose: () => void;
}

/** A row's whole card, in the sheet a compact list opens. */
function SheetContent({ card, row, onClose }: SheetContentProps) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const name = rowName(row);
  const statusInk = card.status ? (toneColor(colors, card.status.tone) ?? colors.text) : colors.text;
  return (
    <View style={styles.sheetBody}>
      <View style={styles.cardHead}>
        <View style={styles.cardName}>
          <Text
            onPress={card.title?.href ? () => openLink(card.title?.href ?? '') : undefined}
            accessibilityRole={card.title?.href ? 'link' : 'header'}
            style={[styles.sheetTitle, { color: card.title?.href ? colors.link : colors.text }]}
          >
            {card.title?.text ?? name}
          </Text>
          {card.id ? (
            <Text style={[styles.cardId, { color: colors.textMuted }]}>
              {card.id.label} {card.id.cell.text}
            </Text>
          ) : null}
        </View>
        {card.status ? (
          <View style={[styles.cardStatus, { backgroundColor: toneSoft(colors, card.status.tone) }]}>
            <Text style={[styles.cardStatusText, { color: statusInk }]}>{card.status.text}</Text>
          </View>
        ) : null}
        <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close" hitSlop={8} style={[styles.sheetClose, { backgroundColor: colors.surface }]}>
          <X size={18} color={colors.text} />
        </Pressable>
      </View>
      {card.lead.length + card.rest.length > 0 ? <FactGrid facts={[...card.lead, ...card.rest]} /> : null}
      {row.details.length > 0 || row.detailsHref || row.detailBlocks.length > 0 ? <RowDetails row={row} width={0} /> : null}
      {card.actions ? (
        <View style={styles.sheetActions}>
          <RowActions actions={card.actions.actions} label={name} />
        </View>
      ) : null}
    </View>
  );
}

/** A long table (a directory) on a phone: one line a row, its card in a sheet. */
function ListRows({ table }: { readonly table: PageTable }) {
  const { colors } = useTheme();
  const pick = usePicks();
  const pickable = pick.isOn ? table.rows.map((row) => row.pickId).filter((id) => id !== '') : [];
  const ticked = pickable.filter((id) => pick.picked.includes(id)).length;
  const [open, setOpen] = useState<number | null>(null);
  const openRow = open !== null ? table.rows[open] : undefined;
  return (
    <View>
      {pickable.length > 0 ? (
        <Pressable
          onPress={() => pick.set(pickable, ticked < pickable.length)}
          accessibilityRole="checkbox"
          accessibilityState={{ checked: ticked === pickable.length ? true : ticked > 0 ? 'mixed' : false }}
          style={[styles.cardsAll, { borderTopColor: colors.raisedBorder }]}
        >
          <TickBox isOn={ticked === pickable.length} isPart={ticked > 0 && ticked < pickable.length} />
          <Text style={[styles.cardsAllText, { color: colors.textMuted }]}>Select all on this page</Text>
        </Pressable>
      ) : null}
      {table.rows.map((row, index) => {
        const card = rowCard(table.columns, row);
        const name = rowName(row);
        const isTicked = row.pickId !== '' && pick.picked.includes(row.pickId);
        const line = [card.id ? `${card.id.label} ${card.id.cell.text}` : '', summaryOf(card)].filter((s) => s !== '').join(' · ');
        return (
          <View
            key={index}
            style={[styles.listRow, { borderTopColor: colors.raisedBorder }, row.tone === 'overdue' ? { borderLeftWidth: 3, borderLeftColor: colors.danger } : null]}
          >
            {pick.isOn && row.pickId ? (
              <Pressable
                onPress={() => pick.set([row.pickId], !isTicked)}
                accessibilityRole="checkbox"
                accessibilityState={{ checked: isTicked }}
                accessibilityLabel={row.pickLabel || `Select ${name}`}
                hitSlop={10}
              >
                <TickBox isOn={isTicked} />
              </Pressable>
            ) : null}
            <Pressable
              onPress={() => setOpen(index)}
              accessibilityRole="button"
              accessibilityLabel={[card.title?.text ?? name, line].filter(Boolean).join('. ')}
              accessibilityHint="Opens its details"
              style={styles.listOpen}
            >
              <Text style={[styles.listTitle, { color: colors.text }]}>{card.title?.text ?? name}</Text>
              {line ? <Text style={[styles.listLine, { color: colors.textMuted }]}>{line}</Text> : null}
            </Pressable>
            <ChevronRight size={16} color={colors.textMuted} />
          </View>
        );
      })}
      <Modal visible={openRow !== undefined} transparent animationType="slide" onRequestClose={() => setOpen(null)}>
        <View style={styles.sheetLayer}>
          <Pressable style={styles.sheetBackdrop} onPress={() => setOpen(null)} accessibilityRole="button" accessibilityLabel="Close details" />
          <View style={[styles.sheet, { backgroundColor: colors.raised }]}>
            <ScrollView>{openRow ? <SheetContent card={rowCard(table.columns, openRow)} row={openRow} onClose={() => setOpen(null)} /> : null}</ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

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
  cardsAll: { flexDirection: 'row', alignItems: 'center', gap: 8, borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 10 },
  cardsAllText: { fontFamily: fonts.semibold, fontSize: 12 },
  card: { borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 14, gap: 10 },
  cardHead: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  cardTick: { paddingTop: 2 },
  cardName: { flex: 1, minWidth: 0, gap: 2 },
  cardTitle: { fontFamily: fonts.bold, fontSize: 14, lineHeight: 19 },
  cardId: { fontFamily: fonts.medium, fontSize: 12 },
  cardStatus: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 2, flexShrink: 0 },
  cardStatusText: { fontFamily: fonts.semibold, fontSize: 12, lineHeight: 18 },
  cardFacts: { flexDirection: 'row', flexWrap: 'wrap', rowGap: 8 },
  cardFact: { width: '50%', paddingRight: 12, gap: 1 },
  cardFactLabel: { fontFamily: fonts.medium, fontSize: 12 },
  cardFactValue: { fontFamily: fonts.semibold, fontSize: 13 },
  cardFoot: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  cardMore: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 36 },
  cardMoreText: { fontFamily: fonts.semibold, fontSize: 13 },
  cardDetails: { borderRadius: 10, overflow: 'hidden', gap: 10, paddingTop: 12 },
  listRow: { flexDirection: 'row', alignItems: 'center', gap: 10, borderTopWidth: 1, paddingHorizontal: 16 },
  listOpen: { flex: 1, minHeight: 52, justifyContent: 'center', paddingVertical: 9, gap: 2 },
  listTitle: { fontFamily: fonts.semibold, fontSize: 14, lineHeight: 19 },
  listLine: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 16 },
  sheetLayer: { flex: 1, justifyContent: 'flex-end' },
  sheetBackdrop: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: 'rgba(15, 23, 42, 0.45)' },
  sheet: { maxHeight: '85%', borderTopLeftRadius: 18, borderTopRightRadius: 18, paddingBottom: 28 },
  sheetBody: { padding: 16, gap: 14 },
  sheetTitle: { fontFamily: fonts.bold, fontSize: 16, lineHeight: 21 },
  sheetClose: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  sheetActions: { alignItems: 'flex-end' },
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
  headRow: { borderBottomWidth: 1 },
  ruled: { borderTopWidth: 1 },
  head: {
    fontFamily: fonts.bold,
    fontSize: 14,
    lineHeight: 32,
    paddingHorizontal: CELL_SIDE,
  },
  cellBox: { minHeight: 32, justifyContent: 'center', paddingHorizontal: CELL_SIDE, paddingVertical: 7 },
  cell: { fontSize: 13, lineHeight: 18 },
  nothing: { opacity: 0.7 },
  numeric: { textAlign: 'right' },
  footnote: { fontFamily: fonts.semibold, fontSize: 13, lineHeight: 18, paddingHorizontal: 16, paddingVertical: 10 },
  explain: { borderTopWidth: 1 },
  explainToggle: { flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: 6, minHeight: 44, paddingHorizontal: 16 },
  explainOpen: { transform: [{ rotate: '180deg' }] },
  explainLabel: { fontFamily: fonts.semibold, fontSize: 13 },
  explainText: { paddingTop: 0 },
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
