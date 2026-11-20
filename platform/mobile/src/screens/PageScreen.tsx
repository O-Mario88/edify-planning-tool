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
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ComponentRef } from 'react';
import { Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import type { NativeScrollEvent, NativeSyntheticEvent } from 'react-native';
import { ChevronLeft, Download } from 'lucide-react-native';

import { ApiError } from '../api/connect';
import { describe, useSession } from '../auth/SessionContext';
import type { GetPageResponse } from '../gen/edify/screens/v1/page_screen_pb';
import type { PageAction } from '../gen/edify/screens/v1/page_pb';
import { fonts, radius, useTheme } from '../theme';
import { MakeRoomContext } from '../ui/Dropdown';
import { PageBlocksView } from '../ui/page/PageBlocksView';
import { PageSkeleton } from '../ui/page/PageSkeleton';
import { ActionButton, Badge, Description, TabRail } from '../ui/page/PageHeaderParts';
import { selectionPath, webPageFor } from '../ui/page/pageLinks';
import { PageFormContext, PageLinkContext, PickContext } from '../ui/page/shared';
import { SelectionBar } from '../ui/page/SelectionBar';
import { Drawer } from '../ui/Drawer';
import { WebDrawer } from '../ui/WebDrawer';
import { PlanningDrawer } from '../ui/planning/PlanningDrawer';

type Query = Readonly<Record<string, string>>;

const TOAST_MS = 4000;
/** A link that opens one of the page's own dialogs ("#dialog=showMscs"). */
const DIALOG_HREF = '#dialog=';
/** The planning drawers the app draws natively, by the path that opens them. */
const PLANNING_DRAWERS: Readonly<Record<string, 'schedule' | 'assign'>> = {
  '/planning/schedule-modal': 'schedule',
  '/planning/assign-partner-modal': 'assign',
};

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
  /** The drawer open on this page: any drawer by its path, or a school's planning drawer. */
  const [drawer, setDrawer] = useState<string | null>(null);
  const [planning, setPlanning] = useState<{ readonly schoolId: string; readonly kind: 'schedule' | 'assign' } | null>(null);
  /** The page's own dialog open as a sheet, by its key. */
  const [dialogKey, setDialogKey] = useState<string | null>(null);
  /** The rows ticked for the page's bar (PageSelection). */
  const [picked, setPicked] = useState<readonly string[]>([]);
  const [toast, setToast] = useState('');
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
      setPicked([]);
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
    (href: string, isDrawer = false) => {
      if (href.startsWith(DIALOG_HREF)) {
        setDialogKey(href.slice(DIALOG_HREF.length));
        return;
      }
      const url = new URL(href, `http://edify.local${path}`);
      if (isDrawer) {
        const planningKind = PLANNING_DRAWERS[url.pathname];
        const school = url.searchParams.get('school_id');
        if (planningKind && school) {
          setPlanning({ schoolId: school, kind: planningKind });
          return;
        }
        setDrawer(url.pathname + url.search);
        return;
      }
      const own = url.pathname.replace(/\/+$/, '') === path.replace(/\/+$/, '');
      if (own) {
        // The page's own tabs, filters and pagers: their link is the whole
        // query — but a link to a page number alone keeps the filters, as the
        // web's pager sends its filter form with it (hx-include).
        const next = Object.fromEntries(url.searchParams.entries());
        const keys = Object.keys(next);
        const isPageOnly = keys.length > 0 && keys.every((key) => key === 'page' || key.endsWith('_page'));
        setQuery((current) => (isPageOnly ? { ...current, ...next } : next));
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

  useEffect(() => {
    if (!toast) {
      return undefined;
    }
    const timer = setTimeout(() => setToast(''), TOAST_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  const saved = useCallback(
    (message: string) => {
      setDrawer(null);
      setPlanning(null);
      setDialogKey(null);
      setToast(message);
      void load();
    },
    [load],
  );
  const picks = useMemo(
    () => ({
      isOn: Boolean(data?.selection),
      picked,
      set: (ids: readonly string[], isTicked: boolean) =>
        setPicked((now) => (isTicked ? [...new Set([...now, ...ids])] : now.filter((id) => !ids.includes(id)))),
    }),
    [data, picked],
  );
  // A form the page shows itself saves with the page's path, then the page reloads.
  const formHost = useMemo(
    () => ({ path, onSaved: saved, onOpenWeb: () => openWeb(webPageFor(path)) }),
    [openWeb, path, saved],
  );

  const openDialog = dialogKey ? data?.dialogs.find((dialog) => dialog.key === dialogKey) : undefined;
  const header = data?.header;
  // Export sits beside the title, as the page header's control does on a phone.
  const exportAction = header?.actions.find((action) => action.key === 'export');
  const buttons = header?.actions.filter((action) => action !== exportAction) ?? [];
  return (
    <PageLinkContext.Provider value={openLink}>
      <PageFormContext.Provider value={formHost}>
        <PickContext.Provider value={picks}>
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
                {exportAction ? <ExportButton action={exportAction} onPress={() => openLink(exportAction.href, exportAction.drawer)} /> : null}
              </View>
              {header?.description ? <Description text={header.description} /> : null}
              {header && (header.badges.length > 0 || buttons.length > 0) ? (
                <View style={styles.controls}>
                  {header.badges.map((badge, index) => (
                    <Badge key={badge.text} badge={badge} isWide={index === 0 && header.badges.length > 1} />
                  ))}
                  {buttons.map((action) => (
                    <ActionButton key={action.key + action.href} action={action} onPress={() => openLink(action.href, action.drawer)} />
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
                  <PageBlocksView blocks={data.blocks} onFilter={filter} isRaised={false} pagePath={path} />
                </View>
              ) : error ? null : (
                <PageSkeleton />
              )}
            </ScrollView>
            {drawer ? (
              <WebDrawer
                source={{ path: drawer }}
                onClose={() => setDrawer(null)}
                onSaved={(message) => saved(message)}
                onUnavailable={() => {
                  // A drawer the app does not draw yet opens on the web.
                  setDrawer(null);
                  openWeb(webPageFor(drawer));
                }}
              />
            ) : null}
            {openDialog ? (
              <Drawer title={openDialog.title} onClose={() => setDialogKey(null)}>
                <PageBlocksView blocks={openDialog.blocks} onFilter={filter} />
              </Drawer>
            ) : null}
            {planning ? (
              <PlanningDrawer
                schoolId={planning.schoolId}
                kind={planning.kind}
                onClose={() => setPlanning(null)}
                onSaved={saved}
                onOpenWeb={(webPath) => {
                  setPlanning(null);
                  openWeb(webPath);
                }}
              />
            ) : null}
            {data?.selection && picked.length > 0 && !drawer ? (
              <SelectionBar
                selection={data.selection}
                count={picked.length}
                onAction={(action) => setDrawer(selectionPath(action, picked))}
                onClear={() => setPicked([])}
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
        </PickContext.Provider>
      </PageFormContext.Provider>
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
  toast: { position: 'absolute', left: 16, right: 16, bottom: 16, borderWidth: 1, borderRadius: 12, padding: 12 },
  toastText: { fontFamily: fonts.semibold, fontSize: 13 },
});
