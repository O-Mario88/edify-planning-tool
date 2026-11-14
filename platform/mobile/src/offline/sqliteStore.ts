/**
 * The phone's offline store: SQLite encrypted with SQLCipher (expo-sqlite,
 * useSQLCipher in app.json). The key is 32 random bytes made on this phone
 * and kept in the keychain / keystore (SecureStore, this device only); the
 * records themselves stay in the database, never in SecureStore. Every
 * change to the queue is one statement or one transaction, so a capture is
 * either written whole or not at all.
 */
import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import * as SQLite from 'expo-sqlite';

import type { CachedSchool, CapturePatch, OfflineStore, PlannedVisit, QueuedCapture, SchoolChange } from './store';
import { TO_SEND } from './queueLogic';
import type { QueueStatus } from './queueLogic';

const DATABASE = 'edify-offline';
const KEY_NAME = 'edify.offlineKey';

const SCHEMA = `
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS school (
  user_id TEXT NOT NULL, school_id TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL, district TEXT NOT NULL,
  cluster TEXT NOT NULL, category TEXT NOT NULL, location_status TEXT NOT NULL, lat REAL, lng REAL,
  version INTEGER NOT NULL, entrance_lat REAL, entrance_lng REAL, verified_at TEXT NOT NULL, access_note TEXT NOT NULL,
  has_pending INTEGER NOT NULL, last_confirmed_at TEXT NOT NULL, PRIMARY KEY (user_id, school_id));
CREATE INDEX IF NOT EXISTS school_code ON school (user_id, code);
CREATE TABLE IF NOT EXISTS planned (user_id TEXT NOT NULL, date TEXT NOT NULL, school_id TEXT NOT NULL, activity_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS planned_day ON planned (user_id, date);
CREATE TABLE IF NOT EXISTS capture (
  id TEXT PRIMARY KEY NOT NULL, user_id TEXT NOT NULL, school_id TEXT NOT NULL, school_name TEXT NOT NULL,
  target TEXT NOT NULL, kind TEXT NOT NULL, point_source TEXT NOT NULL, lat REAL, lng REAL, accuracy_m REAL NOT NULL,
  captured_at INTEGER, sample_count INTEGER NOT NULL, spread_m REAL NOT NULL, base_version INTEGER NOT NULL,
  prev_lat REAL, prev_lng REAL, reason TEXT NOT NULL, access_note TEXT NOT NULL, status TEXT NOT NULL,
  attempts INTEGER NOT NULL, next_try_at INTEGER NOT NULL, note TEXT NOT NULL, flags TEXT NOT NULL,
  result_version INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS capture_due ON capture (user_id, status, next_try_at);
CREATE TABLE IF NOT EXISTS prompt (user_id TEXT NOT NULL, school_id TEXT NOT NULL, date TEXT NOT NULL, PRIMARY KEY (user_id, school_id, date));
`;

async function keyHex(): Promise<string> {
  const options = { keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY };
  const saved = await SecureStore.getItemAsync(KEY_NAME, options);
  if (saved && /^[0-9a-f]{64}$/.test(saved)) return saved;
  const bytes = await Crypto.getRandomBytesAsync(32);
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  await SecureStore.setItemAsync(KEY_NAME, hex, options);
  return hex;
}

interface SchoolRow {
  school_id: string;
  code: string;
  name: string;
  district: string;
  cluster: string;
  category: string;
  location_status: string;
  lat: number | null;
  lng: number | null;
  version: number;
  entrance_lat: number | null;
  entrance_lng: number | null;
  verified_at: string;
  access_note: string;
  has_pending: number;
  last_confirmed_at: string;
}

const schoolOf = (r: SchoolRow): CachedSchool => ({
  schoolId: r.school_id,
  code: r.code,
  name: r.name,
  district: r.district,
  cluster: r.cluster,
  category: r.category,
  locationStatus: r.location_status,
  lat: r.lat,
  lng: r.lng,
  version: r.version,
  entranceLat: r.entrance_lat,
  entranceLng: r.entrance_lng,
  verifiedAt: r.verified_at,
  accessNote: r.access_note,
  hasPending: r.has_pending === 1,
  lastConfirmedAt: r.last_confirmed_at,
});

interface CaptureRow {
  id: string;
  user_id: string;
  school_id: string;
  school_name: string;
  target: string;
  kind: string;
  point_source: string;
  lat: number | null;
  lng: number | null;
  accuracy_m: number;
  captured_at: number | null;
  sample_count: number;
  spread_m: number;
  base_version: number;
  prev_lat: number | null;
  prev_lng: number | null;
  reason: string;
  access_note: string;
  status: string;
  attempts: number;
  next_try_at: number;
  note: string;
  flags: string;
  result_version: number;
  created_at: number;
  updated_at: number;
}

