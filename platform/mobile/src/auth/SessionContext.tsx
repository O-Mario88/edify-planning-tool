/** The signed-in person, for every screen below the provider. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { createEdifyApi } from '../api/edifyApi';
import type { EdifyApi } from '../api/edifyApi';
import type { AppEnvironment } from '../config/environment';
import { refreshTokens, revokeSession, signIn as signInWithIdentity } from './identityClient';
import { KEYSTORE_UNREADABLE, afterFailedCheck, type SessionState } from './launch';
import type { TokenStore } from './tokenStore';

export type { SessionState } from './launch';

interface SessionContextValue {
  readonly state: SessionState;
  readonly api: EdifyApi;
  /** The backends this build talks to (for links to the web app). */
  readonly environment: AppEnvironment;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  /** Ask the server again about a saved sign-in it could not be reached for. */
  retry(): Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

interface ProviderProps {
  readonly environment: AppEnvironment;
  readonly tokenStore: TokenStore;
  readonly children: ReactNode;
}

export function SessionProvider({ environment, tokenStore, children }: ProviderProps) {
  const [state, setState] = useState<SessionState>({ status: 'loading' });

  // One refresh at a time: the identity system rotates refresh tokens and
  // revokes the whole session if one is presented twice.
  const refreshing = useRef<Promise<boolean> | null>(null);

  const refresh = useCallback((): Promise<boolean> => {
    if (refreshing.current) {
      return refreshing.current;
    }
    const attempt = (async () => {
      const stored = await tokenStore.load();
      if (!stored) {
        return false;
      }
      try {
        const next = await refreshTokens(
          environment.identityUrl,
          (url, init) => fetch(url, init),
          stored.refreshToken,
        );
        if (!next) {
          await tokenStore.clear();
          return false;
        }
        await tokenStore.save(next);
        return true;
      } catch {
        // Offline: keep the session; the call that asked reports the failure.
        return false;
      }
    })().finally(() => {
      refreshing.current = null;
    });
    refreshing.current = attempt;
    return attempt;
  }, [environment.identityUrl, tokenStore]);

  const api = useMemo(
    () =>
      createEdifyApi({
        baseUrl: environment.gatewayUrl,
        fetch: (url, init) => fetch(url, init),
        getAccessToken: async () => (await tokenStore.load())?.accessToken ?? null,
        refresh,
      }),
    [environment.gatewayUrl, tokenStore, refresh],
  );

  const loadSession = useCallback(async () => {
    // The phone's keystore can refuse to answer (a broken install, a locked
    // device policy). Startup must still reach Sign in rather than wait on it.
    const stored = await tokenStore.load().catch(() => undefined);
    if (stored === undefined) {
      setState({ status: 'signedOut', notice: KEYSTORE_UNREADABLE });
      return;
    }
    if (!stored) {
      setState({ status: 'signedOut', notice: '' });
      return;
    }
    try {
      setState({ status: 'signedIn', session: await api.getSession() });
    } catch (error) {
      const next = afterFailedCheck(error);
      if (next.shouldClear) {
        await tokenStore.clear().catch(() => undefined);
      }
      setState(next.state);
    }
  }, [api, tokenStore]);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const tokens = await signInWithIdentity(
        environment.identityUrl,
        (url, init) => fetch(url, init),
        email,
        password,
      );
      await tokenStore.save(tokens);
      await loadSession();
    },
    [environment.identityUrl, loadSession, tokenStore],
  );

  // Signing out forgets the tokens on this phone at once and ends the session
  // on the server too, so the refresh token cannot be used again.
  const signOut = useCallback(async () => {
    const stored = await tokenStore.load();
    await tokenStore.clear();
    setState({ status: 'signedOut', notice: '' });
    if (stored) {
      void revokeSession(environment.identityUrl, (url, init) => fetch(url, init), stored.refreshToken);
    }
  }, [environment.identityUrl, tokenStore]);

  const retry = useCallback(async () => {
    setState({ status: 'loading' });
    await loadSession();
  }, [loadSession]);

  const value = useMemo(
    () => ({ state, api, environment, signIn, signOut, retry }),
    [state, api, environment, signIn, signOut, retry],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error('useSession must be used inside SessionProvider');
  }
  return value;
}

export function describe(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.';
}
