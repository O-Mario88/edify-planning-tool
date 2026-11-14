/**
 * The app's offline field work (offline capture brief, 2026-11-14): the
 * encrypted store, the connection, the Pending Sync count, saving a capture
 * and syncing the queue. Syncing starts when the app opens, when the
 * connection comes back, when the app returns to the foreground, after
 * every capture and once a minute while something waits. Nothing is
 * promised while the app is closed: the queue waits for the next of those.
 *
 * The phone's schools belong to one account at a time: the one whose
 * sign-in is saved. Another account's schools are forgotten when someone
 * else signs in; captures are never dropped, only sent with their own
 * account's sign-in.
 */
import { base64Decode } from '@bufbuild/protobuf/wire';
import * as Crypto from 'expo-crypto';
import * as Network from 'expo-network';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { AppState } from 'react-native';

import type { EdifyApi } from '../api/edifyApi';
import { ApiError } from '../api/connect';
import { secureTokenStore } from '../auth/tokenStore';
import { RoutePlannerService } from '../gen/edify/routes/v1/routes_pb';
import { DEFAULT_POLICY } from './gpsMath';
import type { GpsPolicy } from './gpsMath';
import { COUNTED } from './queueLogic';
import { openSqliteStore } from './sqliteStore';
import type { CachedSchool, CaptureKind, CaptureTarget, OfflineStore, QueuedCapture } from './store';

/** A capture sheet to show: drawn at the app's root so a screen re-rendering beneath never closes it. */
export interface CaptureRequest {
  readonly school: CachedSchool;
  readonly target: CaptureTarget;
  readonly onDone?: (saved: QueuedCapture | null) => void;
}
import { META } from './store';
import { syncQueue } from './sync';
import type { CaptureApi, SyncResult } from './sync';

/** The pack is fetched again when older than this. */
const PACK_MAX_AGE_MS = 12 * 60 * 60 * 1000;
/** While captures wait and the app is open, try this often. */
const SYNC_EVERY_MS = 60_000;
/** After a capture, the screen waits at most this long for the server's answer. */
const SAVE_WAIT_MS = 8_000;

export interface NewCapture {
  readonly school: CachedSchool;
  readonly target: CaptureTarget;
  readonly kind: CaptureKind;
  readonly pointSource: 'none' | 'typed' | 'device';
  readonly lat: number | null;
  readonly lng: number | null;
  readonly accuracyM: number;
  readonly capturedAt: number | null;
  readonly sampleCount: number;
  readonly spreadM: number;
  readonly reason: string;
  readonly accessNote: string;
}

interface Account {
  readonly userId: string;
  readonly name: string;
  readonly role: string;
}

interface OfflineValue {
  /** The store is open (false on its first moments, or when it failed). */
  readonly isReady: boolean;
  /** Why the phone's offline store could not be opened, if it could not. */
  readonly storeError: string;
  readonly isOnline: boolean;
  /** Signed in now (false in offline field mode). */
  readonly isSignedIn: boolean;
  readonly account: Account | null;
  readonly pendingCount: number;
  readonly packAt: string;
  readonly policy: GpsPolicy;
  readonly canCapture: boolean;
  readonly lastSync: SyncResult | null;
  /** Bumped whenever the store changes, so screens read it again. */
  readonly revision: number;
  readonly store: OfflineStore | null;
  /** Saves a capture on the phone first, then tries to sync it. */
  saveCapture(capture: NewCapture): Promise<QueuedCapture>;
  syncNow(): Promise<void>;
  refreshPack(): Promise<string>;
  markChanged(): void;
  /** The capture sheet open now, if any (CaptureHost draws it). */
  readonly captureRequest: CaptureRequest | null;
  openCapture(request: CaptureRequest): void;
  closeCapture(saved: QueuedCapture | null): void;
}

const OfflineContext = createContext<OfflineValue | null>(null);

/** The account a saved access token belongs to (its subject), without checking it. */
async function savedAccountId(): Promise<string> {
  try {
    const tokens = await secureTokenStore.load();
    const payload = tokens?.accessToken.split('.')[1];
    if (!payload) return '';
    // The claims are ASCII JSON; no TextDecoder needed on Hermes.
    const json = String.fromCharCode(...base64Decode(payload));
    const parsed: unknown = JSON.parse(json);
    return typeof parsed === 'object' && parsed !== null && typeof (parsed as { sub?: unknown }).sub === 'string' ? (parsed as { sub: string }).sub : '';
  } catch {
    return '';
  }
}

