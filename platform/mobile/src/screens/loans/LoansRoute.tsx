/**
 * Where the loan referral URLs lead: the staff list and an application's
 * page, the lending partners, or a lender's own referrals.
 */
import { useState, type ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { LENDER_CASES_URL, LENDER_CHANNELS_URL, MY_REFERRALS_URL, SHARE_URL, STAFF_LOANS_URL } from './loanRoutes';
import { LenderChannelsScreen } from './LenderChannelsScreen';
import { LoanApplicationScreen } from './LoanApplicationScreen';
import { LoanReferralsScreen } from './LoanReferralsScreen';
import { MyReferralsScreen } from './MyReferralsScreen';
import { LenderCasesScreen } from './LenderCasesScreen';
import { LoanProgressScreen } from './LoanProgressScreen';
import { ShareApplicationScreen } from './ShareSheet';
import { StaffLoansScreen, type ProgressPanel } from './StaffLoansScreen';

export function LoansRoute({ url }: { readonly url: string }) {
  const [applicationId, setApplicationId] = useState('');
  const [isSharing, setIsSharing] = useState(false);
  const [progress, setProgress] = useState<{ id: string; panel: ProgressPanel } | null>(null);
  const [returns, setReturns] = useState(0);
  const sharing = isSharing ? <ShareApplicationScreen eyebrow="Loans & Financing" onBack={() => setIsSharing(false)} /> : null;
  if (url === SHARE_URL) {
    return <ShareApplicationScreen eyebrow="Loans & Financing" />;
  }
  if (url === STAFF_LOANS_URL) {
    const opened = progress ? (
      <LoanProgressScreen key={progress.id} applicationId={progress.id} initialPanel={progress.panel} onBack={() => {
          setProgress(null);
          setReturns((count) => count + 1);
        }}
      />
    ) : null;
    return (
      <KeptUnder top={sharing ?? opened}>
        <StaffLoansScreen onOpen={(id, panel) => setProgress({ id, panel })} onShare={() => setIsSharing(true)} returns={returns} />
      </KeptUnder>
    );
  }
  if (url === LENDER_CASES_URL) {
    return (
      <KeptUnder top={sharing}>
        <LenderCasesScreen onShare={() => setIsSharing(true)} />
      </KeptUnder>
    );
  }
  if (sharing) {
    return sharing;
  }
  if (url === LENDER_CHANNELS_URL) {
    return <LenderChannelsScreen />;
  }
  if (url === MY_REFERRALS_URL) {
    return <MyReferralsScreen onShare={() => setIsSharing(true)} />;
  }
  if (applicationId) {
    return <LoanApplicationScreen key={applicationId} applicationId={applicationId} onBack={() => setApplicationId('')} />;
  }
  return <LoanReferralsScreen onOpen={setApplicationId} onShare={() => setIsSharing(true)} />;
}

/**
 * Shows `top` over a list that stays mounted underneath, so going back finds
 * the list as it was left: its tab, search and place.
 */
function KeptUnder({ top, children }: { readonly top: ReactNode; readonly children: ReactNode }) {
  return (
    <>
      <View style={top ? styles.hidden : styles.fill}>{children}</View>
      {top ? <View style={styles.fill}>{top}</View> : null}
    </>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  hidden: { display: 'none' },
});
