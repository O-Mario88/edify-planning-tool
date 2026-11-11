/**
 * "Cluster Actions" (owner brief, 2026-11-11, part 12): the leader's register
 * of support requests. Open holds drafts, questions from staff and results to
 * review; Waiting holds what staff are working on; Completed holds closed and
 * cancelled actions. Each card says who holds it and how far the support has
 * got, read from the official activities staff linked to it.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ChevronRight, Plus } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ActionCard } from '../../gen/edify/clusters/v1/actions_pb';
import { ClusterActionService } from '../../gen/edify/clusters/v1/actions_pb';
import { fonts, radius, useTheme } from '../../theme';
import { LoanHero, LoanSheet, PrimaryButton, SegmentTabs, StatusChip } from '../loans/loanUi';
import { ACTION_TABS, type ActionTab } from './clusterData';
import { longDate } from './clusterRoutes';
import { Notice } from './opsParts';

interface ClusterActionsScreenProps {
  readonly clusterId: string;
  readonly clusterName: string;
  readonly notice?: string;
  readonly onNew: () => void;
  readonly onOpen: (actionId: string) => void;
}

export function ClusterActionsScreen({ clusterId, clusterName, notice = '', onNew, onOpen }: ClusterActionsScreenProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [tab, setTab] = useState<ActionTab>('open');
  const [cards, setCards] = useState<readonly ActionCard[] | null>(null);
  const [counts, setCounts] = useState<Readonly<Record<string, number>>>({});
  const [error, setError] = useState('');

  const load = useCallback(() => {
    setCards(null);
    setError('');
    api
      .call(ClusterActionService.method.listActions, { clusterId, tab })
      .then((answer) => {
        setCards(answer.actions);
        setCounts(answer.counts);
      })
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, clusterId, tab]);
  useEffect(load, [load]);

  const tabs = ACTION_TABS.map((entry) => ({ key: entry.key, label: counts[entry.key] ? `${entry.label} (${counts[entry.key]})` : entry.label }));
  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LoanHero eyebrow={clusterName} title="Cluster Actions" subtitle="Support your schools need, and how far it has got." />
      <LoanSheet>
        <PrimaryButton label="New Action" icon={Plus} onPress={onNew} />
        {notice ? <Notice text={notice} /> : null}
        <SegmentTabs tabs={tabs} value={tab} onChange={setTab} />
        {error ? <Notice text={error} isError /> : null}
        {cards === null && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading actions" /> : null}
        {cards?.length === 0 ? (
          <Text style={[styles.muted, { color: colors.textMuted }]}>
            {{ open: 'Nothing needs you right now.', waiting: 'No action is with staff.', completed: 'No action is closed yet.' }[tab]}
          </Text>
        ) : null}
        {cards?.map((card) => <ActionCardRow key={card.id} card={card} onPress={() => onOpen(card.id)} />)}
      </LoanSheet>
    </ScrollView>
  );
}

/** One action as a card: its status, schools, who holds it and its next step. */
export function ActionCardRow({ card, onPress }: { readonly card: ActionCard; readonly onPress: () => void }) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${card.title}, ${card.statusLabel}`}
      style={({ pressed }) => [styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder, opacity: pressed ? 0.85 : 1 }]}
    >
      <View style={styles.row}>
        <StatusChip label={card.statusLabel} tone={card.statusTone} />
        {card.isOverdue ? <StatusChip label="Overdue" tone="alert" /> : null}
        {card.priority === 'urgent' || card.priority === 'high' ? <StatusChip label={card.priority === 'urgent' ? 'Urgent' : 'High'} tone="caution" /> : null}
        <Text style={[styles.ref, { color: colors.textSubtle }]}>{card.ref}</Text>
      </View>
      <View style={styles.row}>
        <Text style={[styles.title, { color: colors.text }]} numberOfLines={2}>
          {card.title}
        </Text>
        <ChevronRight size={20} color={colors.textMuted} />
      </View>
      <Text style={[styles.muted, { color: colors.textMuted }]} numberOfLines={2}>
        {[card.schoolsLabel, card.responsible].filter(Boolean).join(' · ')}
      </Text>
      {card.progressSummary ? <Text style={[styles.body, { color: colors.text }]}>{card.progressSummary}</Text> : null}
      <Text style={[styles.muted, { color: colors.textMuted }]}>
        {[`Target ${longDate(card.targetOn)}`, card.latestUpdate].filter(Boolean).join(' · ')}
      </Text>
      {card.nextAction ? <Text style={[styles.next, { color: colors.primary }]}>{card.nextAction}</Text> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 6 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  ref: { fontFamily: fonts.medium, fontSize: 12, marginLeft: 'auto' },
  title: { flex: 1, fontFamily: fonts.bold, fontSize: 16 },
  body: { fontFamily: fonts.semibold, fontSize: 14 },
  muted: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
  next: { fontFamily: fonts.bold, fontSize: 13 },
});