function captureApi(api: EdifyApi): CaptureApi {
  return {
    async submit(c) {
      const answer = await api.call(RoutePlannerService.method.submitLocationCapture, {
        captureId: c.id,
        schoolId: c.schoolId,
        target: c.target,
        kind: c.kind,
        point: c.lat !== null && c.lng !== null ? { lat: c.lat, lng: c.lng } : undefined,
        pointSource: c.pointSource,
        accuracyM: c.accuracyM,
        capturedAt: c.capturedAt ? new Date(c.capturedAt).toISOString().replace(/\.\d{3}Z$/, 'Z') : '',
        sampleCount: c.sampleCount,
        spreadM: c.spreadM,
        baseVersion: c.baseVersion,
        reason: c.reason,
        accessNote: c.accessNote,
      });
      return { outcome: answer.outcome, flags: answer.capture?.flags ?? [], resultVersion: answer.capture?.resultVersion ?? 0, message: answer.message };
    },
    async changes(since) {
      const answer = await api.call(RoutePlannerService.method.listLocationChanges, { since });
      return {
        now: answer.now,
        changes: answer.changes
          .filter((c) => c.point)
          .map((c) => ({ schoolId: c.schoolId, target: c.target === 'entrance' ? 'entrance' : 'school', version: c.version, lat: c.point!.lat, lng: c.point!.lng, changedAt: c.changedAt })),
      };
    },
  };
}

export interface OfflineProviderProps {
  /** The signed-in account, or null (signed out, or offline field mode). */
  readonly signedIn: Account | null;
  readonly api: EdifyApi;
  /** The app could not reach Edify with a saved sign-in. */
  readonly isUnreachable: boolean;
  /** Called when the connection comes back while unreachable. */
  readonly onReconnect: () => void;
  readonly children: ReactNode;
}

