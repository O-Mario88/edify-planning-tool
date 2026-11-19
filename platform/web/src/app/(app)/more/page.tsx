import type { Metadata } from 'next';

import { PhoneMore } from '@/components/phone/PhoneMore';
import { IdentityService } from '@/gen/edify/identity/v1/identity_pb';
import { NavigationService } from '@/gen/edify/screens/v1/navigation_pb';
import { asReader } from '@/lib/auth';
import { gatewayClient, isUnavailable } from '@/lib/gateway';
import { withRoutePlanner } from '@/lib/routePlanner';

export const metadata: Metadata = { title: 'More — Edify' };

/*
 * The phone's More (the bottom bar's last tab): the reader's whole menu in
 * the native app's design, asked of the gateway as the shell asks it.
 */
export default async function MorePage() {
  const [session, navigation] = await asReader((token) =>
    Promise.all([
      gatewayClient(IdentityService, token).getSession({}),
      gatewayClient(NavigationService, token)
        .getNavigation({})
        .catch((error: unknown) => {
          if (isUnavailable(error)) return { sections: [], bottom: [] };
          throw error;
        }),
    ]),
  );
  const person = session.session;
  const activeRole = person?.activeRole ?? '';
  return (
    <PhoneMore
      name={person?.name || person?.email || ''}
      email={person?.email ?? ''}
      activeRole={activeRole}
      roles={person?.roles ?? []}
      sections={withRoutePlanner(navigation.sections, activeRole)}
    />
  );
}
