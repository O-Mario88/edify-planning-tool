/**
 * "Lender Cases" (owner's mockup, 2026-11-11, in Edify's blue): a lending
 * partner's applications and loans — counters, the person's own tasks,
 * search, stage filters and case cards — opening each case's page. The
 * gateway decides which cases each team member sees and what they may do.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { AlertTriangle, CheckCircle2, ChevronRight, FileText, School, Search, Share2, UserCheck } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { CaseRow, GetLenderHomeResponse, ListLenderCasesResponse } from '../../gen/edify/loans/v1/lending_pb';
import { LendingService } from '../../gen/edify/loans/v1/lending_pb';
import { fonts, radius, useTheme } from '../../theme';
import { Select } from '../../ui/Select';
import { CaseScreen } from './CaseScreen';
import { CounterGrid, CounterTile, LoanHero, LoanSheet, PrimaryButton, SegmentTabs, StatusChip } from './loanUi';

type Tab = 'cases' | 'repayments' | 'tasks';

/** Which home figures are the four counters, with their look. */
const COUNTERS = [
  { key: 'unassigned', label: 'New', icon: FileText, tone: 'info' },
  { key: 'in_review', label: 'In review', icon: UserCheck, tone: 'brand' },
  { key: 'active', label: 'Active Loans', icon: CheckCircle2, tone: 'good' },
  { key: 'overdue_loans', label: 'Overdue', icon: AlertTriangle, tone: 'alert' },
] as const;

const STAGE_TONES: Readonly<Record<string, string>> = {
  unassigned: 'info', contact_pending: 'caution', assessment_in_progress: 'caution', awaiting_school_agreement: 'info',
  awaiting_credit_review: 'info', approved: 'good', declined: 'alert', awaiting_disbursement: 'info', active_loan: 'good',
  settled_collateral_pending: 'caution', closed: 'plain',
};

export function LenderCasesScreen({ onShare }: { readonly onShare: () => void }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>('cases');
  const [home, setHome] = useState<GetLenderHomeResponse | null>(null);
  const [list, setList] = useState<ListLenderCasesResponse | null>(null);
  const [filter, setFilter] = useState('');
  const [typed, setTyped] = useState('');
  const [search, setSearch] = useState('');
  const [caseId, setCaseId] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => setSearch(typed.trim()), 350);
    return () => clearTimeout(timer);
  }, [typed]);

  const effectiveFilter = tab === 'repayments' ? filter || 'active_loan' : filter;
  const load = useCallback(() => {
    setIsLoading(true);
    setError('');
    Promise.all([
      api.call(LendingService.method.getLenderHome, {}),
      api.call(LendingService.method.listLenderCases, { filter: effectiveFilter, search, page: 1 }),
    ])
      .then(([nextHome, nextList]) => {
        setHome(nextHome);
        setList(nextList);
      })
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsLoading(false));
  }, [api, effectiveFilter, search]);
  useEffect(load, [load]);

  if (caseId) {
    return (
      <CaseScreen
        applicationId={caseId}
        onBack={() => {
          setCaseId('');
          load();
        }}
      />
    );
  }

  const kpi = (key: string) => home?.kpis.find((item) => item.key === key);
  return (
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <LoanHero eyebrow={home?.roles.join(' · ')} title="Lender Cases" subtitle={home?.lenderName} />
      <LoanSheet>
        <SegmentTabs
          tabs={[
            { key: 'cases', label: 'Cases' },
            { key: 'repayments', label: 'Repayments' },
            { key: 'tasks', label: 'My tasks' },
          ]}
          value={tab}
          onChange={(next) => {
            setTab(next);
            setFilter('');
          }}
        />
        {error ? (
          <Text style={[styles.note, { color: colors.danger }]} accessibilityRole="alert">
            {error}
          </Text>
        ) : null}
        {home ? (
          <CounterGrid>
            {COUNTERS.map((counter) => {
              const figure = kpi(counter.key);
              return (
                <CounterTile
                  key={counter.key}
                  label={counter.label}
                  value={figure?.value ?? '0'}
                  icon={counter.icon}
                  tone={counter.tone}
                  isSelected={Boolean(figure?.filter) && filter === figure?.filter}
                  onPress={figure?.filter ? () => setFilter(filter === figure.filter ? '' : figure.filter) : undefined}
                />
              );
            })}
          </CounterGrid>
        ) : null}

        {tab === 'tasks' && home ? (
          <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
            {home.tasks.length === 0 ? <Text style={[styles.note, { color: colors.textMuted }]}>No tasks for your duties.</Text> : null}
            {home.tasks.map((task) => (
              <Pressable
                key={task.key}
                onPress={() => {
                  setTab('cases');
                  setFilter(task.filter);
                }}
                accessibilityRole="button"
                style={[styles.task, { borderTopColor: colors.border }]}
              >
                <Text style={[styles.taskLabel, { color: colors.text }]}>{task.label}</Text>
                <StatusChip label={task.value} tone={task.tone} />
                <ChevronRight size={18} color={colors.textMuted} />
              </Pressable>
            ))}
          </View>
        ) : null}

        {tab !== 'tasks' ? (
          <>
            <View style={styles.searchRow}>
              <View style={[styles.search, { backgroundColor: colors.raised, borderColor: colors.fieldBorder }]}>
                <Search size={16} color={colors.textMuted} />
                <TextInput
                  value={typed}
                  onChangeText={setTyped}
                  placeholder="Search by school, reference or district"
                  placeholderTextColor={colors.textSubtle}
                  accessibilityLabel="Search cases"
                  autoCorrect={false}
                  style={[styles.searchInput, { color: colors.text }]}
                />
              </View>
            </View>
            {list ? (
              <Select
                label="Stage"
                value={filter}
                placeholder="All stages"
                choices={list.filters.filter((choice) => choice.value !== '').map((choice) => ({ value: choice.value, label: choice.label }))}
                onChange={setFilter}
                variant="filter"
              />
            ) : null}
            {list?.rows.map((row) => (
              <CaseCard key={row.applicationId} row={row} onOpen={setCaseId} />
            ))}
            {list && list.rows.length === 0 && !isLoading ? (
              <Text style={[styles.empty, { color: colors.textMuted }]}>No case matches.</Text>
            ) : null}
          </>
        ) : null}
        {isLoading ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
        <PrimaryButton label="Share Application Link" icon={Share2} isOutline onPress={onShare} />
      </LoanSheet>
    </ScrollView>
  );
}

