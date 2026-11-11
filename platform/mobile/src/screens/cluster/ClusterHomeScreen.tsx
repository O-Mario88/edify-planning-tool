/**
 * The Cluster Leader's Home (owner's mockup and the Cluster Action brief,
 * 2026-11-11): a greeting, the cluster and its schools, four large actions —
 * Plan Meeting, My Schools, Action & Follow-up, Mobilize Schools — the next
 * meeting, and what needs the leader now (the gateway's own records, each
 * opening what it counts). No dashboard: the figures live in Progress &
 * Reports.
 */
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { BarChart3, CalendarDays, CalendarPlus, ChevronRight, ClipboardList, GraduationCap, School, Users } from 'lucide-react-native';
import type { LucideIcon } from 'lucide-react-native';

import type { ClusterActivity, ClusterSummary, GetClusterHomeResponse } from '../../gen/edify/clusters/v1/leadership_pb';
import type { MeetingPlan } from '../../gen/edify/clusters/v1/mobilization_pb';
import { fonts, radius, toneColors, useTheme } from '../../theme';
import { planStatus } from './clusterData';
import { dateBox, longDate, tabOf } from './clusterRoutes';
import type { ClusterTab } from './clusterRoutes';

interface ClusterHomeScreenProps {
  readonly leaderName: string;
  readonly home: GetClusterHomeResponse | null;
  readonly error: string;
  readonly clusters: readonly ClusterSummary[];
  /** The leader's soonest plan still waiting on staff, if any. */
  readonly nextPlan?: MeetingPlan;
  readonly onSelectCluster: (clusterId: string) => void;
  readonly onOpenTab: (tab: ClusterTab) => void;
  readonly onOpenPlan: (planId: string) => void;
  readonly onOpenActivity: (activityId: string) => void;
  readonly onRetry: () => void;
}

const TILES: readonly { readonly label: string; readonly icon: LucideIcon; readonly tab: ClusterTab }[] = [
  { label: 'Plan Meeting', icon: CalendarPlus, tab: 'planMeeting' },
  { label: 'My Schools', icon: School, tab: 'manage' },
  { label: 'Action & Follow-up', icon: ClipboardList, tab: 'actions' },
  { label: 'Mobilize Schools', icon: GraduationCap, tab: 'mobilize' },
];

