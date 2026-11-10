/**
 * Cluster Leaders, for the staff who manage them (brief A1): Admin and
 * Programme Leads for every cluster, a CCEO for their own. Each cluster
 * shows its live leaders; opening one shows every assignment, live and past,
 * with its history, and lets the manager assign, end or replace a leader.
 *
 * The rules are the gateway's (who may manage which cluster, that the account
 * already holds the Cluster Leader role, that nothing is ever deleted); this
 * screen shows what it answers and says plainly when it refuses.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { ChevronLeft, ChevronRight, Search } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { LeaderAssignment, ListLeadersResponse, ManagedCluster } from '../../gen/edify/clusters/v1/leadership_pb';
import { fonts, radius, useTheme } from '../../theme';
import { DateField } from '../../ui/DateField';
import { DrawerButton } from '../../ui/drawerParts';
import { Select } from '../../ui/Select';
import { longDate } from './clusterRoutes';

export function ClusterLeadersScreen() {
  const [openId, setOpenId] = useState('');
  return openId ? (
    <LeadersOfCluster clusterId={openId} onBack={() => setOpenId('')} />
  ) : (
    <ManagedClusters onOpen={setOpenId} />
  );
}

function ManagedClusters({ onOpen }: { readonly onOpen: (clusterId: string) => void }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [search, setSearch] = useState('');
  const [clusters, setClusters] = useState<readonly ManagedCluster[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let isLive = true;
    const timer = setTimeout(() => {
      api
        .listManagedClusters({ page: 1, search: search.trim() })
        .then((answer) => isLive && setClusters(answer.clusters))
        .catch((cause: unknown) => isLive && setError(describe(cause)));
    }, 250);
    return () => {
      isLive = false;
      clearTimeout(timer);
    };
  }, [api, search]);

  return (
    <FlatList
      data={clusters ?? []}
      keyExtractor={(item) => item.cluster?.id ?? ''}
      contentContainerStyle={styles.list}
      ListHeaderComponent={
        <View style={styles.head}>
          <Text style={[styles.eyebrow, { color: colors.eyebrow }]}>CLUSTER LEADERSHIP</Text>
          <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
            Cluster Leaders
          </Text>
          <Text style={[styles.copy, { color: colors.textMuted }]}>
            Give a cluster to a Cluster Leader account, end or replace a leader. Every change is kept.
          </Text>
          <View style={[styles.search, { backgroundColor: colors.surface, borderColor: colors.fieldBorder }]}>
            <Search size={16} color={colors.textMuted} />
            <TextInput
              value={search}
              onChangeText={setSearch}
              placeholder="Search clusters"
              placeholderTextColor={colors.textSubtle}
              accessibilityLabel="Search clusters"
              style={[styles.input, { color: colors.text }]}
            />
          </View>
          {error ? <Text style={[styles.error, { color: colors.danger }]} accessibilityRole="alert">{error}</Text> : null}
        </View>
      }
      ListEmptyComponent={
        clusters === null ? (
          <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />
        ) : (
          <Text style={[styles.copy, { color: colors.textMuted }]}>No cluster you manage matches.</Text>
        )
      }
      renderItem={({ item }) => {
        const cluster = item.cluster;
        if (!cluster) {
          return null;
        }
        return (
          <Pressable
            onPress={() => onOpen(cluster.id)}
            accessibilityRole="button"
            style={[styles.row, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}
          >
            <View style={styles.body}>
              <Text style={[styles.name, { color: colors.text }]}>{cluster.name}</Text>
              <Text style={[styles.meta, { color: colors.textMuted }]}>
                {[cluster.district, cluster.subCounty].filter(Boolean).join(' · ')} · {cluster.memberSchoolCount} schools
              </Text>
              <Text style={[styles.meta, { color: item.liveLeaders.length ? colors.success : colors.warning }]}>
                {item.liveLeaders.length ? `Led by ${item.liveLeaders.join(', ')}` : 'No leader'}
              </Text>
            </View>
            <ChevronRight size={18} color={colors.textMuted} />
          </Pressable>
        );
      }}
    />
  );
}

function LeadersOfCluster({ clusterId, onBack }: { readonly clusterId: string; readonly onBack: () => void }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [answer, setAnswer] = useState<ListLeadersResponse | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(() => {
    api
      .listLeaders(clusterId)
      .then(setAnswer)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, clusterId]);
  useEffect(load, [load]);

  const after = (message: string) => {
    setNotice(message);
    setError('');
    load();
  };

  const live = answer?.assignments.filter((a) => a.status !== 'ended') ?? [];
  const past = answer?.assignments.filter((a) => a.status === 'ended') ?? [];
  return (
    <ScrollView contentContainerStyle={styles.list} keyboardShouldPersistTaps="handled">
      <Pressable onPress={onBack} accessibilityRole="button" style={styles.back} hitSlop={10}>
        <ChevronLeft size={16} color={colors.link} />
        <Text style={[styles.link, { color: colors.link }]}>All clusters</Text>
      </Pressable>
      <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
        {answer?.cluster?.name ?? ' '}
      </Text>
      {answer?.cluster ? (
        <Text style={[styles.copy, { color: colors.textMuted }]}>
          {[answer.cluster.district, answer.cluster.subCounty].filter(Boolean).join(' · ')} · {answer.cluster.memberSchoolCount} member schools
        </Text>
      ) : null}
      {notice ? <Text style={[styles.notice, { color: colors.success }]} accessibilityLiveRegion="polite">{notice}</Text> : null}
      {error ? <Text style={[styles.error, { color: colors.danger }]} accessibilityRole="alert">{error}</Text> : null}
      {!answer && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}

      {answer ? (
        <>
          <Text style={[styles.section, { color: colors.text }]}>Live leaders</Text>
          {live.length === 0 ? <Text style={[styles.copy, { color: colors.textMuted }]}>Nobody leads this cluster now.</Text> : null}
          {live.map((assignment) => (
            <AssignmentCard
              key={assignment.id}
              assignment={assignment}
              candidates={answer.candidates.filter((c) => c.userId !== assignment.userId)}
              onDone={after}
              onError={setError}
            />
          ))}
          <AssignForm clusterId={clusterId} answer={answer} onDone={after} onError={setError} />
          {past.length > 0 ? <Text style={[styles.section, { color: colors.text }]}>Past leaders</Text> : null}
          {past.map((assignment) => (
            <AssignmentCard key={assignment.id} assignment={assignment} candidates={[]} onDone={after} onError={setError} />
          ))}
        </>
      ) : null}
    </ScrollView>
  );
}

interface AssignmentCardProps {
  readonly assignment: LeaderAssignment;
  readonly candidates: ListLeadersResponse['candidates'];
  readonly onDone: (message: string) => void;
  readonly onError: (message: string) => void;
}

function AssignmentCard({ assignment, candidates, onDone, onError }: AssignmentCardProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [reason, setReason] = useState('');
  const [successor, setSuccessor] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const isLive = assignment.status !== 'ended';

  const run = (work: Promise<unknown>, message: string) => {
    setIsBusy(true);
    work
      .then(() => onDone(message))
      .catch((cause: unknown) => onError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <Text style={[styles.name, { color: colors.text }]}>{assignment.leaderName}</Text>
      <Text style={[styles.meta, { color: colors.textMuted }]}>{assignment.leaderEmail}</Text>
      <Text style={[styles.meta, { color: colors.textMuted }]}>
        {longDate(assignment.startsOn)} – {assignment.endsOn ? longDate(assignment.endsOn) : 'open'}
        {assignment.status === 'suspended' ? ' · suspended' : ''}
      </Text>
      {assignment.history.map((event, index) => (
        <Text key={index} style={[styles.history, { color: colors.textSubtle }]}>
          {event.event} by {event.actor || 'someone'} · {event.at.slice(0, 10)}
          {event.reason ? ` · “${event.reason}”` : ''}
        </Text>
      ))}
      {isLive ? (
        <View style={styles.form}>
          <TextInput
            value={reason}
            onChangeText={setReason}
            placeholder="Reason (kept with the history)"
            placeholderTextColor={colors.textSubtle}
            accessibilityLabel={`Reason for changing ${assignment.leaderName}`}
            style={[styles.field, { color: colors.text, borderColor: colors.fieldBorder, backgroundColor: colors.surface }]}
          />
          <DrawerButton
            label="End assignment"
            isBusy={isBusy}
            onPress={() => run(api.endAssignment(assignment.id, reason), `${assignment.leaderName} no longer leads the cluster.`)}
          />
          {candidates.length > 0 ? (
            <>
              <Select
                label="Replace with"
                value={successor}
                choices={candidates.map((c) => ({ value: c.userId, label: `${c.name} (${c.email})` }))}
                placeholder="Choose the new leader"
                onChange={setSuccessor}
                variant="form"
              />
              <DrawerButton
                label="Replace leader"
                isPrimary
                isBusy={isBusy}
                isDisabled={!successor}
                onPress={() => run(api.replaceLeader(assignment.id, successor, reason), 'The cluster has its new leader.')}
              />
            </>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

interface AssignFormProps {
  readonly clusterId: string;
  readonly answer: ListLeadersResponse;
  readonly onDone: (message: string) => void;
  readonly onError: (message: string) => void;
}

function AssignForm({ clusterId, answer, onDone, onError }: AssignFormProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [userId, setUserId] = useState('');
  const [startsOn, setStartsOn] = useState('');
  const [endsOn, setEndsOn] = useState('');
  const [reason, setReason] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const liveIds = new Set(answer.assignments.filter((a) => a.status !== 'ended').map((a) => a.userId));
  const choices = answer.candidates
    .filter((c) => !liveIds.has(c.userId))
    .map((c) => ({ value: c.userId, label: `${c.name} (${c.email})` }));

  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <Text style={[styles.name, { color: colors.text }]}>Assign a leader</Text>
      {choices.length === 0 ? (
        <Text style={[styles.copy, { color: colors.textMuted }]}>
          No other account holds the Cluster Leader role. An Admin gives an account the role on the Users page.
        </Text>
      ) : (
        <View style={styles.form}>
          <Select label="Leader" value={userId} choices={choices} placeholder="Choose a Cluster Leader" onChange={setUserId} variant="form" />
          <DateField label="Starts on" value={startsOn} onChange={setStartsOn} placeholder="Today" />
          <DateField label="Ends on" value={endsOn} onChange={setEndsOn} min={startsOn} placeholder="Open-ended" />
          <TextInput
            value={reason}
            onChangeText={setReason}
            placeholder="Reason (kept with the history)"
            placeholderTextColor={colors.textSubtle}
            accessibilityLabel="Reason for the assignment"
            style={[styles.field, { color: colors.text, borderColor: colors.fieldBorder, backgroundColor: colors.surface }]}
          />
          <DrawerButton
            label="Assign"
            isPrimary
            isBusy={isBusy}
            isDisabled={!userId}
            onPress={() => {
              setIsBusy(true);
              api
                .assignLeader({ clusterId, userId, startsOn, endsOn, reason })
                .then(() => {
                  setUserId('');
                  setReason('');
                  onDone('The leader has the cluster.');
                })
                .catch((cause: unknown) => onError(describe(cause)))
                .finally(() => setIsBusy(false));
            }}
          />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { padding: 12, gap: 10, paddingBottom: 32 },
  head: { gap: 6, marginBottom: 4 },
  eyebrow: { fontFamily: fonts.bold, fontSize: 11, letterSpacing: 1.2 },
  title: { fontFamily: fonts.bold, fontSize: 22, letterSpacing: -0.2 },
  section: { fontFamily: fonts.bold, fontSize: 16, marginTop: 8 },
  copy: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  notice: { fontFamily: fonts.semibold, fontSize: 13 },
  error: { fontFamily: fonts.medium, fontSize: 13 },
  link: { fontFamily: fonts.semibold, fontSize: 13 },
  back: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start' },
  search: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 44, marginTop: 4 },
  input: { flex: 1, fontFamily: fonts.medium, fontSize: 16, paddingVertical: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderRadius: radius.md, padding: 14 },
  body: { flex: 1, gap: 2 },
  name: { fontFamily: fonts.semibold, fontSize: 15 },
  meta: { fontFamily: fonts.medium, fontSize: 12 },
  history: { fontFamily: fonts.medium, fontSize: 12 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 6 },
  form: { gap: 10, marginTop: 6 },
  field: { minHeight: 44, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, fontFamily: fonts.medium, fontSize: 16 },
});
