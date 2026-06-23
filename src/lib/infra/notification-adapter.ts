// Single adapter seam for the legacy notification path (spec §3, §19).
//
// PRINCIPLE: there must be exactly one place notifications are created — the
// backend DomainEventService. The legacy in-memory `emitNotification` server
// action path (src/lib/actions/audit.ts) predates it. Rather than leave two
// independent emitters that can double-fire, every legacy call now funnels
// through this adapter:
//
//   • when a forwarder is configured, the event is routed to the backend
//     DomainEventService (the one source of truth) and NOT duplicated;
//   • when no forwarder is configured, the legacy path is being used DIRECTLY —
//     which is a production smell, so we record a system-health warning that the
//     migration is incomplete (surfaced via legacyNotificationHealth()).
//
// This guarantees the spec rules: "do not create duplicate notifications from
// both legacy and new systems", "keep legacy wrapper only if it forwards", and
// "add system health warning if legacy notification path is still used directly".

import "server-only";
import { observability } from "./index";
import type { NotificationRecord } from "@/lib/actions/audit";

export type LegacyForwarder = (note: NotificationRecord) => void | Promise<void>;

type AdapterState = {
  /** How many times the legacy path fired with NO forwarder configured. */
  directUses: number;
  /** How many times the legacy path was forwarded to DomainEventService. */
  forwardedUses: number;
  lastUseAt?: string;
  lastTemplate?: string;
  forwarderConfigured: boolean;
};

const STATE_KEY = "__edify_legacy_notification_adapter__";
type GlobalWithState = typeof globalThis & {
  [STATE_KEY]?: { state: AdapterState; forwarder: LegacyForwarder | null };
};

function box() {
  const g = globalThis as GlobalWithState;
  if (!g[STATE_KEY]) {
    g[STATE_KEY] = {
      state: { directUses: 0, forwardedUses: 0, forwarderConfigured: false },
      forwarder: null,
    };
  }
  return g[STATE_KEY]!;
}

/** Wire the adapter to the backend DomainEventService (the production seam).
 *  Once set, legacy emitNotification calls forward here and are NOT stored as a
 *  second, independent notification. */
export function setLegacyNotificationForwarder(f: LegacyForwarder | null): void {
  const b = box();
  b.forwarder = f;
  b.state.forwarderConfigured = !!f;
}

/** Funnel a legacy notification through the single adapter seam. */
export function routeLegacyNotification(note: NotificationRecord): void {
  const b = box();
  b.state.lastUseAt = new Date().toISOString();
  b.state.lastTemplate = note.template;

  if (b.forwarder) {
    b.state.forwardedUses += 1;
    try {
      void Promise.resolve(b.forwarder(note)).catch((err) =>
        observability.captureError(err, { tags: { surface: "notification-adapter.forward", template: note.template } }),
      );
    } catch (err) {
      observability.captureError(err, { tags: { surface: "notification-adapter.forward", template: note.template } });
    }
    return;
  }

  // No forwarder → the legacy path is being used directly. In production this is
  // a health warning: notifications should route through DomainEventService.
  b.state.directUses += 1;
  const allowLegacy = process.env.EDIFY_ALLOW_LEGACY_NOTIFICATIONS === "1";
  if (!allowLegacy) {
    observability.captureMessage(
      `system-health: legacy emitNotification used directly (template=${note.template}) — route through DomainEventService`,
      process.env.NODE_ENV === "production" ? "warning" : "info",
      { tags: { surface: "notification-adapter", template: note.template } },
    );
  }
}

/** System-health snapshot of the legacy notification path (spec §19). A non-zero
 *  `directUses` in production means the migration to DomainEventService is
 *  incomplete and notifications may be flowing through the legacy emitter. */
export function legacyNotificationHealth(): AdapterState {
  return { ...box().state };
}

/** Test reset hook. */
export function __resetLegacyNotificationAdapter(): void {
  const g = globalThis as GlobalWithState;
  g[STATE_KEY] = {
    state: { directUses: 0, forwardedUses: 0, forwarderConfigured: false },
    forwarder: null,
  };
}
