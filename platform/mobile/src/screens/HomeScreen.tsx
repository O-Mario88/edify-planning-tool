/**
 * Home: the web app's phone Home (templates/pages/home/index.html), drawn
 * natively from the same view-model, without the greeting band (owner,
 * 2026-11-19). Sizes and colours are that page's own
 * (static/css/pages/home.css).
 */
import { useCallback, useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ApiError } from '../api/connect';
import { describe, useSession } from '../auth/SessionContext';
import type {
  GetHomeResponse,
  HomeFigure,
  HomePriorityRow,
  HomeUpcoming,
} from '../gen/edify/screens/v1/home_pb';
import { fonts, radius, toneColors, useTheme } from '../theme';
import { routeShortcuts } from './route/routeData';
import { SvgIcon } from '../ui/SvgIcon';

const MORNING_ENDS = 12;
const AFTERNOON_ENDS = 17;

/** The greeting for the phone's own clock, as the web page re-words it. */
function greetingNow(): string {
  const hour = new Date().getHours();
  if (hour < MORNING_ENDS) {
    return 'Good morning';
  }
  return hour < AFTERNOON_ENDS ? 'Good afternoon' : 'Good evening';
}

interface HomeScreenProps {
  /** Open a path of the app: a native screen if there is one, else the web. */
  readonly onOpen: (url: string, label: string) => void;
}

interface QueueState {
  readonly rows: readonly HomePriorityRow[];
  readonly total: number | null;
  readonly hasPlan: boolean;
}

