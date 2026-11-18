import { create } from '@bufbuild/protobuf';
import type { MessageInitShape } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { TwoStepVerificationSchema } from '@/gen/edify/screens/v1/settings_pb';

import { channelLines, sessionLine } from './settingsPage';

const two = (over: MessageInitShape<typeof TwoStepVerificationSchema> = {}) =>
  create(TwoStepVerificationSchema, { channel: 'email', emailHint: 'a•••@edify.org', ...over });

describe('channelLines', () => {
  it('marks only the channel in use', () => {
    const marked = (channel: string) =>
      channelLines(two({ channel, appAvailable: true, smsAvailable: true }), '')
        .filter((line) => line.chosen)
        .map((line) => line.key);
    expect(marked('email')).toEqual(['email']);
    expect(marked('sms')).toEqual(['sms']);
    expect(marked('app')).toEqual(['app']);
  });

  it('says why a text message cannot be used, and where one would go when it can', () => {
    const blocked = channelLines(two({ smsBlockedReason: 'Add a phone number to your profile to receive codes by text.' }), '');
    expect(blocked[2]).toMatchObject({ available: false, note: 'Add a phone number to your profile to receive codes by text.' });
    const open = channelLines(two({ smsAvailable: true, phoneHint: '•••• 0001' }), '');
    expect(open[2]).toMatchObject({ available: true, note: '•••• 0001' });
  });

  it('sends the authenticator set-up to the existing web app', () => {
    expect(channelLines(two(), 'https://existing.test')[0]?.link).toEqual({
      label: 'Set it up',
      href: 'https://existing.test/settings/two-step/app',
    });
    expect(channelLines(two({ appAvailable: true }), '')[0]?.link?.label).toBe('Set up again');
  });
});

describe('sessionLine', () => {
  it('states the idle limit', () => {
    expect(sessionLine(30)).toBe('You stay signed in while you are working. After 30 minutes without activity you will be signed out.');
  });
});