function CaseCard({ row, onOpen }: { readonly row: CaseRow; readonly onOpen: (id: string) => void }) {
  const { colors } = useTheme();
  const detail = row.outstanding
    ? `Balance: ${row.outstanding}${row.nextDueOn ? `  |  Next: ${row.nextDueOn}` : ''}`
    : `Applied: ${row.submittedAt}  |  Amount: ${row.requested}`;
  return (
    <Pressable
      onPress={() => onOpen(row.applicationId)}
      accessibilityRole="button"
      accessibilityLabel={`${row.schoolName}, ${row.stageLabel}. Open case`}
      style={({ pressed }) => [styles.caseCard, { backgroundColor: colors.raised, borderColor: colors.raisedBorder, opacity: pressed ? 0.9 : 1 }]}
    >
      <School size={22} color={colors.link} />
      <View style={styles.caseBody}>
        <View style={styles.caseHead}>
          <Text style={[styles.caseTitle, { color: colors.text }]} numberOfLines={1}>
            {row.schoolName}
          </Text>
          <StatusChip label={row.isOverdue ? 'Overdue' : row.servicingLabel || row.stageLabel} tone={row.isOverdue ? 'alert' : STAGE_TONES[row.stage] ?? 'info'} />
        </View>
        <Text style={[styles.note, { color: colors.textMuted }]}>
          {row.reference}
          {row.officerName ? ` · ${row.officerName}` : ''}
        </Text>
        <Text style={[styles.note, { color: colors.textMuted }]}>{detail}</Text>
      </View>
      <ChevronRight size={20} color={colors.textMuted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  note: { fontFamily: fonts.medium, fontSize: 12.5, lineHeight: 18 },
  card: { borderWidth: 1, borderRadius: radius.lg, paddingHorizontal: 14, paddingVertical: 4 },
  task: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 48, borderTopWidth: StyleSheet.hairlineWidth },
  taskLabel: { flex: 1, fontFamily: fonts.semibold, fontSize: 14 },
  searchRow: { flexDirection: 'row', gap: 8 },
  search: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 44 },
  searchInput: { flex: 1, fontFamily: fonts.medium, fontSize: 15, paddingVertical: 8 },
  caseCard: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderRadius: radius.md, padding: 12 },
  caseBody: { flex: 1, gap: 3 },
  caseHead: { flexDirection: 'row', alignItems: 'center', gap: 8, justifyContent: 'space-between' },
  caseTitle: { fontFamily: fonts.bold, fontSize: 15, flexShrink: 1 },
  empty: { fontFamily: fonts.medium, fontSize: 13, textAlign: 'center', paddingVertical: 20 },
});
