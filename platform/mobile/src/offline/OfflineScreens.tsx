/**
 * Field work with no connection (offline capture brief, 2026-11-14,
 * parts 4, 5 and 12). When Edify cannot be reached and the phone holds
 * the signed-in person's schools, the app opens on them: today's visits
 * first, then every school, each with its location and Capture; and the
 * sync queue with its Pending Sync count. When the connection returns the
 * app signs back in by itself and sends what waits.
 */
import { useEffect, useMemo, useState } from 'react';
import { FlatList, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { ChevronLeft, ChevronRight, CloudOff, RefreshCw } from 'lucide-react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { fonts, radius, spacing, useTheme } from '../theme';
import { LocationPanel, dayOf } from './LocationPanel';
import { todayLocal, useOffline } from './OfflineContext';
import { STATUS_TEXT } from './queueLogic';
import type { CachedSchool, QueuedCapture } from './store';
import { VisitPrompt } from './VisitPrompt';

const BLUE = '#1d6fe0';
const TIME = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });

/** The sync queue and the offline schools' state; also reached from More when online. */
export function SyncQueueScreen() {
  const { colors } = useTheme();
  const { store, account, revision, pendingCount, packAt, isOnline, isSignedIn, lastSync, syncNow, refreshPack } = useOffline();
  const [captures, setCaptures] = useState<QueuedCapture[]>([]);
  const [count, setCount] = useState(0);
  const [notice, setNotice] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    if (!store || !account) return;
    let isCurrent = true;
    void Promise.all([store.captures(account.userId), store.schools(account.userId)]).then(([list, schools]) => {
      if (!isCurrent) return;
      setCaptures(list.slice(0, 100));
      setCount(schools.length);
    });
    return () => {
      isCurrent = false;
    };
  }, [store, account, revision]);

  const run = async (task: () => Promise<string | void>) => {
    setIsBusy(true);
    setNotice('');
    try {
      const message = await task();
      if (message) setNotice(message);
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
        Offline schools &amp; sync
      </Text>
      <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
        <Text style={[styles.strong, { color: colors.text }]}>{isOnline ? 'Online' : 'Offline'}</Text>
        <Text style={[styles.text, { color: colors.text }]}>
          {count} schools saved on this phone{packAt ? ` · updated ${TIME.format(new Date(packAt))}` : ''}
        </Text>
        <Text style={[styles.text, { color: pendingCount ? '#b45309' : colors.textMuted }]}>
          {pendingCount ? `${pendingCount} waiting to sync` : 'Nothing waiting to sync'}
        </Text>
        {lastSync?.needsSignIn ? <Text style={[styles.text, { color: colors.danger }]}>Sign in again to sync.</Text> : null}
        {notice ? <Text style={[styles.text, { color: colors.text }]}>{notice}</Text> : null}
        {isSignedIn ? (
          <View style={styles.buttons}>
            <Pressable onPress={() => void run(syncNow)} disabled={isBusy} style={[styles.primary, isBusy && styles.dim]} accessibilityRole="button">
              <RefreshCw size={18} color="#fff" />
              <Text style={styles.primaryText}>Sync now</Text>
            </Pressable>
            <Pressable onPress={() => void run(refreshPack)} disabled={isBusy} style={[styles.outline, isBusy && styles.dim]} accessibilityRole="button">
              <Text style={styles.outlineText}>Update my schools</Text>
            </Pressable>
          </View>
        ) : null}
      </View>
      {captures.length === 0 ? <Text style={[styles.text, { color: colors.textMuted }]}>No captures yet on this phone.</Text> : null}
      {captures.map((c) => (
        <View key={c.id} style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
          <Text style={[styles.strong, { color: colors.text }]}>{c.schoolName}</Text>
          <Text style={[styles.text, { color: colors.text }]}>
            {c.kind === 'confirm' ? 'Location confirmed' : c.target === 'entrance' ? 'Entrance point' : c.kind === 'new' ? 'First location' : 'Correction'}
            {c.lat !== null ? ` · ${c.lat.toFixed(5)}, ${c.lng!.toFixed(5)}` : ''}
            {c.pointSource === 'device' ? ` · ${Math.round(c.accuracyM)} m` : ''}
          </Text>
          <Text style={[styles.text, { color: c.status === 'failed' ? colors.danger : c.status === 'synced' ? '#15803d' : '#b45309' }]}>
            {STATUS_TEXT[c.status]}
          </Text>
          {c.note && c.status !== 'saved_offline' ? <Text style={[styles.meta, { color: colors.textMuted }]}>{c.note}</Text> : null}
          <Text style={[styles.meta, { color: colors.textMuted }]}>Captured {TIME.format(new Date(c.capturedAt ?? c.createdAt))}</Text>
        </View>
      ))}
    </ScrollView>
  );
}

