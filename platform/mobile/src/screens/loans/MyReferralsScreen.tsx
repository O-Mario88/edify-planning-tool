/**
 * Referrals to a lender, for its own staff signed in to Edify (brief §9):
 * only the applications addressed to their lender. They acknowledge receipt,
 * record review, ask for information, record approval or decline, confirm
 * disbursement, and message Edify. The credit decision is theirs alone.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetMyReferralResponse, ListMyReferralsResponse } from '../../gen/edify/loans/v1/loans_pb';
import { LoanReferralService } from '../../gen/edify/loans/v1/loans_pb';
import { useTheme } from '../../theme';
import { DateField } from '../../ui/DateField';
import { DrawerButton } from '../../ui/drawerParts';
import { Select } from '../../ui/Select';
import { Field, Muted, Notice, OpsCard, OpsTitle, SectionLabel, opsStyles } from '../cluster/opsParts';
import { Line, StatusPill } from './loanParts';
import { formatUGX, parseUGX, shortDate, todayISO } from './loanRoutes';

const METHOD = LoanReferralService.method;

export function MyReferralsScreen({ onShare }: { readonly onShare: () => void }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [answer, setAnswer] = useState<ListMyReferralsResponse | null>(null);
  const [openId, setOpenId] = useState('');
  const [error, setError] = useState('');
  const load = useCallback(() => {
    api
      .call(METHOD.listMyReferrals, {})
      .then(setAnswer)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api]);
  useEffect(load, [load]);

  if (openId) {
    return (
      <ReferralScreen
        key={openId}
        applicationId={openId}
        onBack={() => {
          setOpenId('');
          load();
        }}
      />
    );
  }
  return (
    <ScrollView contentContainerStyle={opsStyles.page}>
      <OpsTitle eyebrow={answer?.lenderName ?? 'School loans'} title="Referrals to us" copy="School loan applications Edify has sent to your organisation." />
      <DrawerButton label="Share our application link" isPrimary onPress={onShare} />
      <Notice text={error} isError />
      {!answer && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
      {answer && answer.rows.length === 0 ? <Muted>No school has applied to you through Edify yet.</Muted> : null}
      {answer?.rows.map((row) => (
        <Pressable key={row.id} onPress={() => setOpenId(row.id)} accessibilityRole="button" accessibilityLabel={`Open ${row.schoolName}, ${row.reference}`}>
          <OpsCard>
            <View style={opsStyles.spread}>
              <View style={opsStyles.grow}>
                <Text style={[opsStyles.name, { color: colors.text }]}>{row.schoolName}</Text>
                <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
                  {row.reference} · {row.district} · {formatUGX(row.requestedUgx)} · {shortDate(row.submittedAt)}
                </Text>
              </View>
              <StatusPill status={row.status} label={row.statusLabel} />
            </View>
          </OpsCard>
        </Pressable>
      ))}
    </ScrollView>
  );
}

function ReferralScreen({ applicationId, onBack }: { readonly applicationId: string; readonly onBack: () => void }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [answer, setAnswer] = useState<GetMyReferralResponse | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [action, setAction] = useState('');
  const [note, setNote] = useState('');
  const [approved, setApproved] = useState('');
  const [disbursed, setDisbursed] = useState('');
  const [disbursedOn, setDisbursedOn] = useState('');
  const [reference, setReference] = useState('');
  const [term, setTerm] = useState('');
  const [rate, setRate] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  const load = useCallback(() => {
    api
      .call(METHOD.getMyReferral, { applicationId })
      .then(setAnswer)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, applicationId]);
  useEffect(load, [load]);

  const record = () => {
    const approvedUgx = approved ? parseUGX(approved) : BigInt(0);
    const disbursedUgx = disbursed ? parseUGX(disbursed) : BigInt(0);
    const months = term ? Number(term) : 0;
    if (approvedUgx === null || disbursedUgx === null || !Number.isInteger(months)) {
      setError('Write amounts in whole shillings (38,500,000) and the term in whole months.');
      return;
    }
    setIsBusy(true);
    setError('');
    api
      .call(METHOD.recordLenderUpdate, {
        applicationId, action, note, approvedUgx, disbursedUgx, disbursementDate: disbursedOn,
        disbursementReference: reference, termMonths: months, interestRate: rate,
      })
      .then((result) => {
        setNotice(action === 'message' ? 'Your message was sent to Edify.' : `Recorded: ${result.statusLabel}.`);
        setAction('');
        setNote('');
        load();
      })
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  const application = answer?.application;
  const row = application?.row;
  if (!row || !application) {
    return (
      <ScrollView contentContainerStyle={opsStyles.page}>
        <DrawerButton label="All referrals" onPress={onBack} />
        {error ? <Notice text={error} isError /> : <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />}
      </ScrollView>
    );
  }
  const choices = [...(answer?.actions ?? []).map((choice) => ({ value: choice.value, label: choice.label })), { value: 'message', label: 'Send a message to Edify' }];
  const needsNote = action === 'decline' || action === 'request_information' || action === 'close' || action === 'message';
  return (
    <ScrollView contentContainerStyle={opsStyles.page} keyboardShouldPersistTaps="handled">
      <DrawerButton label="All referrals" onPress={onBack} />
      <OpsTitle eyebrow={row.reference} title={row.schoolName} copy={`Submitted ${shortDate(row.submittedAt)}`} />
      <StatusPill status={row.status} label={row.statusLabel} />
      <Notice text={notice} />
      <Notice text={error} isError />
      <OpsCard>
        <Line label="School ID" value={row.edifySchoolId || 'Not matched'} isFirst />
        <Line label="Location" value={[application.village, application.parish, application.subCounty, row.district].filter(Boolean).join(', ')} />
        <Line label="Director" value={row.directorName} />
        <Line label="Director's phone" value={row.directorPhone} />
        <Line label="Director's email" value={application.directorEmail} />
        <Line label="Enrollment" value={`${row.totalEnrollment} (${application.boys} boys, ${application.girls} girls)`} />
        <Line label="Fees collected per term" value={formatUGX(row.feesCollectedUgx)} />
        <Line label="Purpose" value={row.purposeLabel + (application.purposeOther ? `: ${application.purposeOther}` : '')} />
        <Line label="Requested" value={formatUGX(row.requestedUgx)} isStrong />
        <Line label="Preferred repayment period" value={application.preferredTermMonths ? `${application.preferredTermMonths} months` : ''} />
        <Line label="Approved" value={row.approvedUgx > 0 ? formatUGX(row.approvedUgx) : ''} />
        <Line label="Disbursed" value={row.disbursedUgx > 0 ? formatUGX(row.disbursedUgx) : ''} />
        {application.purposeDetails ? <Muted>{application.purposeDetails}</Muted> : null}
      </OpsCard>

      <OpsCard>
        <SectionLabel>Record progress</SectionLabel>
        <Select label="What to record" value={action} choices={choices} placeholder="Choose" onChange={setAction} variant="form" />
        {action === 'approve' ? (
          <>
            <Field label="Approved amount (UGX)" value={approved} onChange={setApproved} isNumeric />
            <Field label="Term in months (optional)" value={term} onChange={setTerm} isNumeric />
            <Field label="Interest rate (optional)" value={rate} onChange={setRate} placeholder="e.g. 2% a month" />
          </>
        ) : null}
        {action === 'disburse' ? (
          <>
            <Field label="Amount actually disbursed (UGX)" value={disbursed} onChange={setDisbursed} isNumeric />
            <DateField label="Disbursement date" value={disbursedOn} onChange={setDisbursedOn} max={todayISO()} />
            <Field label="Loan or transaction reference" value={reference} onChange={setReference} />
          </>
        ) : null}
        {action ? <Field label={needsNote ? 'Note' : 'Note (optional)'} value={note} onChange={setNote} isMultiline /> : null}
        {action ? <DrawerButton label="Record" isPrimary isBusy={isBusy} isDisabled={needsNote && !note.trim()} onPress={record} /> : null}
      </OpsCard>

      <SectionLabel>History</SectionLabel>
      <OpsCard>
        {answer?.timeline.map((entry, index) => (
          <View key={`${entry.at}-${index}`} style={{ paddingVertical: 5 }}>
            <Text style={[opsStyles.name, { color: colors.text, fontSize: 14 }]}>{entry.label}</Text>
            <Text style={[opsStyles.meta, { color: colors.textMuted }]}>{shortDate(entry.at)}</Text>
            {entry.note ? <Muted>{entry.note}</Muted> : null}
          </View>
        ))}
      </OpsCard>
    </ScrollView>
  );
}
