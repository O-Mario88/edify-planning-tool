/**
 * "My Schools – Loans" (owner's mockup, 2026-11-11, in Edify's blue): the
 * loan applications of the schools a CCEO or PL follows (or, for the BTO,
 * Country Director and RVP, every school), with four counters, the schools
 * that need attention, and one-tap reminders and follow-ups. The gateway
 * decides the portfolio and what each person may see; this only draws it.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, AppState, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { AlertTriangle, CalendarCheck, ChevronRight, Clock, Coins, FileText, MessageSquare, School, Search, Share2 } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ListPortfolioLoansResponse, PortfolioLoanRow } from '../../gen/edify/loans/v1/follow_up_pb';
import { LoanFollowUpService } from '../../gen/edify/loans/v1/follow_up_pb';
import { fonts, radius, toneColors, useTheme } from '../../theme';
import { CounterGrid, CounterTile, IconAction, LoanHero, LoanSheet, PrimaryButton, SegmentTabs, StatusChip } from './loanUi';

type Tab = 'overview' | 'schools' | 'follow_ups';

/** How often a visible loan list checks for confirmed changes. */
const CHANGE_CHECK_MS = 30_000;

const COUNTER_LOOK = {
  applied: { icon: FileText, tone: 'info' },
  processing: { icon: Clock, tone: 'caution' },
  disbursed: { icon: Coins, tone: 'good' },
  follow_up_due: { icon: AlertTriangle, tone: 'alert' },
} as const;

export type ProgressPanel = 'notify' | 'follow_up' | '';

interface StaffLoansScreenProps {
  readonly onOpen: (applicationId: string, panel: ProgressPanel) => void;
  readonly onShare: () => void;
  /** Changes each time the person comes back from a loan, to reload the list. */
  readonly returns?: number;
}

/**
 * Refreshes when anything about school loans changed: checked every 30
 * seconds while the app is open, and again when it comes back.
 */
function useLoanChanges(onChange: () => void) {
  const { api } = useSession();
  const cursor = useRef('');
  useEffect(() => {
    let isLive = true;
    const check = () =>
      api
        .call(LoanFollowUpService.method.getLoanChanges, { since: cursor.current })
        .then((answer) => {
          if (isLive && answer.changed) {
            onChange();
          }
          cursor.current = answer.cursor;
        })
        .catch(() => undefined);
    check();
    const timer = setInterval(check, CHANGE_CHECK_MS);
    const listener = AppState.addEventListener('change', (state) => state === 'active' && check());
    return () => {
      isLive = false;
      clearInterval(timer);
      listener.remove();
    };
  }, [api, onChange]);
}

