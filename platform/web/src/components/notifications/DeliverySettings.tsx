/*
 * "How you are told" (pages/notifications/index.html #delivery-settings):
 * push to all the person's devices, email to their address, and the
 * categories they do not want emailed. Saves natively through Go
 * POST /api/v1/notifications/preferences (Step 3B — zero Django handoff).
 */
import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';

import type { NotificationDelivery } from '@/gen/edify/screens/v1/notification_center_pb';
import { asReader } from '@/lib/auth';
import { gatewayJson } from '@/lib/gatewayJson';

async function savePreferences(formData: FormData) {
  'use server';
  const pushEnabled = formData.get('push_enabled') === 'on';
  const emailEnabled = formData.get('email_enabled') === 'on';
  const mutedCategories = formData
    .getAll('muted_categories')
    .map((v) => String(v).trim())
    .filter(Boolean);

  await asReader((token) =>
    gatewayJson('/api/v1/notifications/preferences', token, {
      method: 'POST',
      body: { emailEnabled, pushEnabled, mutedCategories },
    }),
  );
  revalidatePath('/notifications');
  redirect('/notifications?saved=1#delivery-settings');
}

function Choice({
  name,
  value,
  on,
  children,
}: {
  name: string;
  value?: string;
  on: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="flex min-h-11 cursor-pointer items-center gap-2 text-[13px] font-semibold text-[var(--edify-text)]">
      <input
        type="checkbox"
        name={name}
        value={value}
        defaultChecked={on}
        className="h-4 w-4 rounded-[4px] border border-[var(--edify-border-strong)] accent-[var(--brand-primary)]"
      />
      <span aria-hidden="true" className="sr-only">
        {on ? '✓' : ''}
      </span>
      <span>{children}</span>
      <span className="sr-only">{on ? '(on)' : '(off)'}</span>
    </label>
  );
}

export function DeliverySettings({ delivery }: { delivery: NotificationDelivery; existingWebUrl?: string }) {
  return (
    <section id="delivery-settings" aria-labelledby="delivery-settings-heading" className="space-y-4 card p-4 shadow-[var(--edify-shadow-sm)]">
      <div>
        <h2 id="delivery-settings-heading" className="text-[15px] font-bold">How you are told</h2>
        <p className="text-[13px] text-[var(--edify-text-muted)]">Everything is always here in Edify. Choose where else it reaches you.</p>
      </div>
      <form action={savePreferences} className="space-y-4">
        <div className="space-y-2 border-t border-[var(--edify-border)] pt-3">
          <h3 className="text-[13px] font-bold">All your phones and computers</h3>
          <p className="text-[13px] text-[var(--edify-text-muted)]">Every notification, on each device you turned on above. Urgent notices still reach them.</p>
          <Choice name="push_enabled" on={delivery.pushEnabled}>Send push notifications</Choice>
        </div>
        <div className="space-y-2 border-t border-[var(--edify-border)] pt-3">
          <h3 className="text-[13px] font-bold">Email to {delivery.address}</h3>
          {!delivery.emailConfigured ? (
            <p className="text-[13px] text-[var(--edify-warning-text)]">Email is not set up on this server yet, so nothing is emailed for now. Your choice is kept for when it is.</p>
          ) : null}
          <p className="text-[13px] text-[var(--edify-text-muted)]">
            Only what someone sends you (a Send to, a Follow Up, a reminder) and urgent notices are emailed. Urgent notices are always emailed.
          </p>
          <Choice name="email_enabled" on={delivery.emailEnabled}>Email me</Choice>
          {delivery.categories.length > 0 ? (
            <div className="space-y-1">
              <p className="text-[13px] text-[var(--edify-text-muted)]">Don&apos;t email me about:</p>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {delivery.categories.map((category) => (
                  <Choice key={category.value} name="muted_categories" value={category.value} on={category.muted}>
                    {category.label}
                  </Choice>
                ))}
              </div>
            </div>
          ) : null}
        </div>
        <div className="flex items-center gap-3">
          <button type="submit" className="inline-flex h-8 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-4 text-[12px] font-bold text-white">
            Save preferences
          </button>
          {delivery.saved ? (
            <span role="status" className="text-[13px] font-semibold text-[#047857]">
              Saved.
            </span>
          ) : null}
        </div>
      </form>
    </section>
  );
}
