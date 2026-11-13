/**
 * The Calendar page's month (PageBlock.calendar) as the web draws it on a
 * phone (calendar/index.html's calendar-mobile section): the event-type tabs
 * with their counts, the month as a small Monday-first grid with a dot for
 * each kind a day holds, ‹ Today › around it, and the chosen day's entries
 * under it ("All month" shows every day). Each entry is in its family's
 * colour; a later day of a run has a dotted edge; work on a holiday or a
 * leave day is red with a solid edge. An activity the reader may move or
 * cancel has a tick box for the page's bar; ticking one day of a run ticks
 * every day of it, as they share one activity.
 */
import { ChevronLeft, ChevronRight } from 'lucide-react-native';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { PageCalendar, PageCalendarEvent, PagePanel } from '../../gen/edify/screens/v1/page_pb';
import { fonts, radius, useTheme } from '../../theme';
import {
  DOT_COLOURS,
  type CalendarDayView,
  type CalendarFilter,
  type CalendarMonthView,
  dayHeading,
  dotKinds,
  eventTone,
  kindFilter,
  longDate,
  mondayOffset,
  monthFilter,
  monthOf,
  todayFilter,
} from './calendarMonth';
import { TickBox } from './PageTableView';
import { cardStyles, usePageLink, usePicks } from './shared';

const INITIALS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'] as const;
/** A grid cell: a seventh of the row. */
const CELL_WIDTH = `${100 / 7}%` as const;

interface PageCalendarViewProps {
  readonly calendar: PageCalendar;
  /** The phone month and month card the block stands in for, for their words. */
  readonly panels: readonly PagePanel[];
  /** The page filter form's hidden values (year, month, event_kind, person). */
  readonly hidden: Readonly<Record<string, string>>;
  readonly onFilter: (name: string, value: string, hidden: Readonly<Record<string, string>>) => void;
}

export function PageCalendarView({ calendar, panels, hidden, onFilter }: PageCalendarViewProps) {
  const month = monthOf(calendar, panels);
  const move = (change: CalendarFilter) => onFilter(change.name, change.value, change.hidden);
  return (
    <View style={styles.stack}>
      <KindTabs calendar={calendar} onPick={(kind) => move(kindFilter(hidden, kind))} />
      {/* A new month starts on its own today, as the page opens it. */}
      <MonthCard
        key={`${month.year}-${month.month}-${month.kind}`}
        month={month}
        onStep={(step) => move(monthFilter(hidden, month.year, month.month, step))}
        onToday={() => move(todayFilter(hidden))}
      />
    </View>
  );
}

function KindTabs({ calendar, onPick }: { readonly calendar: PageCalendar; readonly onPick: (kind: string) => void }) {
  const { colors } = useTheme();
  const open = calendar.kind || 'all';
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabScroll}>
      <View style={[styles.tabs, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]} accessibilityRole="tablist">
        {calendar.kinds.map((tab, index) => {
          const isOn = tab.value === open;
          return (
            <Pressable
              key={tab.value}
              onPress={() => onPick(tab.value)}
              accessibilityRole="tab"
              accessibilityState={{ selected: isOn }}
              accessibilityLabel={`${tab.label}, ${tab.count}`}
              style={[styles.tab, isOn && { backgroundColor: colors.segmentActive }, index === 0 && styles.first]}
            >
              <Text style={[styles.tabText, { color: isOn ? '#ffffff' : colors.text }]}>{tab.label}</Text>
              <View style={[styles.count, { backgroundColor: isOn ? 'rgba(255,255,255,0.22)' : colors.border }]}>
                <Text style={[styles.countText, { color: isOn ? '#ffffff' : colors.text }]}>{tab.count}</Text>
              </View>
            </Pressable>
          );
        })}
      </View>
    </ScrollView>
  );
}

interface MonthCardProps {
  readonly month: CalendarMonthView;
  readonly onStep: (step: -1 | 1) => void;
  readonly onToday: () => void;
}

