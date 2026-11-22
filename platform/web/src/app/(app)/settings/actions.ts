'use server';

import { revalidatePath } from 'next/cache';

import { AccountService } from '@/gen/edify/identity/v1/accounts_pb';
import { asReader } from '@/lib/auth';
import { gatewayClient, messageOf } from '@/lib/gateway';
import { GatewayHttpError, gatewayJson } from '@/lib/gatewayJson';

export interface SettingsActionResult {
  readonly ok: boolean;
  readonly message: string;
}

export interface TotpSetupResult {
  readonly ok: boolean;
  readonly secret?: string;
  readonly otpauthUri?: string;
  readonly message?: string;
}

export async function changePasswordAction(input: { password: string; confirm: string }): Promise<SettingsActionResult> {
  if (!input.password || !input.confirm) {
    return { ok: false, message: 'Enter and confirm your new password.' };
  }
  if (input.password !== input.confirm) {
    return { ok: false, message: 'Passwords do not match.' };
  }
  return asReader(async (token) => {
    try {
      await gatewayClient(AccountService, token).setNewPassword({
        password: input.password,
        confirm: input.confirm,
      });
      revalidatePath('/settings');
      return { ok: true, message: 'Password updated.' };
    } catch (error) {
      return { ok: false, message: messageOf(error, 'Could not update password.') };
    }
  });
}

export async function updateTwoStepAction(input: { enabled: boolean; channel: 'email' | 'sms' | 'app' }): Promise<SettingsActionResult> {
  return asReader(async (token) => {
    try {
      await gatewayJson<{ saved: boolean }>('/api/v1/settings/two-step', token, {
        method: 'POST',
        body: { enabled: input.enabled, channel: input.channel },
      });
      revalidatePath('/settings');
      return { ok: true, message: 'Two-step verification settings saved.' };
    } catch (error) {
      if (error instanceof GatewayHttpError) {
        return { ok: false, message: error.message };
      }
      return { ok: false, message: 'Could not save two-step verification settings.' };
    }
  });
}

export async function beginTotpSetupAction(): Promise<TotpSetupResult> {
  return asReader(async (token) => {
    try {
      const res = await gatewayJson<{ secret: string; otpauth_uri: string }>('/api/v1/settings/two-step/totp/setup', token, {
        method: 'POST',
        body: {},
      });
      return { ok: true, secret: res.secret, otpauthUri: res.otpauth_uri };
    } catch (error) {
      if (error instanceof GatewayHttpError) {
        return { ok: false, message: error.message };
      }
      return { ok: false, message: 'Could not start authenticator app setup.' };
    }
  });
}

export async function confirmTotpSetupAction(input: { secret: string; code: string }): Promise<SettingsActionResult> {
  if (!input.secret.trim() || !input.code.trim()) {
    return { ok: false, message: 'Enter the 6-digit code from your authenticator app.' };
  }
  return asReader(async (token) => {
    try {
      await gatewayJson<{ enrolled: boolean }>('/api/v1/settings/two-step/totp/confirm', token, {
        method: 'POST',
        body: { secret: input.secret, code: input.code },
      });
      revalidatePath('/settings');
      return { ok: true, message: 'Authenticator app enrolled and active.' };
    } catch (error) {
      if (error instanceof GatewayHttpError) {
        return { ok: false, message: error.message };
      }
      return { ok: false, message: 'Could not verify authenticator code.' };
    }
  });
}
