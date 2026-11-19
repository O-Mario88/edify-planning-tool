import type { ReactNode } from 'react';

import { IdentityService } from '@/gen/edify/identity/v1/identity_pb';
import { MessagingService } from '@/gen/edify/messaging/v1/messaging_pb';
import { NotificationCenterService } from '@/gen/edify/screens/v1/notification_center_pb';
import { NavigationService } from '@/gen/edify/screens/v1/navigation_pb';
import { SidebarBrand, SidebarNav, Sidebar } from '@/components/shell/Sidebar';
import { BottomNav } from '@/components/shell/BottomNav';
import { TopBar } from '@/components/shell/TopBar';
import { PhoneMenu } from '@/components/shell/TopBarControls';
import { ViewportSync } from '@/components/shell/ViewportSync';
import { asReader, currentPath } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { gatewayClient, isUnavailable } from '@/lib/gateway';
import { pageSearch } from '@/lib/pageSearch';
import { requestView } from '@/lib/requestView';
import { initialsOf } from '@/lib/today';

/*
 * The signed-in shell: the reader's own navigation and session, both asked of
 * the gateway (permissions arrive as data: a link the reader may not open is
 * not in the answer).
 */
export default async function ShellLayout({ children }: { children: ReactNode }) {
  const path = await currentPath();
  const view = await requestView();
  const [session, navigation, messages, notifications] = await asReader((token) =>
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
      // The top bar's badges, as the existing shell's: a count it cannot
      // read draws no badge rather than failing the page (sidebar_counts).
      gatewayClient(MessagingService, token)
        .getUnreadCount({})
        .then((answer) => answer.unread, () => 0),
      gatewayClient(NotificationCenterService, token)
        .getUnreadNotificationCount({})
        .then((answer) => answer.unread, () => 0),
    ]),
  );
  const person = session.session;
  const account = {
    name: person?.name || person?.email || '',
    email: person?.email ?? '',
    initials: initialsOf(person?.name ?? '', person?.email ?? ''),
    activeRole: person?.activeRole ?? '',
    roles: (person?.roles ?? []).map((role) => ({ value: role, label: role })),
    path,
  };
  const menu = (
    <>
      <SidebarBrand />
      <div className="app-sidebar__nav-container">
        <SidebarNav sections={navigation.sections} path={path} />
      </div>
    </>
  );
  // The existing shell's frame (templates/layouts/shell.html): the sidebar
  // beside one column of the top bar over the scrolling workspace.
  return (
    <div className="edify-shell h-full flex overflow-hidden">
      <Sidebar sections={navigation.sections} path={path} />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <TopBar search={pageSearch(path)} account={account} menu={menu} existingWebUrl={environment().existingWebUrl} counts={{ messages, notifications }} />
        <main id="main-content" tabIndex={-1} className="edify-workspace flex-1 overflow-y-auto focus:outline-none relative bg-[var(--edify-bg)]" data-density="compact">
          {children}
        </main>
        <BottomNav items={navigation.bottom} path={path} more={<PhoneMenu asTab>{menu}</PhoneMenu>} />
        <ViewportSync served={view} />
      </div>
    </div>
  );
}
