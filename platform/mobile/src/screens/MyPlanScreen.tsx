/**
 * My Plan: the page the web renders for the same person
 * (pages/my_plan/index.html), drawn natively — its header and Export, the
 * period tabs and Open Calendar, the filters, the figure strips, Planned and
 * remaining, each table of work with its rows and their Actions, and the
 * breakdown by period.
 *
 * The period tabs, filters and pagers stay on the screen and change its
 * query, as the page's own links do. A school opens its native profile. A
 * row's actions, Export and the other links open the web page they belong
 * to, until their drawers are native.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ComponentRef } from 'react';
import { ActivityIndicator, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import type { NativeScrollEvent, NativeSyntheticEvent } from 'react-native';
import { Download } from 'lucide-react-native';

import { ApiError } from '../api/connect';
import { describe, useSession } from '../auth/SessionContext';
import type { GetMyPlanResponse } from '../gen/edify/screens/v1/my_plan_pb';
import { fonts, radius, useTheme } from '../theme';
import { MakeRoomContext } from '../ui/Dropdown';
import { PageBlocksView } from '../ui/page/PageBlocksView';
import { webPageFor } from '../ui/page/pageLinks';
import { PageLinkContext } from '../ui/page/shared';

const MY_PLAN = '/my-plan';

type Query = Readonly<Record<string, string>>;

interface MyPlanScreenProps {
  /** Open a school's profile (its name in a table). */
  readonly onOpenSchool: (schoolId: string) => void;
}

export function MyPlanScreen({ onOpenSchool }: MyPlanScreenProps) {
  const { api, environment, signOut } = useSession();
  const { colors } = useTheme();
  const [query, setQuery] = useState<Query>({});
  const [data, setData] = useState<GetMyPlanResponse | null>(null);
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const scroller = useRef<ComponentRef<typeof ScrollView>>(null);
  const offset = useRef(0);

  const load = useCallback(async () => {
    setIsBusy(true);
    setError('');
    try {
      setData(await api.getMyPlan(query));
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'unauthenticated') {
        await signOut();
        return;
      }
      setError(describe(cause));
    } finally {
      setIsBusy(false);
    }
  }, [api, query, signOut]);

  useEffect(() => {
    void load();
  }, [load]);

  const openWeb = useCallback(
    (path: string) => void Linking.openURL(`${environment.identityUrl}${path}`),
    [environment.identityUrl],
  );

  const openLink = useCallback(
    (href: string) => {
      const url = new URL(href, `http://edify.local${MY_PLAN}`);
      if (url.pathname === MY_PLAN) {
        // The page's own tabs and pagers: their link is the whole query.
        setQuery(Object.fromEntries(url.searchParams.entries()));
        return;
      }
      const school = /^\/schools\/([^/]+)$/.exec(url.pathname);
      if (school && school[1] !== 'closed') {
        onOpenSchool(decodeURIComponent(school[1]));
        return;
      }
      openWeb(webPageFor(url.pathname + url.search));
    },
    [onOpenSchool, openWeb],
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
  const exportAction = header?.actions.find((action) => action.key === 'export');
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
          {header?.eyebrow ? <Text style={[styles.eyebrow, { color: colors.eyebrow }]}>{header.eyebrow}</Text> : null}
          <View style={styles.titleRow}>
            <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
              {header?.title || 'My Plan'}
            </Text>
            {exportAction ? (
              <Pressable
                onPress={() => openLink(exportAction.href)}
                accessibilityRole="button"
                accessibilityLabel="Export this plan to Excel"
                style={[styles.export, { borderColor: colors.outlineBorder, backgroundColor: colors.raised }]}
              >
                <Download size={14} color={colors.textSubtle} />
                <Text style={[styles.exportText, { color: colors.text }]}>{exportAction.label}</Text>
              </Pressable>
            ) : null}
          </View>
          {header?.description ? (
            <Text style={[styles.description, { color: colors.textMuted }]}>{header.description}</Text>
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
            <ActivityIndicator color={colors.primary} accessibilityLabel="Loading My Plan" />
          )}
        </ScrollView>
      </MakeRoomContext.Provider>
    </PageLinkContext.Provider>
  );
}

const styles = StyleSheet.create({
  page: { paddingHorizontal: 16, paddingTop: 20, paddingBottom: 32, gap: 12 },
  eyebrow: { fontFamily: fonts.semibold, fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.4 },
  titleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  title: { flexShrink: 1, fontFamily: fonts.bold, fontSize: 20, lineHeight: 24 },
  export: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 32, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12 },
  exportText: { fontFamily: fonts.semibold, fontSize: 12 },
  description: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19, marginTop: -4 },
  error: { fontFamily: fonts.medium, fontSize: 13 },
});
