import type { ReactNode } from 'react';

import { IdentityService } from '@/gen/edify/identity/v1/identity_pb';
import { NavigationService } from '@/gen/edify/screens/v1/navigation_pb';
import { SidebarBrand, SidebarNav, Sidebar } from '@/components/shell/Sidebar';
import { BottomNav } from '@/components/shell/BottomNav';
import { TopBar } from '@/components/shell/TopBar';
import { PhoneMenu } from '@/components/shell/TopBarControls';
import { asReader, currentPath } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { gatewayClient, isUnavailable } from '@/lib/gateway';
import { pageSearch } from '@/lib/pageSearch';
import { initialsOf } from '@/lib/today';

/*
 * The signed-in shell: the reader's own navigation and session, both asked of
 * the gateway (permissions arrive as data: a link the reader may not open is
 * not in the answer).
 */
export default async function ShellLayout({ children }: { children: ReactNode }) {
  const path = await currentPath();
  const [session, navigation] = await asReader((token) =>
    Promise.all([
      gatewayClient(IdentityService, token).getSession({}),
      gatewayClient(NavigationService, token)
        .getNavigation({})
        .catch((error: unknown) => {
          // The navigation is still the existing application's: a gateway with
          // nothing behind it has none, and the shell is drawn without links.
          if (isUnavailable(error)) return { sections: [], bottom: [] };
          throw error;
        }),
    ]),
  );
  const person = session.session;
  const account = {
    name: person?.name || person?.email || '',
    initials: initialsOf(person?.name ?? '', person?.email ?? ''),
    activeRole: person?.activeRole ?? '',
    roles: (person?.roles ?? []).map((role) => ({ value: role, label: role })),
    path,
  };
  const menu = (
    <>
      <SidebarBrand />
      <div className="mt-5">
        <SidebarNav sections={navigation.sections} path={path} />
      </div>
    </>
  );
  return (
    <div className="flex min-h-dvh">
      <Sidebar sections={navigation.sections} path={path} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar search={pageSearch(path)} account={account} menu={menu} existingWebUrl={environment().existingWebUrl} />
        <main id="main" className="min-w-0 flex-1 pb-24 lg:pb-0">
          {children}
        </main>
        <BottomNav items={navigation.bottom} path={path} more={<PhoneMenu asTab>{menu}</PhoneMenu>} />
      </div>
    </div>
  );
}
