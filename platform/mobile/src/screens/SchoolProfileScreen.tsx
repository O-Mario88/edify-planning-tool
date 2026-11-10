/**
 * A school's profile (School 360): the page the web renders for the same
 * person (pages/schools/detail.html), drawn natively — its back link, title,
 * badges and buttons, its tab rail, and the open tab's blocks.
 *
 * Links stay inside the profile where the page itself only switches tab,
 * year or period; another school's profile opens natively; everything else
 * opens on the web. Add to Project opens the native drawer; the page's other
 * buttons open the profile on the web, where their drawers are.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ComponentRef } from 'react';
import { ActivityIndicator, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import type { NativeScrollEvent, NativeSyntheticEvent } from 'react-native';
import { ChevronLeft } from 'lucide-react-native';

import { ApiError } from '../api/connect';
import { describe, useSession } from '../auth/SessionContext';
import type { PageAction, PageBadge } from '../gen/edify/screens/v1/page_pb';
import type { GetSchoolProfileResponse } from '../gen/edify/screens/v1/school_profile_pb';
import { fonts, toneColors, useTheme } from '../theme';
import { MakeRoomContext } from '../ui/Dropdown';
import { PageBlocksView } from '../ui/page/PageBlocksView';
import { PageLinkContext } from '../ui/page/shared';
import { WebDrawer } from '../ui/WebDrawer';
import { PlanningDrawer } from '../ui/planning/PlanningDrawer';
import { AddToProjectDrawer } from './SchoolActionDrawers';

interface ProfileQuery {
  readonly tab: string;
  readonly fy: string;
  readonly period: string;
}

const START: ProfileQuery = { tab: '', fy: '', period: '' };
/** What the profile's own links may change without leaving it. */
const PROFILE_KEYS: readonly string[] = ['tab', 'fy', 'period'];
const TOAST_MS = 4000;

/** The profile's drawers the app draws from the web's own (WebDrawer), by
 * the end of the path the page's button opens. */
const WEB_DRAWERS: readonly (readonly [string, string])[] = [
  ['/edit-drawer', 'edit'],
  ['/close-drawer', 'close'],
  ['/ssa-entry', 'ssa-entry'],
];

/** The profile's planning drawers (PlanningDrawer), by the path the page's
 * button opens. */
const PLANNING_DRAWERS: readonly (readonly [string, 'schedule' | 'assign'])[] = [
  ['/planning/schedule-modal', 'schedule'],
  ['/planning/assign-partner-modal', 'assign'],
];

interface SchoolProfileScreenProps {
  /** The school's record id. */
  readonly schoolId: string;
  readonly onBack: () => void;
  /** Open another school's profile (a link on this one). */
  readonly onOpenSchool: (schoolId: string) => void;
}

