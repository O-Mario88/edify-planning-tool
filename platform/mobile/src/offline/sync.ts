/**
 * Sending the offline capture queue (offline capture brief, 2026-11-14,
 * part 6). Oldest first, one at a time, each with its capture id so a
 * repeat after a lost answer files nothing twice. A capture is marked
 * Syncing before it goes and gets the server's answer written down when
 * it returns; a lost connection puts it back to wait, with a longer wait
 * each time; an expired sign-in keeps it until the person signs in; a
 * refusal (the school is no longer theirs, the capture is not valid)
 * stops it and says so. After sending, the accepted changes since the last
 * sync are applied to the phone's schools.
 */
import { ApiError } from '../api/connect';
import { actionForError, failedNote, retryDelayMs, statusForOutcome } from './queueLogic';
import type { OfflineStore, QueuedCapture, SchoolChange } from './store';
import { META } from './store';

export interface SubmitAnswer {
  readonly outcome: string;
  readonly flags: readonly string[];
  readonly resultVersion: number;
  readonly message: string;
}

/** The server calls the queue needs (RoutePlannerService, via the gateway). */
export interface CaptureApi {
  submit(capture: QueuedCapture): Promise<SubmitAnswer>;
  changes(since: string): Promise<{ changes: SchoolChange[]; now: string }>;
}

export interface SyncResult {
  readonly sent: number;
  readonly waiting: number;
  readonly failed: number;
  /** The sign-in has expired: sign in again to send the rest. */
  readonly needsSignIn: boolean;
}

let running: Promise<SyncResult> | null = null;

/** Sends what is due; a second call while one runs joins it. */
export function syncQueue(api: CaptureApi, store: OfflineStore, userId: string, now: () => number = Date.now): Promise<SyncResult> {
  running ??= sendDue(api, store, userId, now).finally(() => {
    running = null;
  });
  return running;
}

async function sendDue(api: CaptureApi, store: OfflineStore, userId: string, now: () => number): Promise<SyncResult> {
  const due = await store.dueCaptures(userId, now());
  let sent = 0;
  let waiting = 0;
  let failed = 0;
  for (const capture of due) {
    await store.updateCapture(capture.id, { status: 'syncing' }, now());
    try {
      const answer = await api.submit(capture);
      const next = statusForOutcome(answer.outcome, answer.flags);
      await store.updateCapture(
        capture.id,
        { status: next.status, note: next.note, flags: [...answer.flags], resultVersion: answer.resultVersion },
        now(),
      );
      sent += 1;
    } catch (cause) {
      const code = cause instanceof ApiError ? cause.code : 'network';
      const action = actionForError(code);
      if (action === 'failed') {
        await store.updateCapture(capture.id, { status: 'failed', note: failedNote(code, cause instanceof Error ? cause.message : '') }, now());
        failed += 1;
        continue;
      }
      const attempts = capture.attempts + 1;
      await store.updateCapture(
        capture.id,
        {
          status: 'pending_sync',
          attempts,
          nextTryAt: action === 'sign_in' ? 0 : now() + retryDelayMs(capture.attempts),
          note: action === 'sign_in' ? 'Sign in again to sync.' : 'No connection to Edify. It will sync when there is one.',
        },
        now(),
      );
      waiting += 1;
      if (action === 'sign_in') {
        return { sent, waiting: waiting + (due.length - sent - failed - waiting), failed, needsSignIn: true };
      }
      if (code === 'network' || code === 'timeout') {
        // No connection: the rest would fail the same way; they keep their place.
        return { sent, waiting: waiting + (due.length - sent - failed - waiting), failed, needsSignIn: false };
      }
    }
  }
  await refreshChanges(api, store);
  return { sent, waiting, failed, needsSignIn: false };
}

/** Applies the location changes accepted since the last time to the phone's schools. */
export async function refreshChanges(api: CaptureApi, store: OfflineStore): Promise<number> {
  const since = (await store.meta(META.changesSince)) ?? '';
  try {
    const answer = await api.changes(since);
    for (const change of answer.changes) {
      await store.applyChange(change);
    }
    if (answer.now) await store.setMeta(META.changesSince, answer.now);
    return answer.changes.length;
  } catch {
    // The feed is a refresh: the next sync tries again.
    return 0;
  }
}
