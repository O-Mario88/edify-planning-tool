/**
 * One school loan application for Edify staff (brief §8, §10): its details
 * as the caller's role may see them, where it stands with the lender, its
 * delivery, the actions the role may take, and its timeline and follow-ups,
 * so whoever opens it understands its progress at once.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, Text, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetLoanApplicationResponse } from '../../gen/edify/loans/v1/loans_pb';
import { LoanReferralService } from '../../gen/edify/loans/v1/loans_pb';
import { useTheme } from '../../theme';
import { DrawerButton } from '../../ui/drawerParts';
import { Muted, Notice, OpsCard, OpsTitle, SectionLabel, opsStyles } from '../cluster/opsParts';
import { CorrectionForm, FollowUpForm, LinkLoanForm, OversightForm, ResendButton, SchoolMatchForm } from './LoanApplicationActions';
import { Line, StatusPill } from './loanParts';
import { formatUGX, shortDate } from './loanRoutes';

const MATCH_LABELS: Readonly<Record<string, string>> = {
  matched: 'Matched',
  needs_review: 'Needs a BTO to confirm the school',
  unmatched: 'Not matched yet',
  not_in_directory: 'Not in the School Directory yet',
};

export function LoanApplicationScreen({ applicationId, onBack }: { readonly applicationId: string; readonly onBack: () => void }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [answer, setAnswer] = useState<GetLoanApplicationResponse | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(() => {
    api
      .call(LoanReferralService.method.getLoanApplication, { id: applicationId })
      .then(setAnswer)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, applicationId]);
  useEffect(load, [load]);

  const done = (message: string) => {
    setNotice(message);
    load();
  };

  if (!answer?.application?.row) {
    return (
      <ScrollView contentContainerStyle={opsStyles.page}>
        <DrawerButton label="Back to referrals" onPress={onBack} />
        {error ? <Notice text={error} isError /> : <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />}
      </ScrollView>
    );
  }
  const application = answer.application;
  const row = application.row!;
  const hidden = answer.contactDetailsHidden;
  const location = [application.village, application.parish, application.subCounty, row.district].filter(Boolean).join(', ');
  const delivery = answer.deliveries[0];

  return (
    <ScrollView contentContainerStyle={opsStyles.page} keyboardShouldPersistTaps="handled">
      <DrawerButton label="Back to referrals" onPress={onBack} />
      <OpsTitle eyebrow={row.reference} title={row.schoolName} copy={`${row.lenderName} · submitted ${shortDate(row.submittedAt)}`} />
      <View style={opsStyles.actions}>
        <StatusPill status={row.status} label={row.statusLabel} />
        <StatusPill status={row.deliveryStatus === 'failed' ? 'declined' : 'under_review'} label={row.deliveryLabel} />
      </View>
      <Notice text={notice} />
      <Notice text={error} isError />

      <OpsCard>
        <SectionLabel>The loan</SectionLabel>
        <Line label="Purpose" value={row.purposeLabel + (application.purposeOther ? `: ${application.purposeOther}` : '')} />
        <Line label="Requested" value={formatUGX(row.requestedUgx)} isStrong />
        <Line label="Approved" value={row.approvedUgx > 0 ? formatUGX(row.approvedUgx) : 'Not yet'} />
        <Line label="Disbursed" value={row.disbursedUgx > 0 ? formatUGX(row.disbursedUgx) : 'Not yet'} />
        <Line label="Disbursement date" value={shortDate(application.disbursementDate)} />
        <Line label="Disbursement reference" value={application.disbursementReference} />
        <Line label="Preferred repayment period" value={application.preferredTermMonths ? `${application.preferredTermMonths} months` : ''} />
        <Line label="Agreed term" value={application.agreedTermMonths ? `${application.agreedTermMonths} months` : ''} />
        <Line label="Interest rate" value={application.interestRate} />
        <Line label="Registered loan" value={application.linkedMfiLoanId} />
        {application.purposeDetails ? <Muted>{application.purposeDetails}</Muted> : null}
      </OpsCard>

      <OpsCard>
        <SectionLabel>The school</SectionLabel>
        <Line label="School ID" value={row.edifySchoolId || MATCH_LABELS[row.matchStatus] || row.matchStatus} />
        <Line label="Location" value={location} />
        <Line label="Enrollment" value={`${row.totalEnrollment} (${application.boys} boys, ${application.girls} girls)`} />
        {hidden ? (
          <Muted>Your role sees this application without the director's contact details or the school's fees.</Muted>
        ) : (
          <>
            <Line label="Fees collected per term" value={formatUGX(row.feesCollectedUgx)} />
            <Line label="Director" value={row.directorName} />
            <Line label="Director's phone" value={row.directorPhone} />
            <Line label="Director's email" value={application.directorEmail} />
          </>
        )}
      </OpsCard>

      <OpsCard>
        <SectionLabel>Follow-up</SectionLabel>
        <Line label="Responsible BTO" value={row.responsibleBtoName || 'Nobody yet'} />
        <Line label="Next follow-up" value={row.nextFollowUpOn ? shortDate(row.nextFollowUpOn) + (row.isOverdue ? ' (overdue)' : '') : 'Not set'} />
        <Line label="Last follow-up" value={shortDate(row.lastFollowUpAt) || 'None yet'} />
        <Line label="Lender received it" value={shortDate(application.lenderReceivedAt) || 'Not yet'} />
        {delivery ? (
          <Text style={[opsStyles.meta, { color: delivery.status === 'failed' ? colors.danger : colors.textMuted }]}>
            Notification {delivery.status} after {delivery.attempts} attempt{delivery.attempts === 1 ? '' : 's'}
            {delivery.recipient ? ` to ${delivery.recipient}` : ''}
            {delivery.lastError ? `. ${delivery.lastError}` : ''}
          </Text>
        ) : null}
        {answer.canFollowUp ? (
          <View style={opsStyles.actions}>
            <TakeResponsibility applicationId={application.row!.id} onDone={done} />
            {row.deliveryStatus === 'failed' || row.deliveryStatus === 'queued' ? <ResendButton applicationId={row.id} onDone={done} /> : null}
          </View>
        ) : null}
      </OpsCard>

      {answer.canFollowUp ? <FollowUpForm applicationId={row.id} onDone={done} /> : null}
      {answer.canRecordOversight ? <OversightForm applicationId={row.id} onDone={done} /> : null}
      {answer.canFollowUp ? (
        <SchoolMatchForm applicationId={row.id} candidates={answer.matchCandidates} isMatched={row.matchStatus === 'matched'} onDone={done} />
      ) : null}
      {answer.canFollowUp ? <CorrectionForm applicationId={row.id} actions={answer.correctionActions} onDone={done} /> : null}
      {answer.canFollowUp && row.matchStatus === 'matched' && row.disbursedUgx > 0 && !application.linkedMfiLoanId ? (
        <LinkLoanForm applicationId={row.id} onDone={done} />
      ) : null}

      <SectionLabel>Follow-ups</SectionLabel>
      <OpsCard>
        {answer.followUps.length === 0 ? <Muted>No follow-up recorded yet.</Muted> : null}
        {answer.followUps.map((followUp) => (
          <View key={followUp.id} style={{ gap: 2, paddingVertical: 6 }}>
            <Text style={[opsStyles.name, { color: colors.text, fontSize: 14 }]}>
              {followUp.isOversight ? 'Oversight note' : `By ${followUp.channel}`} · {shortDate(followUp.followedUpOn)}
            </Text>
            <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
              {followUp.staffName}
              {followUp.nextFollowUpOn ? ` · next ${shortDate(followUp.nextFollowUpOn)}` : ''}
            </Text>
            <Muted>{followUp.notes}</Muted>
            {followUp.lenderFeedback ? <Muted>Lender: {followUp.lenderFeedback}</Muted> : null}
            {followUp.nextAction ? <Muted>Next: {followUp.nextAction}</Muted> : null}
          </View>
        ))}
      </OpsCard>

      <SectionLabel>Timeline</SectionLabel>
      <OpsCard>
        {answer.timeline.map((entry, index) => (
          <View key={`${entry.at}-${index}`} style={{ flexDirection: 'row', gap: 10, paddingVertical: 6 }}>
            <View style={{ width: 8, height: 8, borderRadius: 4, marginTop: 6, backgroundColor: entry.actorKind === 'lender' ? colors.success : colors.primary }} />
            <View style={opsStyles.grow}>
              <Text style={[opsStyles.name, { color: colors.text, fontSize: 14 }]}>{entry.label}</Text>
              <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
                {shortDate(entry.at)}
                {entry.actorName ? ` · ${entry.actorName}` : ''}
              </Text>
              {entry.note ? <Muted>{entry.note}</Muted> : null}
              {entry.evidence ? <Muted>Evidence: {entry.evidence}</Muted> : null}
            </View>
          </View>
        ))}
      </OpsCard>
    </ScrollView>
  );
}

function TakeResponsibility({ applicationId, onDone }: { readonly applicationId: string; readonly onDone: (message: string) => void }) {
  const { api } = useSession();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  return (
    <>
      <DrawerButton
        label="I'll follow this up"
        isBusy={isBusy}
        onPress={() => {
          setIsBusy(true);
          api
            .call(LoanReferralService.method.updateTracking, { applicationId, takeResponsibility: true })
            .then(() => onDone('You are now the responsible BTO.'))
            .catch((cause: unknown) => setError(describe(cause)))
            .finally(() => setIsBusy(false));
        }}
      />
      <Notice text={error} isError />
    </>
  );
}
