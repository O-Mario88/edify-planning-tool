/** The signed-in person, for every screen below the provider. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Dimensions, Platform } from 'react-native';

import { createEdifyApi } from '../api/edifyApi';
import type { EdifyApi } from '../api/edifyApi';
import type { ConnectTransport } from '../api/connect';
import { AccountService } from '../gen/edify/identity/v1/accounts_pb';
import type { AppEnvironment } from '../config/environment';
import {
  appDevice,
  publicTransport,
  refreshTokens,
  revokeSession,
  signIn as signInThroughGateway,
  verifySignInCode,
} from './identityClient';
import type { CodeChallenge } from './identityClient';
import { KEYSTORE_UNREADABLE, afterFailedCheck, type SessionState } from './launch';
import type { TokenStore } from './tokenStore';

export type { SessionState } from './launch';

interface SessionContextValue {
  readonly state: SessionState;
  readonly api: EdifyApi;
  /** The backends this build talks to (for links to the web app). */
  readonly environment: AppEnvironment;
  /** The gateway without a session, for the sign-in screen's own calls. */
  readonly signInTransport: ConnectTransport;
  /** Signs in, or returns the code the account needs entered first. */
  signIn(email: string, password: string): Promise<CodeChallenge | null>;
  /** Finishes a sign-in that stopped for its code. */
  verifyCode(challenge: CodeChallenge, code: string): Promise<void>;
  /** Work in another role the account holds; the screens follow. */
  switchRole(role: string): Promise<void>;
  /** Replaces a password an administrator chose. */
  setNewPassword(password: string, confirm: string): Promise<void>;
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

  // Sign-in, refresh and sign-out go to the gateway, which owns signing in.
  const signInTransport = useMemo(() => {
    const screen = Dimensions.get('screen');
    const device = appDevice(Platform.OS, Platform.OS === 'ios' && Platform.isPad, screen.width, screen.height);
    return publicTransport(environment.gatewayUrl, (url, init) => fetch(url, init), device);
  }, [environment.gatewayUrl]);

  // One refresh at a time: refresh tokens rotate, and the whole session is
  // revoked if one is presented twice.
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
        const next = await refreshTokens(signInTransport, stored.refreshToken);
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
  }, [signInTransport, tokenStore]);

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
    async (email: string, password: string): Promise<CodeChallenge | null> => {
      const result = await signInThroughGateway(signInTransport, email, password);
      if (result.kind === 'code') {
        return result.challenge;
      }
      await tokenStore.save(result.tokens);
      await loadSession();
      return null;
    },
    [signInTransport, loadSession, tokenStore],
  );

  const verifyCode = useCallback(
    async (challenge: CodeChallenge, code: string) => {
      await tokenStore.save(await verifySignInCode(signInTransport, challenge, code));
      await loadSession();
    },
    [signInTransport, loadSession, tokenStore],
  );

  const switchRole = useCallback(
    async (role: string) => {
      const answer = await api.call(AccountService.method.switchRole, { role });
      const stored = await tokenStore.load();
      if (!stored || !answer.accessToken) {
        throw new Error('The role could not be switched.');
      }
      // The refresh token stays: the account itself now opens in this role.
      await tokenStore.save({ accessToken: answer.accessToken, refreshToken: stored.refreshToken });
      await loadSession();
    },
    [api, loadSession, tokenStore],
  );

  const setNewPassword = useCallback(
    async (password: string, confirm: string) => {
      await api.call(AccountService.method.setNewPassword, { password, confirm });
      await loadSession();
    },
    [api, loadSession],
  );

  // Signing out forgets the tokens on this phone at once and ends the session
  // on the server too, so the refresh token cannot be used again.
  const signOut = useCallback(async () => {
    const stored = await tokenStore.load();
    await tokenStore.clear();
    setState({ status: 'signedOut', notice: '' });
    if (stored) {
      void revokeSession(signInTransport, stored.refreshToken);
    }
  }, [signInTransport, tokenStore]);

  const retry = useCallback(async () => {
    setState({ status: 'loading' });
    await loadSession();
  }, [loadSession]);

  const value = useMemo(
    () => ({ state, api, environment, signInTransport, signIn, verifyCode, switchRole, setNewPassword, signOut, retry }),
    [state, api, environment, signInTransport, signIn, verifyCode, switchRole, setNewPassword, signOut, retry],
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
