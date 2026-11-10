import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { Geist_400Regular, Geist_500Medium, Geist_600SemiBold, Geist_700Bold, useFonts } from '@expo-google-fonts/geist';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { SessionProvider, useSession } from './src/auth/SessionContext';
import { secureTokenStore } from './src/auth/tokenStore';
import { EnvironmentError, loadEnvironment } from './src/config/environment';
import type { AppEnvironment } from './src/config/environment';
import type { Session } from './src/gen/edify/identity/v1/identity_pb';
import type { GetNavigationResponse } from './src/gen/edify/screens/v1/navigation_pb';
import { HomeScreen } from './src/screens/HomeScreen';
import { MenuScreen, WebOnlyScreen } from './src/screens/MoreScreen';
import { SchoolProfileScreen } from './src/screens/SchoolProfileScreen';
import { MyPlanScreen } from './src/screens/MyPlanScreen';
import { SchoolsScreen } from './src/screens/SchoolsScreen';
import { SignInScreen } from './src/screens/SignInScreen';
import { AppShell, MENU_URL } from './src/shell/AppShell';
import { ThemeProvider, signInPalette, spacing, useTheme } from './src/theme';
import { DropdownLayer } from './src/ui/Dropdown';

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

/** The paths this app draws itself. Every other path opens on the web. */
const NATIVE_PATHS: readonly string[] = ['/home', '/schools', '/my-plan'];

function pathOf(url: string): string {
  return url.split(/[?#]/)[0].replace(/\/+$/, '') || '/';
}

/** A school's profile: /schools/<record id>. */
const SCHOOL_PROFILE = /^\/schools\/([^/]+)$/;

function schoolOf(url: string): string | null {
  const match = SCHOOL_PROFILE.exec(pathOf(url));
  return match && match[1] !== 'closed' ? decodeURIComponent(match[1]) : null;
}

function isNative(url: string): boolean {
  return NATIVE_PATHS.includes(pathOf(url)) || schoolOf(url) !== null;
}

export default function App() {
  const [areFontsLoaded] = useFonts({ Geist_400Regular, Geist_500Medium, Geist_600SemiBold, Geist_700Bold });

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
  if (!areFontsLoaded) {
    return <Loading />;
  }
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <DropdownLayer>
          <SessionProvider environment={startup.environment} tokenStore={secureTokenStore}>
            <Root />
          </SessionProvider>
        </DropdownLayer>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}

function Loading() {
  return (
    <View style={styles.centered}>
      <ActivityIndicator color={signInPalette.link} accessibilityLabel="Loading" />
    </View>
  );
}

function Root() {
  const { state } = useSession();
  if (state.status === 'loading') {
    return <Loading />;
  }
  if (state.status === 'signedOut') {
    return (
      <>
        <SignInScreen notice={state.notice} />
        <StatusBar style="dark" />
      </>
    );
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

function SignedIn({ session }: { readonly session: Session }) {
  const { api } = useSession();
  const { isDark } = useTheme();
  const [route, setRoute] = useState<Route>(HOME);
  const [searchSignal, setSearchSignal] = useState(0);
  const [navigation, setNavigation] = useState<GetNavigationResponse | null>(null);

  useEffect(() => {
    let isCurrent = true;
    api
      .getNavigation()
      .then((answer) => (isCurrent ? setNavigation(answer) : undefined))
      // Without its menu the app still shows Home; Home reports its own errors.
      .catch(() => undefined);
    return () => {
      isCurrent = false;
    };
  }, [api]);

  const open = useCallback((url: string, label: string) => setRoute({ url, label }), []);
  const openSchool = useCallback(
    (schoolId: string) => setRoute({ url: `/schools/${encodeURIComponent(schoolId)}`, label: 'School' }),
    [],
  );

  function handleSearch() {
    setRoute({ url: '/schools', label: 'Schools' });
    setSearchSignal((count) => count + 1);
  }

  const path = pathOf(route.url);
  let screen;
  if (route.url === MENU_URL) {
    screen = (
      <MenuScreen session={session} sections={navigation?.sections ?? []} isNative={isNative} onOpen={open} />
    );
  } else if (path === '/home') {
    screen = <HomeScreen onOpen={open} />;
  } else if (path === '/schools') {
    screen = <SchoolsScreen searchSignal={searchSignal} onOpenSchool={openSchool} />;
  } else if (path === '/my-plan') {
    screen = <MyPlanScreen onOpenSchool={openSchool} />;
  } else if (schoolOf(route.url)) {
    const schoolId = schoolOf(route.url) ?? '';
    screen = (
      <SchoolProfileScreen
        key={schoolId}
        schoolId={schoolId}
        onBack={() => open('/schools', 'Schools')}
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
      activeUrl={schoolOf(route.url) ? '/schools' : route.url}
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
