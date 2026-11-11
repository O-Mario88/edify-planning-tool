/**
 * A school's loan history on its profile (brief §12): its applications
 * through Edify's public link, its applications through the existing web
 * form, and the loans its lenders registered in the loan ledger. Requested,
 * approved and disbursed amounts stay apart. For the BTO and the Country
 * Director; the gateway refuses anyone else.
 */
import { useEffect, useState } from 'react';
import { Text, View } from 'react-native';

import { useSession } from '../../auth/SessionContext';
import type { GetSchoolLoanHistoryResponse } from '../../gen/edify/loans/v1/loans_pb';
import { LoanReferralService } from '../../gen/edify/loans/v1/loans_pb';
import { useTheme } from '../../theme';
import { Muted, OpsCard, SectionLabel, opsStyles } from '../cluster/opsParts';
import { StatusPill } from './loanParts';
import { formatUGX, shortDate } from './loanRoutes';

const HISTORY_ROLES = new Set(['BusinessTransformationOfficer', 'CountryDirector']);

export function canSeeSchoolLoans(role: string): boolean {
  return HISTORY_ROLES.has(role);
}

export function SchoolLoanHistory({ schoolId }: { readonly schoolId: string }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [history, setHistory] = useState<GetSchoolLoanHistoryResponse | null>(null);
  const [isUnavailable, setIsUnavailable] = useState(false);
  useEffect(() => {
    let isCurrent = true;
    api
      .call(LoanReferralService.method.getSchoolLoanHistory, { schoolId })
      .then((answer) => (isCurrent ? setHistory(answer) : undefined))
      .catch(() => (isCurrent ? setIsUnavailable(true) : undefined));
    return () => {
      isCurrent = false;
    };
  }, [api, schoolId]);

  if (isUnavailable || !history) {
    return null;
  }
  const isEmpty =
    history.applications.length === 0 && history.webFormApplications.length === 0 && history.registeredLoans.length === 0;
  return (
    <OpsCard>
      <SectionLabel>Loan history</SectionLabel>
      {isEmpty ? <Muted>No loan application or registered loan yet.</Muted> : null}
      {history.applications.map((row) => (
        <View key={row.id} style={opsStyles.spread}>
          <View style={opsStyles.grow}>
            <Text style={[opsStyles.name, { color: colors.text, fontSize: 14 }]}>
              {row.purposeLabel} · {formatUGX(row.requestedUgx)} requested
            </Text>
            <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
              {row.reference} · {row.lenderName} · {shortDate(row.submittedAt)}
              {row.approvedUgx > 0 ? ` · ${formatUGX(row.approvedUgx)} approved` : ''}
              {row.disbursedUgx > 0 ? ` · ${formatUGX(row.disbursedUgx)} disbursed` : ''}
            </Text>
          </View>
          <StatusPill status={row.status} label={row.statusLabel} />
        </View>
      ))}
      {history.webFormApplications.map((application) => (
        <View key={application.id} style={opsStyles.spread}>
          <View style={opsStyles.grow}>
            <Text style={[opsStyles.name, { color: colors.text, fontSize: 14 }]}>
              {application.purpose} · {formatUGX(application.requestedUgx)} requested
            </Text>
            <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
              Web form · {application.lenderName || 'No lender chosen'} · {shortDate(application.submittedAt)}
            </Text>
          </View>
          <StatusPill status={application.status} label={application.status.replace(/_/g, ' ')} />
        </View>
      ))}
      {history.registeredLoans.map((loan) => (
        <View key={loan.id} style={opsStyles.spread}>
          <View style={opsStyles.grow}>
            <Text style={[opsStyles.name, { color: colors.text, fontSize: 14 }]}>
              {loan.purpose} · {loan.disbursedUgx > 0 ? `${formatUGX(loan.disbursedUgx)} disbursed` : 'not disbursed'}
            </Text>
            <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
              Registered loan · {loan.lenderName}
              {loan.disbursementDate ? ` · ${shortDate(loan.disbursementDate)}` : ''}
            </Text>
          </View>
          <StatusPill status={loan.status === 'disbursed' || loan.status === 'active' || loan.status === 'repaid' ? 'disbursed' : 'under_review'} label={loan.status} />
        </View>
      ))}
    </OpsCard>
  );
}
