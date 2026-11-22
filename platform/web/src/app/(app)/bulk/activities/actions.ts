'use server';

import { revalidatePath } from 'next/cache';

import { asReader } from '@/lib/auth';
import { gatewayJson } from '@/lib/gatewayJson';

export interface BulkPreviewItem {
  id: string;
  title: string;
  where: string;
  day: string;
  eligible: boolean;
  reason?: string;
}

export interface BulkPreviewResult {
  kind: 'reschedule' | 'cancel';
  eligible: BulkPreviewItem[];
  excluded: BulkPreviewItem[];
  previewToken: string;
}

export interface BulkConfirmResult {
  done: { ActivityID: string; Title: string }[];
  refused: { ActivityID: string; Title: string; Refusal: string }[];
  message: string;
  outcome?: string;
  replayed?: boolean;
}

export async function previewBulkActivitiesAction(input: {
  kind: 'reschedule' | 'cancel';
  activityIds: readonly string[];
  date?: string;
  reason?: string;
}): Promise<{ ok: true; data: BulkPreviewResult } | { ok: false; error: string }> {
  try {
    const data = await asReader((token) =>
      gatewayJson<BulkPreviewResult>('/api/v1/bulk/activities/preview', token, {
        method: 'POST',
        body: {
          kind: input.kind,
          activityIds: [...input.activityIds],
          date: input.date ?? '',
          reason: input.reason ?? '',
        },
      }),
    );
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Preview failed.' };
  }
}

export async function confirmBulkActivitiesAction(input: {
  kind: 'reschedule' | 'cancel';
  activityIds: readonly string[];
  date?: string;
  reason: string;
  idempotencyKey: string;
}): Promise<{ ok: true; data: BulkConfirmResult } | { ok: false; error: string }> {
  try {
    const data = await asReader((token) =>
      gatewayJson<BulkConfirmResult>('/api/v1/bulk/activities/confirm', token, {
        method: 'POST',
        body: {
          kind: input.kind,
          activityIds: [...input.activityIds],
          date: input.date ?? '',
          reason: input.reason,
          idempotencyKey: input.idempotencyKey,
        },
      }),
    );
    revalidatePath('/my-plan');
    revalidatePath('/calendar');
    revalidatePath('/work-plan');
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Bulk update failed.' };
  }
}
