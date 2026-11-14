/**
 * The offline capture queue's rules (offline capture brief, 2026-11-14,
 * parts 5 and 6): what each state means to the person, when to try again,
 * and what an answer from the server means for the capture on the phone.
 * A capture leaves the phone's queue only after the server has answered
 * and that answer is written down.
 */

export type QueueStatus =
  | 'saved_offline'
  | 'pending_sync'
  | 'syncing'
  | 'synced'
  | 'awaiting_review'
  | 'conflict'
  | 'failed';

export const STATUS_TEXT: Record<QueueStatus, string> = {
  saved_offline: 'Saved on this phone',
  pending_sync: 'Waiting to sync',
  syncing: 'Syncing…',
  synced: 'Synced',
  awaiting_review: 'Synced: waiting for review',
  conflict: 'Synced: location changed meanwhile, a reviewer will decide',
  failed: 'Not synced: action needed',
};

/** Statuses still to be sent. */
export const TO_SEND: readonly QueueStatus[] = ['saved_offline', 'pending_sync', 'syncing'];
/** Statuses the Pending Sync count shows. */
export const COUNTED: readonly QueueStatus[] = ['saved_offline', 'pending_sync', 'syncing', 'failed'];

/** The wait before try number attempts+1: 15 s, 30 s, 1 min … at most 30 min. */
export function retryDelayMs(attempts: number): number {
  const base = 15_000 * 2 ** Math.max(0, attempts);
  return Math.min(base, 30 * 60_000);
}

/** What the server's answer means for the capture on the phone. */
export function statusForOutcome(outcome: string, flags: readonly string[]): { status: QueueStatus; note: string } {
  switch (outcome) {
    case 'accepted':
      return { status: 'synced', note: "Synced. This is now the school's location." };
    case 'noted':
      return { status: 'synced', note: 'Synced. The location is marked as checked.' };
    case 'rejected':
      return { status: 'synced', note: 'Synced. A reviewer did not accept this location.' };
    default:
      return flags.includes('version_conflict')
        ? { status: 'conflict', note: 'Synced. The location changed while you were offline; a reviewer will decide.' }
        : { status: 'awaiting_review', note: 'Synced. Waiting for a reviewer to approve it.' };
  }
}

export type ErrorAction = 'retry' | 'sign_in' | 'failed';

/**
 * What a failed send means: try again later (no connection, the server
 * busy), keep it until the person signs in again, or stop and ask them
 * (refused: their access to the school has gone, or the capture is not
 * valid). Cached rights on the phone never override the server.
 */
export function actionForError(code: string): ErrorAction {
  if (code === 'unauthenticated') return 'sign_in';
  if (code === 'permission_denied' || code === 'not_found' || code === 'invalid_argument' || code === 'failed_precondition') {
    return 'failed';
  }
  return 'retry';
}

export function failedNote(code: string, message: string): string {
  if (code === 'permission_denied' || code === 'not_found') {
    return message || 'You can no longer change this school’s location.';
  }
  return message || 'The capture could not be accepted.';
}
