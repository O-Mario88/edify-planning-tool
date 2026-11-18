/**
 * The Settings page's answer (SettingsScreenService, read by Go:
 * docs/migration/176) laid out as the page's lines. Every fact comes from
 * the gateway; the words are the template's own
 * (templates/pages/settings/index.html).
 *
 * Turning two-step verification on or off, or moving it to another channel,
 * is a save the existing web app still makes, so the page shows the choice
 * and opens the existing page to change it.
 */
import type { TwoStepVerification } from '@/gen/edify/screens/v1/settings_pb';

export const SETTINGS_PATH = '/settings';

export interface ChannelLine {
  readonly key: 'app' | 'email' | 'sms';
  readonly label: string;
  readonly note: string;
  readonly chosen: boolean;
  readonly available: boolean;
  /** The authenticator app's set-up link, in the existing web app. */
  readonly link?: { readonly label: string; readonly href: string };
}

/** The three channels as the page lists them: app, email, text message. */
export function channelLines(two: TwoStepVerification, existingWebUrl: string): ChannelLine[] {
  const setUp = `${existingWebUrl}${SETTINGS_PATH}/two-step/app`;
  return [
    {
      key: 'app',
      label: 'Authenticator app',
      note: two.appAvailable
        ? 'Set up on your phone.'
        : 'Google Authenticator, Microsoft Authenticator or Authy on your phone — works with no email or text message.',
      chosen: two.channel === 'app',
      available: true,
      link: { label: two.appAvailable ? 'Set up again' : 'Set it up', href: setUp },
    },
    {
      key: 'email',
      label: 'Email',
      note: two.emailHint,
      // The template marks Email for every channel but a text message, so
      // an app user saw both App and Email marked and the browser kept the
      // later, Email; here only the channel in use is marked.
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