function MonthCard({ month, onStep, onToday }: MonthCardProps) {
  const { colors } = useTheme();
  const [chosen, setChosen] = useState(month.today);
  const shown = month.days.filter((day) => day.events.length > 0 && (!chosen || day.day === chosen));
  const empty = chosen ? 'No events for this date.' : month.empty;
  return (
    <View
      style={[cardStyles.card, styles.clip, { backgroundColor: colors.raised, borderColor: colors.border }]}
      accessibilityLabel={month.title}
    >
      <View style={styles.header}>
        <View style={styles.headerWords}>
          {month.eyebrow ? <Text style={[styles.eyebrow, { color: colors.eyebrow }]}>{month.eyebrow.toUpperCase()}</Text> : null}
          <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
            {month.title}
          </Text>
        </View>
        <View style={styles.nav}>
          <Pressable onPress={() => onStep(-1)} accessibilityRole="button" accessibilityLabel="Previous month" hitSlop={10}>
            <ChevronLeft size={18} color={colors.text} />
          </Pressable>
          <Pressable onPress={onToday} accessibilityRole="button" hitSlop={8}>
            <Text style={[styles.todayLink, { color: colors.accentText }]}>Today</Text>
          </Pressable>
          <Pressable onPress={() => onStep(1)} accessibilityRole="button" accessibilityLabel="Next month" hitSlop={10}>
            <ChevronRight size={18} color={colors.text} />
          </Pressable>
        </View>
      </View>
      <MonthGrid month={month} chosen={chosen} onChoose={setChosen} />
      <View style={[styles.daySection, { borderTopColor: colors.border }]}>
        <View style={styles.dayHead}>
          <Text style={[styles.eyebrow, { color: colors.textMuted }]}>SELECTED DAY</Text>
          <Text style={[styles.title, { color: colors.text }]}>{chosen ? longDate(month.year, month.month, chosen) : month.title}</Text>
          <View style={styles.dayTools}>
            <Pressable
              onPress={() => setChosen(0)}
              accessibilityRole="button"
              accessibilityState={{ selected: !chosen }}
              style={[styles.allMonth, { backgroundColor: colors.primarySoft }]}
            >
              <Text style={[styles.allMonthText, { color: colors.accentText }]}>All month</Text>
            </Pressable>
            <SelectAll picks={month.picks} />
          </View>
        </View>
        <Agenda month={month} days={shown} empty={empty} />
      </View>
    </View>
  );
}

interface MonthGridProps {
  readonly month: CalendarMonthView;
  readonly chosen: number;
  readonly onChoose: (day: number) => void;
}

