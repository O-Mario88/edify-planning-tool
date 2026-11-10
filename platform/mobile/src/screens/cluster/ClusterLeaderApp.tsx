/**
 * The app for a Cluster Leader (brief A1-A3): the clusters assigned to them
 * and nothing else. The gateway decides that reach on every request; this
 * screen only shows what it answers — Home, the member schools and the
 * upcoming activities of the cluster chosen, and the account menu.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';

import { describe, useSession } from '../../auth/SessionContext';
import type { ClusterSummary, GetClusterHomeResponse } from '../../gen/edify/clusters/v1/leadership_pb';
import type { Session } from '../../gen/edify/identity/v1/identity_pb';
import { AppShell, MENU_URL } from '../../shell/AppShell';
import { fonts, radius, useTheme } from '../../theme';
import { MenuScreen } from '../MoreScreen';
import { ActivityRow, ClusterHomeScreen } from './ClusterHomeScreen';
import { MemberSchoolsScreen } from './MemberSchoolsScreen';
import { CLUSTER_TABS, clusterBottomBar, tabOfUrl } from './clusterRoutes';
import type { ClusterTab } from './clusterRoutes';

function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return [words[0]?.[0], words.length > 1 ? words[words.length - 1][0] : undefined].filter(Boolean).join('').toUpperCase() || '?';
}

export function ClusterLeaderApp({ session }: { readonly session: Session }) {
  const { api } = useSession();
  const { isDark } = useTheme();
  const [url, setUrl] = useState(CLUSTER_TABS.home);
  const [clusters, setClusters] = useState<readonly ClusterSummary[] | null>(null);
  const [clusterId, setClusterId] = useState('');
  const [home, setHome] = useState<GetClusterHomeResponse | null>(null);
  const [error, setError] = useState('');
  const bottom = useMemo(() => clusterBottomBar(), []);

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

  const tab = tabOfUrl(url);
  const openTab = (next: ClusterTab) => setUrl(CLUSTER_TABS[next]);
  const chosen = clusters?.find((cluster) => cluster.id === clusterId);

  let screen;
  if (url === MENU_URL) {
    screen = <MenuScreen session={session} sections={[]} isNative={() => true} onOpen={(next) => setUrl(next)} />;
  } else if (clusters === null) {
    screen = error ? <Notice title="The portal did not load" copy={error} /> : <Loading />;
  } else if (clusters.length === 0) {
    screen = (
      <Notice
        title="No cluster is assigned to you yet"
        copy="Your CCEO or Programme Lead gives you a cluster. Once they have, it opens here."
      />
    );
  } else if (tab === 'schools' && chosen) {
    screen = <MemberSchoolsScreen key={chosen.id} clusterId={chosen.id} clusterName={chosen.name} />;
  } else if (tab === 'activities') {
    screen = <ActivitiesScreen home={home} clusterName={chosen?.name ?? ''} />;
  } else {
    screen = (
      <ClusterHomeScreen
        home={home}
        error={error}
        clusters={clusters}
        onSelectCluster={setClusterId}
        onOpenTab={openTab}
        onRetry={loadHome}
      />
    );
  }

  return (
    <AppShell
      bottom={bottom}
      activeUrl={url}
      onOpen={(next) => setUrl(next)}
      initials={initialsOf(session.name)}
      onSearch={() => openTab('schools')}
      hasInbox={false}
    >
      {screen}
      <StatusBar style={isDark ? 'light' : 'dark'} />
    </AppShell>
  );
}

function ActivitiesScreen({ home, clusterName }: { readonly home: GetClusterHomeResponse | null; readonly clusterName: string }) {
  const { colors } = useTheme();
  if (!home) {
    return <Loading />;
  }
  return (
    <ScrollView contentContainerStyle={styles.list}>
      <Text style={[styles.eyebrow, { color: colors.eyebrow }]}>{clusterName.toUpperCase()}</Text>
      <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
        Upcoming activities
      </Text>
      {home.upcoming.length === 0 ? (
        <Text style={[styles.copy, { color: colors.textMuted }]}>
          No cluster activity is planned yet. Once your CCEO schedules one, it appears here.
        </Text>
      ) : (
        <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
          {home.upcoming.map((activity) => (
            <ActivityRow key={activity.id} activity={activity} />
          ))}
        </View>
      )}
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
      <View style={[styles.card, styles.notice, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
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
  list: { padding: 12, gap: 8, paddingBottom: 24 },
  eyebrow: { fontFamily: fonts.bold, fontSize: 11, letterSpacing: 1.2 },
  title: { fontFamily: fonts.bold, fontSize: 22, letterSpacing: -0.2, marginBottom: 4 },
  copy: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 12, gap: 8 },
  notice: { alignSelf: 'stretch', padding: 20 },
  noticeTitle: { fontFamily: fonts.bold, fontSize: 16 },
});
