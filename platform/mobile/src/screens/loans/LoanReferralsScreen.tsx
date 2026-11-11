/**
 * School loan referrals for Edify staff (brief §8, §12): the dashboard's
 * figures, the filtered list of applications, the application link to share
 * with schools, and the export. Pressing a figure filters the list to what
 * it counts; an application opens its own page.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetLoanDashboardResponse, ListLoanApplicationsResponse, LoanApplicationRow } from '../../gen/edify/loans/v1/loans_pb';
import { LoanReferralService } from '../../gen/edify/loans/v1/loans_pb';
import { fonts, radius, useTheme } from '../../theme';
import { DrawerButton } from '../../ui/drawerParts';
import { Select } from '../../ui/Select';
import { ChoiceRow, Muted, Notice, OpsCard, OpsTitle, SectionLabel, opsStyles } from '../cluster/opsParts';
import { Line, StatusPill, Tile, TileGrid, shareCsv } from './loanParts';
import { formatUGX, shortDate } from './loanRoutes';

const METHOD = LoanReferralService.method;

interface Filter {
  readonly search: string;
  readonly status: string;
  readonly partnerId: string;
  readonly needsFollowUp: boolean;
  readonly deliveryStatus: string;
  readonly matchStatus: string;
}

const NO_FILTER: Filter = { search: '', status: '', partnerId: '', needsFollowUp: false, deliveryStatus: '', matchStatus: '' };

interface LoanReferralsScreenProps {
  readonly onOpen: (applicationId: string) => void;
  readonly onShare: () => void;
}

export function LoanReferralsScreen({ onOpen, onShare }: LoanReferralsScreenProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [filter, setFilter] = useState<Filter>(NO_FILTER);
  const [typed, setTyped] = useState('');
  const [page, setPage] = useState(1);
  const [list, setList] = useState<ListLoanApplicationsResponse | null>(null);
  const [dashboard, setDashboard] = useState<GetLoanDashboardResponse | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(() => {
    setError('');
    const request = { filter: { ...filter } };
    api
      .call(METHOD.listLoanApplications, { ...request, page })
      .then(setList)
      .catch((cause: unknown) => setError(describe(cause)));
    api
      .call(METHOD.getLoanDashboard, request)
      .then(setDashboard)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, filter, page]);
  useEffect(load, [load]);

  // A search runs once typing pauses.
  useEffect(() => {
    const timer = setTimeout(() => {
      setPage(1);
      setFilter((current) => (current.search === typed ? current : { ...current, search: typed }));
    }, 350);
    return () => clearTimeout(timer);
  }, [typed]);

  const only = (next: Partial<Filter>) => {
    setPage(1);
    setFilter({ ...NO_FILTER, search: filter.search, ...next });
  };

  const exportCsv = () => {
    api
      .call(METHOD.exportLoanApplications, { filter: { ...filter } })
      .then((answer) => shareCsv(answer.fileName, answer.csv).then(() => setNotice(`Exported ${answer.rows} applications.`)))
      .catch((cause: unknown) => setError(describe(cause)));
  };

  const totalPages = list ? Math.max(1, Math.ceil(list.total / Math.max(1, list.pageSize))) : 1;

  return (
    <ScrollView contentContainerStyle={opsStyles.page} keyboardShouldPersistTaps="handled">
      <OpsTitle
        eyebrow="School loans"
        title="Loan referrals"
        copy="Applications schools sent through Edify's public link, and where each stands with its lender."
      />
      <View style={opsStyles.actions}>
        <DrawerButton label="Share application link" isPrimary onPress={onShare} />
        <DrawerButton label="Export" onPress={exportCsv} />
      </View>
      <Notice text={notice} />
      <Notice text={error} isError />

      {dashboard ? (
        <>
          <TileGrid>
            <Tile label="Applications" value={String(dashboard.totalApplications)} onPress={() => only({})} />
            <Tile label="Awaiting lender receipt" value={String(dashboard.awaitingLenderReceipt)} tone="caution" onPress={() => only({ status: 'awaiting_lender_receipt' })} />
            <Tile label="With the lender" value={String(dashboard.underReview)} tone="info" onPress={() => only({ status: 'under_review' })} />
            <Tile label="Approved (incl. disbursed)" value={String(dashboard.approved)} tone="good" onPress={() => only({ status: 'approved' })} />
            <Tile label="Declined" value={String(dashboard.declined)} tone="alert" onPress={() => only({ status: 'declined' })} />
            <Tile label="Disbursed loans" value={String(dashboard.disbursed)} tone="good" onPress={() => only({ status: 'disbursed' })} />
            <Tile label="Need follow-up" value={String(dashboard.needsFollowUp)} tone="caution" onPress={() => only({ needsFollowUp: true })} />
            <Tile label="Delivery problems" value={String(dashboard.deliveryProblems)} tone="alert" onPress={() => only({ deliveryStatus: 'failed' })} />
            <Tile label="School to match" value={String(dashboard.needsSchoolMatch)} tone="caution" onPress={() => only({ matchStatus: 'needs_review' })} />
          </TileGrid>
          <OpsCard>
            <Line label="Requested" value={formatUGX(dashboard.requestedUgx)} isFirst />
            <Line label="Approved" value={formatUGX(dashboard.approvedUgx)} />
            <Line label="Disbursed (lender-confirmed)" value={formatUGX(dashboard.disbursedUgx)} isStrong />
          </OpsCard>
          <Measures dashboard={dashboard} />
          <Breakdowns dashboard={dashboard} />
        </>
      ) : !error ? (
        <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />
      ) : null}

      <SectionLabel>Applications</SectionLabel>
      <TextInput
        value={typed}
        onChangeText={setTyped}
        placeholder="Search school, reference or School ID"
        placeholderTextColor={colors.textSubtle}
        accessibilityLabel="Search applications"
        style={[styles.search, { color: colors.text, borderColor: colors.fieldBorder, backgroundColor: colors.surface }]}
      />
      {list ? (
        <View style={styles.filters}>
          <Select
            label="Status"
            value={filter.status}
            choices={list.statuses.map((choice) => ({ value: choice.value, label: choice.label }))}
            placeholder="Every status"
            hasEmptyChoice
            onChange={(status) => only({ status, partnerId: filter.partnerId })}
            variant="form"
          />
          <Select
            label="Lender"
            value={filter.partnerId}
            choices={list.lenders.map((lender) => ({ value: lender.partnerId, label: lender.name }))}
            placeholder="Every lender"
            hasEmptyChoice
            onChange={(partnerId) => only({ partnerId, status: filter.status })}
            variant="form"
          />
          <ChoiceRow
            label="Show"
            value={filter.needsFollowUp ? 'follow' : 'all'}
            choices={[
              { value: 'all', label: 'All' },
              { value: 'follow', label: 'Needs follow-up' },
            ]}
            onChange={(value) => only({ needsFollowUp: value === 'follow', status: filter.status, partnerId: filter.partnerId })}
          />
        </View>
      ) : null}
      {list?.contactDetailsHidden ? <Muted>Your role sees each application without the director's contact details or the school's fees.</Muted> : null}
      {list && list.rows.length === 0 ? <Muted>No application matches.</Muted> : null}
      {list?.rows.map((row) => <ApplicationCard key={row.id} row={row} onOpen={onOpen} />)}
      {list && totalPages > 1 ? (
        <View style={opsStyles.actions}>
          <DrawerButton label="Previous" isDisabled={page <= 1} onPress={() => setPage((current) => current - 1)} />
          <Text style={[styles.pageText, { color: colors.textMuted }]}>
            Page {page} of {totalPages}
          </Text>
          <DrawerButton label="Next" isDisabled={page >= totalPages} onPress={() => setPage((current) => current + 1)} />
        </View>
      ) : null}
    </ScrollView>
  );
}

function ApplicationCard({ row, onOpen }: { readonly row: LoanApplicationRow; readonly onOpen: (id: string) => void }) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={() => onOpen(row.id)}
      accessibilityRole="button"
      accessibilityLabel={`${row.schoolName}, ${row.reference}, ${row.statusLabel}`}
      style={({ pressed }) => [styles.card, { backgroundColor: colors.raised, borderColor: row.isOverdue ? colors.warning : colors.raisedBorder, opacity: pressed ? 0.88 : 1 }]}
    >
      <View style={opsStyles.spread}>
        <View style={opsStyles.grow}>
          <Text style={[opsStyles.name, { color: colors.text }]} numberOfLines={2}>
            {row.schoolName}
          </Text>
          <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
            {row.reference} · {row.district}
            {row.edifySchoolId ? ` · ID ${row.edifySchoolId}` : ' · not yet matched'}
          </Text>
        </View>
        <StatusPill status={row.status} label={row.statusLabel} />
      </View>
      <View style={styles.cardFacts}>
        <Text style={[styles.amount, { color: colors.text }]}>{formatUGX(row.requestedUgx)}</Text>
        <Text style={[opsStyles.meta, { color: colors.textMuted }]} numberOfLines={1}>
          {row.purposeLabel} · {row.lenderName}
        </Text>
      </View>
      <Text style={[opsStyles.meta, { color: row.deliveryStatus === 'failed' ? colors.danger : colors.textMuted }]}>
        {row.deliveryLabel} · submitted {shortDate(row.submittedAt)}
        {row.nextFollowUpOn ? ` · follow up ${shortDate(row.nextFollowUpOn)}` : ''}
        {row.isOverdue ? ' · overdue' : ''}
      </Text>
    </Pressable>
  );
}

function Measures({ dashboard }: { readonly dashboard: GetLoanDashboardResponse }) {
  const { colors } = useTheme();
  const shown = (value: number, unit: string) =>
    unit === 'percent' ? `${Math.round(value)}%` : unit === 'ugx' ? formatUGX(Math.round(value)) : `${value.toFixed(1)} ${unit}`;
  return (
    <OpsCard>
      <SectionLabel>How quickly lenders act</SectionLabel>
      {dashboard.measures.map((measure) => (
        <Line
          key={measure.key}
          label={measure.label}
          value={measure.available ? shown(measure.value, measure.unit) : `Too few yet (${measure.basedOn})`}
        />
      ))}
      <Text style={[opsStyles.meta, { color: colors.textSubtle }]}>A measure shows once at least three applications support it.</Text>
    </OpsCard>
  );
}

const BREAKDOWNS = [
  { key: 'byLender', title: 'By lending partner' },
  { key: 'byDistrict', title: 'By district' },
  { key: 'byPurpose', title: 'By loan purpose' },
  { key: 'byMonth', title: 'By month' },
  { key: 'byQuarter', title: 'By quarter' },
  { key: 'byFinancialYear', title: 'By financial year' },
] as const;

function Breakdowns({ dashboard }: { readonly dashboard: GetLoanDashboardResponse }) {
  const { colors } = useTheme();
  const [which, setWhich] = useState<(typeof BREAKDOWNS)[number]['key']>('byLender');
  const rows = dashboard[which];
  return (
    <OpsCard>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
        {BREAKDOWNS.map((breakdown) => {
          const isOn = breakdown.key === which;
          return (
            <Pressable
              key={breakdown.key}
              onPress={() => setWhich(breakdown.key)}
              accessibilityRole="tab"
              accessibilityState={{ selected: isOn }}
              style={[styles.tab, { backgroundColor: isOn ? colors.primary : colors.surface, borderColor: isOn ? colors.primary : colors.border }]}
            >
              <Text style={[styles.tabText, { color: isOn ? colors.primaryInk : colors.text }]}>{breakdown.title}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
      {rows.length === 0 ? <Muted>Nothing to break down yet.</Muted> : null}
      {rows.map((row) => (
        <View key={row.key} style={[styles.breakdown, { borderTopColor: colors.border }]}>
          <View style={opsStyles.grow}>
            <Text style={[opsStyles.name, { color: colors.text, fontSize: 14 }]}>{row.label}</Text>
            <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
              {row.applications} applied · {row.approved} approved · {row.disbursed} disbursed
            </Text>
          </View>
          <View style={styles.breakdownAmounts}>
            <Text style={[styles.amountSmall, { color: colors.text }]}>{formatUGX(row.requestedUgx)}</Text>
            <Text style={[opsStyles.meta, { color: colors.success }]}>{formatUGX(row.disbursedUgx)} out</Text>
          </View>
        </View>
      ))}
    </OpsCard>
  );
}

const styles = StyleSheet.create({
  search: { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10, fontFamily: fonts.medium, fontSize: 15 },
  filters: { gap: 4 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 8 },
  cardFacts: { gap: 2 },
  amount: { fontFamily: fonts.bold, fontSize: 17, fontVariant: ['tabular-nums'] },
  amountSmall: { fontFamily: fonts.semibold, fontSize: 13, fontVariant: ['tabular-nums'] },
  pageText: { fontFamily: fonts.medium, fontSize: 13, alignSelf: 'center' },
  tabs: { gap: 6, paddingBottom: 4 },
  tab: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 6 },
  tabText: { fontFamily: fonts.semibold, fontSize: 12.5 },
  breakdown: { flexDirection: 'row', gap: 10, paddingVertical: 9, borderTopWidth: StyleSheet.hairlineWidth },
  breakdownAmounts: { alignItems: 'flex-end' },
});
