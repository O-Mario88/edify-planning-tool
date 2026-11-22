'use server';

import { revalidatePath } from 'next/cache';

import { PageDrawerService } from '@/gen/edify/screens/v1/drawer_pb';
import { asReader } from '@/lib/auth';
import { gatewayClient, messageOf } from '@/lib/gateway';

export interface FormActionResult {
  readonly ok: boolean;
  readonly message: string;
}

export async function raiseEscalationAction(values: Record<string, string>): Promise<FormActionResult> {
  return asReader(async (token) => {
    try {
      const resp = await gatewayClient(PageDrawerService, token).saveDrawer({
        path: '/escalations',
        form: 'raise',
        values,
      });
      if (!resp.saved) {
        return { ok: false, message: resp.error || 'Could not send escalation.' };
      }
      revalidatePath('/escalations');
      return { ok: true, message: resp.message || 'Escalation sent.' };
    } catch (error) {
      return { ok: false, message: messageOf(error, 'Could not send escalation.') };
    }
  });
}
