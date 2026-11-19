/**
 * The redesigned Today for the native app (docs/migration/177 stage D, 179,
 * 180), the web's components/today/TodayScreen drawn natively: from Go's Home
 * answer, the next thing on the reader's plan, what waits on them and the
 * figures that hold something. Which rows and figures it shows is
 * ds/todayView's choice, the same as the web's. HomeScreen loads Home and
 * hands it here for the roles already redesigned.
 */
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Button, EmptyState, KpiStat, SectionHeader, Skeleton, StatusBadge, Surface, TaskList, TaskRow, useDs } from '../ds/components';
import { tokens } from '../ds/tokens';
import { countedFigures, nextUp, todosLinkLabel, toneOf, waitingRows } from '../ds/todayView';
import type { GetHomeResponse, HomeFigure, HomePriorityRow, HomeUpcoming } from '../gen/edify/screens/v1/home_pb';
import { fonts } from '../theme';

type Open = (url: string, label: string) => void;

export interface TodayQueue {
  readonly rows: readonly HomePriorityRow[];
  readonly total: number | null;
}

interface TodayScreenProps {
  readonly home: GetHomeResponse;
  readonly figures: readonly HomeFigure[];
  readonly queue: TodayQueue | null;
  readonly queueError: boolean;
  readonly onRetryQueue: () => void;
  readonly onOpen: Open;
}

function NextUp({ next, onOpen }: { readonly next: HomeUpcoming | undefined; readonly onOpen: Open }) {
  const c = useDs();
  if (!next) {
    return (
      <EmptyState
        title="Nothing planned next"
        body="Plan a visit or a training and it appears here."
        action={{ label: 'Open My Plan', onPress: () => onOpen('/my-plan', 'My Plan') }}
      />
    );
  }
  const when = next.isToday ? 'Next up · today' : `Next up · ${next.day} ${next.month}`;
  return (
    <Surface>
      <Text style={[s.caption, { color: c['text-subtle'] }]}>{next.time ? `${when} · ${next.time}` : when}</Text>
      <Text style={[s.lead, { color: c.text }]}>{next.title}</Text>
      <Text style={[s.caption, { color: c['text-subtle'] }]}>{[next.where, next.typeLabel].filter(Boolean).join(' · ')}</Text>
      <View style={s.nextActions}>
        <Button label="Open" onPress={() => onOpen(next.url, next.title)} />
        {next.statusLabel ? <StatusBadge tone="info">{next.statusLabel}</StatusBadge> : null}
      </View>
    </Surface>
  );
}

function Waiting({ queue, queueError, onRetryQueue, onOpen }: Omit<TodayScreenProps, 'home' | 'figures'>) {
  if (queueError) {
    return (
      <EmptyState
        title="What waits on you did not load"
        body="Check your connection, then try again."
        action={{ label: 'Try again', onPress: onRetryQueue }}
      />
    );
  }
  if (!queue) {
    return <Skeleton label="Loading what waits on you" />;
  }
  const waiting = waitingRows(queue.rows);
  if (waiting.length === 0) {
    return <EmptyState title="Nothing waits on you" body="New work appears here as soon as it is yours to do." />;
  }
  return (
    <TaskList>
      {waiting.map((row, i) => (
        <TaskRow
          key={`${row.key}-${i}`}
          title={row.title}
          context={row.context || undefined}
          status={row.statusLabel || row.dueLabel || undefined}
          tone={toneOf(row.statusTone || row.dueTone)}
          action={row.actionLabel || 'Open'}
          onPress={() => onOpen(row.url, row.title)}
          last={i === waiting.length - 1}
        />
      ))}
    </TaskList>
  );
}

export function TodayScreen({ home, figures, queue, queueError, onRetryQueue, onOpen }: TodayScreenProps) {
  const c = useDs();
  const counted = countedFigures(figures);
  return (
    <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={s.page} testID="today">
      <View>
        <Text style={[s.caption, { color: c['text-subtle'] }]}>
          {home.todayLabel} · FY{home.fy}
          {home.roleTitle ? ` · ${home.roleTitle}` : ''}
        </Text>
        <Text style={[s.title, { color: c.text }]} accessibilityRole="header">
          Today
        </Text>
      </View>

      {home.hasPlan ? <NextUp next={nextUp(home.upcoming)} onOpen={onOpen} /> : null}

      <SectionHeader
        title="Waiting on you"
        linkLabel={todosLinkLabel(queue?.total)}
        onLink={() => onOpen('/todos', 'To-Do')}
      />
      <Waiting queue={queue} queueError={queueError} onRetryQueue={onRetryQueue} onOpen={onOpen} />

      {counted.length ? (
        <>
          <SectionHeader title="At a glance" />
          <Surface>
            <View style={s.kpis}>
              {counted.map((f, i) => (
                <KpiStat key={`${f.key}-${i}`} label={f.label} value={f.value} />
              ))}
            </View>
          </Surface>
        </>
      ) : null}

      {home.shortcuts.length ? (
        <>
          <SectionHeader title="Go to" />
          <View style={s.shortcuts}>
            {home.shortcuts.map((sc, i) => (
              <View key={`${sc.url}-${i}`} style={s.shortcut}>
                <Button kind="secondary" label={sc.label} onPress={() => onOpen(sc.url, sc.label)} />
              </View>
            ))}
          </View>
        </>
      ) : null}
    </ScrollView>
  );
}

const { text, space } = tokens;

const s = StyleSheet.create({
  page: { paddingHorizontal: space[4], paddingTop: space[5], paddingBottom: space[8], gap: space[3] },
  caption: { fontFamily: fonts.semibold, fontSize: text.caption.size, lineHeight: text.caption.line },
  title: { fontFamily: fonts.bold, fontSize: text.title.size, lineHeight: text.title.line, marginTop: space[1] },
  lead: { fontFamily: fonts.bold, fontSize: text.lead.size, lineHeight: text.lead.line, marginTop: space[1] },
  nextActions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: space[2], marginTop: space[3] },
  kpis: { flexDirection: 'row', flexWrap: 'wrap' },
  shortcuts: { flexDirection: 'row', flexWrap: 'wrap', marginHorizontal: -space[1] },
  shortcut: { width: '50%', padding: space[1] },
});