type Tab = 'today' | 'schools' | 'sync';

export interface OfflineFieldAppProps {
  readonly notice: string;
  onRetry(): void;
  onSignOut(): void;
}

/** The app with no connection: the person's saved schools, capture and the queue. */
export function OfflineFieldApp({ notice, onRetry, onSignOut }: OfflineFieldAppProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { store, account, revision, pendingCount, packAt } = useOffline();
  const [tab, setTab] = useState<Tab>('today');
  const [schools, setSchools] = useState<CachedSchool[]>([]);
  const [todayIds, setTodayIds] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [openId, setOpenId] = useState('');

  useEffect(() => {
    if (!store || !account) return;
    let isCurrent = true;
    void Promise.all([store.schools(account.userId), store.plannedOn(account.userId, todayLocal())]).then(([all, planned]) => {
      if (!isCurrent) return;
      setSchools(all);
      setTodayIds(planned.map((p) => p.schoolId));
    });
    return () => {
      isCurrent = false;
    };
  }, [store, account, revision]);

  const shown = useMemo(() => {
    if (tab === 'today') return todayIds.map((id) => schools.find((s) => s.schoolId === id)).filter((s): s is CachedSchool => Boolean(s));
    const q = query.trim().toLowerCase();
    return q ? schools.filter((s) => s.name.toLowerCase().includes(q) || s.code.includes(q) || s.district.toLowerCase().includes(q)) : schools;
  }, [tab, todayIds, schools, query]);

  const open = schools.find((s) => s.schoolId === openId) ?? null;

  return (
    <View style={[styles.app, { backgroundColor: colors.bg, paddingTop: insets.top }]}>
      <View style={styles.banner}>
        <CloudOff size={18} color="#fff" />
        <View style={styles.flex}>
          <Text style={styles.bannerText}>Offline · your saved schools</Text>
          <Text style={styles.bannerSub} numberOfLines={2}>
            {notice || 'Edify cannot be reached.'} Captures are kept on this phone and sync by themselves.
          </Text>
        </View>
        <Pressable onPress={onRetry} accessibilityRole="button" style={styles.bannerButton}>
          <Text style={styles.bannerButtonText}>Try again</Text>
        </Pressable>
      </View>
      {open ? (
        <ScrollView contentContainerStyle={styles.page}>
          <Pressable onPress={() => setOpenId('')} accessibilityRole="link" style={styles.back}>
            <ChevronLeft size={16} color={BLUE} />
            <Text style={styles.backText}>Back</Text>
          </Pressable>
          <Text style={[styles.title, { color: colors.text }]}>{open.name}</Text>
          <Text style={[styles.text, { color: colors.textMuted }]}>
            School ID {open.code || '—'} · {open.district || 'No district'}
            {open.cluster ? ` · ${open.cluster}` : ''}
          </Text>
          <View style={styles.gap} />
          <VisitPrompt school={open} />
          <LocationPanel school={open} footer={<Text style={[styles.meta, { color: colors.textMuted }]}>Offline: the location saved on this phone{packAt ? ` (${dayOf(packAt)})` : ''}.</Text>} />
        </ScrollView>
      ) : (
        <>
          <View style={[styles.tabs, { borderColor: colors.border }]} accessibilityRole="tablist">
            {(
              [
                ['today', `Today (${todayIds.length})`],
                ['schools', `My schools (${schools.length})`],
                ['sync', pendingCount ? `Sync (${pendingCount})` : 'Sync'],
              ] as const
            ).map(([key, label]) => (
              <Pressable
                key={key}
                onPress={() => setTab(key)}
                accessibilityRole="tab"
                accessibilityState={{ selected: tab === key }}
                style={[styles.tab, tab === key && styles.tabOn]}
              >
                <Text style={[styles.tabText, { color: tab === key ? '#fff' : colors.text }]}>{label}</Text>
              </Pressable>
            ))}
          </View>
          {tab === 'sync' ? (
            <SyncQueueScreen />
          ) : (
            <FlatList
              data={shown}
              keyExtractor={(s) => s.schoolId}
              contentContainerStyle={styles.page}
              keyboardShouldPersistTaps="handled"
              ListHeaderComponent={
                tab === 'schools' ? (
                  <TextInput
                    value={query}
                    onChangeText={setQuery}
                    placeholder="Search name, School ID or district"
                    placeholderTextColor={colors.textSubtle}
                    accessibilityLabel="Search your saved schools"
                    style={[styles.search, { color: colors.text, borderColor: colors.border, backgroundColor: colors.card }]}
                  />
                ) : undefined
              }
              ListEmptyComponent={
                <Text style={[styles.text, { color: colors.textMuted }]}>
                  {tab === 'today' ? 'No visits saved for today. Your schools are under My schools.' : 'No school matches.'}
                </Text>
              }
              renderItem={({ item }) => (
                <Pressable
                  onPress={() => setOpenId(item.schoolId)}
                  accessibilityRole="button"
                  style={[styles.row, { borderColor: colors.border, backgroundColor: colors.card }]}
                >
                  <View style={styles.flex}>
                    <Text style={[styles.strong, { color: colors.text }]} numberOfLines={2}>
                      {item.name}
                    </Text>
                    <Text style={[styles.meta, { color: item.lat === null ? '#b45309' : colors.textMuted }]}>
                      {item.code} · {item.lat === null ? 'GPS location not captured' : item.locationStatus === 'verified' ? 'Verified location' : 'Location not yet verified'}
                    </Text>
                  </View>
                  <ChevronRight size={20} color={colors.textMuted} />
                </Pressable>
              )}
            />
          )}
          <Pressable onPress={onSignOut} accessibilityRole="button" style={styles.signOut}>
            <Text style={[styles.meta, { color: colors.textMuted }]}>Sign out</Text>
          </Pressable>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  app: { flex: 1 },
  flex: { flex: 1 },
  page: { padding: spacing.md, gap: spacing.sm, paddingBottom: spacing.xl },
  title: { fontFamily: fonts.bold, fontSize: 20 },
  card: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: 4 },
  strong: { fontFamily: fonts.semibold, fontSize: 15 },
  text: { fontFamily: fonts.medium, fontSize: 14 },
  meta: { fontFamily: fonts.regular, fontSize: 13 },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.sm },
  primary: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: BLUE, borderRadius: radius.sm, paddingHorizontal: 16, minHeight: 48 },
  primaryText: { fontFamily: fonts.semibold, fontSize: 16, color: '#fff' },
  outline: { borderWidth: 1.5, borderColor: BLUE, borderRadius: radius.sm, paddingHorizontal: 14, minHeight: 48, justifyContent: 'center' },
  outlineText: { fontFamily: fonts.semibold, fontSize: 15, color: BLUE },
  dim: { opacity: 0.6 },
  banner: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#334155', paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  bannerText: { fontFamily: fonts.semibold, fontSize: 15, color: '#fff' },
  bannerSub: { fontFamily: fonts.regular, fontSize: 12, color: '#e2e8f0' },
  bannerButton: { borderWidth: 1, borderColor: '#fff', borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 40, justifyContent: 'center' },
  bannerButtonText: { fontFamily: fonts.semibold, fontSize: 14, color: '#fff' },
  tabs: { flexDirection: 'row', margin: spacing.md, marginBottom: 0, borderWidth: 1, borderRadius: radius.md, overflow: 'hidden' },
  tab: { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4 },
  tabOn: { backgroundColor: BLUE },
  tabText: { fontFamily: fonts.semibold, fontSize: 14 },
  search: { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 48, fontFamily: fonts.regular, fontSize: 16, marginBottom: spacing.sm },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderWidth: 1, borderRadius: radius.md, padding: spacing.md, minHeight: 64 },
  back: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 44 },
  backText: { fontFamily: fonts.semibold, fontSize: 15, color: BLUE },
  gap: { height: spacing.sm },
  signOut: { alignItems: 'center', minHeight: 44, justifyContent: 'center' },
});
