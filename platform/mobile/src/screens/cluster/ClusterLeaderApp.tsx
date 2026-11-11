/**
 * The app for a Cluster Leader: the clusters assigned to them and nothing
 * else. The gateway decides that reach on every request; this screen only
 * shows what it answers. Laid out after the owner's mockup (2026-11-11):
 * Home, Meetings and Schools tabs; Plan Meeting and Mobilize Schools forms;
 * a meeting's details; Manage Cluster; Progress & Reports; and, under More,
 * follow-up, requests to staff and the loan application link.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';

import { describe, useSession } from '../../auth/SessionContext';
import type { ClusterActionView } from '../../gen/edify/clusters/v1/actions_pb';
import type { ClusterSummary, GetClusterHomeResponse } from '../../gen/edify/clusters/v1/leadership_pb';
import type { MeetingPlan } from '../../gen/edify/clusters/v1/mobilization_pb';
import { ClusterMobilizationService } from '../../gen/edify/clusters/v1/mobilization_pb';
import type { Session } from '../../gen/edify/identity/v1/identity_pb';
import { AppShell, MENU_URL } from '../../shell/AppShell';
import { fonts, radius, useTheme } from '../../theme';
import { MenuScreen } from '../MoreScreen';
import { ShareApplicationScreen } from '../loans/ShareSheet';
import { ActionDetailScreen } from './ActionDetailScreen';
import { ActionForm } from './ActionForm';
import { ActivityScreen } from './ActivityScreen';
import { ClusterActionsScreen } from './ClusterActionsScreen';
import { ClusterHomeScreen } from './ClusterHomeScreen';
import { ActionItemsScreen, RequestsScreen } from './ClusterWorkScreens';
import { ManageClusterScreen } from './ManageClusterScreen';
import { MeetingDetailScreen } from './MeetingDetailScreen';
import { MeetingForm } from './MeetingForm';
import { MeetingsScreen } from './MeetingsScreen';
import { MemberSchoolsScreen } from './MemberSchoolsScreen';
import { ProgressScreen } from './ProgressScreen';
import { CLUSTER_TABS, clusterBottomBar, clusterWorkSection, tabOf, tabOfUrl, whenOf } from './clusterRoutes';

const WAITING = new Set(['draft', 'submitted', 'returned', 'approved']);

function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return [words[0]?.[0], words.length > 1 ? words[words.length - 1][0] : undefined].filter(Boolean).join('').toUpperCase() || '?';
}

export function ClusterLeaderApp({ session }: { readonly session: Session }) {
  const { api } = useSession();
  const { isDark } = useTheme();
  const [url, setUrl] = useState(CLUSTER_TABS.home);
  const [when, setWhen] = useState<'upcoming' | 'past'>('upcoming');
  const [activityId, setActivityId] = useState('');
  const [planId, setPlanId] = useState('');
  const [actionId, setActionId] = useState('');
  // The New Action form, or a draft being edited; null when closed.
  const [actionForm, setActionForm] = useState<{ readonly draft?: ClusterActionView; readonly fromMeeting?: string } | null>(null);
  const [actionNotice, setActionNotice] = useState('');
  const [clusters, setClusters] = useState<readonly ClusterSummary[] | null>(null);
  const [clusterId, setClusterId] = useState('');
  const [home, setHome] = useState<GetClusterHomeResponse | null>(null);
  const [plans, setPlans] = useState<readonly MeetingPlan[]>([]);
  const [error, setError] = useState('');
  const bottom = useMemo(() => clusterBottomBar(), []);
  const sections = useMemo(() => [clusterWorkSection()], []);

  const loadClusters = useCallback(() => {
    setError('');
    api
      .getMyClusters()
      .then((answer) => {
        setClusters(answer.clusters);
        setClusterId((current) =>
          answer.clusters.some((cluster) => cluster.id === current) ? current : (answer.clusters[0]?.id ?? ''),
        );
      })
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api]);

  const loadHome = useCallback(() => {
    if (!clusterId) {
      return;
    }
    setError('');
    api
      .getClusterHome(clusterId)
      .then(setHome)
      .catch((cause: unknown) => setError(describe(cause)));
    api
      .call(ClusterMobilizationService.method.listPlans, { clusterId })
      .then((answer) => setPlans(answer.plans))
      .catch(() => setPlans([]));
  }, [api, clusterId]);

  useEffect(loadClusters, [loadClusters]);
  useEffect(() => {
    setHome(null);
    loadHome();
  }, [loadHome]);

  const open = (next: string) => {
    setActivityId('');
    setPlanId('');
    setActionId('');
    setActionForm(null);
    setActionNotice('');
    const tab = tabOf(next.replace(/^cluster:/, '')) ?? tabOfUrl(next);
    if (tab) {
      setWhen(whenOf(next));
      setUrl(CLUSTER_TABS[tab]);
      if (tab === 'home') {
        loadHome();
      }
    } else {
      setUrl(next);
    }
  };
  const tab = tabOfUrl(url);
  const chosen = clusters?.find((cluster) => cluster.id === clusterId);
  const props = { clusterId: chosen?.id ?? '', clusterName: chosen?.name ?? '' };
  const nextPlan = plans.filter((plan) => WAITING.has(plan.status)).sort((a, b) => a.plannedOn.localeCompare(b.plannedOn))[0];
  const openPlan = (id: string) => {
    setActivityId('');
    setPlanId(id);
  };

  let screen;
  if (url === MENU_URL) {
    screen = <MenuScreen session={session} sections={sections} isNative={() => true} onOpen={(next) => open(next)} />;
  } else if (clusters === null) {
    screen = error ? <Notice title="The portal did not load" copy={error} /> : <Loading />;
  } else if (clusters.length === 0 || !chosen) {
    screen = <Notice title="No cluster is assigned to you yet" copy="Your CCEO or Programme Lead gives you a cluster. Once they have, it opens here." />;
  } else if (actionForm) {
    screen = (
      <ActionForm
        key={actionForm.draft?.card?.id ?? 'new'}
        {...props}
        draft={actionForm.draft}
        fromMeeting={actionForm.fromMeeting}
        onDone={(id, isSent) => {
          setActionForm(null);
          setActionNotice(isSent ? 'Sent for support. Each school went to the CCEO who holds it.' : 'Draft saved.');
          setUrl(CLUSTER_TABS.actions);
          setActionId(id);
        }}
        onBack={() => setActionForm(null)}
      />
    );
  } else if (actionId) {
    screen = (
      <ActionDetailScreen
        key={actionId}
        actionId={actionId}
        notice={actionNotice}
        onEdit={(draft) => setActionForm({ draft })}
        onBack={() => {
          setActionId('');
          setActionNotice('');
          setUrl(CLUSTER_TABS.actions);
        }}
      />
    );
  } else if (activityId) {
    screen = <ActivityScreen key={activityId} activityId={activityId} onBack={() => setActivityId('')} />;
  } else if (planId) {
    screen = (
      <MeetingDetailScreen
        key={planId}
        planId={planId}
        {...props}
        onOpenActivity={setActivityId}
        onOpenAction={(id) => {
          setPlanId('');
          setActionId(id);
        }}
        onRaiseAction={(meeting) => {
          setPlanId('');
          setActionForm({ fromMeeting: meeting });
        }}
        onBack={() => setPlanId('')}
      />
    );
  } else if (tab === 'meetings') {
    screen = (
      <MeetingsScreen
        key={chosen.id}
        {...props}
        initialWhen={when}
        onPlanMeeting={() => open(CLUSTER_TABS.planMeeting)}
        onMobilize={() => open(CLUSTER_TABS.mobilize)}
        onOpenPlan={openPlan}
        onOpenActivity={setActivityId}
      />
    );
  } else if (tab === 'planMeeting' || tab === 'mobilize') {
    screen = (
      <MeetingForm
        key={`${chosen.id}-${tab}`}
        kind={tab === 'mobilize' ? 'training' : 'meeting'}
        {...props}
        onDone={(id) => {
          setUrl(CLUSTER_TABS.meetings);
          loadHome();
          openPlan(id);
        }}
        onBack={() => open(CLUSTER_TABS.home)}
      />
    );
  } else if (tab === 'schools') {
    screen = <MemberSchoolsScreen key={chosen.id} {...props} />;
  } else if (tab === 'manage') {
    screen = <ManageClusterScreen key={chosen.id} cluster={chosen} onOpenSchools={() => open(CLUSTER_TABS.schools)} onOpenActivity={setActivityId} />;
  } else if (tab === 'progress') {
    screen = <ProgressScreen key={chosen.id} cluster={chosen} />;
  } else if (tab === 'share') {
    screen = <ShareApplicationScreen key={chosen.id} eyebrow={chosen.name} />;
  } else if (tab === 'actions') {
    screen = <ClusterActionsScreen key={chosen.id} {...props} onNew={() => setActionForm({})} onOpen={setActionId} />;
  } else if (tab === 'todos') {
    screen = <ActionItemsScreen key={chosen.id} {...props} />;
  } else if (tab === 'requests') {
    screen = <RequestsScreen key={chosen.id} {...props} />;
  } else {
    screen = (
      <ClusterHomeScreen
        leaderName={session.name}
        home={home}
        error={error}
        clusters={clusters}
        nextPlan={nextPlan}
        onSelectCluster={setClusterId}
        onOpenTab={(next) => open(CLUSTER_TABS[next])}
        onOpenPlan={openPlan}
        onOpenActivity={setActivityId}
        onRetry={loadHome}
      />
    );
  }

  return (
    <AppShell bottom={bottom} activeUrl={url} onOpen={(next) => open(next)} initials={initialsOf(session.name)} onSearch={() => open(CLUSTER_TABS.schools)} hasInbox={false}>
      {screen}
      <StatusBar style={isDark ? 'light' : 'dark'} />
    </AppShell>
  );
}

function Loading() {
  const { colors } = useTheme();
  return (
    <View style={styles.centered}>
      <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />
    </View>
  );
}

function Notice({ title, copy }: { readonly title: string; readonly copy: string }) {
  const { colors } = useTheme();
  return (
    <View style={styles.centered}>
      <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
        <Text style={[styles.noticeTitle, { color: colors.text }]} accessibilityRole="header">
          {title}
        </Text>
        <Text style={[styles.copy, { color: colors.textMuted }]}>{copy}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  copy: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  card: { alignSelf: 'stretch', borderWidth: 1, borderRadius: radius.lg, padding: 20, gap: 8 },
  noticeTitle: { fontFamily: fonts.bold, fontSize: 16 },
});
