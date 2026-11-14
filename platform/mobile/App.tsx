import { useCallback, useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Geist_400Regular, Geist_500Medium, Geist_600SemiBold, Geist_700Bold, Geist_700Bold_Italic, useFonts } from '@expo-google-fonts/geist';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { LOADING_HINT_AFTER_MS } from './src/auth/launch';
import { SessionProvider, useSession } from './src/auth/SessionContext';
import { secureTokenStore } from './src/auth/tokenStore';
import { EnvironmentError, loadEnvironment } from './src/config/environment';
import type { AppEnvironment } from './src/config/environment';
import type { Session } from './src/gen/edify/identity/v1/identity_pb';
import type { GetNavigationResponse } from './src/gen/edify/screens/v1/navigation_pb';
import { HomeScreen } from './src/screens/HomeScreen';
import { MenuScreen, WebOnlyScreen } from './src/screens/MoreScreen';
import { SchoolProfileScreen } from './src/screens/SchoolProfileScreen';
import { PageScreen } from './src/screens/PageScreen';
import { PAGE_PATHS } from './src/nativePages';
import { HOME_URL, landingUrl } from './src/landing';
import { SchoolsScreen } from './src/screens/SchoolsScreen';
import { NewPasswordScreen } from './src/screens/NewPasswordScreen';
import { UsersScreen } from './src/screens/admin/UsersScreen';
import { PartnerTeamScreen } from './src/screens/partner/PartnerTeamScreen';
import { ActingLeadershipScreen } from './src/screens/acting/ActingLeadershipScreen';
import { ACTING_URL, isWorkingAsActing } from './src/screens/acting/actingData';
import { SignInScreen } from './src/screens/SignInScreen';
import { ClusterLeaderApp } from './src/screens/cluster/ClusterLeaderApp';
import { ClusterLeadersScreen } from './src/screens/cluster/ClusterLeadersScreen';
import { LEADERS_URL, SUPPORT_URL, canManageLeaders, leadersSection } from './src/screens/cluster/clusterRoutes';
import { SupportRequestsScreen } from './src/screens/cluster/SupportRequestsScreen';
import { LoansRoute } from './src/screens/loans/LoansRoute';
import { isLoansUrl, loansSection } from './src/screens/loans/loanRoutes';
import { RouteFlow } from './src/screens/route/RouteFlow';
import { LocationReportsScreen } from './src/screens/route/LocationReportsScreen';
import { LOCATION_REPORTS_URL, isRouteUrl, routeSection } from './src/screens/route/routeData';
import { AppShell, MENU_URL } from './src/shell/AppShell';
import { ThemeProvider, signInPalette, spacing, useTheme } from './src/theme';
import { DropdownLayer } from './src/ui/Dropdown';
import { LaunchView } from './src/ui/LaunchView';

// The native launch screen stays up until the app knows what to open: fonts
// loaded and the saved sign-in confirmed (Root hides it). No timer keeps it
// longer than that.
void SplashScreen.preventAutoHideAsync().catch(() => undefined);
SplashScreen.setOptions({ duration: 200, fade: true });

type Startup = { ok: true; environment: AppEnvironment } | { ok: false; reason: string };

// Expo inlines EXPO_PUBLIC_* at build time, and only when each variable is
// read by its full name. The app validates them once, before anything renders.
function start(): Startup {
  try {
    return {
      ok: true,
      environment: loadEnvironment({
        EXPO_PUBLIC_EDIFY_ENV: process.env.EXPO_PUBLIC_EDIFY_ENV,
        EXPO_PUBLIC_EDIFY_GATEWAY_URL: process.env.EXPO_PUBLIC_EDIFY_GATEWAY_URL,
        EXPO_PUBLIC_EDIFY_IDENTITY_URL: process.env.EXPO_PUBLIC_EDIFY_IDENTITY_URL,
      }),
    };
  } catch (error) {
    const reason = error instanceof EnvironmentError ? error.message : 'The app could not start.';
    return { ok: false, reason };
  }
}

const startup = start();

/** The screens the app draws itself beside its pages. */
const OWN_SCREENS: readonly string[] = ['/home', '/schools'];
/** The existing role a Cluster Leader signs in with (apps/core/rbac.py). */
const CLUSTER_LEADER = 'ClusterLeader';

