/**
 * The Settings page's answer (SettingsScreenService, read by Go:
 * docs/migration/176) laid out as the page's lines. Every fact comes from
 * the gateway and updates are saved natively in Go.
 */
import type { TwoStepVerification } from '@/gen/edify/screens/v1/settings_pb';

export const SETTINGS_PATH = '/settings';

export interface ChannelLine {
  readonly key: 'app' | 'email' | 'sms';
  readonly label: string;
  readonly note: string;
  readonly chosen: boolean;
  readonly available: boolean;
}

/** The three channels as the page lists them: app, email, text message. */
export function channelLines(two: TwoStepVerification, _existingWebUrl = ''): ChannelLine[] {
  void _existingWebUrl;
  return [
    {
      key: 'app',
      label: 'Authenticator app',
      note: two.appAvailable
        ? 'Set up on your phone.'
        : 'Not enrolled yet. Choose Email or Text message until an authenticator app is enrolled.',
      chosen: two.channel === 'app',
      available: two.appAvailable,
    },
    {
      key: 'email',
      label: 'Email',
      note: two.emailHint,
      chosen: two.channel !== 'sms' && two.channel !== 'app',
      available: true,
    },
    {
      key: 'sms',
      label: 'Text message',
      note: two.smsAvailable ? two.phoneHint : two.smsBlockedReason,
      chosen: two.channel === 'sms',
      available: two.smsAvailable,
    },
  ];
}

/** The session card's sentence. */
export function sessionLine(minutes: number): string {
  return `You stay signed in while you are working. After ${minutes} minutes without activity you will be signed out.`;
}