export function OfflineProvider({ signedIn, api, isUnreachable, onReconnect, children }: OfflineProviderProps) {
  const [store, setStore] = useState<OfflineStore | null>(null);
  const [storeError, setStoreError] = useState('');
  const [isOnline, setIsOnline] = useState(true);
  const [account, setAccount] = useState<Account | null>(null);
  const [pendingCount, setPendingCount] = useState(0);
  const [packAt, setPackAt] = useState('');
  const [policy, setPolicy] = useState<GpsPolicy>(DEFAULT_POLICY);
  const [canCapture, setCanCapture] = useState(false);
  const [lastSync, setLastSync] = useState<SyncResult | null>(null);
  const [revision, setRevision] = useState(0);
  const [captureRequest, setCaptureRequest] = useState<CaptureRequest | null>(null);
  const openRequest = useRef<CaptureRequest | null>(null);
  const openCapture = useCallback((request: CaptureRequest) => {
    openRequest.current = request;
    setCaptureRequest(request);
  }, []);
  const closeCapture = useCallback((saved: QueuedCapture | null) => {
    const done = openRequest.current?.onDone;
    openRequest.current = null;
    setCaptureRequest(null);
    done?.(saved);
  }, []);
  const markChanged = useCallback(() => setRevision((n) => n + 1), []);
  const reconnect = useRef(onReconnect);
  reconnect.current = onReconnect;

  // Open the encrypted store once; a crash mid-send leaves nothing half done.
  useEffect(() => {
    let isCurrent = true;
    openSqliteStore()
      .then(async (opened) => {
        await opened.recoverSyncing();
        if (isCurrent) setStore(opened);
      })
      .catch(() => {
        if (isCurrent) setStoreError('This phone’s offline store could not be opened, so captures cannot be saved offline. Restart the app and try again.');
      });
    return () => {
      isCurrent = false;
    };
  }, []);

  // Whose phone this is: the signed-in account, or, offline, the saved
  // sign-in's account when the phone holds its schools.
  useEffect(() => {
    if (!store) return;
    let isCurrent = true;
    void (async () => {
      if (signedIn) {
        const owner = await store.meta(META.owner);
        if (owner !== signedIn.userId) {
          await store.forgetOthers(signedIn.userId);
          await store.setMeta(META.packAt, '');
          await store.setMeta(META.changesSince, '');
        }
        await store.setMeta(META.owner, signedIn.userId);
        await store.setMeta(META.ownerName, signedIn.name);
        await store.setMeta(META.ownerRole, signedIn.role);
        if (isCurrent) setAccount(signedIn);
        return;
      }
      const [owner, saved] = await Promise.all([store.meta(META.owner), savedAccountId()]);
      if (!isCurrent) return;
      if (isUnreachable && owner && owner === saved) {
        setAccount({ userId: owner, name: (await store.meta(META.ownerName)) ?? '', role: (await store.meta(META.ownerRole)) ?? '' });
      } else {
        setAccount(null);
      }
    })();
    return () => {
      isCurrent = false;
    };
  }, [store, signedIn, isUnreachable]);

  // The counts and pack facts, read again whenever the store changes.
  useEffect(() => {
    if (!store || !account) return;
    let isCurrent = true;
    void (async () => {
      const mine = await store.captures(account.userId);
      const [at, savedPolicy, capture] = await Promise.all([store.meta(META.packAt), store.meta(META.policy), store.meta(META.canCapture)]);
      if (!isCurrent) return;
      setPendingCount(mine.filter((c) => COUNTED.includes(c.status)).length);
      setPackAt(at ?? '');
      setCanCapture(capture === 'true');
      if (savedPolicy) {
        try {
          const parsed = JSON.parse(savedPolicy) as GpsPolicy;
          if (parsed.goodM > 0 && parsed.confirmM >= parsed.goodM) setPolicy(parsed);
        } catch {
          // The default policy stands.
        }
      }
    })();
    return () => {
      isCurrent = false;
    };
  }, [store, account, revision]);

  const isSignedIn = signedIn !== null;
  const syncApi = useMemo(() => captureApi(api), [api]);

  const syncNow = useCallback(async () => {
    if (!store || !signedIn) return;
    const result = await syncQueue(syncApi, store, signedIn.userId);
    setLastSync(result);
    markChanged();
  }, [store, signedIn, syncApi, markChanged]);

  const refreshPack = useCallback(async (): Promise<string> => {
    if (!store || !signedIn) return 'Connect to the internet to update your schools.';
    try {
      const pack = await api.call(RoutePlannerService.method.getOfflinePack, { days: 14 });
      const schools: CachedSchool[] = pack.schools
        .filter((o) => o.school)
        .map((o) => {
          const s = o.school!;
          return {
            schoolId: s.schoolId,
            code: s.code,
            name: s.name,
            district: s.district,
            cluster: s.cluster,
            category: s.category,
            locationStatus: s.locationStatus,
            lat: s.point?.lat ?? null,
            lng: s.point?.lng ?? null,
            version: s.locationVersion,
            entranceLat: s.entrance?.lat ?? null,
            entranceLng: s.entrance?.lng ?? null,
            verifiedAt: o.verifiedAt,
            accessNote: o.accessNote,
            hasPending: o.hasPending,
            lastConfirmedAt: o.lastConfirmedAt,
          };
        });
      await store.replacePack(
        signedIn.userId,
        schools,
        pack.planned.map((p) => ({ date: p.date, schoolId: p.schoolId, activityId: p.activityId })),
      );
      await store.setMeta(META.packAt, pack.generatedAt);
      await store.setMeta(META.canCapture, String(pack.canCapture));
      if (pack.policy) await store.setMeta(META.policy, JSON.stringify({ goodM: pack.policy.goodM, confirmM: pack.policy.confirmM }));
      // The pack is newer than any change feed so far.
      await store.setMeta(META.changesSince, pack.generatedAt);
      markChanged();
      return `${schools.length} schools saved for offline work.`;
    } catch (cause) {
      return cause instanceof ApiError ? cause.message : 'Your schools could not be saved for offline work. Please try again.';
    }
  }, [store, signedIn, api, markChanged]);

  // Signed in: fetch the pack when it is old, then send what waits.
  useEffect(() => {
    if (!store || !signedIn || account?.userId !== signedIn.userId) return;
    void (async () => {
      const at = await store.meta(META.packAt);
      if (!at || Date.now() - Date.parse(at) > PACK_MAX_AGE_MS) await refreshPack();
      await syncNow();
    })();
  }, [store, signedIn, account, refreshPack, syncNow]);

  // The connection: back online, send (or, offline field mode, sign back in).
  const wasOnline = useRef(true);
  useEffect(() => {
    const apply = (state: Network.NetworkState) => {
      const online = state.isConnected !== false && state.isInternetReachable !== false;
      const cameBack = online && !wasOnline.current;
      wasOnline.current = online;
      setIsOnline(online);
      if (!cameBack) return;
      if (isUnreachable) reconnect.current();
      else void syncNow();
    };
    void Network.getNetworkStateAsync().then(apply).catch(() => undefined);
    const subscription = Network.addNetworkStateListener(apply);
    return () => subscription.remove();
  }, [isUnreachable, syncNow]);

  // Back in the foreground: try again.
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (next) => {
      if (next !== 'active') return;
      if (isUnreachable) reconnect.current();
      else void syncNow();
    });
    return () => subscription.remove();
  }, [isUnreachable, syncNow]);

  // While something waits and the app is open, try once a minute.
  useEffect(() => {
    if (pendingCount === 0 || !isSignedIn) return;
    const timer = setInterval(() => void syncNow(), SYNC_EVERY_MS);
    return () => clearInterval(timer);
  }, [pendingCount, isSignedIn, syncNow]);

  const saveCapture = useCallback(
    async (input: NewCapture): Promise<QueuedCapture> => {
      if (!store || !account) throw new Error('The phone’s offline store is not open yet. Please try again.');
      const now = Date.now();
      const capture: QueuedCapture = {
        id: Crypto.randomUUID(),
        userId: account.userId,
        schoolId: input.school.schoolId,
        schoolName: input.school.name,
        target: input.target,
        kind: input.kind,
        pointSource: input.pointSource,
        lat: input.lat,
        lng: input.lng,
        accuracyM: input.accuracyM,
        capturedAt: input.capturedAt,
        sampleCount: input.sampleCount,
        spreadM: input.spreadM,
        baseVersion: input.target === 'entrance' ? (input.school.entranceLat !== null ? 1 : 0) : input.school.version,
        prevLat: input.target === 'entrance' ? input.school.entranceLat : input.school.lat,
        prevLng: input.target === 'entrance' ? input.school.entranceLng : input.school.lng,
        reason: input.reason,
        accessNote: input.accessNote,
        status: 'saved_offline',
        attempts: 0,
        nextTryAt: 0,
        note: 'Saved on this phone. It will sync when there is a connection.',
        flags: [],
        resultVersion: 0,
        createdAt: now,
        updatedAt: now,
      };
      await store.addCapture(capture);
      markChanged();
      if (isSignedIn && isOnline) {
        // Saved on the phone already; wait a little for the server's word, never long.
        await Promise.race([syncNow(), new Promise((resolve) => setTimeout(resolve, SAVE_WAIT_MS))]);
        return (await store.captures(account.userId)).find((c) => c.id === capture.id) ?? capture;
      }
      return capture;
    },
    [store, account, isSignedIn, isOnline, syncNow, markChanged],
  );

  const value = useMemo<OfflineValue>(
    () => ({
      isReady: store !== null,
      storeError,
      isOnline,
      isSignedIn,
      account,
      pendingCount,
      packAt,
      policy,
      canCapture,
      lastSync,
      revision,
      store,
      saveCapture,
      syncNow,
      refreshPack,
      markChanged,
      captureRequest,
      openCapture,
      closeCapture,
    }),
    [captureRequest, openCapture, closeCapture, store, storeError, isOnline, isSignedIn, account, pendingCount, packAt, policy, canCapture, lastSync, revision, saveCapture, syncNow, refreshPack, markChanged],
  );
  return <OfflineContext.Provider value={value}>{children}</OfflineContext.Provider>;
}

export function useOffline(): OfflineValue {
  const value = useContext(OfflineContext);
  if (!value) throw new Error('useOffline must be used inside OfflineProvider');
  return value;
}

/** Today in Kampala, "YYYY-MM-DD" (the phone's own calendar day). */
export function todayLocal(now: Date = new Date()): string {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}
