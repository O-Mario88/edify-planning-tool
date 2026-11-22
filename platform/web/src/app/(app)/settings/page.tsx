import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { SettingsScreenService } from '@/gen/edify/screens/v1/settings_pb';
import type { GetSettingsResponse } from '@/gen/edify/screens/v1/settings_pb';
import { Card } from '@/components/blocks/Card';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { AppearanceChoice } from '@/components/settings/AppearanceChoice';
import { ChangePasswordForm, TwoStepForm } from '@/components/settings/SecurityForms';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { gatewayClient, isNotFound, isUnavailable } from '@/lib/gateway';
import { SETTINGS_PATH, channelLines, sessionLine } from '@/lib/settingsPage';

export const metadata: Metadata = { title: 'Settings · Edify' };

const BUTTON =
  'inline-flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] px-3 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)] hover:bg-[var(--edify-surface-muted)]';
const LINK = 'font-bold text-[var(--brand-primary-text)] hover:underline';

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card label={title}>
      <div className="space-y-3">
        <h2 className="text-[length:var(--edify-text-heading-size)] font-semibold">{title}</h2>
        {children}
      </div>
    </Card>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-[var(--edify-text-muted)]">{children}</p>;
}

/*
 * Settings, drawn from the gateway's answer (SettingsScreenService) and saved
 * directly through Go AccountService.SetNewPassword and POST /api/v1/settings/two-step.
 */
export default async function SettingsPage() {
  const existingWebUrl = environment().existingWebUrl;
  const answer = await asReader(async (token): Promise<GetSettingsResponse | null> => {
    try {
      return await gatewayClient(SettingsScreenService, token).getSettings({});
    } catch (error) {
      if (isNotFound(error)) notFound();
      if (isUnavailable(error)) return null;
      throw error;
    }
  });
  if (answer === null) return <NotMovedYet href={`${existingWebUrl}${SETTINGS_PATH}`} />;

  const two = answer.twoStep;
  const initialChannel: 'email' | 'sms' | 'app' =
    two?.channel === 'sms' ? 'sms' : two?.channel === 'app' ? 'app' : 'email';

  return (
    <div className="mx-auto max-w-[900px] space-y-5 px-4 pb-24 pt-5 sm:px-6 lg:pb-8" data-page={SETTINGS_PATH}>
      <div data-block="header">
        <p className="text-[length:var(--edify-text-label-size)] font-semibold uppercase text-[var(--brand-primary-text)] dark:text-[var(--edify-accent-text)]">
          Account
        </p>
        <h1 className="text-[length:var(--edify-text-display-size)] font-bold leading-[1.15] text-[var(--edify-text)]">Settings</h1>
        <p className="text-[length:var(--edify-text-label-size)] font-medium text-[var(--edify-text-muted)]">
          Your account, security and appearance preferences.
        </p>
      </div>

      <Section title="Account security">
        <div className="rounded-[8px] border border-[var(--edify-border)] px-3 py-2">
          <p className="text-[length:var(--edify-text-micro-size)] font-semibold uppercase text-[var(--edify-text-muted)]">Email</p>
          <p className="truncate font-semibold">{answer.email}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/profile" className={BUTTON}>
            View profile
          </Link>
        </div>
        {answer.mustChangePassword ? <ChangePasswordForm mustChange={answer.mustChangePassword} /> : null}
      </Section>

      <Section title="Programme master data">
        <Muted>Review the governed Activities used by SSA-led Planning, scheduling, evidence and analytics.</Muted>
        <Link href="/settings/activity-catalogue/" className={BUTTON}>
          Open Activity Catalogue
        </Link>
      </Section>

      {two ? (
        <TwoStepForm
          initialInForce={two.inForce}
          requiredByPolicy={two.requiredByPolicy}
          initialChannel={initialChannel}
          channels={channelLines(two)}
        />
      ) : null}

      <Section title="Appearance">
        <Muted>Choose the workspace that best suits your environment. Your preference is stored on this device.</Muted>
        <AppearanceChoice />
      </Section>

      <Section title="Notifications">
        <Muted>
          Approvals, returns, escalations and To-Dos are always in the bell. They can also reach this phone or computer when Edify is closed, and your
          email.
        </Muted>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <Link href="/notifications#delivery-settings" className={LINK}>
            Push and email settings →
          </Link>
          <Link href="/notifications" className={LINK}>
            Open notifications →
          </Link>
        </div>
      </Section>

      <Section title="Session">
        <Muted>Signed in as {answer.email}.</Muted>
        <Muted>{sessionLine(answer.sessionIdleMinutes)}</Muted>
        <Muted>Use the avatar in the upper-right corner to log out.</Muted>
      </Section>
    </div>
  );
}