function pathOf(url: string): string {
  return url.split(/[?#]/)[0].replace(/\/+$/, '') || '/';
}

/** A school's profile: /schools/<record id>. */
const SCHOOL_PROFILE = /^\/schools\/([^/]+)$/;

function schoolOf(url: string): string | null {
  const match = SCHOOL_PROFILE.exec(pathOf(url));
  return match && match[1] !== 'closed' ? decodeURIComponent(match[1]) : null;
}

/** The query a route opened with, as a page's own parameters. */
function queryOf(url: string): Record<string, string> {
  const at = url.indexOf('?');
  return at < 0 ? {} : Object.fromEntries(new URLSearchParams(url.slice(at + 1)).entries());
}

/** The pages the app draws from their components: those the menu marks
 * (the feed's own list, for this reader), and the known ones until it loads. */
function pagesOf(navigation: GetNavigationResponse | null): ReadonlySet<string> {
  const items = [...(navigation?.bottom ?? []), ...(navigation?.sections ?? []).flatMap((section) => section.items)];
  return new Set([...PAGE_PATHS, ...items.filter((item) => item.native).map((item) => pathOf(item.url))]);
}

export default function App() {
  const [areFontsLoaded] = useFonts({ Geist_400Regular, Geist_500Medium, Geist_600SemiBold, Geist_700Bold, Geist_700Bold_Italic });
  useEffect(() => {
    if (!startup.ok) {
      void SplashScreen.hideAsync().catch(() => undefined);
    }
  }, []);

  if (!startup.ok) {
    return (
      <View style={styles.centered}>
        <Text style={styles.heading} accessibilityRole="header">
          This build is not configured
        </Text>
        <Text style={styles.body}>{startup.reason}</Text>
      </View>
    );
  }
  // The saved sign-in is checked while the fonts load, not after them: the
  // provider mounts at once and Root waits for both under the launch screen.
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <DropdownLayer>
          <SessionProvider environment={startup.environment} tokenStore={secureTokenStore}>
            {areFontsLoaded ? <Root /> : null}
          </SessionProvider>
        </DropdownLayer>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}

function hideLaunchScreen() {
  void SplashScreen.hideAsync().catch(() => undefined);
}

function Root() {
  const { state, retry, signOut } = useSession();
  // Hide the native launch screen once the app knows what to open; a slow
  // check hands over to the identical LaunchView, which then says so.
  useEffect(() => {
    if (state.status !== 'loading') {
      hideLaunchScreen();
    }
  }, [state.status]);
  useEffect(() => {
    const timer = setTimeout(hideLaunchScreen, LOADING_HINT_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);
  if (state.status === 'loading') {
    return (
      <>
        <LaunchView />
        <StatusBar style="light" />
      </>
    );
  }
  if (state.status === 'unreachable') {
    return (
      <>
        <LaunchView problem={state.notice} onRetry={() => void retry()} onSignOut={() => void signOut()} />
        <StatusBar style="light" />
      </>
    );
  }
  if (state.status === 'signedOut') {
    return (
      <>
        <SignInScreen notice={state.notice} />
        <StatusBar style="dark" />
      </>
    );
  }
  // A password an administrator chose is replaced before anything else.
  if (state.session.mustChangePassword) {
    return (
      <>
        <NewPasswordScreen />
        <StatusBar style="dark" />
      </>
    );
  }
  // A Cluster Leader's reach is their assigned clusters, not a web menu: the
  // portal of their own (brief A1-A3).
  if (state.session.activeRole === CLUSTER_LEADER) {
    return <ClusterLeaderApp session={state.session} />;
  }
  return <SignedIn session={state.session} />;
}

function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = [words[0]?.[0], words.length > 1 ? words[words.length - 1][0] : undefined];
  return letters.filter(Boolean).join('').toUpperCase() || '?';
}

interface Route {
  readonly url: string;
  readonly label: string;
}

const HOME: Route = { url: '/home', label: 'Home' };

/** The web's Users page; native for the Admin, who alone manages accounts. */
const USERS_URL = '/admin-panel/users';
const ADMIN = 'Admin';
/** The web's partner Team page; native for the Partner Admin, who runs the team. */
const PARTNER_TEAM_URL = '/partner/users';
const PARTNER_ADMIN = 'PartnerAdmin';

function SignedIn({ session }: { readonly session: Session }) {
  const { api } = useSession();
  const { isDark } = useTheme();
  const [route, setRoute] = useState<Route>(HOME);
  const [searchSignal, setSearchSignal] = useState(0);
  const [navigation, setNavigation] = useState<GetNavigationResponse | null>(null);
  // Entering or leaving an acting capacity keeps the role's name ("CCEO")
  // but changes the menu the existing application serves, so it counts too.
  const actingNow = isWorkingAsActing(session);

  useEffect(() => {
    let isCurrent = true;
    api
      .getNavigation()
      .then((answer) => {
        if (!isCurrent) {
          return;
        }
        setNavigation(answer);
        // Land where the web lands this role, unless the person has moved on.
        const landing = landingUrl(session.activeRole, answer);
        if (landing !== HOME_URL) {
          setRoute((current) => (current === HOME ? { url: landing, label: '' } : current));
        }
      })
      // Without its menu the app still shows Home; Home reports its own errors.
      .catch(() => undefined);
    return () => {
      isCurrent = false;
    };
  }, [api, session.activeRole, actingNow]);

  const pages = useMemo(() => pagesOf(navigation), [navigation]);
  // Every other path opens on the web.
  const isNative = useCallback(
    (url: string) =>
      url === LEADERS_URL ||
      url === SUPPORT_URL ||
      (pathOf(url) === USERS_URL && session.activeRole === ADMIN) ||
      (pathOf(url) === PARTNER_TEAM_URL && session.activeRole === PARTNER_ADMIN) ||
      pathOf(url) === ACTING_URL ||
      isLoansUrl(url) ||
      isRouteUrl(url) ||
      url === LOCATION_REPORTS_URL ||
      OWN_SCREENS.includes(pathOf(url)) ||
      pages.has(pathOf(url)) ||
      schoolOf(url) !== null,
    [pages, session.activeRole],
  );
  // Staff who manage cluster leaders find them under their own menu.
  const sections = useMemo(
    () => {
      const loans = loansSection(session.activeRole);
      const routes = routeSection(session.activeRole);
      return [
        ...(navigation?.sections ?? []),
        ...(routes ? [routes] : []),
        ...(canManageLeaders(session.activeRole) ? [leadersSection()] : []),
        ...(loans ? [loans] : []),
      ];
    },
    [navigation, session.activeRole],
  );
  const open = useCallback((url: string, label: string) => setRoute({ url, label }), []);
  const openPage = useCallback((url: string) => open(url, ''), [open]);
  // A school opened from a field route (or the location reports) goes back there (same day).
  const [schoolFrom, setSchoolFrom] = useState<Route | null>(null);
  const openSchool = useCallback(
    (schoolId: string) =>
      setRoute((current) => {
        setSchoolFrom(isRouteUrl(current.url) || current.url === LOCATION_REPORTS_URL ? current : null);
        return { url: `/schools/${encodeURIComponent(schoolId)}`, label: 'School' };
      }),
    [],
  );

  function handleSearch() {
    setRoute({ url: '/schools', label: 'Schools' });
    setSearchSignal((count) => count + 1);
  }

  const path = pathOf(route.url);
  let screen;
  if (route.url === MENU_URL) {
    screen = <MenuScreen session={session} sections={sections} isNative={isNative} onOpen={open} />;
  } else if (route.url === LEADERS_URL) {
    screen = <ClusterLeadersScreen />;
  } else if (route.url === SUPPORT_URL) {
    screen = <SupportRequestsScreen />;
  } else if (path === USERS_URL && session.activeRole === ADMIN) {
    screen = <UsersScreen />;
  } else if (path === PARTNER_TEAM_URL && session.activeRole === PARTNER_ADMIN) {
    screen = <PartnerTeamScreen />;
  } else if (path === ACTING_URL) {
    screen = <ActingLeadershipScreen />;
  } else if (isLoansUrl(route.url)) {
    screen = <LoansRoute key={route.url} url={route.url} />;
  } else if (route.url === LOCATION_REPORTS_URL) {
    screen = <LocationReportsScreen onOpenSchool={openSchool} />;
  } else if (isRouteUrl(route.url)) {
    // One element for both screens, so the day survives planner ↔ details.
    screen = <RouteFlow url={route.url} onOpen={open} onOpenSchool={openSchool} />;
  } else if (path === '/home') {
    screen = <HomeScreen onOpen={open} />;
  } else if (path === '/schools') {
    screen = <SchoolsScreen searchSignal={searchSignal} onOpenSchool={openSchool} />;
  } else if (pages.has(path)) {
    screen = (
      <PageScreen
        key={route.url}
        path={path}
        initialQuery={queryOf(route.url)}
        isNative={isNative}
        onOpen={openPage}
        onOpenSchool={openSchool}
      />
    );
  } else if (schoolOf(route.url)) {
    const schoolId = schoolOf(route.url) ?? '';
    screen = (
      <SchoolProfileScreen
        key={schoolId}
        schoolId={schoolId}
        onBack={() => (schoolFrom ? open(schoolFrom.url, schoolFrom.label) : open('/schools', 'Schools'))}
        backLabel={schoolFrom ? (schoolFrom.url === LOCATION_REPORTS_URL ? 'Back to reports' : 'Back to route') : undefined}
        onOpenRoute={(url) => open(url, url === LOCATION_REPORTS_URL ? 'Location Reports' : 'Smart Route Planner')}
        onOpenSchool={openSchool}
      />
    );
  } else {
    screen = <WebOnlyScreen title={route.label} webPath={route.url} />;
  }

  return (
    <AppShell
      bottom={navigation?.bottom ?? []}
      // A school's profile belongs to the Schools tab, as on the web.
      activeUrl={schoolOf(route.url) ? '/schools' : isRouteUrl(route.url) ? '/my-plan' : path}
      onOpen={open}
      initials={initialsOf(session.name)}
      onSearch={handleSearch}
    >
      {screen}
      <StatusBar style={isDark ? 'light' : 'dark'} />
    </AppShell>
  );
}

const styles = StyleSheet.create({
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
    backgroundColor: signInPalette.page,
  },
  heading: { fontSize: 20, fontWeight: '700', color: signInPalette.title, marginBottom: spacing.md },
  body: { fontSize: 16, color: signInPalette.subtitle, textAlign: 'center' },
});
