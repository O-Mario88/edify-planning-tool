/**
 * The cluster's member schools (brief A2: "View the authorized directory of
 * member schools"): every operating school in the cluster, whatever its
 * district, each with its Edify School ID. Searched by name or School ID,
 * fifty to a page as every Edify table.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Search } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { MemberSchool } from '../../gen/edify/clusters/v1/leadership_pb';
import { fonts, radius, useTheme } from '../../theme';

/** Wait this long after the last keystroke before searching. */
const SEARCH_DELAY_MS = 300;

interface MemberSchoolsScreenProps {
  readonly clusterId: string;
  readonly clusterName: string;
}

export function MemberSchoolsScreen({ clusterId, clusterName }: MemberSchoolsScreenProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [schools, setSchools] = useState<readonly MemberSchool[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const asked = useRef(0);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(
    (wanted: number) => {
      const ticket = ++asked.current;
      setIsLoading(true);
      setError('');
      api
        .listMemberSchools(clusterId, { page: wanted, search: query })
        .then((answer) => {
          if (ticket !== asked.current) {
            return; // a newer search answered first
          }
          setSchools((before) => (wanted === 1 ? answer.schools : [...before, ...answer.schools]));
          setPage(wanted);
          setTotal(Number(answer.page?.total ?? 0));
        })
        .catch((cause: unknown) => ticket === asked.current && setError(describe(cause)))
        .finally(() => ticket === asked.current && setIsLoading(false));
    },
    [api, clusterId, query],
  );

  useEffect(() => {
    load(1);
  }, [load]);

  const hasMore = schools.length < total;
  return (
    <FlatList
      data={schools}
      keyExtractor={(school) => school.id}
      contentContainerStyle={styles.list}
      ListHeaderComponent={
        <View style={styles.head}>
          <Text style={[styles.eyebrow, { color: colors.eyebrow }]}>{clusterName.toUpperCase()}</Text>
          <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
            Member schools
          </Text>
          <Text style={[styles.count, { color: colors.textMuted }]}>
            {total} {total === 1 ? 'school' : 'schools'}
            {query ? ` matching “${query}”` : ''}
          </Text>
          <View style={[styles.search, { backgroundColor: colors.surface, borderColor: colors.fieldBorder }]}>
            <Search size={16} color={colors.textMuted} />
            <TextInput
              value={search}
              onChangeText={setSearch}
              placeholder="Search by name or School ID"
              placeholderTextColor={colors.textSubtle}
              accessibilityLabel="Search member schools"
              autoCorrect={false}
              style={[styles.input, { color: colors.text }]}
            />
          </View>
          {error ? <Text style={[styles.error, { color: colors.danger }]} accessibilityRole="alert">{error}</Text> : null}
        </View>
      }
      renderItem={({ item }) => <SchoolRow school={item} />}
      ListEmptyComponent={
        isLoading ? undefined : (
          <Text style={[styles.empty, { color: colors.textMuted }]}>
            {query ? 'No member school matches that search.' : 'This cluster has no operating member school yet.'}
          </Text>
        )
      }
      ListFooterComponent={
        isLoading ? (
          <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" style={styles.footer} />
        ) : hasMore ? (
          <Pressable onPress={() => load(page + 1)} accessibilityRole="button" style={[styles.more, { borderColor: colors.border }]}>
            <Text style={[styles.moreText, { color: colors.link }]}>Show more</Text>
          </Pressable>
        ) : undefined
      }
    />
  );
}

function SchoolRow({ school }: { readonly school: MemberSchool }) {
  const { colors } = useTheme();
  return (
    <View
      style={[styles.row, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}
      accessible
      accessibilityLabel={`${school.name}, School ID ${school.schoolId}, ${school.district}`}
    >
      <View style={[styles.id, { backgroundColor: colors.primarySoft }]}>
        <Text style={[styles.idText, { color: colors.link }]}>{school.schoolId}</Text>
      </View>
      <View style={styles.body}>
        <Text style={[styles.name, { color: colors.text }]}>{school.name}</Text>
        <Text style={[styles.meta, { color: colors.textMuted }]}>
          {[school.district, school.subCounty].filter(Boolean).join(' · ') || 'District not recorded'}
        </Text>
        {school.currentFySsaStatus ? (
          <Text style={[styles.meta, { color: colors.textSubtle }]}>SSA: {school.currentFySsaStatus.replace(/_/g, ' ')}</Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  list: { padding: 12, gap: 8, paddingBottom: 24 },
  head: { gap: 6, marginBottom: 4 },
  eyebrow: { fontFamily: fonts.bold, fontSize: 11, letterSpacing: 1.2 },
  title: { fontFamily: fonts.bold, fontSize: 22, letterSpacing: -0.2 },
  count: { fontFamily: fonts.medium, fontSize: 13 },
  search: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 44, marginTop: 4 },
  input: { flex: 1, fontFamily: fonts.medium, fontSize: 16, paddingVertical: 8 },
  error: { fontFamily: fonts.medium, fontSize: 13 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderRadius: radius.md, padding: 12 },
  id: { minWidth: 56, borderRadius: radius.sm, paddingHorizontal: 8, paddingVertical: 6, alignItems: 'center' },
  idText: { fontFamily: fonts.bold, fontSize: 13, fontVariant: ['tabular-nums'] },
  body: { flex: 1, gap: 2 },
  name: { fontFamily: fonts.semibold, fontSize: 14 },
  meta: { fontFamily: fonts.medium, fontSize: 12 },
  empty: { fontFamily: fonts.medium, fontSize: 13, textAlign: 'center', paddingVertical: 24 },
  footer: { paddingVertical: 16 },
  more: { alignSelf: 'center', borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 18, paddingVertical: 9, marginTop: 4 },
  moreText: { fontFamily: fonts.semibold, fontSize: 13 },
});
