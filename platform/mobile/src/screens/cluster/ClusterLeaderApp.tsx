/**
 * The app for a Cluster Leader (brief A1-A7): the clusters assigned to them
 * and nothing else. The gateway decides that reach on every request; this
 * screen only shows what it answers — Home, the member schools, the cluster's
 * activities (each opens its mobilisation, attendance and minutes), and the
 * work pages under More: plans, action items, requests and the report.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';

import { describe, useSession } from '../../auth/SessionContext';
import type { ClusterActivity, ClusterSummary, GetClusterHomeResponse } from '../../gen/edify/clusters/v1/leadership_pb';
import { ClusterLeadershipService } from '../../gen/edify/clusters/v1/leadership_pb';
import type { Session } from '../../gen/edify/identity/v1/identity_pb';
import { AppShell, MENU_URL } from '../../shell/AppShell';
import { fonts, radius, useTheme } from '../../theme';
import { MenuScreen } from '../MoreScreen';
import { ActivityScreen } from './ActivityScreen';
import { ActivityRow, ClusterHomeScreen } from './ClusterHomeScreen';
import { ActionItemsScreen, ClusterReportScreen, RequestsScreen } from './ClusterWorkScreens';
import { ShareApplicationScreen } from '../loans/ShareSheet';
import { MemberSchoolsScreen } from './MemberSchoolsScreen';
import { PlansScreen } from './PlansScreen';
import { CLUSTER_TABS, clusterBottomBar, clusterWorkSection, tabOf, tabOfUrl, whenOf } from './clusterRoutes';
import { ChoiceRow, OpsTitle } from './opsParts';

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
  const [clusters, setClusters] = useState<readonly ClusterSummary[] | null>(null);
  const [clusterId, setClusterId] = useState('');
  const [home, setHome] = useState<GetClusterHomeResponse | null>(null);
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
  }, [api, clusterId]);

  useEffect(loadClusters, [loadClusters]);
  useEffect(() => {
    setHome(null);
    loadHome();
  }, [loadHome]);

  const open = (next: string) => {
    setActivityId('');
    const tab = tabOf(next.replace(/^cluster:/, ''));
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

  let screen;
  if (url === MENU_URL) {
    screen = <MenuScreen session={session} sections={sections} isNative={() => true} onOpen={(next) => open(next)} />;
  } else if (clusters === null) {
    screen = error ? <Notice title="The portal did not load" copy={error} /> : <Loading />;
  } else if (clusters.length === 0 || !chosen) {
    screen = <Notice title="No cluster is assigned to you yet" copy="Your CCEO or Programme Lead gives you a cluster. Once they have, it opens here." />;
  } else if (activityId) {
    screen = <ActivityScreen key={activityId} activityId={activityId} onBack={() => setActivityId('')} />;
  } else if (tab === 'schools') {
    screen = <MemberSchoolsScreen key={chosen.id} {...props} />;
  } else if (tab === 'activities') {
    screen = <ActivitiesScreen key={`${chosen.id}-${when}`} {...props} when={when} onWhen={setWhen} onOpen={setActivityId} />;
  } else if (tab === 'share') {
    screen = <ShareApplicationScreen key={chosen.id} eyebrow={chosen.name} />;
  } else if (tab === 'plans') {
    screen = <PlansScreen key={chosen.id} {...props} />;
  } else if (tab === 'actions') {
    screen = <ActionItemsScreen key={chosen.id} {...props} />;
  } else if (tab === 'requests') {
    screen = <RequestsScreen key={chosen.id} {...props} />;
  } else if (tab === 'report') {
    screen = <ClusterReportScreen key={chosen.id} {...props} />;
  } else {
    screen = (
      <ClusterHomeScreen
        home={home}
        error={error}
        clusters={clusters}
        onSelectCluster={setClusterId}
        onOpenTab={(next) => open(next)}
        onRetry={loadHome}
      />
    );
  }

  return (
    <AppShell bottom={bottom} activeUrl={url} onOpen={(next) => open(next)} initials={initialsOf(session.name)} onSearch={() => open('schools')} hasInbox={false}>
      {screen}
      <StatusBar style={isDark ? 'light' : 'dark'} />
    </AppShell>
  );
}

interface ActivitiesProps {
  readonly clusterId: string;
  readonly clusterName: string;
  readonly when: 'upcoming' | 'past';
  readonly onWhen: (when: 'upcoming' | 'past') => void;
  readonly onOpen: (activityId: string) => void;
}

function ActivitiesScreen({ clusterId, clusterName, when, onWhen, onOpen }: ActivitiesProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [activities, setActivities] = useState<readonly ClusterActivity[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api
      .call(ClusterLeadershipService.method.listActivities, { clusterId, when })
      .then((answer) => setActivities(answer.activities))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, clusterId, when]);
  return (
    <ScrollView contentContainerStyle={styles.list}>
      <OpsTitle eyebrow={clusterName} title="Activities" copy="Open one to mobilise schools, record attendance or write its minutes." />
      <ChoiceRow
        label="Show"
        value={when}
        choices={[
          { value: 'upcoming', label: 'Upcoming' },
          { value: 'past', label: 'Past 120 days' },
        ]}
        onChange={(value) => onWhen(value === 'past' ? 'past' : 'upcoming')}
      />
      {error ? <Text style={[styles.copy, { color: colors.danger }]}>{error}</Text> : null}
      {activities === null && !error ? <Loading /> : null}
      {activities?.length === 0 ? (
        <Text style={[styles.copy, { color: colors.textMuted }]}>
          {when === 'past' ? 'No activity in the last 120 days.' : 'No cluster activity is planned yet. Once your CCEO schedules one, it appears here.'}
        </Text>
      ) : null}
      {activities?.map((activity) => (
        <Pressable key={activity.id} onPress={() => onOpen(activity.id)} accessibilityRole="button" accessibilityLabel={`Open ${activity.name}`}>
          <ActivityRow activity={activity} />
        </Pressable>
      ))}
    </ScrollView>
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
  list: { padding: 12, gap: 10, paddingBottom: 24 },
  copy: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  card: { alignSelf: 'stretch', borderWidth: 1, borderRadius: radius.lg, padding: 20, gap: 8 },
  noticeTitle: { fontFamily: fonts.bold, fontSize: 16 },
});
