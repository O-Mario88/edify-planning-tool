/**
 * "Cluster Support Requests" for staff (owner brief, 2026-11-11, part 5.3):
 * each school a Cluster Leader asked support for, routed to the CCEO who holds
 * it (or their Program Lead when no one does). Queues: New, Clarification,
 * Accepted, Planned, In progress, Overdue, Completed. A request is answered on
 * the action itself: acknowledge, accept and plan it in Edify, then link the
 * official activity, whose own status then reports the progress.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ChevronRight } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { SupportRequestRow } from '../../gen/edify/clusters/v1/actions_pb';
import { ClusterActionService } from '../../gen/edify/clusters/v1/actions_pb';
import { fonts, radius, useTheme } from '../../theme';
import { LoanHero, LoanSheet, SegmentTabs, StatusChip } from '../loans/loanUi';
import { ActionDetailScreen } from './ActionDetailScreen';
import { SUPPORT_QUEUES, type SupportScope } from './clusterData';
import { longDate } from './clusterRoutes';
import { Notice } from './opsParts';

export function SupportRequestsScreen() {
  const { api } = useSession();
  const { colors } = useTheme();
  const [scope, setScope] = useState<SupportScope>('mine');
  const [queue, setQueue] = useState('');
  const [rows, setRows] = useState<readonly SupportRequestRow[] | null>(null);
  const [counts, setCounts] = useState<Readonly<Record<string, number>>>({});
  const [hasTeam, setHasTeam] = useState(false);
  const [actionId, setActionId] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(() => {
    setRows(null);
    setError('');
    api
      .call(ClusterActionService.method.listSupportRequests, { scope, queue })
      .then((answer) => {
        setRows(answer.rows);
        setCounts(answer.counts);
        setHasTeam(answer.hasTeam);
      })
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, scope, queue]);
  useEffect(load, [load]);

  if (actionId) {
    return (
      <ActionDetailScreen
        key={actionId}
        actionId={actionId}
        onBack={() => {
          setActionId('');
          load();
        }}
      />
    );
  }

  const open = SUPPORT_QUEUES.filter((entry) => entry.key !== 'completed').reduce((sum, entry) => sum + (counts[entry.key] ?? 0), 0);
  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LoanHero
        eyebrow="Cluster leadership"
        title="Cluster Support Requests"
        subtitle={`${open} open. Accept and plan each in Edify, then link the activity.`}
      />
      <LoanSheet>
        {hasTeam ? (
          <SegmentTabs<SupportScope>
            tabs={[
              { key: 'mine', label: 'Mine' },
              { key: 'team', label: 'My team' },
            ]}
            value={scope}
            onChange={setScope}
          />
        ) : null}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
          {[{ key: '', label: 'All open' }, ...SUPPORT_QUEUES].map((entry) => {
            const isOn = entry.key === queue;
            const count = entry.key ? counts[entry.key] : open;
            return (
              <Pressable
                key={entry.key || 'all'}
                onPress={() => setQueue(entry.key)}
                accessibilityRole="tab"
                accessibilityState={{ selected: isOn }}
                style={[styles.chip, { borderColor: isOn ? colors.primary : colors.border, backgroundColor: isOn ? colors.primary : colors.raised }]}
              >
                <Text style={[styles.chipText, { color: isOn ? colors.primaryInk : colors.text }]}>
                  {count ? `${entry.label} (${count})` : entry.label}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
        {error ? <Notice text={error} isError /> : null}
        {rows === null && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading requests" /> : null}
        {rows?.length === 0 ? <Text style={[styles.muted, { color: colors.textMuted }]}>No support requests here.</Text> : null}
        {rows?.map((row) => (
          <Pressable
            key={`${row.actionId}-${row.schoolId}`}
            onPress={() => setActionId(row.actionId)}
            accessibilityRole="button"
            accessibilityLabel={`${row.schoolName}: ${row.support}, ${row.progressLabel}`}
            style={({ pressed }) => [styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder, opacity: pressed ? 0.85 : 1 }]}
          >
            <View style={styles.row}>
              <StatusChip label={row.progressLabel} tone={row.progressTone} />
              {row.isOverdue ? <StatusChip label="Overdue" tone="alert" /> : null}
              {row.priority === 'urgent' || row.priority === 'high' ? <StatusChip label={row.priority === 'urgent' ? 'Urgent' : 'High'} tone="caution" /> : null}
              <Text style={[styles.ref, { color: colors.textSubtle }]}>{row.ref}</Text>
            </View>
            <View style={styles.row}>
              <Text style={[styles.title, { color: colors.text }]} numberOfLines={2}>
                {row.schoolName}
              </Text>
              <ChevronRight size={20} color={colors.textMuted} />
            </View>
            <Text style={[styles.body, { color: colors.text }]}>{row.support}</Text>
            {row.description ? (
              <Text style={[styles.muted, { color: colors.textMuted }]} numberOfLines={2}>
                {row.description}
              </Text>
            ) : null}
            <Text style={[styles.muted, { color: colors.textMuted }]}>
              {[row.edifySchoolId, row.clusterName, row.leader && `from ${row.leader}`].filter(Boolean).join(' · ')}
            </Text>
            <Text style={[styles.muted, { color: colors.textMuted }]}>
              {[
                `Target ${longDate(row.targetOn)}`,
                row.daysWaiting > 0 ? `${row.daysWaiting} ${row.daysWaiting === 1 ? 'day' : 'days'} since sent` : '',
                scope === 'team' ? row.responsibleStaff || 'Not yet assigned' : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            </Text>
          </Pressable>
        ))}
      </LoanSheet>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  chips: { gap: 8, paddingVertical: 2 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 14, minHeight: 40, justifyContent: 'center' },
  chipText: { fontFamily: fonts.semibold, fontSize: 14 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 6 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  ref: { fontFamily: fonts.medium, fontSize: 12, marginLeft: 'auto' },
  title: { flex: 1, fontFamily: fonts.bold, fontSize: 16 },
  body: { fontFamily: fonts.semibold, fontSize: 14 },
  muted: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
});
