/**
 * School Directory: the web app's phone directory (templates/pages/schools/
 * index.html and partials/schools/*), drawn natively from the same
 * view-model, with the same rows, order, counts, filters and row actions.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ComponentRef } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import type { NativeScrollEvent, NativeSyntheticEvent } from 'react-native';
import { ChevronDown, ChevronUp, Download, Plus, Search, X } from 'lucide-react-native';

import { ApiError } from '../api/connect';
import { describe, useSession } from '../auth/SessionContext';
import type {
  DirectoryRowAction,
  DirectorySchool,
  GetSchoolDirectoryResponse,
} from '../gen/edify/screens/v1/school_directory_pb';
import { fonts, radius, useTheme } from '../theme';
import { Dropdown, MakeRoomContext, MenuList, menuHeight, useDropdown } from '../ui/Dropdown';
import type { MenuEntry } from '../ui/Dropdown';
import { Select } from '../ui/Select';
import { AddToClusterDrawer, AddToProjectDrawer, BulkClusterDrawer, BulkProjectDrawer } from './SchoolActionDrawers';
import { SchoolRow, TickBox } from './SchoolRow';

/** Row actions drawn natively; the rest still open on the web. */
const NATIVE_ACTIONS: Readonly<Record<string, 'cluster' | 'project'>> = {
  add_to_cluster: 'cluster',
  change_cluster: 'cluster',
  assign_to_project: 'project',
};

const TOAST_MS = 4000;

const EXPORT_FORMATS = [
  { key: 'xlsx', label: 'Export to Excel (.xlsx)' },
  { key: 'csv', label: 'Export to CSV (.csv)' },
] as const;
/** The most extra views the page offers (the More views menu). */
const MAX_VIEWS = 6;
/** The More filters panel: four labelled selects (272 x 282 on the web). */
const MORE_FILTERS_WIDTH = 272;
const MORE_FILTERS_HEIGHT = 282;

/** The page's own query parameters. */
interface Query {
  readonly q: string;
  readonly fy: string;
  readonly district: string;
  readonly subCounty: string;
  readonly schoolType: string;
  readonly clusterStatus: string;
  readonly projectStatus: string;
  readonly gap: string;
  readonly tab: string;
  readonly page: number;
}

const DEFAULT_QUERY: Query = {
  q: '',
  fy: '',
  district: '',
  subCounty: '',
  schoolType: '',
  clusterStatus: '',
  projectStatus: '',
  gap: '',
  tab: 'all',
  page: 1,
};

const EMPTY_STATES: Readonly<Record<string, string>> = {
  registry_empty: 'No schools have been uploaded yet.',
  scope_empty: 'No schools are assigned to you yet.',
  no_matches: 'No school matches these filters.',
};

interface SchoolsScreenProps {
  /** Changes each time the top bar's search button is pressed. */
  readonly searchSignal: number;
  /** Open a school's profile (its name is a link, as on the web). */
  readonly onOpenSchool: (schoolId: string) => void;
}