export function SchoolProfileScreen({ schoolId, onBack, onOpenSchool }: SchoolProfileScreenProps) {
  const { api, environment, signOut } = useSession();
  const { colors } = useTheme();
  const [query, setQuery] = useState<ProfileQuery>(START);
  const [data, setData] = useState<GetSchoolProfileResponse | null>(null);
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [isProjectOpen, setIsProjectOpen] = useState(false);
  const [webDrawer, setWebDrawer] = useState<string | null>(null);
  const [planningDrawer, setPlanningDrawer] = useState<'schedule' | 'assign' | null>(null);
  const [toast, setToast] = useState('');
  const scroller = useRef<ComponentRef<typeof ScrollView>>(null);
  const offset = useRef(0);

  const load = useCallback(async () => {
    setIsBusy(true);
    setError('');
    try {
      setData(await api.getSchoolProfile({ schoolId, ...query }));
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'unauthenticated') {
        await signOut();
        return;
      }
      setError(describe(cause));
    } finally {
      setIsBusy(false);
    }
  }, [api, query, schoolId, signOut]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!toast) {
      return undefined;
    }
    const timer = setTimeout(() => setToast(''), TOAST_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  const openWeb = useCallback(
    (path: string) => void Linking.openURL(`${environment.identityUrl}${path}`),
    [environment.identityUrl],
  );

  const openLink = useCallback(
    (href: string) => {
      const url = new URL(href, 'http://edify.local');
      const own = data?.webPath ?? `/schools/${schoolId}`;
      const params = url.searchParams;
      const keys = [...params.keys()];
      if (url.pathname === own && keys.every((key) => PROFILE_KEYS.includes(key))) {
        setQuery((current) => ({
          tab: params.get('tab') ?? current.tab,
          fy: params.get('fy') ?? current.fy,
          period: params.get('period') ?? current.period,
        }));
        scroller.current?.scrollTo({ y: 0, animated: false });
        return;
      }
      const school = /^\/schools\/([^/]+)$/.exec(url.pathname);
      if (school && school[1] !== 'closed' && keys.length === 0) {
        onOpenSchool(decodeURIComponent(school[1]));
        return;
      }
      openWeb(url.pathname + url.search);
    },
    [data?.webPath, onOpenSchool, openWeb, schoolId],
  );

  const makeRoom = useCallback((pixels: number) => {
    scroller.current?.scrollTo({ y: offset.current + pixels, animated: false });
  }, []);

  function runAction(action: PageAction) {
    if (action.href.endsWith('/assign-to-project')) {
      setIsProjectOpen(true);
      return;
    }
    const drawer = WEB_DRAWERS.find(([ending]) => action.href.split('?')[0].endsWith(ending));
    if (drawer) {
      setWebDrawer(drawer[1]);
      return;
    }
    const planning = PLANNING_DRAWERS.find(([path]) => action.href.split('?')[0] === path);
    if (planning) {
      setPlanningDrawer(planning[1]);
      return;
    }
    // The page's other drawers are on the web: open the profile there.
    openWeb(`${data?.webPath ?? `/schools/${schoolId}`}?tab=${query.tab || 'overview'}`);
  }

  function trackScroll(event: NativeSyntheticEvent<NativeScrollEvent>) {
    offset.current = event.nativeEvent.contentOffset.y;
  }

  const header = data?.header;
  return (
    <PageLinkContext.Provider value={openLink}>
      <MakeRoomContext.Provider value={makeRoom}>
        <ScrollView
          ref={scroller}
          onScroll={trackScroll}
          scrollEventThrottle={16}
          contentContainerStyle={styles.page}
          keyboardShouldPersistTaps="handled"
        >
          <Pressable onPress={onBack} accessibilityRole="link" hitSlop={8} style={styles.back}>
            <ChevronLeft size={14} color={colors.link} />
            <Text style={[styles.backText, { color: colors.link }]}>{header?.backLabel || 'Back to School Directory'}</Text>
          </Pressable>
          {data && header ? (
            <>
              <View>
                <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
                  {header.title}
                </Text>
                <Description text={header.description} />
              </View>
              <View style={styles.controls}>
                {header.badges.map((badge, index) => (
                  <Badge key={badge.text} badge={badge} isWide={index === 0} />
                ))}
                {header.actions.map((action) => (
                  <ActionButton key={action.key} action={action} onPress={() => runAction(action)} />
                ))}
              </View>
              <TabRail
                tabs={data.tabs.map((tab) => ({ key: tab.key, label: tab.label, active: tab.active }))}
                onPick={(tab) => setQuery((current) => ({ ...current, tab }))}
              />
              {isBusy ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
              {error ? (
                <Text style={[styles.error, { color: colors.danger }]} accessibilityRole="alert">
                  {error}
                </Text>
              ) : null}
              <PageBlocksView
                blocks={data.blocks}
                onFilter={(name, value) => setQuery((current) => ({ ...current, [name]: value }))}
              />
            </>
          ) : error ? (
            <Text style={[styles.error, { color: colors.danger }]} accessibilityRole="alert">
              {error}
            </Text>
          ) : (
            <ActivityIndicator color={colors.primary} accessibilityLabel="Loading the school's profile" />
          )}
        </ScrollView>
        {isProjectOpen ? (
          <AddToProjectDrawer
            schoolId={schoolId}
            onClose={() => setIsProjectOpen(false)}
            onSaved={(message) => {
              setIsProjectOpen(false);
              setToast(message);
              void load();
            }}
          />
        ) : null}
        {webDrawer ? (
          <WebDrawer
            schoolId={schoolId}
            kind={webDrawer}
            onClose={() => setWebDrawer(null)}
            onSaved={(message, redirect) => {
              setWebDrawer(null);
              // The school left the reader's portfolio: the web goes back to
              // the directory, and so does the app.
              if (redirect.split('?')[0] === '/schools') {
                onBack();
                return;
              }
              setToast(message);
              void load();
            }}
          />
        ) : null}
        {planningDrawer ? (
          <PlanningDrawer
            schoolId={schoolId}
            kind={planningDrawer}
            onClose={() => setPlanningDrawer(null)}
            onSaved={(message) => {
              setPlanningDrawer(null);
              setToast(message);
              void load();
            }}
            onOpenWeb={(path) => {
              setPlanningDrawer(null);
              openWeb(path);
            }}
          />
        ) : null}
        {toast ? (
          <View
            style={[styles.toast, { backgroundColor: colors.successSoft, borderColor: colors.success }]}
            accessibilityRole="alert"
            accessibilityLiveRegion="polite"
          >
            <Text style={[styles.toastText, { color: colors.success }]}>{toast}</Text>
          </View>
        ) : null}
      </MakeRoomContext.Provider>
    </PageLinkContext.Provider>
  );
}

/** "School ID: 1286", the value bold as the page sets it. */
function Description({ text }: { readonly text: string }) {
  const { colors } = useTheme();
  const at = text.indexOf(': ');
  return (
    <Text style={[styles.description, { color: colors.textMuted }]}>
      {at > 0 ? (
        <>
          {text.slice(0, at + 2)}
          <Text style={[styles.descriptionValue, { color: colors.text }]}>{text.slice(at + 2)}</Text>
        </>
      ) : (
        text
      )}
    </Text>
  );
}

function Badge({ badge, isWide }: { readonly badge: PageBadge; readonly isWide: boolean }) {
  const { colors } = useTheme();
  const tone = badge.tone === 'plain' ? undefined : toneColors(colors, badge.tone);
  return (
    <View
      accessibilityLabel={badge.title ? `${badge.text}. ${badge.title}` : badge.text}
      style={[
        styles.badge,
        isWide && styles.wide,
        tone ? { backgroundColor: tone.soft, borderColor: tone.fg, borderWidth: 1 } : { backgroundColor: colors.surfaceMuted },
      ]}
    >
      <Text style={[styles.badgeText, { color: tone ? tone.fg : colors.textMuted }]}>{badge.text}</Text>
    </View>
  );
}

function ActionButton({ action, onPress }: { readonly action: PageAction; readonly onPress: () => void }) {
  const { colors } = useTheme();
  const look = action.primary
    ? { backgroundColor: colors.primary, borderColor: colors.primary }
    : action.enabled
      ? { backgroundColor: colors.raised, borderColor: colors.border }
      : { backgroundColor: colors.surfaceMuted, borderColor: colors.border };
  const ink = action.primary ? colors.primaryInk : action.enabled ? colors.text : colors.textSubtle;
  return (
    <Pressable
      onPress={onPress}
      disabled={!action.enabled}
      accessibilityRole="button"
      accessibilityLabel={action.enabled ? action.label : `${action.label} unavailable: ${action.reason}`}
      accessibilityState={{ disabled: !action.enabled }}
      style={[styles.action, look, action.primary ? styles.primaryShadow : styles.shadow]}
    >
      <Text style={[styles.actionText, { color: ink }]}>{action.label}</Text>
    </Pressable>
  );
}

interface TabItem {
  readonly key: string;
  readonly label: string;
  readonly active: boolean;
}

/** The profile's tab rail: straight dividers, the open tab filled, the rail
 * scrolling sideways when it is longer than the screen. */
function TabRail({ tabs, onPick }: { readonly tabs: readonly TabItem[]; readonly onPick: (key: string) => void }) {
  const { colors } = useTheme();
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={[styles.rail, { backgroundColor: colors.surface }]}
      accessibilityRole="tablist"
    >
      {tabs.map((tab, index) => {
        const next = tabs[index + 1];
        const hasRule = next !== undefined && !tab.active && !next.active;
        return (
          <Pressable
            key={tab.key}
            onPress={() => onPick(tab.key)}
            accessibilityRole="tab"
            accessibilityState={{ selected: tab.active }}
            style={[styles.tab, tab.active && { backgroundColor: colors.segmentActive }, tab.active && index === 0 && styles.tabFirst]}
          >
            <Text style={[styles.tabText, tab.active ? styles.tabOn : { color: colors.textMuted }]}>{tab.label}</Text>
            {hasRule ? <View style={[styles.tabRule, { backgroundColor: colors.border }]} /> : null}
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { paddingHorizontal: 16, paddingTop: 20, paddingBottom: 32, gap: 16 },
  back: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start' },
  backText: { fontFamily: fonts.semibold, fontSize: 12, textTransform: 'uppercase' },
  title: { fontFamily: fonts.bold, fontSize: 20, lineHeight: 23 },
  description: { fontFamily: fonts.medium, fontSize: 13, marginTop: 4 },
  descriptionValue: { fontFamily: fonts.bold },
  controls: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  badge: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2, alignItems: 'center' },
  wide: { width: '100%' },
  badgeText: { fontFamily: fonts.semibold, fontSize: 12 },
  action: {
    flexGrow: 1,
    height: 32,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  shadow: { boxShadow: '0px 1px 3px 0px rgba(0, 0, 0, 0.1), 0px 1px 2px -1px rgba(0, 0, 0, 0.1)' },
  primaryShadow: { boxShadow: '0px 6px 14px -10px rgba(14, 93, 163, 0.44)' },
  actionText: { fontFamily: fonts.semibold, fontSize: 12 },
  rail: { flexGrow: 0, borderRadius: 10 },
  tab: { height: 32, paddingHorizontal: 14, justifyContent: 'center' },
  tabFirst: { borderTopLeftRadius: 8, borderBottomLeftRadius: 8 },
  tabText: { fontFamily: fonts.semibold, fontSize: 13 },
  tabOn: { fontFamily: fonts.bold, color: '#ffffff' },
  tabRule: { position: 'absolute', right: 0, top: 8, bottom: 8, width: 1 },
  error: { fontFamily: fonts.medium, fontSize: 13 },
  toast: { position: 'absolute', left: 16, right: 16, bottom: 16, borderWidth: 1, borderRadius: 12, padding: 12 },
  toastText: { fontFamily: fonts.semibold, fontSize: 13 },
});
