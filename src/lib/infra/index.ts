// Infrastructure adapter resolver.
//
// Every external dependency in this codebase goes through an adapter
// that exposes a stable interface and ships TWO implementations:
//
//   • a **dev default** that works locally without any external service
//     (writes to disk, logs to console, in-memory rate-limit, …)
//   • a **production implementation** behind a feature flag, auto-
//     selected when the right env var is present
//
// Application code calls the resolved adapter — it doesn't care which
// implementation is in use. Switching to production is a flip of an
// env var, not a code change.
//
// Boot-time summary is logged once so the runtime makes its mode
// obvious in logs ("storage: dev (file://) · email: console · …").

import "server-only";
import { resolveStorage }       from "./storage";
import { resolveEmail }          from "./email";
import { resolveSms }            from "./sms";
import { resolveObservability }  from "./observability";
import { resolveRateLimit }      from "./rate-limit";
import { resolveCache }          from "./cache";
import { resolveDb }             from "./db";
import { resolveSalesforce }     from "./salesforce";

// Resolve once at module load — adapters are singletons per process.
// Importing this file anywhere gives you the live adapter set.
export const storage       = resolveStorage();
export const email          = resolveEmail();
export const sms            = resolveSms();
export const observability  = resolveObservability();
export const rateLimit      = resolveRateLimit();
export const cache          = resolveCache();
export const db             = resolveDb();
export const salesforce     = resolveSalesforce();

// Banner — printed once at boot. Surfaces in dev console + production
// logs so an operator can tell at a glance which adapters are wired.
// Calling code can also import this for an /admin/health view.

export type BootSummary = {
  storage:      string;
  email:        string;
  sms:          string;
  observability:string;
  rateLimit:    string;
  cache:        string;
  db:           string;
  salesforce:   string;
};

export function bootSummary(): BootSummary {
  return {
    storage:       storage.label,
    email:         email.label,
    sms:           sms.label,
    observability: observability.label,
    rateLimit:     rateLimit.label,
    cache:         cache.label,
    db:            db.label,
    salesforce:    salesforce.label,
  };
}

// Auto-print on first import. Once per process. Skipped under
// vitest so the suite output stays clean.
if (process.env.NODE_ENV !== "test" && !process.env.EDIFY_QUIET_BOOT) {
  const s = bootSummary();
  // eslint-disable-next-line no-console
  console.log(
    "[edify-infra] " +
    `storage=${s.storage} email=${s.email} sms=${s.sms} ` +
    `obs=${s.observability} rate=${s.rateLimit} cache=${s.cache} ` +
    `db=${s.db} salesforce=${s.salesforce}`,
  );
}