export function SchoolsScreen({ searchSignal, onOpenSchool }: SchoolsScreenProps) {
  const { api, environment, signOut } = useSession();
  const { colors } = useTheme();
  const searchField = useRef<ComponentRef<typeof TextInput>>(null);
  const [query, setQuery] = useState<Query>(DEFAULT_QUERY);
  const [draft, setDraft] = useState('');
  const [data, setData] = useState<GetSchoolDirectoryResponse | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  const [openId, setOpenId] = useState<string | null>(null);
  const exportMenu = useDropdown(menuHeight(EXPORT_FORMATS.length));
  const viewsMenu = useDropdown(menuHeight(MAX_VIEWS, 'compact'));
  const moreFilters = useDropdown(MORE_FILTERS_HEIGHT);
  const list = useRef<FlatList<DirectorySchool>>(null);
  const scrollOffset = useRef(0);
  // The page searches from the top bar's search button, as on the web.
  const [isSearching, setIsSearching] = useState(false);
  const [drawer, setDrawer] = useState<{ kind: 'cluster' | 'project'; schoolId: string } | null>(null);
  // The ticked schools (record ids), for the bulk bar. A new page or filter clears them, as on the web.
  const [selected, setSelected] = useState<readonly string[]>([]);
  const [bulk, setBulk] = useState<'cluster' | 'project' | null>(null);
  const [toast, setToast] = useState('');

  const load = useCallback(async () => {
    setIsBusy(true);
    setError('');
    try {
      setData(await api.getSchoolDirectory(query));
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

  useEffect(() => {
    setSelected([]);
  }, [query]);

  useEffect(() => {
    if (searchSignal > 0) {
      setIsSearching(true);
      // Focus once the field has been drawn.
      setTimeout(() => searchField.current?.focus(), 0);
    }
  }, [searchSignal]);

  /** Change filters; every change goes back to the first page, as the page does. */
  function update(change: Partial<Query>) {
    setOpenId(null);
    setQuery((current) => ({ ...current, page: 1, ...change }));
  }

  function clearFilters() {
    setDraft('');
    setQuery({ ...DEFAULT_QUERY, tab: query.tab });
  }

  useEffect(() => {
    if (!toast) {
      return undefined;
    }
    const timer = setTimeout(() => setToast(''), TOAST_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  /** A bulk save: the web's confirmation, with any skipped schools named. */
  function handleBulkSaved(message: string, warnings: readonly string[]) {
    setBulk(null);
    setSelected([]);
    setToast([message, ...warnings].join(' '));
    void load();
  }

  function toggleSelected(schoolId: string) {
    setSelected((current) =>
      current.includes(schoolId) ? current.filter((id) => id !== schoolId) : [...current, schoolId],
    );
  }

  /** A drawer saved: show the web's confirmation and redraw the list. */
  function handleSaved(message: string) {
    setDrawer(null);
    setToast(message);
    void load();
  }

  /** Open a path of the web app (drawers and exports are still there). */
  function openWeb(path: string) {
    void Linking.openURL(`${environment.identityUrl}${path}`);
  }

  /** Scroll the list up so a dropdown near the foot has room to drop down. */
  const makeRoom = useCallback((pixels: number) => {
    list.current?.scrollToOffset({ offset: scrollOffset.current + pixels, animated: false });
  }, []);

  function trackScroll(event: NativeSyntheticEvent<NativeScrollEvent>) {
    scrollOffset.current = event.nativeEvent.contentOffset.y;
  }

  /** A row's Actions menu: native drawers where built, the web otherwise. */
  function rowActions(school: DirectorySchool): readonly MenuEntry[] {
    return school.actions.map((action: DirectoryRowAction) => {
      const native = NATIVE_ACTIONS[action.key];
      return {
        key: action.key,
        label: native ? action.label : `${action.label} (on the web)`,
        reason: action.enabled ? undefined : action.reason,
        isDisabled: !action.enabled,
        onPress: () =>
          native
            ? setDrawer({ kind: native, schoolId: school.id })
            : openWeb(`/schools?q=${encodeURIComponent(school.schoolId)}`),
      };
    });
  }

  const filters = data?.filters;
  const tabs = data?.tabs ?? [];
  const activeTab = tabs.find((tab) => tab.key === (data?.activeTab ?? query.tab)) ?? tabs[0];
  const otherTabs = tabs.filter((tab) => tab.key !== activeTab?.key);
  const total = Number(data?.page?.total ?? 0n);
  const totalPages = data?.page?.totalPages ?? 1;
  const hasFilters =
    query.q !== '' ||
    query.district !== '' ||
    query.subCounty !== '' ||
    query.schoolType !== '' ||
    query.clusterStatus !== '' ||
    query.projectStatus !== '' ||
    query.gap !== '';
  const schools = data?.schools ?? [];
  const isPageSelected = schools.length > 0 && schools.every((school) => selected.includes(school.id));
  const moreCount = [query.schoolType, query.clusterStatus, query.projectStatus, query.gap].filter(Boolean)
    .length;

  const header = (
    <View>
      <Text style={[styles.eyebrow, { color: colors.eyebrow }]}>Schools & Field</Text>
      <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
        School Directory
      </Text>
      <View style={styles.headerButtons}>
        {data?.canAddSchool ? (
          <Pressable
            onPress={() => openWeb('/schools/add-school')}
            accessibilityRole="button"
            accessibilityLabel="Add School, opens on the web"
            style={[styles.button, { backgroundColor: colors.primary }]}
          >
            <Plus size={16} color={colors.primaryInk} />
            <Text style={[styles.buttonText, { color: colors.primaryInk }]}>Add School</Text>
          </Pressable>
        ) : null}
        <Pressable
          ref={exportMenu.triggerRef}
          onPress={exportMenu.toggle}
          accessibilityRole="button"
          accessibilityLabel="Export"
          accessibilityState={{ expanded: exportMenu.isOpen }}
          style={[
            styles.button,
            styles.buttonOutline,
            {
              borderColor: exportMenu.isOpen ? colors.primary : colors.border,
              backgroundColor: exportMenu.isOpen ? colors.primarySoft : colors.surface,
            },
          ]}
        >
          <Download size={16} color={colors.text} />
          <Text style={[styles.buttonText, { color: colors.text }]}>Export</Text>
          {exportMenu.isOpen ? <ChevronUp size={14} color={colors.text} /> : <ChevronDown size={14} color={colors.text} />}
        </Pressable>
      </View>
      <Text style={[styles.description, { color: colors.textMuted }]}>
        Manage uploaded schools, ownership, clustering, SSA readiness, and planning status.
      </Text>

      {isSearching ? (
      <View style={[styles.search, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <Search size={16} color={colors.textSubtle} />
        <TextInput
          ref={searchField}
          style={[styles.searchInput, { color: colors.text }]}
          value={draft}
          onChangeText={setDraft}
          onSubmitEditing={() => update({ q: draft.trim() })}
          returnKeyType="search"
          placeholder="Search schools, School IDs, districts, sub-counties…"
          placeholderTextColor={colors.textSubtle}
          autoCorrect={false}
          autoCapitalize="none"
          accessibilityLabel="Search schools"
        />
        <Pressable
          onPress={() => {
            setDraft('');
            setIsSearching(false);
            update({ q: '' });
          }}
          accessibilityRole="button"
          accessibilityLabel="Close search"
          hitSlop={10}
        >
          <X size={16} color={colors.textMuted} />
        </Pressable>
      </View>
      ) : null}

      {filters ? (
        <View style={styles.filterRow}>
          <View style={styles.filter}>
            <Text style={[styles.filterLabel, { color: colors.textMuted }]} numberOfLines={1}>
              Fiscal year
            </Text>
            <Select
              variant="filter"
              label="Fiscal year"
              value={filters.fy}
              choices={filters.fyOptions}
              placeholder="Current"
              onChange={(fy) => update({ fy })}
            />
          </View>
          <View style={styles.filter}>
            <Text style={[styles.filterLabel, { color: colors.textMuted }]}>District</Text>
            <Select
              variant="filter"
              label="District"
              value={filters.district}
              choices={filters.districts}
              placeholder="All"
              onChange={(district) => update({ district, subCounty: '' })}
            />
          </View>
          <View style={styles.filter}>
            <Text style={[styles.filterLabel, { color: colors.textMuted }]} numberOfLines={1}>
              Sub-county
            </Text>
            <Select
              variant="filter"
              label="Sub-county"
              value={filters.subCounty}
              choices={filters.district ? filters.subCounties : []}
              placeholder={filters.district ? 'All' : 'Choose district'}
              isDisabled={!filters.district}
              onChange={(subCounty) => update({ subCounty })}
            />
          </View>
          <Pressable
            ref={moreFilters.triggerRef}
            onPress={moreFilters.toggle}
            accessibilityRole="button"
            accessibilityLabel={`More filters${moreCount ? `, ${moreCount} set` : ''}`}
            accessibilityState={{ expanded: moreFilters.isOpen }}
            style={[
              styles.moreButton,
              {
                borderColor: moreFilters.isOpen ? colors.primary : colors.border,
                backgroundColor: moreFilters.isOpen ? colors.surface : colors.raised,
              },
            ]}
          >
            <Text style={[styles.moreText, { color: moreFilters.isOpen ? colors.link : colors.text }]}>
              More{moreCount ? ` ${moreCount}` : ''}
            </Text>
            {moreFilters.isOpen ? (
              <ChevronUp size={14} color={colors.link} />
            ) : (
              <ChevronDown size={14} color={colors.text} />
            )}
          </Pressable>
          <Pressable
            onPress={clearFilters}
            disabled={!hasFilters}
            accessibilityRole="button"
            accessibilityLabel="Clear filters"
            style={[styles.clear, { borderColor: colors.border, backgroundColor: colors.raised, opacity: hasFilters ? 1 : 0.5 }]}
          >
            <X size={16} color={colors.text} />
          </Pressable>
        </View>
      ) : null}

      <View style={[styles.cardTop, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
        <View style={[styles.segments, { backgroundColor: colors.surfaceMuted }]}>
          {activeTab ? (
            <View style={[styles.segment, styles.segmentActive, { backgroundColor: colors.segmentActive }]}>
              <Text style={styles.segmentActiveText} numberOfLines={1}>
                {activeTab.label}
              </Text>
              <Text style={styles.segmentActiveText}>{activeTab.count.toLocaleString()}</Text>
            </View>
          ) : null}
          {otherTabs.length > 0 ? (
            <Pressable
              ref={viewsMenu.triggerRef}
              onPress={viewsMenu.toggle}
              accessibilityRole="button"
              accessibilityLabel={`More views, ${otherTabs.length}`}
              accessibilityState={{ expanded: viewsMenu.isOpen }}
              style={styles.segment}
            >
              <Text style={[styles.segmentText, { color: colors.text }]}>More</Text>
              <View style={[styles.countBubble, { backgroundColor: colors.border }]}>
                <Text style={[styles.segmentText, { color: colors.text }]}>{otherTabs.length}</Text>
              </View>
              {viewsMenu.isOpen ? <ChevronUp size={14} color={colors.text} /> : <ChevronDown size={14} color={colors.text} />}
            </Pressable>
          ) : null}
        </View>
        <View style={[styles.listbar, styles.listbarRow, { borderTopColor: colors.raisedBorder }]}>
          {data && !data.readOnly && data.schools.length > 0 ? (
            <Pressable
              onPress={() =>
                setSelected(isPageSelected ? [] : data.schools.map((school) => school.id))
              }
              accessibilityRole="checkbox"
              accessibilityState={{ checked: isPageSelected }}
              accessibilityLabel="Select page"
              style={styles.selectPage}
            >
              <TickBox isChecked={isPageSelected} />
              <Text style={[styles.selectText, { color: colors.text }]}>Select page</Text>
            </Pressable>
          ) : null}
          {error ? (
            <Text style={[styles.error, { color: colors.danger }]} accessibilityRole="alert">
              {error}
            </Text>
          ) : data ? (
            <Text style={[styles.listed, { color: colors.textSubtle }]}>
              {total.toLocaleString()} {total === 1 ? 'school' : 'schools'} listed
            </Text>
          ) : (
            <ActivityIndicator color={colors.primary} accessibilityLabel="Loading schools" />
          )}
        </View>
        {selected.length > 0 ? (
          <View
            style={[styles.bulkBar, { borderTopColor: colors.raisedBorder, backgroundColor: colors.primarySoft }]}
            accessibilityLiveRegion="polite"
          >
            <Text style={[styles.bulkCount, { color: colors.text }]}>{selected.length} selected</Text>
            <View style={styles.bulkButtons}>
              <BulkButton label="Assign cluster" onPress={() => setBulk('cluster')} />
              <BulkButton label="Assign project" onPress={() => setBulk('project')} />
              <BulkButton label="Match staff (on the web)" onPress={() => openWeb('/schools')} />
              {data?.mayTransferSchool ? (
                <BulkButton label="Reassign owner (on the web)" onPress={() => openWeb('/schools')} />
              ) : null}
              <BulkButton label="Clear" onPress={() => setSelected([])} />
            </View>
          </View>
        ) : null}
      </View>
    </View>
  );


  return (
    <>
      <MakeRoomContext.Provider value={makeRoom}>
      <FlatList
        ref={list}
        onScroll={trackScroll}
        scrollEventThrottle={16}
        data={schools}
        keyExtractor={(school) => school.id}
        renderItem={({ item, index }) => (
          <SchoolRow
            school={item}
            isOpen={openId === item.id}
            isLast={index === schools.length - 1}
            canAct={!data?.readOnly}
            isSelected={selected.includes(item.id)}
            onSelect={() => toggleSelected(item.id)}
            onToggle={() => setOpenId((current) => (current === item.id ? null : item.id))}
            actions={rowActions(item)}
            onOpen={data?.mayOpenProfile ? () => onOpenSchool(item.id) : undefined}
          />
        )}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={
          isBusy ? (
            <View style={[styles.empty, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
              <ActivityIndicator color={colors.primary} accessibilityLabel="Loading schools" />
            </View>
          ) : (
            <View style={[styles.empty, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
              <Text style={[styles.emptyText, { color: colors.textMuted }]}>
                {EMPTY_STATES[data?.emptyState ?? ''] ?? 'No schools to show.'}
              </Text>
            </View>
          )
        }
        ListFooterComponent={
          totalPages > 1 ? (
            <View style={styles.pager}>
              <Pressable
                onPress={() => setQuery((current) => ({ ...current, page: current.page - 1 }))}
                disabled={query.page <= 1 || isBusy}
                accessibilityRole="button"
                accessibilityLabel="Previous page"
                style={[styles.pageButton, { borderColor: colors.borderStrong, opacity: query.page <= 1 ? 0.4 : 1 }]}
              >
                <Text style={[styles.pageText, { color: colors.text }]}>Previous</Text>
              </Pressable>
              <Text style={[styles.pageLabel, { color: colors.textMuted }]}>
                Page {data?.page?.page ?? query.page} of {totalPages}
              </Text>
              <Pressable
                onPress={() => setQuery((current) => ({ ...current, page: current.page + 1 }))}
                disabled={query.page >= totalPages || isBusy}
                accessibilityRole="button"
                accessibilityLabel="Next page"
                style={[
                  styles.pageButton,
                  { borderColor: colors.borderStrong, opacity: query.page >= totalPages ? 0.4 : 1 },
                ]}
              >
                <Text style={[styles.pageText, { color: colors.text }]}>Next</Text>
              </Pressable>
            </View>
          ) : undefined
        }
      />

      </MakeRoomContext.Provider>

      <Dropdown
        anchor={viewsMenu.anchor}
        onClose={viewsMenu.close}
        align="end"
        minWidth={176}
        panelStyle={[styles.viewsPanel, { backgroundColor: colors.surface }]}
        contentStyle={styles.menuContent}
        accessibilityLabel="School directory views"
      >
        <MenuList
          variant="compact"
          onClose={viewsMenu.close}
          items={otherTabs.map((tab) => ({
            key: tab.key,
            label: tab.label,
            count: tab.count.toLocaleString(),
            onPress: () => update({ tab: tab.key }),
          }))}
        />
      </Dropdown>

      <Dropdown
        anchor={exportMenu.anchor}
        onClose={exportMenu.close}
        align="start"
        minWidth={176}
        contentStyle={styles.menuContent}
        accessibilityLabel="Export"
      >
        <MenuList
          onClose={exportMenu.close}
          items={EXPORT_FORMATS.map((format) => ({
            key: format.key,
            label: format.label,
            onPress: () => openWeb(`/schools?export=${format.key}`),
          }))}
        />
      </Dropdown>

      {drawer?.kind === 'cluster' ? (
        <AddToClusterDrawer schoolId={drawer.schoolId} onClose={() => setDrawer(null)} onSaved={handleSaved} />
      ) : null}
      {drawer?.kind === 'project' ? (
        <AddToProjectDrawer schoolId={drawer.schoolId} onClose={() => setDrawer(null)} onSaved={handleSaved} />
      ) : null}
      {bulk === 'cluster' && data ? (
        <BulkClusterDrawer
          schoolIds={selected}
          clusters={data.bulkClusters}
          onClose={() => setBulk(null)}
          onSaved={handleBulkSaved}
        />
      ) : null}
      {bulk === 'project' && data ? (
        <BulkProjectDrawer
          schoolIds={selected}
          projects={data.bulkProjects}
          projectsOf={(id) => data.schools.find((school) => school.id === id)?.projectIds ?? []}
          onClose={() => setBulk(null)}
          onSaved={handleBulkSaved}
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

      {filters ? (
        <Dropdown
          anchor={moreFilters.anchor}
          onClose={moreFilters.close}
          align="end"
          width={MORE_FILTERS_WIDTH}
          panelStyle={styles.morePanel}
          contentStyle={styles.moreContent}
          accessibilityLabel="More filters"
        >
          {[
            { label: 'Partner type', value: filters.schoolType, choices: filters.schoolTypes, placeholder: 'All', key: 'schoolType' },
            { label: 'Cluster status', value: filters.clusterStatus, choices: filters.clusterStatuses, placeholder: 'All', key: 'clusterStatus' },
            { label: 'Missing detail', value: filters.gap, choices: filters.gaps, placeholder: 'All schools', key: 'gap' },
            { label: 'Project status', value: filters.projectStatus, choices: filters.projectStatuses, placeholder: 'All', key: 'projectStatus' },
          ].map((field) => (
            <View key={field.key} style={styles.moreField}>
              <Text style={[styles.moreLabel, { color: colors.textMuted }]}>{field.label}</Text>
              <Select
                variant="filter"
                label={field.label}
                value={field.value}
                choices={field.choices}
                placeholder={field.placeholder}
                onChange={(value) => update({ [field.key]: value } as Partial<Query>)}
              />
            </View>
          ))}
        </Dropdown>
      ) : null}
    </>
  );
}

function BulkButton({ label, onPress }: { readonly label: string; readonly onPress: () => void }) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={[styles.bulkButton, { borderColor: colors.borderStrong, backgroundColor: colors.raised }]}
    >
      <Text style={[styles.bulkButtonText, { color: colors.text }]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  list: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 28 },
  eyebrow: { fontFamily: fonts.semibold, fontSize: 13, textTransform: 'uppercase' },
  title: { fontFamily: fonts.bold, fontSize: 20, lineHeight: 23, marginTop: 10 },
  headerButtons: { flexDirection: 'row', gap: 8, marginTop: 10 },
  button: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    height: 40,
    borderRadius: radius.sm,
    paddingHorizontal: 14,
  },
  buttonOutline: { borderWidth: 1 },
  buttonText: { fontFamily: fonts.semibold, fontSize: 13 },
  description: { fontFamily: fonts.regular, fontSize: 13, lineHeight: 19.5, marginTop: 10 },
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    height: 40,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: 12,
    marginTop: 16,
  },
  searchInput: { flex: 1, fontFamily: fonts.regular, fontSize: 13, paddingVertical: 0 },
  filterRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 6, marginTop: 20 },
  filter: { flex: 1, gap: 4 },
  filterLabel: { fontFamily: fonts.medium, fontSize: 12 },
  moreButton: {
    height: 32,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: 10,
  },
  moreText: { fontFamily: fonts.bold, fontSize: 12 },
  clear: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderRadius: radius.sm },
  cardTop: {
    marginTop: 16,
    borderWidth: 1,
    borderBottomWidth: 0,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingTop: 16,
  },
  segments: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    marginHorizontal: 16,
    marginBottom: 16,
    borderRadius: radius.sm - 2,
  },
  segment: { height: 36, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12 },
  segmentActive: { borderTopLeftRadius: radius.sm - 2, borderBottomLeftRadius: radius.sm - 2, minWidth: 150, justifyContent: 'center', gap: 16 },
  segmentActiveText: { fontFamily: fonts.bold, fontSize: 12, color: '#ffffff' },
  segmentText: { fontFamily: fonts.semibold, fontSize: 12 },
  countBubble: { borderRadius: radius.pill, paddingHorizontal: 7, paddingVertical: 1 },
  listbar: { borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 14 },
  listbarRow: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  selectPage: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 32 },
  selectText: { fontFamily: fonts.semibold, fontSize: 13 },
  bulkBar: { borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 10, gap: 8 },
  bulkCount: { fontFamily: fonts.bold, fontSize: 13 },
  bulkButtons: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  bulkButton: { minHeight: 36, justifyContent: 'center', borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12 },
  bulkButtonText: { fontFamily: fonts.semibold, fontSize: 12 },
  listed: { fontFamily: fonts.medium, fontSize: 12, textTransform: 'uppercase' },
  error: { fontFamily: fonts.medium, fontSize: 13 },
  empty: { borderWidth: 1, borderBottomLeftRadius: radius.lg, borderBottomRightRadius: radius.lg, padding: 20 },
  emptyText: { fontFamily: fonts.regular, fontSize: 13, textAlign: 'center' },
  pager: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 16 },
  pageButton: { minHeight: 40, justifyContent: 'center', borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 14 },
  pageText: { fontFamily: fonts.semibold, fontSize: 13 },
  pageLabel: { fontFamily: fonts.medium, fontSize: 12 },
  toast: { position: 'absolute', left: 16, right: 16, bottom: 16, borderWidth: 1, borderRadius: radius.md, padding: 12 },
  toastText: { fontFamily: fonts.semibold, fontSize: 13 },
  menuContent: { padding: 4 },
  viewsPanel: { borderRadius: 10 },
  morePanel: { borderRadius: 16 },
  moreContent: { padding: 14, gap: 12 },
  moreField: { gap: 6 },
  moreLabel: { fontFamily: fonts.medium, fontSize: 12 },
});
