/**
 * The offline store held in memory: the web build (where the phone's
 * encrypted database does not exist) and the tests. Nothing survives a
 * reload here, so the web build does not offer offline work.
 */
import type { CachedSchool, CapturePatch, OfflineStore, PlannedVisit, QueuedCapture, SchoolChange } from './store';
import { TO_SEND } from './queueLogic';

export function memoryStore(): OfflineStore {
  const meta = new Map<string, string>();
  let schools: (CachedSchool & { userId: string })[] = [];
  let planned: (PlannedVisit & { userId: string })[] = [];
  let captures: QueuedCapture[] = [];
  const prompted = new Set<string>();
  return {
    async meta(key) {
      return meta.get(key) ?? null;
    },
    async setMeta(key, value) {
      meta.set(key, value);
    },
    async replacePack(userId, next, visits) {
      schools = [...schools.filter((s) => s.userId !== userId), ...next.map((s) => ({ ...s, userId }))];
      planned = [...planned.filter((p) => p.userId !== userId), ...visits.map((p) => ({ ...p, userId }))];
    },
    async forgetOthers(userId) {
      schools = schools.filter((s) => s.userId === userId);
      planned = planned.filter((p) => p.userId === userId);
    },
    async schools(userId) {
      return schools.filter((s) => s.userId === userId);
    },
    async school(userId, ref) {
      return schools.find((s) => s.userId === userId && (s.schoolId === ref || s.code === ref)) ?? null;
    },
    async plannedOn(userId, date) {
      return planned.filter((p) => p.userId === userId && p.date === date);
    },
    async applyChange(change: SchoolChange) {
      schools = schools.map((s) => {
        if (s.schoolId !== change.schoolId) return s;
        if (change.target === 'entrance') return { ...s, entranceLat: change.lat, entranceLng: change.lng };
        if (change.version <= s.version) return s;
        return { ...s, lat: change.lat, lng: change.lng, version: change.version, locationStatus: 'verified', verifiedAt: change.changedAt };
      });
    },
    async addCapture(capture) {
      if (!captures.some((c) => c.id === capture.id)) captures = [...captures, capture];
    },
    async captures(userId) {
      return captures.filter((c) => !userId || c.userId === userId).sort((a, b) => b.createdAt - a.createdAt);
    },
    async dueCaptures(userId, now) {
      return captures
        .filter((c) => c.userId === userId && TO_SEND.includes(c.status) && c.nextTryAt <= now)
        .sort((a, b) => a.createdAt - b.createdAt);
    },
    async updateCapture(id, patch: CapturePatch, now) {
      captures = captures.map((c) => (c.id === id ? { ...c, ...patch, updatedAt: now } : c));
    },
    async recoverSyncing() {
      captures = captures.map((c) => (c.status === 'syncing' ? { ...c, status: 'pending_sync' } : c));
    },
    async wasPrompted(userId, schoolId, date) {
      return prompted.has(`${userId}|${schoolId}|${date}`);
    },
    async markPrompted(userId, schoolId, date) {
      prompted.add(`${userId}|${schoolId}|${date}`);
    },
  };
}
