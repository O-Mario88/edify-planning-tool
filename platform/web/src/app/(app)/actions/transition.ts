'use server';

import { revalidatePath } from 'next/cache';

import { PageDrawerService } from '@/gen/edify/screens/v1/drawer_pb';
import { asReader } from '@/lib/auth';
import { gatewayClient, messageOf } from '@/lib/gateway';

export interface TeamActionTransitionResult {
  readonly ok: boolean;
  readonly message: string;
}

const ACTION_TRANSITION_RE = /^\/actions\/[A-Za-z0-9_-]+\/(acknowledge|start|block|return|cancel|escalate|resolve)$/;

export async function transitionTeamAction(path: string, reason = ''): Promise<TeamActionTransitionResult> {
  const clean = path.split('?')[0] ?? path;
  if (!ACTION_TRANSITION_RE.test(clean)) {
    return { ok: false, message: 'Unsupported action transition.' };
  }
  return asReader(async (token) => {
    try {
      const resp = await gatewayClient(PageDrawerService, token).saveDrawer({
        path: clean,
        values: reason ? { reason } : {},
      });
      if (!resp.saved) {
        return { ok: false, message: resp.error || 'Could not update this action.' };
      }
      revalidatePath('/actions/mine');
      revalidatePath('/actions/sent');
      return { ok: true, message: resp.message || 'Action updated.' };
    } catch (error) {
      return { ok: false, message: messageOf(error, 'Could not update this action.') };
    }
  });
}
