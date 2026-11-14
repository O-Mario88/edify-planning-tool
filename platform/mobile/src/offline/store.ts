/**
 * What the phone keeps for field work without a connection (offline
 * capture brief, 2026-11-14, parts 4 and 5): the least of each assigned
 * school the capture screen needs, the planned visits, and the queue of
 * captures waiting to sync. The native store is SQLite encrypted with
 * SQLCipher (sqliteStore.ts); the web build and the tests use memory.
 */
import type { QueueStatus } from './queueLogic';

export interface CachedSchool {
  readonly schoolId: string;
  readonly code: string;
  readonly name: string;
  readonly district: string;
  readonly cluster: string;
  readonly category: string;
  /** verified, recorded, missing or invalid. */
  readonly locationStatus: string;
  readonly lat: number | null;
  readonly lng: number | null;
  readonly version: number;
  readonly entranceLat: number | null;
  readonly entranceLng: number | null;
  readonly verifiedAt: string;
  readonly accessNote: string;
  readonly hasPending: boolean;
  readonly lastConfirmedAt: string;
}

export interface PlannedVisit {
  readonly date: string;
  readonly schoolId: string;
  readonly activityId: string;
}

export type CaptureTarget = 'school' | 'entrance';
export type CaptureKind = 'new' | 'correction' | 'confirm';

export interface QueuedCapture {
  /** The capture id (a UUID): the server's idempotency key. */
  readonly id: string;
  readonly userId: string;
  readonly schoolId: string;
  readonly schoolName: string;
  readonly target: CaptureTarget;
  readonly kind: CaptureKind;
  readonly pointSource: 'none' | 'typed' | 'device';
  readonly lat: number | null;
  readonly lng: number | null;
  readonly accuracyM: number;
  /** When the phone took the fix (ms since the epoch), or null. */
  readonly capturedAt: number | null;
  readonly sampleCount: number;
  readonly spreadM: number;
  readonly baseVersion: number;
  readonly prevLat: number | null;
  readonly prevLng: number | null;
  readonly reason: string;
  readonly accessNote: string;
  readonly status: QueueStatus;
  readonly attempts: number;
  /** Not to be sent again before this (ms since the epoch). */
  readonly nextTryAt: number;
  /** The last word on it, for the person. */
  readonly note: string;
  readonly flags: readonly string[];
  readonly resultVersion: number;
  readonly createdAt: number;
  readonly updatedAt: number;
}

export type CapturePatch = Partial<Pick<QueuedCapture, 'status' | 'attempts' | 'nextTryAt' | 'note' | 'flags' | 'resultVersion'>>;

/** An accepted location change, as the server's feed gives it. */
export interface SchoolChange {
  readonly schoolId: string;
  readonly target: CaptureTarget;
  readonly version: number;
  readonly lat: number;
  readonly lng: number;
  readonly changedAt: string;
}

export interface OfflineStore {
  meta(key: string): Promise<string | null>;
  setMeta(key: string, value: string): Promise<void>;
  /** Replaces the user's schools and planned visits in one transaction. */
  replacePack(userId: string, schools: readonly CachedSchool[], planned: readonly PlannedVisit[]): Promise<void>;
  /** Forgets every other account's schools and visits (never their queued captures). */
  forgetOthers(userId: string): Promise<void>;
  schools(userId: string): Promise<CachedSchool[]>;
  /** One school by its id or School ID. */
  school(userId: string, ref: string): Promise<CachedSchool | null>;
  plannedOn(userId: string, date: string): Promise<PlannedVisit[]>;
  applyChange(change: SchoolChange): Promise<void>;
  addCapture(capture: QueuedCapture): Promise<void>;
  /** Every queued capture, newest first (the user's, or all). */
  captures(userId?: string): Promise<QueuedCapture[]>;
  /** The user's captures due to send now, oldest first. */
  dueCaptures(userId: string, now: number): Promise<QueuedCapture[]>;
  updateCapture(id: string, patch: CapturePatch, now: number): Promise<void>;
  /** Captures a crash left mid-send go back to waiting (the server is idempotent). */
  recoverSyncing(): Promise<void>;
  wasPrompted(userId: string, schoolId: string, date: string): Promise<boolean>;
  markPrompted(userId: string, schoolId: string, date: string): Promise<void>;
}

export const META = {
  owner: 'owner_user_id',
  ownerName: 'owner_name',
  ownerRole: 'owner_role',
  packAt: 'pack_generated_at',
  policy: 'capture_policy',
  canCapture: 'can_capture',
  changesSince: 'changes_since',
} as const;
