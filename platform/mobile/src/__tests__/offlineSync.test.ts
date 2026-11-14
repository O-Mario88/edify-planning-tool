import { ApiError } from '../api/connect';
import { memoryStore } from '../offline/memoryStore';
import type { OfflineStore, QueuedCapture } from '../offline/store';
import { META } from '../offline/store';
import { syncQueue } from '../offline/sync';
import type { CaptureApi } from '../offline/sync';

const capture = (id: string, created: number, over: Partial<QueuedCapture> = {}): QueuedCapture => ({
  id, userId: 'u1', schoolId: 's1', schoolName: 'Nakasero P/S', target: 'school', kind: 'new', pointSource: 'device',
  lat: 0.3476, lng: 32.5825, accuracyM: 8, capturedAt: created, sampleCount: 5, spreadM: 2, baseVersion: 0,
  prevLat: null, prevLng: null, reason: '', accessNote: '', status: 'saved_offline', attempts: 0, nextTryAt: 0, note: '',
  flags: [], resultVersion: 0, createdAt: created, updatedAt: created, ...over,
});

const school = { schoolId: 's1', code: '1001', name: 'Nakasero P/S', district: 'Kampala', cluster: 'C1', category: 'Client',
  locationStatus: 'missing', lat: null, lng: null, version: 0, entranceLat: null, entranceLng: null, verifiedAt: '',
  accessNote: '', hasPending: false, lastConfirmedAt: '' };

function api(answers: ((c: QueuedCapture) => Promise<{ outcome: string; flags: string[]; resultVersion: number; message: string }>)[]): CaptureApi & { sent: string[] } {
  const sent: string[] = [];
  return {
    sent,
    async submit(c) {
      sent.push(c.id);
      const next = answers.shift();
      if (!next) throw new Error('unexpected send');
      return next(c);
    },
    async changes() {
      return { changes: [{ schoolId: 's1', target: 'school', version: 1, lat: 0.3476, lng: 32.5825, changedAt: '2026-11-14T10:00:00Z' }], now: '2026-11-14T10:00:01Z' };
    },
  };
}

const ok = (outcome: string, flags: string[] = [], resultVersion = 0) => async () => ({ outcome, flags, resultVersion, message: '' });
const fail = (code: string) => async () => {
  throw new ApiError('refused', code, '', '');
};

describe('syncing the offline capture queue', () => {
  let store: OfflineStore;
  beforeEach(async () => {
    store = memoryStore();
    await store.replacePack('u1', [school], []);
  });

  it('sends oldest first and writes each answer down, then applies the accepted change', async () => {
    await store.addCapture(capture('b', 2));
    await store.addCapture(capture('a', 1));
    const server = api([ok('accepted', [], 1), ok('pending', ['accuracy_fair'])]);
    const result = await syncQueue(server, store, 'u1', () => 100);
    expect(server.sent).toEqual(['a', 'b']);
    expect(result).toEqual({ sent: 2, waiting: 0, failed: 0, needsSignIn: false });
    const byId = Object.fromEntries((await store.captures('u1')).map((c) => [c.id, c]));
    expect(byId.a.status).toBe('synced');
    expect(byId.b.status).toBe('awaiting_review');
    expect((await store.school('u1', '1001'))?.version).toBe(1);
    expect(await store.meta(META.changesSince)).toBe('2026-11-14T10:00:01Z');
  });

  it('keeps a capture when the connection drops, and waits before trying again', async () => {
    await store.addCapture(capture('a', 1));
    await store.addCapture(capture('b', 2));
    const result = await syncQueue(api([fail('network')]), store, 'u1', () => 1_000);
    expect(result.waiting).toBe(2);
    const a = (await store.captures('u1')).find((c) => c.id === 'a')!;
    expect(a.status).toBe('pending_sync');
    expect(a.attempts).toBe(1);
    expect(a.nextTryAt).toBe(16_000);
    expect(await store.dueCaptures('u1', 2_000)).toHaveLength(1);
  });

  it('keeps everything for an expired sign-in and says so', async () => {
    await store.addCapture(capture('a', 1));
    const result = await syncQueue(api([fail('unauthenticated')]), store, 'u1', () => 5);
    expect(result.needsSignIn).toBe(true);
    const [a] = await store.captures('u1');
    expect(a.status).toBe('pending_sync');
    expect(a.note).toMatch(/Sign in again/);
  });

  it('stops on a refusal: the school is no longer the person’s', async () => {
    await store.addCapture(capture('a', 1));
    await store.addCapture(capture('b', 2));
    const result = await syncQueue(api([fail('not_found'), ok('accepted', [], 1)]), store, 'u1', () => 5);
    expect(result.failed).toBe(1);
    expect(result.sent).toBe(1);
    const a = (await store.captures('u1')).find((c) => c.id === 'a')!;
    expect(a.status).toBe('failed');
  });

  it('marks a capture that met a changed location as a conflict', async () => {
    await store.addCapture(capture('a', 1, { kind: 'correction' }));
    await syncQueue(api([ok('pending', ['correction', 'version_conflict'])]), store, 'u1', () => 5);
    expect((await store.captures('u1'))[0].status).toBe('conflict');
  });

  it('sends a capture a crash left mid-send again, under the same id', async () => {
    await store.addCapture(capture('a', 1, { status: 'syncing' }));
    await store.recoverSyncing();
    const server = api([ok('accepted', [], 1)]);
    await syncQueue(server, store, 'u1', () => 5);
    expect(server.sent).toEqual(['a']);
  });

  it('never sends another account’s captures', async () => {
    await store.addCapture(capture('mine', 1));
    await store.addCapture(capture('theirs', 2, { userId: 'u2' }));
    const server = api([ok('accepted', [], 1)]);
    await syncQueue(server, store, 'u1', () => 5);
    expect(server.sent).toEqual(['mine']);
  });

  it('joins a sync already running instead of sending twice', async () => {
    await store.addCapture(capture('a', 1));
    const server = api([ok('accepted', [], 1)]);
    await Promise.all([syncQueue(server, store, 'u1', () => 5), syncQueue(server, store, 'u1', () => 5)]);
    expect(server.sent).toEqual(['a']);
  });
});