export function StaffLoansScreen({ onOpen, onShare, returns = 0 }: StaffLoansScreenProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>('overview');
  const [scope, setScope] = useState('');
  const [counter, setCounter] = useState('');
  const [typed, setTyped] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [answer, setAnswer] = useState<ListPortfolioLoansResponse | null>(null);
  const [rows, setRows] = useState<readonly PortfolioLoanRow[]>([]);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => setSearch(typed.trim()), 350);
    return () => clearTimeout(timer);
  }, [typed]);

  const shownCounter = tab === 'follow_ups' ? 'follow_up_due' : tab === 'schools' ? counter : '';
  const load = useCallback(
    (wanted: number) => {
      setIsLoading(true);
      setError('');
      api
        .call(LoanFollowUpService.method.listPortfolioLoans, { scope, counter: shownCounter, search, page: wanted })
        .then((next) => {
          setAnswer(next);
          setRows((before) => (wanted === 1 ? next.rows : [...before, ...next.rows]));
          setPage(wanted);
        })
        .catch((cause: unknown) => setError(describe(cause)))
        .finally(() => setIsLoading(false));
    },
    [api, scope, shownCounter, search],
  );
  useEffect(() => load(1), [load, returns]);
  const refresh = useCallback(() => load(1), [load]);
  useLoanChanges(refresh);

  const attention = rows.filter((row) => row.needsAttention);
  const shown = tab === 'overview' ? attention.slice(0, 5) : rows;
  const title = answer?.scope === 'all' ? 'Schools – Loans' : 'My Schools – Loans';
  const subtitle = answer ? `${answer.scopeLabel}${answer.portfolioSchools ? ` (${answer.portfolioSchools} schools)` : ''}` : undefined;

  return (
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <LoanHero eyebrow="Loans & Financing" title={title} subtitle={subtitle} />
      <LoanSheet>
        <SegmentTabs
          tabs={[
            { key: 'overview', label: 'Overview' },
            { key: 'schools', label: 'My Schools' },
            { key: 'follow_ups', label: 'Follow-ups' },
          ]}
          value={tab}
          onChange={(next) => {
            setTab(next);
            setCounter('');
          }}
        />
        {answer && answer.scopes.length > 1 ? (
          <View style={styles.scopes} accessibilityRole="radiogroup">
            {answer.scopes.map((option) => {
              const isOn = option.value === answer.scope;
              return (
                <Pressable
                  key={option.value}
                  onPress={() => setScope(option.value)}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: isOn }}
                  style={[styles.scope, { borderColor: isOn ? colors.primary : colors.border, backgroundColor: isOn ? colors.primarySoft : colors.raised }]}
                >
                  <Text style={[styles.scopeText, { color: isOn ? colors.primary : colors.text }]}>{option.label}</Text>
                </Pressable>
              );
            })}
          </View>
        ) : null}
        {error ? (
          <Text style={[styles.note, { color: colors.danger }]} accessibilityRole="alert">
            {error}
          </Text>
        ) : null}

        {answer && tab === 'overview' ? (
          <>
            <CounterGrid>
              {answer.counters.map((item) => {
                const look = COUNTER_LOOK[item.key as keyof typeof COUNTER_LOOK] ?? COUNTER_LOOK.applied;
                return (
                  <CounterTile
                    key={item.key}
                    label={item.label}
                    value={String(item.schools)}
                    detail={`${item.records} ${item.records === 1 ? 'application' : 'applications'}`}
                    icon={look.icon}
                    tone={look.tone}
                    onPress={() => {
                      setTab(item.key === 'follow_up_due' ? 'follow_ups' : 'schools');
                      setCounter(item.key === 'follow_up_due' ? '' : item.key);
                    }}
                  />
                );
              })}
            </CounterGrid>
            <Text style={[styles.note, { color: colors.textSubtle }]}>
              Counters show schools; a school with two loans counts once. {answer.schoolsWithoutApplication > 0
                ? `${answer.schoolsWithoutApplication} of your schools have no loan application.`
                : ''}
            </Text>
            <PrimaryButton label="Share Loan Application" icon={Share2} isOutline onPress={onShare} />
            <View style={styles.sectionHead}>
              <Text style={[styles.sectionTitle, { color: colors.text }]} accessibilityRole="header">
                Schools Requiring Attention
              </Text>
              <Pressable onPress={() => setTab('follow_ups')} accessibilityRole="button" hitSlop={8}>
                <Text style={[styles.viewAll, { color: colors.link }]}>View All →</Text>
              </Pressable>
            </View>
          </>
        ) : null}

        {tab !== 'overview' ? (
          <View style={[styles.search, { backgroundColor: colors.raised, borderColor: colors.fieldBorder }]}>
            <Search size={16} color={colors.textMuted} />
            <TextInput
              value={typed}
              onChangeText={setTyped}
              placeholder="Search by school, reference or district"
              placeholderTextColor={colors.textSubtle}
              accessibilityLabel="Search school loans"
              autoCorrect={false}
              style={[styles.searchInput, { color: colors.text }]}
            />
          </View>
        ) : null}
        {tab === 'schools' && counter ? (
          <Pressable onPress={() => setCounter('')} accessibilityRole="button">
            <Text style={[styles.note, { color: colors.link }]}>
              Showing: {answer?.counters.find((item) => item.key === counter)?.label ?? counter} · Show all
            </Text>
          </Pressable>
        ) : null}

        {shown.map((row) => (
          <SchoolLoanCard key={row.applicationId} row={row} onOpen={onOpen} />
        ))}
        {!isLoading && shown.length === 0 ? (
          <Text style={[styles.empty, { color: colors.textMuted }]}>
            {tab === 'overview' ? 'No school needs a loan follow-up right now.' : 'No school loan matches.'}
          </Text>
        ) : null}
        {isLoading ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
        {tab !== 'overview' && answer && rows.length < answer.total && !isLoading ? (
          <Pressable onPress={() => load(page + 1)} accessibilityRole="button" style={[styles.more, { borderColor: colors.border }]}>
            <Text style={[styles.viewAll, { color: colors.link }]}>Show more</Text>
          </Pressable>
        ) : null}
      </LoanSheet>
    </ScrollView>
  );
}