const flagsOf = (raw: string): string[] => {
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((f): f is string => typeof f === 'string') : [];
  } catch {
    return [];
  }
};

const captureOf = (r: CaptureRow): QueuedCapture => ({
  id: r.id,
  userId: r.user_id,
  schoolId: r.school_id,
  schoolName: r.school_name,
  target: r.target === 'entrance' ? 'entrance' : 'school',
  kind: r.kind === 'confirm' ? 'confirm' : r.kind === 'correction' ? 'correction' : 'new',
  pointSource: r.point_source === 'device' ? 'device' : r.point_source === 'typed' ? 'typed' : 'none',
  lat: r.lat,
  lng: r.lng,
  accuracyM: r.accuracy_m,
  capturedAt: r.captured_at,
  sampleCount: r.sample_count,
  spreadM: r.spread_m,
  baseVersion: r.base_version,
  prevLat: r.prev_lat,
  prevLng: r.prev_lng,
  reason: r.reason,
  accessNote: r.access_note,
  status: r.status as QueueStatus,
  attempts: r.attempts,
  nextTryAt: r.next_try_at,
  note: r.note,
  flags: flagsOf(r.flags),
  resultVersion: r.result_version,
  createdAt: r.created_at,
  updatedAt: r.updated_at,
});

const CAPTURE_PATCH_COLUMNS: Record<keyof CapturePatch, string> = {
  status: 'status',
  attempts: 'attempts',
  nextTryAt: 'next_try_at',
  note: 'note',
  flags: 'flags',
  resultVersion: 'result_version',
};

let opening: Promise<OfflineStore> | null = null;

/**
 * Opens (and on first use creates) the encrypted store, once per app
 * process: two opens at once would each make a key, and the file would be
 * encrypted with one while the keychain kept the other.
 */
export function openSqliteStore(): Promise<OfflineStore> {
  opening ??= openOnce().catch((cause: unknown) => {
    opening = null;
    throw cause;
  });
  return opening;
}

