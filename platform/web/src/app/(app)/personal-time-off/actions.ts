'use server';

import { revalidatePath } from 'next/cache';

import { PageDrawerService } from '@/gen/edify/screens/v1/drawer_pb';
import { asReader } from '@/lib/auth';
import { gatewayClient, messageOf } from '@/lib/gateway';

export interface LeaveRequestResult {
  readonly ok: boolean;
  readonly message: string;
}

export async function submitLeaveRequestAction(values: Record<string, string>): Promise<LeaveRequestResult> {
  return asReader(async (token) => {
    try {
      const resp = await gatewayClient(PageDrawerService, token).saveDrawer({
        path: '/personal-time-off/request',
        values,
      });
      if (!resp.saved) {
        return { ok: false, message: resp.error || 'Could not submit leave request.' };
      }
      revalidatePath('/personal-time-off');
      return { ok: true, message: resp.message || 'Leave request submitted.' };
    } catch (error) {
      return { ok: false, message: messageOf(error, 'Could not submit leave request.') };
    }
  });
}