export function HomeScreen({ onOpen }: HomeScreenProps) {
  const { api, signOut, state } = useSession();
  const role = state.status === 'signedIn' ? state.session.activeRole : '';
  const { colors } = useTheme();
  const [home, setHome] = useState<GetHomeResponse | null>(null);
  const [figures, setFigures] = useState<readonly HomeFigure[]>([]);
  const [queue, setQueue] = useState<QueueState | null>(null);
  const [queueError, setQueueError] = useState(false);
  const [error, setError] = useState('');

  const guard = useCallback(
    async (cause: unknown): Promise<boolean> => {
      if (cause instanceof ApiError && cause.code === 'unauthenticated') {
        await signOut();
        return true;
      }
      return false;
    },
    [signOut],
  );

  /** Swap the To-Do figures into their tiles, as /home/queue does. */
  const mergeFigures = useCallback((incoming: readonly HomeFigure[]) => {
    setFigures((current) => current.map((f) => incoming.find((n) => n.key === f.key) ?? f));
  }, []);

  const loadQueue = useCallback(async () => {
    setQueueError(false);
    try {
      const answer = await api.getHomeQueue();
      mergeFigures(answer.queueFigures);
      setQueue({ rows: answer.priorityRows, total: answer.priorityTotal ?? null, hasPlan: answer.hasPlan });
      if (answer.todoFiguresLater) {
        const later = await api.getHomeTodoFigures();
        mergeFigures(later.queueFigures);
        setQueue((current) => (current ? { ...current, total: later.priorityTotal } : current));
      }
    } catch (cause) {
      if (!(await guard(cause))) {
        setQueueError(true);
      }
    }
  }, [api, guard, mergeFigures]);

  const load = useCallback(async () => {
    setError('');
    try {
      const answer = await api.getHome();
      if (answer.redirectUrl) {
        onOpen(answer.redirectUrl, 'Schools');
        return;
      }
      setHome(answer);
      setFigures(answer.figures);
      void loadQueue();
    } catch (cause) {
      if (!(await guard(cause))) {
        setError(describe(cause));
      }
    }
  }, [api, guard, loadQueue, onOpen]);

  useEffect(() => {
    void load();
  }, [load]);

  const glyph = (name: string) => home?.glyphs[name] ?? '';
  const cardStyle = [styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }];

  return (
    <ScrollView contentContainerStyle={styles.page}>
      {/* The work first (owner, 2026-11-19: drop the greeting band on
          phones): the role and the greeting on two quiet lines. */}
      <View style={styles.head}>
        <Text style={[styles.headRole, { color: colors.textSubtle }]}>
          {home?.roleTitle ? `Home · ${home.roleTitle}` : 'Home'}
        </Text>
        <Text style={[styles.headGreeting, { color: colors.text }]} accessibilityRole="header">
          {greetingNow()}
          {home?.firstName ? `, ${home.firstName}` : ''}
        </Text>
      </View>

      {error ? (
        <View style={cardStyle}>
          <Empty title="Home did not load" copy={error} cta="Try again" onPress={() => void load()} />
        </View>
      ) : null}

      {home ? (
        <>
          <View style={cardStyle}>
            <View style={styles.cardHead}>
              <Text style={[styles.cardTitle, { color: colors.text }]}>Today’s overview</Text>
              <Text style={[styles.date, { color: colors.textMuted }]}>
                {home.todayLabel} · FY{home.fy}
              </Text>
            </View>
            <View style={styles.grid}>
              {figures.map((figure) => (
                <FigureTile key={figure.key} figure={figure} onOpen={onOpen} />
              ))}
            </View>
          </View>

          <View style={cardStyle}>
            <View style={styles.cardHead}>
              <View style={styles.cardTitleRow}>
                <SvgIcon xml={glyph('bolt')} size={18} color={colors.primary} />
                <Text style={[styles.cardTitle, { color: colors.text }]}>Priority actions</Text>
              </View>
              {queue && queue.total !== null ? (
                <Pressable
                  onPress={() => onOpen('/todos', 'To-Do')}
                  accessibilityRole="link"
                  accessibilityLabel={`To-Dos ${queue.total}`}
                  style={styles.seeAll}
                  hitSlop={12}
                >
                  <Text style={[styles.seeAllText, { color: colors.link }]}>To-Dos {queue.total}</Text>
                  <SvgIcon xml={glyph('arrow')} size={16} color={colors.link} />
                </Pressable>
              ) : null}
            </View>
            {queueError ? (
              <Empty
                title="Your priority actions did not load"
                copy="Check your connection, then try again."
                cta="Try again"
                onPress={() => void loadQueue()}
              />
            ) : null}
            {!queue && !queueError ? <Skeleton /> : null}
            {queue && queue.rows.length === 0 ? (
              <Empty
                title="Nothing needs you right now"
                copy="New work appears here as soon as it is yours to do."
                cta={queue.hasPlan ? 'Open My Plan' : undefined}
                onPress={() => onOpen('/my-plan', 'My Plan')}
              />
            ) : null}
            {queue && queue.rows.length > 0 ? (
              <View style={styles.list}>
                {queue.rows.map((row) => (
                  <PriorityRow key={row.key || row.title} row={row} chevron={glyph('chevron')} clock={glyph('clock')} onOpen={onOpen} />
                ))}
              </View>
            ) : null}
          </View>

          {routeShortcuts(home.shortcuts, role).length > 0 ? (
            <View style={cardStyle}>
              <View style={styles.cardHead}>
                <View style={styles.cardTitleRow}>
                  <SvgIcon xml={glyph('grid')} size={18} color={colors.primary} />
                  <Text style={[styles.cardTitle, { color: colors.text }]}>Quick access</Text>
                </View>
              </View>
              <View style={styles.grid}>
                {routeShortcuts(home.shortcuts, role).map((shortcut) => (
                  <Pressable
                    key={shortcut.url}
                    onPress={() => onOpen(shortcut.url, shortcut.label)}
                    accessibilityRole="link"
                    accessibilityLabel={shortcut.label}
                    style={[styles.shortcut, { borderColor: colors.raisedBorder }]}
                  >
                    <SvgIcon xml={shortcut.iconSvg} size={24} color={colors.primary} />
                    <Text style={[styles.shortcutLabel, { color: colors.text }]} numberOfLines={1}>
                      {shortcut.label}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          ) : null}

          {home.hasPlan ? (
            <View style={cardStyle}>
              <View style={styles.cardHead}>
                <View style={styles.cardTitleRow}>
                  <SvgIcon xml={glyph('calendar')} size={18} color={colors.primary} />
                  <Text style={[styles.cardTitle, { color: colors.text }]}>Upcoming activities</Text>
                </View>
                {home.upcoming.length > 0 ? (
                  <Pressable
                    onPress={() => onOpen('/my-plan?status=upcoming', 'My Plan')}
                    accessibilityRole="link"
                    style={styles.seeAll}
                    hitSlop={12}
                  >
                    <Text style={[styles.seeAllText, { color: colors.link }]}>View all</Text>
                    <SvgIcon xml={glyph('arrow')} size={16} color={colors.link} />
                  </Pressable>
                ) : null}
              </View>
              {home.upcoming.length === 0 ? (
                <Empty
                  title="No activities coming up"
                  copy="Plan your next visit or training and it will show here."
                  cta="Open My Plan"
                  onPress={() => onOpen('/my-plan', 'My Plan')}
                />
              ) : (
                <View style={styles.list}>
                  {home.upcoming.map((activity) => (
                    <UpcomingRow key={activity.id} activity={activity} chevron={glyph('chevron')} onOpen={onOpen} />
                  ))}
                </View>
              )}
            </View>
          ) : null}
        </>
      ) : null}
    </ScrollView>
  );
}

type Open = (url: string, label: string) => void;

function FigureTile({ figure, onOpen }: { readonly figure: HomeFigure; readonly onOpen: Open }) {
  const { colors } = useTheme();
  const tone = toneColors(colors, figure.tone);
  const isTinted = figure.tone === 'brand' || figure.tone === 'info';
  return (
    <Pressable
      onPress={() => onOpen(figure.url, figure.label)}
      accessibilityRole="link"
      accessibilityLabel={`${figure.label}: ${figure.loading ? 'loading' : figure.value}. ${figure.description}`}
      style={[
        styles.figure,
        { borderColor: colors.raisedBorder, backgroundColor: isTinted ? tone.soft : colors.surface },
      ]}
    >
      <SvgIcon xml={figure.iconSvg} size={18} color={tone.fg} />
      {figure.loading ? (
        <View style={[styles.skeleton, styles.skeletonValue, { backgroundColor: colors.border }]} />
      ) : (
        <Text style={[styles.figureValue, { color: colors.text }]} numberOfLines={1} adjustsFontSizeToFit>
          {figure.value}
        </Text>
      )}
      <Text style={[styles.figureLabel, { color: colors.textMuted }]} numberOfLines={2}>
        {figure.label}
      </Text>
    </Pressable>
  );
}

interface PriorityRowProps {
  readonly row: HomePriorityRow;
  readonly chevron: string;
  readonly clock: string;
  readonly onOpen: Open;
}

function PriorityRow({ row, chevron, clock, onOpen }: PriorityRowProps) {
  const { colors } = useTheme();
  const mark = toneColors(colors, row.markTone || row.statusTone);
  const status = toneColors(colors, row.statusTone);
  const due = toneColors(colors, row.dueTone);
  return (
    <Pressable
      onPress={() => onOpen(row.url, row.title)}
      accessibilityRole="link"
      accessibilityLabel={`${row.title}. ${row.context}. ${row.statusLabel}. ${row.actionLabel}`}
      style={[styles.item, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}
    >
      <View style={[styles.mark, { backgroundColor: mark.soft }]}>
        <SvgIcon xml={row.iconSvg} size={20} color={mark.fg} />
      </View>
      <View style={styles.itemBody}>
        <Text style={[styles.itemName, { color: colors.text }]} numberOfLines={2}>
          {row.title}
        </Text>
        {row.context ? (
          <Text style={[styles.itemSub, { color: colors.textMuted }]} numberOfLines={1}>
            {row.context}
          </Text>
        ) : null}
        <View style={styles.tags}>
          {row.statusLabel ? (
            <View style={[styles.tag, { backgroundColor: status.soft }]}>
              <Text style={[styles.tagText, { color: status.fg }]}>{row.statusLabel}</Text>
            </View>
          ) : null}
          {row.dueLabel ? (
            <View style={styles.due}>
              <SvgIcon xml={clock} size={12} color={due.fg} />
              <Text style={[styles.tagText, { color: due.fg }]}>{row.dueLabel}</Text>
            </View>
          ) : null}
        </View>
      </View>
      <View style={styles.go}>
        <Text style={[styles.goText, { color: colors.link }]}>{row.actionLabel}</Text>
        <SvgIcon xml={chevron} size={16} color={colors.link} />
      </View>
    </Pressable>
  );
}

interface UpcomingRowProps {
  readonly activity: HomeUpcoming;
  readonly chevron: string;
  readonly onOpen: Open;
}

function UpcomingRow({ activity, chevron, onOpen }: UpcomingRowProps) {
  const { colors } = useTheme();
  const name = activity.where ? `${activity.title} — ${activity.where}` : activity.title;
  const sub = [activity.time, activity.typeLabel, activity.statusLabel].filter(Boolean).join(' · ');
  return (
    <Pressable
      onPress={() => onOpen(activity.url, activity.title)}
      accessibilityRole="link"
      accessibilityLabel={`${name}. ${sub}`}
      style={[styles.item, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}
    >
      <View
        style={[
          styles.datebox,
          { backgroundColor: activity.isToday ? colors.primary : colors.primarySoft },
        ]}
      >
        <Text style={[styles.dateMonth, { color: activity.isToday ? colors.primaryInk : colors.accentText }]}>
          {activity.isToday ? 'TODAY' : activity.month}
        </Text>
        <Text style={[styles.dateDay, { color: activity.isToday ? colors.primaryInk : colors.accentText }]}>
          {activity.day}
        </Text>
      </View>
      <View style={styles.itemBody}>
        <Text style={[styles.itemName, { color: colors.text }]} numberOfLines={2}>
          {name}
        </Text>
        <Text style={[styles.itemSub, { color: colors.textMuted }]} numberOfLines={1}>
          {sub}
        </Text>
      </View>
      <SvgIcon xml={chevron} size={16} color={colors.textSubtle} />
    </Pressable>
  );
}

interface EmptyProps {
  readonly title: string;
  readonly copy: string;
  readonly cta?: string;
  readonly onPress: () => void;
}

function Empty({ title, copy, cta, onPress }: EmptyProps) {
  const { colors } = useTheme();
  return (
    <View style={styles.empty} accessibilityRole="alert">
      <Text style={[styles.emptyTitle, { color: colors.text }]}>{title}</Text>
      <Text style={[styles.emptyCopy, { color: colors.textMuted }]}>{copy}</Text>
      {cta ? (
        <Pressable
          onPress={onPress}
          accessibilityRole="button"
          accessibilityLabel={cta}
          style={[styles.emptyCta, { backgroundColor: colors.primary }]}
        >
          <Text style={[styles.emptyCtaText, { color: colors.primaryInk }]}>{cta}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function Skeleton() {
  const { colors } = useTheme();
  return (
    <View style={styles.list} accessibilityLabel="Loading your priority actions">
      {[0, 1].map((row) => (
        <View key={row} style={[styles.item, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
          <View style={[styles.mark, { backgroundColor: colors.border }]} />
          <View style={[styles.skeleton, styles.skeletonLine, { backgroundColor: colors.border }]} />
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 20, gap: 8 },
  head: { paddingTop: 14, paddingHorizontal: 16, paddingBottom: 2 },
  headRole: { fontFamily: fonts.semibold, fontSize: 12, lineHeight: 16 },
  headGreeting: { fontFamily: fonts.bold, fontSize: 20, lineHeight: 28, marginTop: 2 },
  card: { marginHorizontal: 12, padding: 14, borderWidth: 1, borderRadius: radius.lg },
  cardHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    marginBottom: 10,
    minHeight: 20,
  },
  cardTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cardTitle: { fontFamily: fonts.bold, fontSize: 15, lineHeight: 19.5 },
  date: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 18 },
  seeAll: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  seeAllText: { fontFamily: fonts.semibold, fontSize: 13, lineHeight: 19.5 },
  grid: { flexDirection: 'row', gap: 8 },
  figure: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingHorizontal: 4,
    minHeight: 94,
  },
  figureValue: { fontFamily: fonts.medium, fontSize: 18, lineHeight: 20.8 },
  figureLabel: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 14.4, textAlign: 'center' },
  list: { gap: 8 },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingLeft: 12,
    paddingRight: 10,
  },
  mark: { width: 40, height: 40, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center' },
  itemBody: { flex: 1, gap: 2 },
  itemName: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 16.9 },
  itemSub: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 15.6 },
  tags: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 2 },
  tag: { borderRadius: radius.pill, paddingVertical: 1, paddingHorizontal: 8 },
  tagText: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 18 },
  due: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  go: { flexDirection: 'row', alignItems: 'center', gap: 2 },
  goText: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 18 },
  shortcut: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: 8,
    paddingHorizontal: 4,
    minHeight: 62,
  },
  shortcutLabel: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 14.4, textAlign: 'center' },
  datebox: { width: 44, height: 44, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  dateMonth: { fontFamily: fonts.bold, fontSize: 9, lineHeight: 11 },
  dateDay: { fontFamily: fonts.bold, fontSize: 16, lineHeight: 18 },
  empty: { alignItems: 'center', paddingVertical: 12, gap: 4 },
  emptyTitle: { fontFamily: fonts.semibold, fontSize: 13, textAlign: 'center' },
  emptyCopy: { fontFamily: fonts.regular, fontSize: 12, textAlign: 'center' },
  emptyCta: {
    marginTop: 8,
    minHeight: 44,
    justifyContent: 'center',
    borderRadius: radius.sm,
    paddingHorizontal: 16,
  },
  emptyCtaText: { fontFamily: fonts.semibold, fontSize: 13 },
  skeleton: { borderRadius: radius.xs, opacity: 0.6 },
  skeletonValue: { width: 28, height: 20 },
  skeletonLine: { flex: 1, height: 14 },
});
