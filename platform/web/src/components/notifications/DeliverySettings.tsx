/*
 * "How you are told" (pages/notifications/index.html #delivery-settings):
 * push to all the person's devices, email to their address, and the
 * categories they do not want emailed, as the gateway answers them. Saving
 * them is a save the existing web still makes (docs/migration/43), so the
 * choices are shown as they stand and Change opens the existing page.
 */
import type { NotificationDelivery } from '@/gen/edify/screens/v1/notification_center_pb';

function Choice({ on, children }: { on: boolean; children: React.ReactNode }) {
  return (
    <p className="flex min-h-11 items-center gap-2 text-[13px] font-semibold text-[var(--edify-text)]">
      <span aria-hidden="true" className={`grid h-4 w-4 place-items-center rounded-[4px] border border-[var(--edify-border-strong)] ${on ? 'bg-[var(--brand-primary)] text-white' : ''}`}>
        {on ? '✓' : ''}
      </span>
      <span>{children}</span>
      <span className="sr-only">{on ? '(on)' : '(off)'}</span>
    </p>
  );
}

export function DeliverySettings({ delivery, existingWebUrl }: { delivery: NotificationDelivery; existingWebUrl: string }) {
  return (
    <section id="delivery-settings" aria-labelledby="delivery-settings-heading" className="space-y-4 card p-4 shadow-[var(--edify-shadow-sm)]">
      <div>
        <h2 id="delivery-settings-heading" className="text-[15px] font-bold">How you are told</h2>
        <p className="text-[13px] text-[var(--edify-text-muted)]">Everything is always here in Edify. Choose where else it reaches you.</p>
      </div>
      <div className="space-y-2 border-t border-[var(--edify-border)] pt-3">
        <h3 className="text-[13px] font-bold">All your phones and computers</h3>
        <p className="text-[13px] text-[var(--edify-text-muted)]">Every notification, on each device you turned on above. Urgent notices still reach them.</p>
        <Choice on={delivery.pushEnabled}>Send push notifications</Choice>
      </div>
      <div className="space-y-2 border-t border-[var(--edify-border)] pt-3">
        <h3 className="text-[13px] font-bold">Email to {delivery.address}</h3>
        {!delivery.emailConfigured ? (
          <p className="text-[13px] text-[var(--edify-warning-text)]">Email is not set up on this server yet, so nothing is emailed for now. Your choice is kept for when it is.</p>
        ) : null}
        <p className="text-[13px] text-[var(--edify-text-muted)]">
          Only what someone sends you (a Send to, a Follow Up, a reminder) and urgent notices are emailed. Urgent notices are always emailed.
        </p>
        <Choice on={delivery.emailEnabled}>Email me</Choice>
        {delivery.categories.length > 0 ? (
          <div className="space-y-1">
            <p className="text-[13px] text-[var(--edify-text-muted)]">Don&apos;t email me about:</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {delivery.categories.map((category) => (
                <Choice key={category.value} on={category.muted}>
                  {category.label}
                </Choice>
              ))}
            </div>
          </div>
        ) : null}
      </div>
      <div className="flex items-center gap-3">
        <a href={`${existingWebUrl}/notifications/#delivery-settings`} className="inline-flex h-8 items-center rounded-[var(--radius-control)] bg-[var(--brand-primary)] px-4 text-[12px] font-bold text-white">
          Change
        </a>
        {delivery.saved ? (
          <span role="status" className="text-[13px] font-semibold text-[#047857]">
            Saved.
          </span>
        ) : null}
      </div>
    </section>
  );
}