export function ClusterHomeScreen(props: ClusterHomeScreenProps) {
  const { leaderName, home, error, clusters, nextPlan, onSelectCluster, onOpenTab, onOpenPlan, onOpenActivity, onRetry } = props;
  const { colors } = useTheme();
  const cluster = home?.cluster;
  const card = [styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }];
  const open = (href: string) => {
    const tab = tabOf(href);
    if (tab) {
      onOpenTab(tab);
    }
  };
  const firstName = leaderName.trim().split(/\s+/)[0] || 'Cluster Leader';
  const next = home?.upcoming[0];

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LinearGradient colors={colors.heroGradient} style={styles.hero}>
        <Text style={styles.greeting} accessibilityRole="header">
          Hello, {firstName} 👋
        </Text>
        <Text style={styles.heroText}>{cluster ? [cluster.name, cluster.district].filter(Boolean).join(' · ') : ' '}</Text>
      </LinearGradient>

      {clusters.length > 1 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.switcher}>
          {clusters.map((option) => {
            const isOn = option.id === cluster?.id;
            return (
              <Pressable
                key={option.id}
                onPress={() => onSelectCluster(option.id)}
                accessibilityRole="tab"
                accessibilityState={{ selected: isOn }}
                style={[styles.chip, { backgroundColor: isOn ? colors.primary : colors.raised, borderColor: isOn ? colors.primary : colors.border }]}
              >
                <Text style={[styles.chipText, { color: isOn ? colors.primaryInk : colors.text }]}>{option.name}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      ) : null}

      {error ? (
        <View style={card}>
          <Text style={[styles.cardTitle, { color: colors.text }]}>Your cluster did not load</Text>
          <Text style={[styles.copy, { color: colors.textMuted }]}>{error}</Text>
          <Pressable onPress={onRetry} accessibilityRole="button" style={[styles.cta, { backgroundColor: colors.primary }]}>
            <Text style={[styles.ctaText, { color: colors.primaryInk }]}>Try again</Text>
          </Pressable>
        </View>
      ) : null}

      {cluster ? (
        <Pressable
          onPress={() => onOpenTab('schools')}
          accessibilityRole="button"
          accessibilityLabel={`My Cluster, ${cluster.memberSchoolCount} schools`}
          style={[styles.clusterCard, { backgroundColor: colors.primarySoft }]}
        >
          <Users size={30} color={colors.primary} />
          <View style={styles.flex}>
            <Text style={[styles.clusterEyebrow, { color: colors.text }]}>My Cluster</Text>
            <Text style={[styles.clusterCount, { color: colors.text }]}>{cluster.memberSchoolCount} Schools</Text>
          </View>
          <ChevronRight size={22} color={colors.text} />
        </Pressable>
      ) : null}

      <View style={styles.tiles}>
        {TILES.map((tile) => (
          <Pressable
            key={tile.tab}
            onPress={() => onOpenTab(tile.tab)}
            accessibilityRole="button"
            style={[styles.tile, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}
          >
            <tile.icon size={34} color={colors.primary} />
            <Text style={[styles.tileLabel, { color: colors.text }]}>{tile.label}</Text>
          </Pressable>
        ))}
      </View>

      {next || nextPlan ? (
        <Pressable
          onPress={() => (next ? onOpenActivity(next.id) : nextPlan && onOpenPlan(nextPlan.id))}
          accessibilityRole="button"
          style={[styles.upcoming, { backgroundColor: colors.primarySoft }]}
        >
          <View style={styles.flex}>
            <View style={styles.upcomingHead}>
              <CalendarDays size={18} color={colors.primary} />
              <Text style={[styles.cardTitle, { color: colors.text }]}>Upcoming</Text>
            </View>
            {next ? <UpcomingLine title={next.name} detail={`${longDate(next.date)}${next.location ? ` · ${next.location}` : ''}`} /> : null}
            {!next && nextPlan ? (
              <UpcomingLine
                title={nextPlan.title}
                detail={`${longDate(nextPlan.plannedOn)}${nextPlan.startsAt ? ` · ${nextPlan.startsAt}` : ''} · ${planStatus(nextPlan.status).label}`}
              />
            ) : null}
          </View>
          <ChevronRight size={22} color={colors.text} />
        </Pressable>
      ) : null}

      {home ? (
        <View style={card}>
          <Text style={[styles.cardTitle, { color: colors.text }]} accessibilityRole="header">
            Needs Your Attention
          </Text>
          {home.priorityActions.length === 0 ? (
            <Text style={[styles.copy, { color: colors.textMuted }]}>Nothing needs you right now.</Text>
          ) : (
            home.priorityActions.map((action) => {
              const tone = toneColors(colors, action.tone);
              return (
                <Pressable key={action.key} onPress={() => open(action.href)} accessibilityRole="link" style={[styles.row, { borderColor: colors.raisedBorder }]}>
                  <View style={[styles.badge, { backgroundColor: tone.soft }]}>
                    <Text style={[styles.badgeText, { color: tone.fg }]}>{action.count}</Text>
                  </View>
                  <View style={styles.flex}>
                    <Text style={[styles.rowTitle, { color: colors.text }]}>{action.label}</Text>
                    {action.detail ? <Text style={[styles.rowSub, { color: colors.textMuted }]}>{action.detail}</Text> : null}
                  </View>
                  <ChevronRight size={16} color={colors.textMuted} />
                </Pressable>
              );
            })
          )}
        </View>
      ) : null}

      <Pressable onPress={() => onOpenTab('progress')} accessibilityRole="button" style={[styles.card, styles.rowCard, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
        <BarChart3 size={24} color={colors.primary} />
        <Text style={[styles.rowTitle, styles.flex, { color: colors.text }]}>Progress & Reports</Text>
        <ChevronRight size={18} color={colors.textMuted} />
      </Pressable>
    </ScrollView>
  );
}

function UpcomingLine({ title, detail }: { readonly title: string; readonly detail: string }) {
  const { colors } = useTheme();
  return (
    <>
      <Text style={[styles.rowTitle, { color: colors.text }]}>{title}</Text>
      <Text style={[styles.rowSub, { color: colors.textMuted }]}>{detail}</Text>
    </>
  );
}

export function ActivityRow({ activity }: { readonly activity: ClusterActivity }) {
  const { colors } = useTheme();
  const box = dateBox(activity.date);
  return (
    <View style={[styles.row, { borderColor: colors.raisedBorder, backgroundColor: colors.raised }]} accessible accessibilityLabel={`${activity.name}, ${longDate(activity.date)}`}>
      <View style={[styles.datebox, { backgroundColor: colors.primarySoft }]}>
        {box.day ? (
          <>
            <Text style={[styles.dateMonth, { color: colors.link }]}>{box.month}</Text>
            <Text style={[styles.dateDay, { color: colors.link }]}>{box.day}</Text>
          </>
        ) : (
          <CalendarDays size={18} color={colors.link} />
        )}
      </View>
      <View style={styles.flex}>
        <Text style={[styles.rowTitle, { color: colors.text }]}>{activity.name}</Text>
        <Text style={[styles.rowSub, { color: colors.textMuted }]}>{[activity.type, activity.location || 'Venue to be set'].join(' · ')}</Text>
        <View style={styles.facts}>
          <Users size={12} color={colors.textMuted} />
          <Text style={[styles.fact, { color: colors.textMuted }]}>
            {activity.invitedSchools} invited · {activity.confirmedSchools} confirmed
          </Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 24, gap: 12 },
  hero: { paddingTop: 22, paddingHorizontal: 20, paddingBottom: 40, marginBottom: -28, gap: 4 },
  greeting: { fontFamily: fonts.bold, fontSize: 24, lineHeight: 30, color: '#ffffff' },
  heroText: { fontFamily: fonts.semibold, fontSize: 14, color: 'rgba(255,255,255,0.9)' },
  switcher: { gap: 8, paddingHorizontal: 12, paddingTop: 30 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 14, paddingVertical: 7 },
  chipText: { fontFamily: fonts.semibold, fontSize: 13 },
  flex: { flex: 1, gap: 2 },
  clusterCard: { marginHorizontal: 12, borderRadius: radius.lg, padding: 16, flexDirection: 'row', alignItems: 'center', gap: 14 },
  clusterEyebrow: { fontFamily: fonts.semibold, fontSize: 14 },
  clusterCount: { fontFamily: fonts.bold, fontSize: 22 },
  tiles: { marginHorizontal: 12, flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  tile: { flexGrow: 1, flexBasis: '45%', minHeight: 112, borderWidth: 1, borderRadius: radius.lg, alignItems: 'center', justifyContent: 'center', gap: 10, padding: 12 },
  tileLabel: { fontFamily: fonts.bold, fontSize: 16, textAlign: 'center' },
  upcoming: { marginHorizontal: 12, borderRadius: radius.lg, padding: 14, flexDirection: 'row', alignItems: 'center', gap: 10 },
  upcomingHead: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4 },
  card: { marginHorizontal: 12, padding: 16, borderWidth: 1, borderRadius: radius.lg, gap: 10 },
  rowCard: { flexDirection: 'row', alignItems: 'center' },
  cardTitle: { fontFamily: fonts.bold, fontSize: 16 },
  copy: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderRadius: radius.md, padding: 10 },
  rowTitle: { fontFamily: fonts.semibold, fontSize: 15 },
  rowSub: { fontFamily: fonts.medium, fontSize: 13 },
  facts: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2 },
  fact: { fontFamily: fonts.medium, fontSize: 12 },
  badge: { minWidth: 36, height: 36, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 8 },
  badgeText: { fontFamily: fonts.bold, fontSize: 14 },
  datebox: { width: 46, height: 46, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  dateMonth: { fontFamily: fonts.bold, fontSize: 10, lineHeight: 12 },
  dateDay: { fontFamily: fonts.bold, fontSize: 18, lineHeight: 20 },
  cta: { alignSelf: 'flex-start', minHeight: 44, justifyContent: 'center', borderRadius: radius.sm, paddingHorizontal: 16 },
  ctaText: { fontFamily: fonts.semibold, fontSize: 13 },
});
