/**
 * Any page the app draws from its components (My Plan, To-Do, Dashboard,
 * Clusters, Budget …): the page the web renders for the same person, drawn
 * natively — its back link, eyebrow, title, description, pills and buttons,
 * its tabs, and its blocks.
 *
 * A link that only changes this page's own query (its tabs, filters,
 * pagers) stays on the screen. A page the app draws opens natively, a
 * school opens its profile, and everything else opens on the web — a
 * drawer on the page its record belongs to.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ComponentRef } from 'react';
import { ActivityIndicator, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import type { NativeScrollEvent, NativeSyntheticEvent } from 'react-native';
import { ChevronLeft, Download } from 'lucide-react-native';

import { ApiError } from '../api/connect';
import { describe, useSession } from '../auth/SessionContext';
import type { GetPageResponse } from '../gen/edify/screens/v1/page_screen_pb';
import type { PageAction } from '../gen/edify/screens/v1/page_pb';
import { fonts, radius, useTheme } from '../theme';
import { MakeRoomContext } from '../ui/Dropdown';
import { PageBlocksView } from '../ui/page/PageBlocksView';
import { ActionButton, Badge, Description, TabRail } from '../ui/page/PageHeaderParts';
import { webPageFor } from '../ui/page/pageLinks';
import { PageLinkContext } from '../ui/page/shared';

type Query = Readonly<Record<string, string>>;

interface PageScreenProps {
  /** The page's web path ("/my-plan"). */
  readonly path: string;
  /** The query the page opened with ("?fy=2026"). */
  readonly initialQuery?: Query;
  /** Whether the app draws a web path itself. */
  readonly isNative: (path: string) => boolean;
  /** Open a path the app draws (another page, a tab). */
  readonly onOpen: (url: string) => void;
  /** Open a school's profile. */
  readonly onOpenSchool: (schoolId: string) => void;
}

