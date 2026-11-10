/**
 * The Cluster Leader's Home (brief A3): the cluster they lead, its overview
 * counts (each opens what it counts), the actions that need them, the
 * cluster's upcoming activities and the quick actions. Drawn in the Home
 * screen's own frame — the hero, the cards, the type — so the portal reads
 * as part of the same app.
 */
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { CalendarDays, ChevronRight, MapPin, Users } from 'lucide-react-native';

import type {
  ClusterActivity,
  ClusterSummary,
  GetClusterHomeResponse,
  HomeCount,
  QuickAction,
} from '../../gen/edify/clusters/v1/leadership_pb';
import { fonts, radius, toneColors, useTheme } from '../../theme';
import { dateBox, longDate, tabOf } from './clusterRoutes';
import type { ClusterTab } from './clusterRoutes';

interface ClusterHomeScreenProps {
  readonly home: GetClusterHomeResponse | null;
  readonly error: string;
  readonly clusters: readonly ClusterSummary[];
  readonly onSelectCluster: (clusterId: string) => void;
  readonly onOpenTab: (tab: ClusterTab) => void;
  readonly onRetry: () => void;
}

export function ClusterHomeScreen({ home, error, clusters, onSelectCluster, onOpenTab, onRetry }: ClusterHomeScreenProps) {
  const { colors } = useTheme();
  const cluster = home?.cluster;
  const card = [styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }];
  const open = (href: string) => {
    const tab = tabOf(href);
    if (tab) {
      onOpenTab(tab);
    }
  };

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LinearGradient colors={colors.heroGradient} style={styles.hero}>
        <Text style={styles.eyebrow}>CLUSTER LEADER PORTAL</Text>
        <Text style={styles.name} accessibilityRole="header">
          {cluster?.name ?? ' '}
        </Text>
        {cluster ? (
          <View style={styles.heroLine}>
            <MapPin size={14} color="rgba(255,255,255,0.8)" />
            <Text style={styles.heroText}>{[cluster.district, cluster.subCounty].filter(Boolean).join(' · ')}</Text>
          </View>
        ) : null}
        {cluster?.myAssignment ? (
          <Text style={styles.heroMeta}>
            Leading since {longDate(cluster.myAssignment.startsOn)}
            {cluster.responsibleStaff ? ` · CCEO ${cluster.responsibleStaff}` : ''}
          </Text>
        ) : null}
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

      {home ? (
        <>
          <View style={card}>
            <Text style={[styles.cardTitle, { color: colors.text }]} accessibilityRole="header">
              Cluster overview
            </Text>
            <View style={styles.tiles}>
              {home.overview.map((count) => (
                <CountTile key={count.key} count={count} onOpen={open} />
              ))}
            </View>
          </View>

          <View style={card}>
            <Text style={[styles.cardTitle, { color: colors.text }]} accessibilityRole="header">
              My priority actions
            </Text>
            {home.priorityActions.length === 0 ? (
              <Text style={[styles.copy, { color: colors.textMuted }]}>
                Nothing needs you right now. New work appears here as soon as it is yours to do.
              </Text>
            ) : (
              home.priorityActions.map((action) => {
                const tone = toneColors(colors, action.tone);
                return (
                  <Pressable key={action.key} onPress={() => open(action.href)} accessibilityRole="link" style={[styles.row, { borderColor: colors.raisedBorder }]}>
                    <View style={[styles.badge, { backgroundColor: tone.soft }]}>
                      <Text style={[styles.badgeText, { color: tone.fg }]}>{action.count}</Text>
                    </View>
                    <View style={styles.rowBody}>
                      <Text style={[styles.rowTitle, { color: colors.text }]}>{action.label}</Text>
                      {action.detail ? <Text style={[styles.rowSub, { color: colors.textMuted }]}>{action.detail}</Text> : null}
                    </View>
                    <ChevronRight size={16} color={colors.textMuted} />
                  </Pressable>
                );
              })
            )}
          </View>

          <View style={card}>
            <View style={styles.cardHead}>
              <Text style={[styles.cardTitle, { color: colors.text }]} accessibilityRole="header">
                Upcoming cluster activities
              </Text>
              {home.upcoming.length > 0 ? (
                <Pressable onPress={() => onOpenTab('activities')} accessibilityRole="link" hitSlop={10}>
                  <Text style={[styles.link, { color: colors.link }]}>See all</Text>
                </Pressable>
              ) : null}
            </View>
            {home.upcoming.length === 0 ? (
              <Text style={[styles.copy, { color: colors.textMuted }]}>
                No cluster activity is planned yet. Once your CCEO schedules one, it appears here.
              </Text>
            ) : (
              home.upcoming.slice(0, 3).map((activity) => <ActivityRow key={activity.id} activity={activity} />)
            )}
          </View>

          <View style={card}>
            <Text style={[styles.cardTitle, { color: colors.text }]} accessibilityRole="header">
              Quick actions
            </Text>
            <View style={styles.actions}>
              {home.quickActions.map((action) => (
                <QuickActionButton key={action.key} action={action} onOpen={open} />
              ))}
            </View>
          </View>
        </>
      ) : null}
    </ScrollView>
  );
}