function MonthGrid({ month, chosen, onChoose }: MonthGridProps) {
  const { colors, isDark } = useTheme();
  const lead = mondayOffset(month.year, month.month);
  return (
    <View style={styles.grid} accessibilityLabel={month.title}>
      {INITIALS.map((initial, index) => (
        <Text key={`initial-${index}`} style={[styles.cell, styles.initial, { color: colors.textMuted }]}>
          {initial}
        </Text>
      ))}
      {Array.from({ length: lead }, (_, index) => (
        <View key={`lead-${index}`} style={styles.cell} />
      ))}
      {month.days.map((day) => {
        const isChosen = chosen === day.day;
        const isToday = month.today === day.day && !isChosen;
        const count = day.events.length;
        return (
          <Pressable
            key={day.day}
            onPress={() => onChoose(day.day)}
            accessibilityRole="button"
            accessibilityState={{ selected: isChosen }}
            accessibilityLabel={`${longDate(month.year, month.month, day.day)}${count ? `, ${count} events` : ''}`}
            style={[styles.cell, styles.dayCell]}
          >
            <View
              style={[
                styles.dayNumber,
                isChosen && { backgroundColor: colors.primary },
                isToday && { borderWidth: 2, borderColor: colors.primary },
              ]}
            >
              <Text style={[styles.dayText, { color: isChosen ? colors.primaryInk : colors.text }]}>{day.day}</Text>
            </View>
            <View style={styles.dots}>
              {dotKinds(day).map((kind) => (
                <View key={kind} style={[styles.dot, { backgroundColor: DOT_COLOURS[kind]?.[isDark ? 'dark' : 'light'] }]} />
              ))}
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

/** "Select all" on the month: ticks or clears every activity the reader may tick. */
function SelectAll({ picks }: { readonly picks: readonly string[] }) {
  const { colors } = useTheme();
  const pick = usePicks();
  if (!pick.isOn || picks.length === 0) {
    return null;
  }
  const isAll = picks.every((id) => pick.picked.includes(id));
  const isPart = !isAll && picks.some((id) => pick.picked.includes(id));
  return (
    <Pressable
      onPress={() => pick.set(picks, !isAll)}
      accessibilityRole="checkbox"
      accessibilityState={{ checked: isAll ? true : isPart ? 'mixed' : false }}
      style={styles.selectAll}
      hitSlop={6}
    >
      <TickBox isOn={isAll} isPart={isPart} />
      <Text style={[styles.selectAllText, { color: colors.text }]}>Select all</Text>
    </Pressable>
  );
}

interface AgendaProps {
  readonly month: CalendarMonthView;
  readonly days: readonly CalendarDayView[];
  readonly empty: string;
}

function Agenda({ month, days, empty }: AgendaProps) {
  const { colors } = useTheme();
  if (days.length === 0) {
    return <Text style={[styles.empty, { color: colors.textMuted }]}>{empty}</Text>;
  }
  return (
    <View>
      {days.map((day) => (
        <View key={day.day} style={[styles.agendaDay, { borderTopColor: colors.border }]}>
          <View style={styles.agendaHead}>
            <Text style={[styles.agendaTitle, { color: colors.text }]}>{dayHeading(month.year, month.month, day.day)}</Text>
            {day.day === month.today ? (
              <View style={[styles.todayPill, { backgroundColor: colors.primarySoft }]}>
                <Text style={[styles.todayPillText, { color: colors.accentText }]}>Today</Text>
              </View>
            ) : null}
          </View>
          <View style={styles.chips}>
            {day.events.map((event, index) => (
              <EventChip key={index} event={event} />
            ))}
          </View>
        </View>
      ))}
    </View>
  );
}

function EventChip({ event }: { readonly event: PageCalendarEvent }) {
  const { isDark } = useTheme();
  const openLink = usePageLink();
  const pick = usePicks();
  const tone = eventTone(event, isDark);
  const isPickable = pick.isOn && event.pickId !== '';
  const isTicked = isPickable && pick.picked.includes(event.pickId);
  const edge = tone.edge
    ? { borderLeftWidth: 3, borderColor: tone.edge, borderStyle: 'solid' as const }
    : event.continued
      ? { borderLeftWidth: 3, borderColor: tone.ink, borderStyle: 'dotted' as const, borderTopLeftRadius: 0, borderBottomLeftRadius: 0 }
      : null;
  const words = (
    <>
      <Text style={[styles.chipTitle, { color: tone.ink }]}>{event.title}</Text>
      {event.meta ? <Text style={[styles.chipMeta, { color: tone.ink }]}>{event.meta}</Text> : null}
    </>
  );
  return (
    <View style={[styles.chip, { backgroundColor: tone.fill }, edge]}>
      {isPickable ? (
        <Pressable
          onPress={() => pick.set([event.pickId], !isTicked)}
          accessibilityRole="checkbox"
          accessibilityState={{ checked: isTicked }}
          accessibilityLabel={`Select ${event.title}${event.meta ? `, ${event.meta}` : ''}`}
          hitSlop={8}
          style={styles.chipTick}
        >
          <TickBox isOn={isTicked} />
        </Pressable>
      ) : null}
      {event.href ? (
        <Pressable onPress={() => openLink(event.href)} accessibilityRole="link" style={styles.chipBody}>
          {words}
        </Pressable>
      ) : (
        <View style={styles.chipBody}>{words}</View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  tabScroll: { flexGrow: 0 },
  tabs: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: radius.sm },
  tab: { flexDirection: 'row', alignItems: 'center', gap: 8, height: 36, paddingHorizontal: 14 },
  first: { borderTopLeftRadius: radius.sm - 1, borderBottomLeftRadius: radius.sm - 1 },
  tabText: { fontFamily: fonts.semibold, fontSize: 12 },
  count: { borderRadius: radius.pill, paddingHorizontal: 7, paddingVertical: 1 },
  countText: { fontFamily: fonts.semibold, fontSize: 12 },
  clip: { overflow: 'hidden' },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingTop: 16 },
  headerWords: { flexShrink: 1 },
  eyebrow: { fontFamily: fonts.semibold, fontSize: 12, letterSpacing: 0.4 },
  title: { fontFamily: fonts.bold, fontSize: 16 },
  nav: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  todayLink: { fontFamily: fonts.semibold, fontSize: 13 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 12, paddingTop: 12, paddingBottom: 16, rowGap: 4 },
  cell: { width: CELL_WIDTH, alignItems: 'center' },
  initial: { fontFamily: fonts.semibold, fontSize: 12, textAlign: 'center', paddingBottom: 4 },
  dayCell: { height: 44, justifyContent: 'center' },
  dayNumber: { width: 32, height: 32, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center' },
  dayText: { fontFamily: fonts.semibold, fontSize: 14 },
  dots: { flexDirection: 'row', gap: 2, height: 6 },
  dot: { width: 6, height: 6, borderRadius: 3 },
  daySection: { borderTopWidth: 1, paddingVertical: 12 },
  dayHead: { paddingHorizontal: 16, paddingBottom: 8, gap: 2 },
  dayTools: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 8 },
  allMonth: { borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 6 },
  allMonthText: { fontFamily: fonts.semibold, fontSize: 13 },
  selectAll: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  selectAllText: { fontFamily: fonts.semibold, fontSize: 13 },
  empty: { fontFamily: fonts.medium, fontSize: 13, paddingHorizontal: 16, paddingVertical: 16 },
  agendaDay: { borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 12, gap: 8 },
  agendaHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  agendaTitle: { fontFamily: fonts.bold, fontSize: 13 },
  todayPill: { borderRadius: radius.pill, paddingHorizontal: 8 },
  todayPillText: { fontFamily: fonts.semibold, fontSize: 12 },
  chips: { gap: 6 },
  chip: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, borderRadius: radius.xs, paddingHorizontal: 8, paddingVertical: 6 },
  chipTick: { paddingTop: 1 },
  chipBody: { flex: 1, minWidth: 0 },
  chipTitle: { fontFamily: fonts.semibold, fontSize: 12.5 },
  chipMeta: { fontFamily: fonts.medium, fontSize: 12.5, opacity: 0.8 },
});