export function PageScreen({ path, initialQuery = {}, isNative, onOpen, onOpenSchool }: PageScreenProps) {
  const { api, environment, signOut } = useSession();
  const { colors } = useTheme();
  const [query, setQuery] = useState<Query>(initialQuery);
  const [data, setData] = useState<GetPageResponse | null>(null);
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const scroller = useRef<ComponentRef<typeof ScrollView>>(null);
  const offset = useRef(0);

  const load = useCallback(async () => {
    setIsBusy(true);
    setError('');
    try {
      const answer = await api.getPage(path, query);
      if (answer.redirect) {
        onOpen(answer.redirect);
        return;
      }
      setData(answer);
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'unauthenticated') {
        await signOut();
        return;
      }
      setError(describe(cause));
    } finally {
      setIsBusy(false);
    }
  }, [api, onOpen, path, query, signOut]);

  useEffect(() => {
    void load();
  }, [load]);

  const openWeb = useCallback(
    (webPath: string) => void Linking.openURL(`${environment.identityUrl}${webPath}`),
    [environment.identityUrl],
  );

  const openLink = useCallback(
    (href: string) => {
      const url = new URL(href, `http://edify.local${path}`);
      const own = url.pathname.replace(/\/+$/, '') === path.replace(/\/+$/, '');
      if (own) {
        // The page's own tabs, filters and pagers: their link is the whole query.
        setQuery(Object.fromEntries(url.searchParams.entries()));
        scroller.current?.scrollTo({ y: 0, animated: false });
        return;
      }
      const school = /^\/schools\/([^/]+)$/.exec(url.pathname);
      if (school && school[1] !== 'closed') {
        onOpenSchool(decodeURIComponent(school[1]));
        return;
      }
      if (isNative(url.pathname)) {
        onOpen(url.pathname + url.search);
        return;
      }
      openWeb(webPageFor(url.pathname + url.search));
    },
    [isNative, onOpen, onOpenSchool, openWeb, path],
  );

  const filter = useCallback(
    (name: string, value: string, hidden: Readonly<Record<string, string>>) => {
      // As the filter form submits: every select's value and its hidden ones.
      const filters = data?.blocks.find((block) => block.kind.case === 'filters');
      const values =
        filters?.kind.case === 'filters'
          ? Object.fromEntries(filters.kind.value.filters.map((item) => [item.name, item.value]))
          : {};
      setQuery({ ...hidden, ...values, [name]: value });
    },
    [data],
  );

  const makeRoom = useCallback((pixels: number) => {
    scroller.current?.scrollTo({ y: offset.current + pixels, animated: false });
  }, []);

  function trackScroll(event: NativeSyntheticEvent<NativeScrollEvent>) {
    offset.current = event.nativeEvent.contentOffset.y;
  }

  const header = data?.header;
  // Export sits beside the title, as the page header's control does on a phone.
  const exportAction = header?.actions.find((action) => action.key === 'export');
  const buttons = header?.actions.filter((action) => action !== exportAction) ?? [];
  return (
    <PageLinkContext.Provider value={openLink}>
      <MakeRoomContext.Provider value={makeRoom}>
        <ScrollView
          ref={scroller}
          onScroll={trackScroll}
          scrollEventThrottle={16}
          contentContainerStyle={styles.page}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={isBusy && data !== null} onRefresh={() => void load()} />}
        >
          {header?.backLabel ? (
            <Pressable onPress={() => openLink(header.backHref)} accessibilityRole="link" hitSlop={8} style={styles.back}>
              <ChevronLeft size={14} color={colors.link} />
              <Text style={[styles.backText, { color: colors.link }]}>{header.backLabel}</Text>
            </Pressable>
          ) : null}
          {header?.eyebrow ? <Text style={[styles.eyebrow, { color: colors.eyebrow }]}>{header.eyebrow}</Text> : null}
          <View style={styles.titleRow}>
            <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
              {header?.title ?? ''}
            </Text>
            {exportAction ? <ExportButton action={exportAction} onPress={() => openLink(exportAction.href)} /> : null}
          </View>
          {header?.description ? <Description text={header.description} /> : null}
          {header && (header.badges.length > 0 || buttons.length > 0) ? (
            <View style={styles.controls}>
              {header.badges.map((badge, index) => (
                <Badge key={badge.text} badge={badge} isWide={index === 0 && header.badges.length > 1} />
              ))}
              {buttons.map((action) => (
                <ActionButton key={action.key + action.href} action={action} onPress={() => openLink(action.href)} />
              ))}
            </View>
          ) : null}
          {data && data.tabs.length > 0 ? (
            <TabRail
              tabs={data.tabs.map((tab) => ({ key: tab.key, label: tab.label, active: tab.active }))}
              onPick={(tab) => setQuery((current) => ({ ...current, tab }))}
            />
          ) : null}
          {error ? (
            <Text style={[styles.error, { color: colors.danger }]} accessibilityRole="alert">
              {error}
            </Text>
          ) : null}
          {data ? (
            <View style={{ opacity: isBusy ? 0.6 : 1 }}>
              <PageBlocksView blocks={data.blocks} onFilter={filter} isRaised={false} />
            </View>
          ) : error ? null : (
            <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />
          )}
        </ScrollView>
      </MakeRoomContext.Provider>
    </PageLinkContext.Provider>
  );
}

function ExportButton({ action, onPress }: { readonly action: PageAction; readonly onPress: () => void }) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${action.label} to Excel`}
      style={[styles.export, { borderColor: colors.outlineBorder, backgroundColor: colors.raised }]}
    >
      <Download size={14} color={colors.textSubtle} />
      <Text style={[styles.exportText, { color: colors.text }]}>{action.label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { paddingHorizontal: 16, paddingTop: 20, paddingBottom: 32, gap: 12 },
  back: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start' },
  backText: { fontFamily: fonts.semibold, fontSize: 12, textTransform: 'uppercase' },
  eyebrow: { fontFamily: fonts.semibold, fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.4 },
  titleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  title: { flexShrink: 1, fontFamily: fonts.bold, fontSize: 20, lineHeight: 24 },
  controls: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  export: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 32, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12 },
  exportText: { fontFamily: fonts.semibold, fontSize: 12 },
  error: { fontFamily: fonts.medium, fontSize: 13 },
});
