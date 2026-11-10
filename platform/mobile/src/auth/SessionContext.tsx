/** The signed-in person, for every screen below the provider. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { ApiError } from '../api/connect';
import { createEdifyApi } from '../api/edifyApi';
import type { EdifyApi } from '../api/edifyApi';
import type { AppEnvironment } from '../config/environment';
import type { Session } from '../gen/edify/identity/v1/identity_pb';
import { refreshTokens, signIn as signInWithIdentity } from './identityClient';
import type { TokenStore } from './tokenStore';

export type SessionState =
  | { status: 'loading' }
  | { status: 'signedOut'; notice: string }
  | { status: 'signedIn'; session: Session };

interface SessionContextValue {
  readonly state: SessionState;
  readonly api: EdifyApi;
  /** The backends this build talks to (for links to the web app). */
  readonly environment: AppEnvironment;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
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
    if (!(await tokenStore.load())) {
      setState({ status: 'signedOut', notice: '' });
      return;
    }
    try {
      setState({ status: 'signedIn', session: await api.getSession() });
    } catch (error) {
      const expired = error instanceof ApiError && error.code === 'unauthenticated';
      if (expired) {
        await tokenStore.clear();
      }
      setState({
        status: 'signedOut',
        notice: expired ? 'Your session has expired. Please sign in again.' : describe(error),
      });
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

  const signOut = useCallback(async () => {
    await tokenStore.clear();
    setState({ status: 'signedOut', notice: '' });
  }, [tokenStore]);

  const value = useMemo(
    () => ({ state, api, environment, signIn, signOut }),
    [state, api, environment, signIn, signOut],
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
