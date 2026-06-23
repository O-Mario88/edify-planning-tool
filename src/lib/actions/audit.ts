// Shared audit + notification emitters for server actions.
//
// Every Bucket-C server action MUST call `emitAudit` (and usually
// `emitNotification`) after a successful mutation. Centralising this
// gives us:
//
//   • One place to set the row shape so production migration is a
//     find-and-replace (these in-memory stores are shaped exactly
//     like the Prisma `AuditEvent` and `Notification` models in
//     `prisma/schema.prisma`).
//   • A repo-grep test that fails CI if a server action mutates
//     state without calling `emitAudit` — see audit-coverage.test.ts.
//   • A single feature flag (process.env.EDIFY_AUDIT_SINK) to switch
//     between memory, console, and Prisma once the DB is wired.
//
// The stores live on `globalThis` so they survive Next's dev HMR and
// share state across both server actions and read-side server
// components within the same Node process.

import "server-only";

// ─── Audit event shape ──────────────────────────────────────────────
// Mirror of prisma.schema.AuditEvent. Adding/removing a field here
// must be matched in the schema or the swap will fail typecheck.

export type AuditEventRecord = {
  id:          string;
  action:      string;   // "fundPlan.approved" / "fundPlan.returned" / ...
  subjectKind: string;   // "FundApprovalItem" / "Plan" / "WeeklyFundRequest"
  subjectId:   string;
  actorId:     string;   // staffId
  actorRole:   string;
  actorName?:  string;
  payload?:    Record<string, unknown>;
  createdAt:   string;   // ISO
};

// ─── Notification shape ─────────────────────────────────────────────
// Mirror of prisma.schema.Notification.

export type NotificationRecord = {
  id:        string;
  userId:    string;            // recipient staffId
  template:  string;            // "fundPlan.approved" — copy lives elsewhere
  channel:   "Inbox" | "Email" | "SMS";
  title:     string;
  body:      string;
  href?:     string;
  read:      boolean;
  readAt?:   string;
  createdAt: string;
  // Optional task context — maps to the Notification.payload JSON column
  // in prisma, kept flat here so read-side pages render without parsing.
  dueDate?:           string;   // "Today" / "Thu 17:00" / "3 days overdue"
  recommendedAction?: string;   // the one concrete next step
  actionLabel?:       string;   // label for the single action link (href)
  category?:          string;   // "Planning" / "Payment" / "Partner" / ...
  priority?:          "normal" | "important" | "urgent" | "critical";
  actionRequired?:    boolean;
};

// ─── Global stores (HMR-safe) ───────────────────────────────────────

type Store = {
  audits: AuditEventRecord[];
  notifications: NotificationRecord[];
};

const STORE_KEY = "__edify_action_store__";
type GlobalWithStore = typeof globalThis & { [STORE_KEY]?: Store };

function getStore(): Store {
  const g = globalThis as GlobalWithStore;
  if (!g[STORE_KEY]) g[STORE_KEY] = { audits: [], notifications: [] };
  return g[STORE_KEY]!;
}

function randomId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

// ─── Emitters ───────────────────────────────────────────────────────

export function emitAudit(input: Omit<AuditEventRecord, "id" | "createdAt">): AuditEventRecord {
  const event: AuditEventRecord = {
    id: randomId("aud"),
    createdAt: new Date().toISOString(),
    ...input,
  };
  getStore().audits.unshift(event);
  // Newest-first to keep `/admin/audit-log` queries O(1) on the head.
  return event;
}

export function emitNotification(
  input: Omit<NotificationRecord, "id" | "createdAt" | "read"> & { read?: boolean },
): NotificationRecord {
  const note: NotificationRecord = {
    id: randomId("not"),
    createdAt: new Date().toISOString(),
    read: input.read ?? false,
    ...input,
  };
  getStore().notifications.unshift(note);
  dispatchSafely(note);
  return note;
}

// Bulk variant for fan-out (one event, N recipients). All written
// under the same parent timestamp so the inbox order is stable.
export function emitNotificationFanOut(
  recipients: string[],
  input: Omit<NotificationRecord, "id" | "createdAt" | "read" | "userId">,
): NotificationRecord[] {
  const at = new Date().toISOString();
  return recipients.map((userId) => {
    const note: NotificationRecord = {
      id: randomId("not"),
      createdAt: at,
      read: false,
      userId,
      ...input,
    };
    getStore().notifications.unshift(note);
    dispatchSafely(note);
    return note;
  });
}

// Lazy import to avoid an import cycle: dispatch.ts imports audit.ts
// (for the NotificationRecord type) so we resolve at call time.
function dispatchSafely(note: NotificationRecord): void {
  // Single adapter seam (spec §3): funnel every legacy emit through the adapter
  // so it either forwards to DomainEventService or records a health warning that
  // the legacy path is being used directly. Never let this throw into the caller.
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { routeLegacyNotification } = require("@/lib/infra/notification-adapter") as {
      routeLegacyNotification: (n: NotificationRecord) => void;
    };
    routeLegacyNotification(note);
  } catch {
    // Adapter unavailable (isolated unit test) — fall through to dispatch.
  }
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { dispatchAfterEmit } = require("@/lib/infra/dispatch") as {
      dispatchAfterEmit: (n: NotificationRecord) => void;
    };
    dispatchAfterEmit(note);
  } catch (err) {
    // Dispatcher hasn't been wired in this environment (e.g. a unit
    // test loading audit.ts in isolation). Report via observability
    // when available so we don't silently drop real fan-outs.
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const obs = require("@/lib/infra/observability") as {
        resolveObservability: () => { captureMessage: (m: string) => void };
      };
      obs.resolveObservability().captureMessage(
        `audit.dispatchSafely: dispatcher unavailable — ${String(err)}`,
      );
    } catch {
      // Both modules unavailable — quietly drop.
    }
  }
}

// ─── Read-side helpers (used by /admin/audit-log + /notifications) ──
//
// These intentionally return shallow copies so a consumer can sort /
// slice without corrupting the head of the global store.

export function readAuditLog(opts?: {
  subjectKind?: string;
  subjectId?: string;
  actorId?: string;
  limit?: number;
}): AuditEventRecord[] {
  let rows = getStore().audits;
  if (opts?.subjectKind) rows = rows.filter((r) => r.subjectKind === opts.subjectKind);
  if (opts?.subjectId)   rows = rows.filter((r) => r.subjectId === opts.subjectId);
  if (opts?.actorId)     rows = rows.filter((r) => r.actorId === opts.actorId);
  return rows.slice(0, opts?.limit ?? 200);
}

export function readNotificationsFor(userId: string, opts?: { unreadOnly?: boolean; limit?: number }): NotificationRecord[] {
  let rows = getStore().notifications.filter((n) => n.userId === userId);
  // Role-token reads return the live emitted rows only. The spec §20
  // CCEO catalogue is materialised by the backend (emitted as
  // NotificationRecord rows by the corresponding workflow jobs) — no
  // frontend mock fallback.
  if (opts?.unreadOnly) rows = rows.filter((n) => !n.read);
  return rows.slice(0, opts?.limit ?? 50);
}

// Test / reset hook — only used from vitest setup. In production this
// is a no-op call site that should be wrapped behind a env check at
// the caller, since the underlying store will be Postgres.
export function __resetActionStore() {
  const g = globalThis as GlobalWithStore;
  g[STORE_KEY] = { audits: [], notifications: [] };
}
