'use client';

import { useState, useTransition } from 'react';

import { Badge } from '@/components/blocks/Badge';
import { Card } from '@/components/blocks/Card';
import type { ChannelLine } from '@/lib/settingsPage';

import {
  beginTotpSetupAction,
  changePasswordAction,
  confirmTotpSetupAction,
  updateTwoStepAction,
} from '@/app/(app)/settings/actions';

const INPUT =
  'h-9 w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[length:var(--edify-text-body-size)] text-[var(--edify-text)]';
const PRIMARY =
  'inline-flex h-8 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-3 text-[length:var(--edify-text-label-size)] font-semibold text-white disabled:opacity-60';
const SECONDARY =
  'inline-flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] px-3 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)] hover:bg-[var(--edify-surface-muted)] disabled:opacity-60';

export function ChangePasswordForm({ mustChange }: { mustChange: boolean }) {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [status, setStatus] = useState<{ ok: boolean; message: string } | null>(null);
  const [pending, startTransition] = useTransition();

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus(null);
    startTransition(async () => {
      const result = await changePasswordAction({ password, confirm });
      setStatus(result);
      if (result.ok) {
        setPassword('');
        setConfirm('');
      }
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3 rounded-[8px] border border-[var(--edify-border)] p-3" data-form="change-password">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[length:var(--edify-text-label-size)] font-semibold">Change password</p>
        {mustChange ? <Badge tone="warning">Action required</Badge> : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-[length:var(--edify-text-label-size)]">
          <span className="font-medium text-[var(--edify-text-muted)]">New password</span>
          <input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className={INPUT}
          />
        </label>
        <label className="space-y-1 text-[length:var(--edify-text-label-size)]">
          <span className="font-medium text-[var(--edify-text-muted)]">Confirm password</span>
          <input
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            className={INPUT}
          />
        </label>
      </div>
      {status ? (
        <p
          role="status"
          className={`text-[length:var(--edify-text-label-size)] font-medium ${status.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'}`}
        >
          {status.message}
        </p>
      ) : null}
      <button type="submit" disabled={pending} className={PRIMARY}>
        {pending ? 'Saving…' : 'Update password'}
      </button>
    </form>
  );
}

export function TwoStepForm({
  initialInForce,
  requiredByPolicy,
  initialChannel,
  channels,
}: {
  initialInForce: boolean;
  requiredByPolicy: boolean;
  initialChannel: 'email' | 'sms' | 'app';
  channels: readonly ChannelLine[];
}) {
  const [enabled, setEnabled] = useState(initialInForce);
  const [channel, setChannel] = useState<'email' | 'sms' | 'app'>(initialChannel);
  const [status, setStatus] = useState<{ ok: boolean; message: string } | null>(null);
  const [totpSecret, setTotpSecret] = useState('');
  const [totpUri, setTotpUri] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [totpStatus, setTotpStatus] = useState<{ ok: boolean; message: string } | null>(null);
  const [pending, startTransition] = useTransition();

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus(null);
    startTransition(async () => {
      const result = await updateTwoStepAction({ enabled: requiredByPolicy || enabled, channel });
      setStatus(result);
    });
  }

  function onBeginTotp() {
    setTotpStatus(null);
    startTransition(async () => {
      const res = await beginTotpSetupAction();
      if (!res.ok || !res.secret) {
        setTotpStatus({ ok: false, message: res.message || 'Could not start authenticator setup.' });
        return;
      }
      setTotpSecret(res.secret);
      setTotpUri(res.otpauthUri || '');
    });
  }

  function onConfirmTotp() {
    setTotpStatus(null);
    startTransition(async () => {
      const res = await confirmTotpSetupAction({ secret: totpSecret, code: totpCode });
      setTotpStatus(res);
      if (res.ok) {
        setTotpSecret('');
        setTotpUri('');
        setTotpCode('');
        setEnabled(true);
        setChannel('app');
      }
    });
  }

  return (
    <Card label="Two-step verification">
      <div className="space-y-4">
        <form onSubmit={onSubmit} className="space-y-3" data-form="two-step-settings">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-[length:var(--edify-text-heading-size)] font-semibold">Two-step verification</h2>
              <p className="mt-1 text-[var(--edify-text-muted)]">
                After your password, we send a single-use code to confirm it is you. It means a stolen password on its own is not enough to reach your
                workspace.
              </p>
            </div>
            <Badge tone={requiredByPolicy || enabled ? 'success' : 'neutral'}>{requiredByPolicy || enabled ? 'On' : 'Off'}</Badge>
          </div>

          {requiredByPolicy ? (
            <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
              Your organisation requires two-step verification, so this cannot be turned off. You can still choose where the code is sent.
            </p>
          ) : (
            <label className="flex items-center gap-2 text-[length:var(--edify-text-label-size)] font-semibold">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="h-4 w-4 rounded border-[var(--edify-border-strong)]"
              />
              Require a single-use verification code at sign-in
            </label>
          )}

          {requiredByPolicy || enabled ? (
            <div>
              <p className="text-[length:var(--edify-text-label-size)] font-semibold">Get my code from</p>
              <ul className="mt-2 space-y-2">
                {channels.map((line) => (
                  <li key={line.key} className={`flex items-start gap-2.5 ${line.available ? '' : 'opacity-60'}`} data-channel={line.key}>
                    <input
                      type="radio"
                      name="mfa_channel"
                      value={line.key}
                      checked={channel === line.key}
                      disabled={!line.available}
                      onChange={() => setChannel(line.key)}
                      className="mt-1 h-3.5 w-3.5 shrink-0"
                    />
                    <span>
                      <span className="font-semibold">{line.label}</span>
                      {channel === line.key ? <span className="sr-only"> (in use)</span> : null}
                      <span className="block text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">{line.note}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {status ? (
            <p
              role="status"
              className={`text-[length:var(--edify-text-label-size)] font-medium ${status.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'}`}
            >
              {status.message}
            </p>
          ) : null}

          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={pending} className={PRIMARY}>
              {pending ? 'Saving…' : 'Save two-step settings'}
            </button>
            <button type="button" disabled={pending} onClick={onBeginTotp} className={SECONDARY}>
              Set up authenticator app
            </button>
          </div>
        </form>

        {totpSecret ? (
          <div className="space-y-3 rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface-muted)]/40 p-3" data-form="totp-setup">
            <p className="text-[length:var(--edify-text-label-size)] font-semibold">Enroll Authenticator App</p>
            <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
              Add this manual setup key in Google Authenticator, Microsoft Authenticator, or Authy, then enter the 6-digit code it generates.
            </p>
            <div className="space-y-1">
              <p className="text-[length:var(--edify-text-micro-size)] font-semibold uppercase text-[var(--edify-text-muted)]">Setup Key</p>
              <code className="block break-all rounded bg-[var(--edify-surface)] px-2.5 py-1.5 font-mono text-[13px]">{totpSecret}</code>
              {totpUri ? <p className="break-all text-[11px] text-[var(--edify-text-muted)]">{totpUri}</p> : null}
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <label className="space-y-1 text-[length:var(--edify-text-label-size)]">
                <span className="font-medium text-[var(--edify-text-muted)]">6-digit code</span>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                  placeholder="123456"
                  className={`${INPUT} max-w-[160px]`}
                />
              </label>
              <button type="button" disabled={pending} onClick={onConfirmTotp} className={PRIMARY}>
                Verify &amp; enable
              </button>
            </div>
          </div>
        ) : null}

        {totpStatus ? (
          <p
            role="status"
            className={`text-[length:var(--edify-text-label-size)] font-medium ${totpStatus.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'}`}
          >
            {totpStatus.message}
          </p>
        ) : null}
      </div>
    </Card>
  );
}
