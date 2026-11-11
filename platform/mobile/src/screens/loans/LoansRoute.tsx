/**
 * Where the loan referral URLs lead: the staff list and an application's
 * page, the lending partners, or a lender's own referrals.
 */
import { useState } from 'react';

import { LENDER_CHANNELS_URL, MY_REFERRALS_URL } from './loanRoutes';
import { LenderChannelsScreen } from './LenderChannelsScreen';
import { LoanApplicationScreen } from './LoanApplicationScreen';
import { LoanReferralsScreen } from './LoanReferralsScreen';
import { MyReferralsScreen } from './MyReferralsScreen';

export function LoansRoute({ url }: { readonly url: string }) {
  const [applicationId, setApplicationId] = useState('');
  if (url === LENDER_CHANNELS_URL) {
    return <LenderChannelsScreen />;
  }
  if (url === MY_REFERRALS_URL) {
    return <MyReferralsScreen />;
  }
  if (applicationId) {
    return <LoanApplicationScreen key={applicationId} applicationId={applicationId} onBack={() => setApplicationId('')} />;
  }
  return <LoanReferralsScreen onOpen={setApplicationId} />;
}
