/**
 * The leader's Meetings tab: what they have planned (waiting on staff, or
 * returned to them) and the cluster's meetings and trainings staff have
 * scheduled in Edify, upcoming or past. Plan Meeting and Mobilize Training
 * start new ones.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { CalendarPlus, ChevronRight, GraduationCap, Users } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ClusterActivity } from '../../gen/edify/clusters/v1/leadership_pb';
import { ClusterLeadershipService } from '../../gen/edify/clusters/v1/leadership_pb';
import type { MeetingPlan } from '../../gen/edify/clusters/v1/mobilization_pb';
import { ClusterMobilizationService } from '../../gen/edify/clusters/v1/mobilization_pb';
import { fonts, radius, useTheme } from '../../theme';
import { LoanHero, LoanSheet, PrimaryButton, SegmentTabs, StatusChip } from '../loans/loanUi';
import { ActivityRow } from './ClusterHomeScreen';
import { planStatus } from './clusterData';
import { longDate } from './clusterRoutes';

type When = 'upcoming' | 'past';
const WAITING = new Set(['draft', 'submitted', 'returned', 'approved']);

interface MeetingsScreenProps {
  readonly clusterId: string;
  readonly clusterName: string;
  readonly initialWhen: When;
  readonly onPlanMeeting: () => void;
  readonly onMobilize: () => void;
  readonly onOpenPlan: (planId: string) => void;
  readonly onOpenActivity: (activityId: string) => void;
}

export function MeetingsScreen(props: MeetingsScreenProps) {
  const { clusterId, clusterName, initialWhen, onPlanMeeting, onMobilize, onOpenPlan, onOpenActivity } = props;
  const { api } = useSession();
  const { colors } = useTheme();
  const [when, setWhen] = useState<When>(initialWhen);
  const [plans, setPlans] = useState<readonly MeetingPlan[] | null>(null);
  const [activities, setActivities] = useState<readonly ClusterActivity[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .call(ClusterMobilizationService.method.listPlans, { clusterId })
      .then((answer) => setPlans(answer.plans))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, clusterId]);
  useEffect(() => {
    setActivities(null);
    api
      .call(ClusterLeadershipService.method.listActivities, { clusterId, when })
      .then((answer) => setActivities(answer.activities))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, clusterId, when]);

  const planned = (plans ?? []).filter((plan) => WAITING.has(plan.status)).sort((a, b) => a.plannedOn.localeCompare(b.plannedOn));
  const isLoading = activities === null || plans === null;
  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LoanHero eyebrow={clusterName} title="Meetings" subtitle="Plan meetings and trainings, and invite your schools." />
      <LoanSheet>
        <SegmentTabs
          tabs={[
            { key: 'upcoming', label: 'Upcoming' },
            { key: 'past', label: 'Past' },
          ]}
          value={when}
          onChange={setWhen}
        />
        <View style={styles.buttons}>
          <View style={styles.flex}>
            <PrimaryButton label="Plan Meeting" icon={CalendarPlus} onPress={onPlanMeeting} />
          </View>
          <View style={styles.flex}>
            <PrimaryButton label="Mobilize Training" icon={GraduationCap} isOutline onPress={onMobilize} />
          </View>
        </View>
        {error ? <Text style={[styles.muted, { color: colors.danger }]}>{error}</Text> : null}
        {isLoading && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}

        {when === 'upcoming' && planned.length > 0 ? (
          <>
            <Text style={[styles.section, { color: colors.textMuted }]}>YOUR PLANS</Text>
            {planned.map((plan) => (
              <PlanCard key={plan.id} plan={plan} onOpen={() => onOpenPlan(plan.id)} />
            ))}
          </>
        ) : null}

        {activities && activities.length > 0 ? (
          <>
            <Text style={[styles.section, { color: colors.textMuted }]}>{when === 'upcoming' ? 'SCHEDULED IN EDIFY' : 'HELD OR PAST'}</Text>
            {activities.map((activity) => (
              <Pressable key={activity.id} onPress={() => onOpenActivity(activity.id)} accessibilityRole="button" accessibilityLabel={`Open ${activity.name}`}>
                <ActivityRow activity={activity} />
              </Pressable>
            ))}
          </>
        ) : null}

        {!isLoading && activities?.length === 0 && (when === 'past' || planned.length === 0) ? (
          <Text style={[styles.empty, { color: colors.textMuted }]}>
            {when === 'past' ? 'No meeting in the last 120 days.' : 'Nothing planned yet. Plan a meeting or a training to start.'}
          </Text>
        ) : null}
      </LoanSheet>
    </ScrollView>
  );
}

function PlanCard({ plan, onOpen }: { readonly plan: MeetingPlan; readonly onOpen: () => void }) {
  const { colors } = useTheme();
  const status = planStatus(plan.status);
  return (
    <Pressable
      onPress={onOpen}
      accessibilityRole="button"
      accessibilityLabel={`${plan.title}, ${status.label}. Open`}
      style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}
    >
      <View style={styles.flex}>
        <View style={styles.cardHead}>
          <Text style={[styles.cardTitle, { color: colors.text }]} numberOfLines={2}>
            {plan.title}
          </Text>
          <StatusChip label={status.label} tone={status.tone} />
        </View>
        <Text style={[styles.muted, { color: colors.textMuted }]}>
          {[longDate(plan.plannedOn), plan.startsAt, plan.venue].filter(Boolean).join(' · ')}
        </Text>
        <View style={styles.invited}>
          <Users size={14} color={colors.textMuted} />
          <Text style={[styles.muted, { color: colors.textMuted }]}>{plan.invitedCount} schools invited</Text>
        </View>
      </View>
      <ChevronRight size={20} color={colors.textMuted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  buttons: { flexDirection: 'row', gap: 10 },
  flex: { flex: 1, gap: 4 },
  section: { fontFamily: fonts.bold, fontSize: 12, letterSpacing: 0.8, marginTop: 4 },
  card: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderRadius: radius.md, padding: 14 },
  cardHead: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 },
  cardTitle: { flex: 1, fontFamily: fonts.bold, fontSize: 15 },
  muted: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
  invited: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  empty: { fontFamily: fonts.medium, fontSize: 14, textAlign: 'center', paddingVertical: 24 },
});