async function openOnce(): Promise<OfflineStore> {
  const key = await keyHex();
  // The file is named for its key, so a key and its file always go together:
  // should the keychain ever lose the key, the old file is left untouched
  // and a new one is begun.
  const tag = (await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, key)).slice(0, 12);
  const db = await SQLite.openDatabaseAsync(`${DATABASE}-${tag}.db`);
  // SQLCipher: the key comes before anything else touches the file.
  await db.execAsync(`PRAGMA key = "x'${key}'"`);
  await db.execAsync('PRAGMA journal_mode = WAL;');
  await db.execAsync(SCHEMA);
  const params = (values: (string | number | null)[]) => values;

  const store: OfflineStore = {
    async meta(key) {
      const row = await db.getFirstAsync<{ value: string }>('SELECT value FROM meta WHERE key = ?', key);
      return row?.value ?? null;
    },
    async setMeta(key, value) {
      await db.runAsync('INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', key, value);
    },
    async replacePack(userId, schools, planned: readonly PlannedVisit[]) {
      // One transaction on the keyed connection (an exclusive transaction
      // opens a second connection, which has no key).
      await db.withTransactionAsync(async () => {
        await db.runAsync('DELETE FROM school WHERE user_id = ?', userId);
        await db.runAsync('DELETE FROM planned WHERE user_id = ?', userId);
        const insertSchool = await db.prepareAsync(
          `INSERT INTO school (user_id, school_id, code, name, district, cluster, category, location_status, lat, lng, version,
             entrance_lat, entrance_lng, verified_at, access_note, has_pending, last_confirmed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        );
        try {
          for (const s of schools) {
            await insertSchool.executeAsync(
              params([userId, s.schoolId, s.code, s.name, s.district, s.cluster, s.category, s.locationStatus, s.lat, s.lng, s.version,
                s.entranceLat, s.entranceLng, s.verifiedAt, s.accessNote, s.hasPending ? 1 : 0, s.lastConfirmedAt]),
            );
          }
        } finally {
          await insertSchool.finalizeAsync();
        }
        for (const p of planned) {
          await db.runAsync('INSERT INTO planned (user_id, date, school_id, activity_id) VALUES (?, ?, ?, ?)', userId, p.date, p.schoolId, p.activityId);
        }
      });
    },
    async forgetOthers(userId) {
      await db.withTransactionAsync(async () => {
        await db.runAsync('DELETE FROM school WHERE user_id <> ?', userId);
        await db.runAsync('DELETE FROM planned WHERE user_id <> ?', userId);
      });
    },
    async schools(userId) {
      const rows = await db.getAllAsync<SchoolRow>('SELECT * FROM school WHERE user_id = ? ORDER BY name, school_id', userId);
      return rows.map(schoolOf);
    },
    async school(userId, ref) {
      const row = await db.getFirstAsync<SchoolRow>('SELECT * FROM school WHERE user_id = ? AND (school_id = ? OR code = ?)', userId, ref, ref);
      return row ? schoolOf(row) : null;
    },
    async plannedOn(userId, date) {
      const rows = await db.getAllAsync<{ date: string; school_id: string; activity_id: string }>(
        'SELECT date, school_id, activity_id FROM planned WHERE user_id = ? AND date = ?',
        userId,
        date,
      );
      return rows.map((r) => ({ date: r.date, schoolId: r.school_id, activityId: r.activity_id }));
    },
    async applyChange(change: SchoolChange) {
      if (change.target === 'entrance') {
        await db.runAsync('UPDATE school SET entrance_lat = ?, entrance_lng = ? WHERE school_id = ?', change.lat, change.lng, change.schoolId);
        return;
      }
      await db.runAsync(
        `UPDATE school SET lat = ?, lng = ?, version = ?, location_status = 'verified', verified_at = ?
         WHERE school_id = ? AND version < ?`,
        change.lat,
        change.lng,
        change.version,
        change.changedAt,
        change.schoolId,
        change.version,
      );
    },
    async addCapture(c) {
      await db.runAsync(
        `INSERT OR IGNORE INTO capture (id, user_id, school_id, school_name, target, kind, point_source, lat, lng, accuracy_m,
           captured_at, sample_count, spread_m, base_version, prev_lat, prev_lng, reason, access_note, status, attempts,
           next_try_at, note, flags, result_version, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        params([c.id, c.userId, c.schoolId, c.schoolName, c.target, c.kind, c.pointSource, c.lat, c.lng, c.accuracyM, c.capturedAt,
          c.sampleCount, c.spreadM, c.baseVersion, c.prevLat, c.prevLng, c.reason, c.accessNote, c.status, c.attempts, c.nextTryAt,
          c.note, JSON.stringify(c.flags), c.resultVersion, c.createdAt, c.updatedAt]),
      );
    },
    async captures(userId) {
      const rows = userId
        ? await db.getAllAsync<CaptureRow>('SELECT * FROM capture WHERE user_id = ? ORDER BY created_at DESC', userId)
        : await db.getAllAsync<CaptureRow>('SELECT * FROM capture ORDER BY created_at DESC');
      return rows.map(captureOf);
    },
    async dueCaptures(userId, now) {
      const marks = TO_SEND.map(() => '?').join(', ');
      const rows = await db.getAllAsync<CaptureRow>(
        `SELECT * FROM capture WHERE user_id = ? AND status IN (${marks}) AND next_try_at <= ? ORDER BY created_at`,
        userId,
        ...TO_SEND,
        now,
      );
      return rows.map(captureOf);
    },
    async updateCapture(id, patch, now) {
      const sets: string[] = [];
      const values: (string | number)[] = [];
      for (const [field, column] of Object.entries(CAPTURE_PATCH_COLUMNS) as [keyof CapturePatch, string][]) {
        const value = patch[field];
        if (value === undefined) continue;
        sets.push(`${column} = ?`);
        values.push(field === 'flags' ? JSON.stringify(value) : (value as string | number));
      }
      sets.push('updated_at = ?');
      values.push(now, id);
      await db.runAsync(`UPDATE capture SET ${sets.join(', ')} WHERE id = ?`, ...values);
    },
    async recoverSyncing() {
      await db.runAsync("UPDATE capture SET status = 'pending_sync' WHERE status = 'syncing'");
    },
    async wasPrompted(userId, schoolId, date) {
      const row = await db.getFirstAsync('SELECT 1 FROM prompt WHERE user_id = ? AND school_id = ? AND date = ?', userId, schoolId, date);
      return row !== null;
    },
    async markPrompted(userId, schoolId, date) {
      await db.runAsync('INSERT OR IGNORE INTO prompt (user_id, school_id, date) VALUES (?, ?, ?)', userId, schoolId, date);
    },
  };
  return serialized(store);
}

/**
 * Every call one after another: a transaction on the shared connection is
 * not exclusive, so nothing may run beside it.
 */
function serialized(store: OfflineStore): OfflineStore {
  let chain: Promise<unknown> = Promise.resolve();
  const wrapped = {} as Record<string, unknown>;
  for (const [name, fn] of Object.entries(store) as [string, (...args: unknown[]) => Promise<unknown>][]) {
    wrapped[name] = (...args: unknown[]) => {
      const run = chain.then(() => fn(...args));
      chain = run.catch(() => undefined);
      return run;
    };
  }
  return wrapped as unknown as OfflineStore;
}
