/**
 * "Progress & Reports" (owner's mockup, 2026-11-11): My Cluster — the
 * financial year's meetings and trainings, the member schools' SSA
 * performance against the year before, the activity summary and the report
 * as a PDF — and My Schools, each school's SSA status and repeated absences.
 * Figures are the gateway's report; nothing is estimated here.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { CalendarDays, ChevronDown, ChevronRight, Download, GraduationCap, ListChecks, School, TrendingUp } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ClusterSummary } from '../../gen/edify/clusters/v1/leadership_pb';
import type { GetClusterReportResponse, SsaPerformance } from '../../gen/edify/clusters/v1/mobilization_pb';
import { ClusterMobilizationService } from '../../gen/edify/clusters/v1/mobilization_pb';
import { fonts, radius, useTheme } from '../../theme';
import { savePdf } from '../../ui/savePdf';
import { LoanHero, LoanSheet, SegmentTabs, StatusChip } from '../loans/loanUi';
import { ssaStatusLabel, useAllMembers } from './clusterData';
import { Notice } from './opsParts';

const METHOD = ClusterMobilizationService.method;
type Tab = 'cluster' | 'schools';

export function ProgressScreen({ cluster }: { readonly cluster: ClusterSummary }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [tab, setTab] = useState<Tab>('cluster');
  const [report, setReport] = useState<GetClusterReportResponse | null>(null);
  const [error, setError] = useState('');
  const [isSummaryOpen, setIsSummaryOpen] = useState(false);
  const [download, setDownload] = useState<'idle' | 'busy' | 'done'>('idle');

  useEffect(() => {
    api
      .call(METHOD.getClusterReport, { clusterId: cluster.id })
      .then(setReport)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, cluster.id]);

  const figure = (key: string) => report?.figures.find((item) => item.key === key)?.value ?? '0';
  const downloadPdf = () => {
    setDownload('busy');
    setError('');
    api
      .call(METHOD.getClusterReportPdf, { clusterId: cluster.id })
      .then((answer) => savePdf(answer.pdf, answer.fileName))
      .then(() => setDownload('done'))
      .catch((cause: unknown) => {
        setDownload('idle');
        setError(describe(cause));
      });
  };
  const card = [styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }];

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LoanHero eyebrow={cluster.name} title="Progress & Reports" subtitle={report?.period} />
      <LoanSheet>
        <SegmentTabs
          tabs={[
            { key: 'cluster', label: 'My Cluster' },
            { key: 'schools', label: 'My Schools' },
          ]}
          value={tab}
          onChange={setTab}
        />
        {error ? <Notice text={error} isError /> : null}
        {!report && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}

        {tab === 'cluster' && report ? (
          <>
            <View style={card}>
              <Text style={[styles.cardTitle, { color: colors.text }]} accessibilityRole="header">
                Cluster Overview
              </Text>
              <View style={styles.overview}>
                <Stat icon={School} value={String(cluster.memberSchoolCount)} label="Schools" />
                <Stat icon={CalendarDays} value={figure('meetings_held')} label={`Meetings held\n(this FY)`} />
                <Stat icon={GraduationCap} value={figure('trainings_held')} label={`Trainings held\n(this FY)`} />
              </View>
            </View>

            {report.ssaPerformance ? <SsaCard ssa={report.ssaPerformance} /> : null}

            <Pressable onPress={() => setIsSummaryOpen(!isSummaryOpen)} accessibilityRole="button" accessibilityState={{ expanded: isSummaryOpen }} style={[card, styles.row]}>
              <ListChecks size={22} color={colors.primary} />
              <Text style={[styles.rowLabel, { color: colors.text }]}>Activity Summary</Text>
              {isSummaryOpen ? <ChevronDown size={20} color={colors.textMuted} /> : <ChevronRight size={20} color={colors.textMuted} />}
            </Pressable>
            {isSummaryOpen ? (
              <View style={card}>
                {[
                  ...report.figures,
                  ...report.trainingByIntervention.map((count) => ({ key: `t-${count.label}`, label: `Trainings held: ${count.label}`, value: String(count.count) })),
                  ...report.needsStaff.map((count) => ({ key: count.label, label: count.label, value: String(count.count) })),
                ].map((item) => (
                  <View key={item.key} style={[styles.fact, { borderTopColor: colors.border }]}>
                    <Text style={[styles.factLabel, { color: colors.textMuted }]}>{item.label}</Text>
                    <Text style={[styles.factValue, { color: colors.text }]}>{item.value}</Text>
                  </View>
                ))}
              </View>
            ) : null}

            <Pressable onPress={downloadPdf} disabled={download === 'busy'} accessibilityRole="button" style={[card, styles.row]}>
              <Download size={22} color={colors.primary} />
              <Text style={[styles.rowLabel, { color: colors.text }]}>
                {download === 'busy' ? 'Preparing the report…' : download === 'done' ? 'Report ready — download again' : 'Download Report (PDF)'}
              </Text>
              <ChevronRight size={20} color={colors.textMuted} />
            </Pressable>
          </>
        ) : null}

        {tab === 'schools' ? <SchoolsProgress cluster={cluster} report={report} /> : null}
      </LoanSheet>
    </ScrollView>
  );
}

function Stat({ icon: Icon, value, label }: { readonly icon: typeof School; readonly value: string; readonly label: string }) {
  const { colors } = useTheme();
  return (
    <View style={styles.stat} accessible accessibilityLabel={`${value} ${label.replace('\n', ' ')}`}>
      <Icon size={22} color={colors.primary} />
      <Text style={[styles.statValue, { color: colors.text }]}>{value}</Text>
      <Text style={[styles.statLabel, { color: colors.textMuted }]}>{label}</Text>
    </View>
  );
}

function SsaCard({ ssa }: { readonly ssa: SsaPerformance }) {
  const { colors } = useTheme();
  const previous = Number(ssa.previousAverage) || 0;
  const current = Number(ssa.currentAverage) || 0;
  const top = Math.max(previous, current, 1);
  const isUp = ssa.change.startsWith('+');
  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <View style={styles.row}>
        <TrendingUp size={22} color={colors.primary} />
        <Text style={[styles.rowLabel, { color: colors.text }]}>SSA Performance (Cluster)</Text>
      </View>
      <View style={styles.ssa}>
        <View style={styles.flex}>
          {ssa.change ? (
            <>
              <Text style={[styles.change, { color: isUp ? colors.success : colors.danger }]}>{ssa.change}</Text>
              <Text style={[styles.factLabel, { color: colors.textMuted }]}>
                average score vs {ssa.previousPeriod} ({isUp ? 'up' : 'down'}), for the {ssa.schoolsCompared}{' '}
                {ssa.schoolsCompared === 1 ? 'school' : 'schools'} assessed in both years
              </Text>
            </>
          ) : (
            <Text style={[styles.factLabel, { color: colors.textMuted }]}>
              No change shown yet: no member school has a confirmed SSA record in both {ssa.previousPeriod} and {ssa.currentPeriod}.
            </Text>
          )}
        </View>
        <View style={styles.bars}>
          {[
            { label: ssa.previousPeriod.replace('FY ', "FY'"), value: previous, text: ssa.previousAverage },
            { label: ssa.currentPeriod.replace('FY ', "FY'"), value: current, text: ssa.currentAverage },
          ].map((bar, index) => (
            <View key={bar.label} style={styles.barColumn} accessible accessibilityLabel={`${bar.label}: ${bar.text || 'no record'}`}>
              <Text style={[styles.barText, { color: colors.text }]}>{bar.text || '–'}</Text>
              <View style={[styles.bar, { height: Math.max(4, (bar.value / top) * 56), backgroundColor: index === 1 ? colors.primary : colors.primarySoft }]} />
              <Text style={[styles.barText, { color: colors.textMuted }]}>{bar.label}</Text>
            </View>
          ))}
        </View>
      </View>
      <Text style={[styles.factLabel, { color: colors.textSubtle }]}>
        Bars: average of all assessed member schools — {ssa.schoolsPrevious} in {ssa.previousPeriod}, {ssa.schoolsCurrent} in{' '}
        {ssa.currentPeriod}.
      </Text>
    </View>
  );
}

function SchoolsProgress({ cluster, report }: { readonly cluster: ClusterSummary; readonly report: GetClusterReportResponse | null }) {
  const { colors } = useTheme();
  const members = useAllMembers(cluster.id);
  const absences = new Map((report?.repeatedlyAbsent ?? []).map((school) => [school.schoolId, school]));
  return (
    <>
      {members.error ? <Notice text={members.error} isError /> : null}
      {members.schools === null && !members.error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
      {members.schools?.map((school) => {
        const absent = absences.get(school.id);
        const ssa = school.currentFySsaStatus || 'none';
        const isDone = ssa === 'done';
        return (
          <View key={school.id} style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
            <View style={styles.row}>
              <Text style={[styles.rowLabel, { color: colors.text }]}>{school.name}</Text>
              <StatusChip label={ssa === 'none' ? 'No SSA status' : `SSA ${ssaStatusLabel(ssa)}`} tone={isDone ? 'good' : 'caution'} />
            </View>
            <Text style={[styles.factLabel, { color: colors.textMuted }]}>{[school.schoolId, school.district].filter(Boolean).join(' · ')}</Text>
            {absent ? (
              <Text style={[styles.factLabel, { color: colors.danger }]}>
                Absent from {absent.absences} of {absent.invitations} activities it was invited to.
              </Text>
            ) : null}
          </View>
        );
      })}
    </>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  flex: { flex: 1, gap: 2 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 10 },
  cardTitle: { fontFamily: fonts.bold, fontSize: 16 },
  overview: { flexDirection: 'row' },
  stat: { flex: 1, alignItems: 'center', gap: 4 },
  statValue: { fontFamily: fonts.bold, fontSize: 24 },
  statLabel: { fontFamily: fonts.medium, fontSize: 12, textAlign: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  rowLabel: { flex: 1, fontFamily: fonts.semibold, fontSize: 15 },
  fact: { flexDirection: 'row', justifyContent: 'space-between', gap: 10, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 8 },
  factLabel: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18, flexShrink: 1 },
  factValue: { fontFamily: fonts.bold, fontSize: 14 },
  ssa: { flexDirection: 'row', alignItems: 'flex-end', gap: 12 },
  change: { fontFamily: fonts.bold, fontSize: 30 },
  bars: { flexDirection: 'row', alignItems: 'flex-end', gap: 10 },
  barColumn: { alignItems: 'center', gap: 4 },
  bar: { width: 26, borderRadius: 6 },
  barText: { fontFamily: fonts.semibold, fontSize: 11 },
});