function CountTile({ count, onOpen }: { readonly count: HomeCount; readonly onOpen: (href: string) => void }) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={() => onOpen(count.href)}
      accessibilityRole="link"
      accessibilityLabel={`${count.label}: ${count.value}`}
      style={[styles.tile, { backgroundColor: colors.surface, borderColor: colors.border }]}
    >
      <Text style={[styles.tileValue, { color: colors.text }]}>{count.value}</Text>
      <View style={styles.tileFoot}>
        <Text style={[styles.tileLabel, { color: colors.textMuted }]}>{count.label}</Text>
        <ChevronRight size={14} color={colors.textMuted} />
      </View>
    </Pressable>
  );
}

export function ActivityRow({ activity }: { readonly activity: ClusterActivity }) {
  const { colors } = useTheme();
  const box = dateBox(activity.date);
  return (
    <View style={[styles.row, { borderColor: colors.raisedBorder }]} accessible accessibilityLabel={`${activity.name}, ${longDate(activity.date)}`}>
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
      <View style={styles.rowBody}>
        <Text style={[styles.rowTitle, { color: colors.text }]}>{activity.name}</Text>
        <Text style={[styles.rowSub, { color: colors.textMuted }]}>
          {[activity.type, activity.location || 'Venue to be set'].join(' · ')}
        </Text>
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

function QuickActionButton({ action, onOpen }: { readonly action: QuickAction; readonly onOpen: (href: string) => void }) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={() => onOpen(action.href)}
      disabled={!action.enabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: !action.enabled }}
      accessibilityHint={action.enabled ? undefined : action.reason}
      style={[
        styles.action,
        action.enabled
          ? { backgroundColor: colors.primary, borderColor: colors.primary }
          : { backgroundColor: colors.surfaceMuted, borderColor: colors.border },
      ]}
    >
      <Text style={[styles.actionLabel, { color: action.enabled ? colors.primaryInk : colors.textSubtle }]}>{action.label}</Text>
      {action.enabled ? null : <Text style={[styles.actionReason, { color: colors.textSubtle }]}>{action.reason}</Text>}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 24, gap: 10 },
  hero: { paddingTop: 22, paddingHorizontal: 20, paddingBottom: 40, marginBottom: -24, gap: 6 },
  eyebrow: { fontFamily: fonts.bold, fontSize: 11, letterSpacing: 1.4, color: 'rgba(215, 230, 239, 0.88)' },
  name: { fontFamily: fonts.bold, fontSize: 24, lineHeight: 29, color: '#ffffff', letterSpacing: -0.3 },
  heroLine: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  heroText: { fontFamily: fonts.semibold, fontSize: 13, color: 'rgba(255,255,255,0.9)' },
  heroMeta: { fontFamily: fonts.medium, fontSize: 12, color: 'rgba(215, 230, 239, 0.88)' },
  switcher: { gap: 8, paddingHorizontal: 12, paddingTop: 30 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 14, paddingVertical: 7 },
  chipText: { fontFamily: fonts.semibold, fontSize: 13 },
  card: { marginHorizontal: 12, padding: 16, borderWidth: 1, borderRadius: radius.lg, gap: 10 },
  cardHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  cardTitle: { fontFamily: fonts.bold, fontSize: 15, lineHeight: 19.5 },
  copy: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  link: { fontFamily: fonts.semibold, fontSize: 13 },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tile: { flexGrow: 1, flexBasis: '45%', borderWidth: 1, borderRadius: radius.md, padding: 12, gap: 4 },
  tileValue: { fontFamily: fonts.bold, fontSize: 26, lineHeight: 30, fontVariant: ['tabular-nums'] },
  tileFoot: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 4 },
  tileLabel: { flex: 1, fontFamily: fonts.semibold, fontSize: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderRadius: radius.md, padding: 10 },
  rowBody: { flex: 1, gap: 2 },
  rowTitle: { fontFamily: fonts.semibold, fontSize: 14 },
  rowSub: { fontFamily: fonts.medium, fontSize: 12 },
  facts: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2 },
  fact: { fontFamily: fonts.medium, fontSize: 12 },
  badge: { minWidth: 36, height: 36, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 8 },
  badgeText: { fontFamily: fonts.bold, fontSize: 14 },
  datebox: { width: 46, height: 46, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  dateMonth: { fontFamily: fonts.bold, fontSize: 10, lineHeight: 12 },
  dateDay: { fontFamily: fonts.bold, fontSize: 18, lineHeight: 20 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  action: { flexGrow: 1, flexBasis: '45%', minHeight: 48, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 10, justifyContent: 'center', gap: 2 },
  actionLabel: { fontFamily: fonts.semibold, fontSize: 13 },
  actionReason: { fontFamily: fonts.medium, fontSize: 11, lineHeight: 14 },
  cta: { alignSelf: 'flex-start', minHeight: 44, justifyContent: 'center', borderRadius: radius.sm, paddingHorizontal: 16 },
  ctaText: { fontFamily: fonts.semibold, fontSize: 13 },
});
