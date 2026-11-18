import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { SettingsScreenService } from '@/gen/edify/screens/v1/settings_pb';
import type { GetSettingsResponse, TwoStepVerification } from '@/gen/edify/screens/v1/settings_pb';
import { Badge } from '@/components/blocks/Badge';
import { Card } from '@/components/blocks/Card';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { AppearanceChoice } from '@/components/settings/AppearanceChoice';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { gatewayClient, isNotFound, isUnavailable } from '@/lib/gateway';
import { SETTINGS_PATH, channelLines, sessionLine } from '@/lib/settingsPage';

export const metadata: Metadata = { title: 'Settings · Edify' };

const BUTTON =
  'inline-flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] px-3 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)] hover:bg-[var(--edify-surface-muted)]';
const PRIMARY =
  'inline-flex h-8 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-3 text-[length:var(--edify-text-label-size)] font-semibold text-white';
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

function TwoStep({ two, existingWebUrl }: { two: TwoStepVerification; existingWebUrl: string }) {
  return (
    <Card label="Two-step verification">
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[length:var(--edify-text-heading-size)] font-semibold">Two-step verification</h2>
            <p className="mt-1 text-[var(--edify-text-muted)]">
              After your password, we send a single-use code to confirm it is you. It means a stolen password on its own is not enough to reach your
              workspace.
            </p>
          </div>
          <Badge tone={two.inForce ? 'success' : 'neutral'}>{two.inForce ? 'On' : 'Off'}</Badge>
        </div>
        {two.requiredByPolicy ? (
          <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
            Your organisation requires two-step verification, so this cannot be turned off. You can still choose where the code is sent.
          </p>
        ) : null}
        {two.inForce ? (
          <div>
            <p className="text-[length:var(--edify-text-label-size)] font-semibold">Get my code from</p>
            <ul className="mt-2 space-y-2">
              {channelLines(two, existingWebUrl).map((line) => (
                <li key={line.key} className={`flex items-start gap-2.5 ${line.available ? '' : 'opacity-60'}`} data-channel={line.key}>
                  <span
                    aria-hidden
                    className={`mt-1 h-3.5 w-3.5 shrink-0 rounded-full border ${line.chosen ? 'border-[var(--brand-primary)] bg-[var(--brand-primary)]' : 'border-[var(--edify-border-strong)]'}`}
                  />
                  <span>
                    <span className="font-semibold">{line.label}</span>
                    {line.chosen ? <span className="sr-only"> (in use)</span> : null}
                    <span className="block text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
                      {line.note}
                      {line.link ? (
                        <>
                          {' '}
                          <a href={line.link.href} className="underline">
                            {line.link.label}
                          </a>
                        </>
                      ) : null}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
          Changing two-step verification has not moved to the new web app yet; it opens in the existing web app.
        </p>
        <a href={`${existingWebUrl}${SETTINGS_PATH}`} className={PRIMARY}>
          Change two-step verification
        </a>
      </div>
    </Card>
  );
}

/*
 * Settings, drawn from the gateway's answer, which Go reads
 * (SettingsScreenService): account security, programme master data,
 * two-step verification, appearance, notifications and the session.
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
          {answer.mustChangePassword ? (
            <a href={`${existingWebUrl}/change-password`} className={PRIMARY}>
              Change password
            </a>
          ) : null}
        </div>
      </Section>

      <Section title="Programme master data">
        <Muted>Review the governed Activities used by SSA-led Planning, scheduling, evidence and analytics.</Muted>
        <Link href="/settings/activity-catalogue/" className={BUTTON}>
          Open Activity Catalogue
        </Link>
      </Section>

      {answer.twoStep ? <TwoStep two={answer.twoStep} existingWebUrl={existingWebUrl} /> : null}

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