function SchoolLoanCard({ row, onOpen }: { readonly row: PortfolioLoanRow; readonly onOpen: (id: string, panel: ProgressPanel) => void }) {
  const { colors } = useTheme();
  const edge = toneColors(colors, row.followUpTone && row.followUpTone !== 'plain' ? row.followUpTone : row.statusTone).fg;
  const meta = row.nextPaymentOn ? `Next installment: ${row.nextPaymentOn}` : `Applied: ${row.appliedOn}`;
  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder, borderLeftColor: edge }]}>
      <Pressable
        onPress={() => onOpen(row.applicationId, '')}
        accessibilityRole="button"
        accessibilityLabel={`${row.schoolName}, ${row.statusLabel}. Open loan progress`}
        style={styles.cardMain}
      >
        <School size={22} color={colors.link} />
        <View style={styles.cardBody}>
          <Text style={[styles.cardTitle, { color: colors.text }]}>{row.schoolName}</Text>
          <Text style={[styles.cardMeta, { color: colors.textMuted }]} numberOfLines={1}>
            {row.reference} · {row.lenderName}
          </Text>
          <View style={styles.chips}>
            <StatusChip label={row.statusLabel} tone={row.statusTone} />
            {row.followUpLabel && row.followUpLabel !== '—' ? <StatusChip label={row.followUpLabel} tone={row.followUpTone} /> : null}
          </View>
          <Text style={[styles.cardMeta, { color: colors.textMuted }]}>
            {meta}
            {row.responsibleStaff ? ` · ${row.responsibleStaff}` : ''}
          </Text>
          {row.lastNotification ? (
            <Text style={[styles.cardMeta, { color: colors.textSubtle }]} numberOfLines={1}>
              Last reminder: {row.lastNotification}
            </Text>
          ) : null}
        </View>
        <ChevronRight size={20} color={colors.textMuted} />
      </Pressable>
      <View style={[styles.cardActions, { borderTopColor: colors.border }]}>
        <IconAction label="Send Reminder" icon={MessageSquare} onPress={() => onOpen(row.applicationId, 'notify')} isDisabled={!row.canNotify} />
        <IconAction label="Record Follow-up" icon={CalendarCheck} onPress={() => onOpen(row.applicationId, 'follow_up')} isDisabled={!row.canFollowUp} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  scopes: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  scope: { borderWidth: 1.5, borderRadius: radius.pill, paddingHorizontal: 14, minHeight: 36, justifyContent: 'center' },
  scopeText: { fontFamily: fonts.semibold, fontSize: 13 },
  note: { fontFamily: fonts.medium, fontSize: 12.5, lineHeight: 18 },
  sectionHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 },
  sectionTitle: { fontFamily: fonts.bold, fontSize: 17 },
  viewAll: { fontFamily: fonts.semibold, fontSize: 13 },
  search: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 44 },
  searchInput: { flex: 1, fontFamily: fonts.medium, fontSize: 15, paddingVertical: 8 },
  card: { borderWidth: 1, borderLeftWidth: 4, borderRadius: radius.md, overflow: 'hidden' },
  cardMain: { flexDirection: 'row', gap: 10, padding: 12, alignItems: 'flex-start' },
  cardBody: { flex: 1, gap: 4 },
  cardTitle: { fontFamily: fonts.bold, fontSize: 15 },
  cardMeta: { fontFamily: fonts.medium, fontSize: 12.5 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  cardActions: { flexDirection: 'row', justifyContent: 'space-around', borderTopWidth: StyleSheet.hairlineWidth, paddingVertical: 2 },
  empty: { fontFamily: fonts.medium, fontSize: 13, textAlign: 'center', paddingVertical: 20 },
  more: { alignSelf: 'center', borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 18, paddingVertical: 9 },
});
