// Email adapter — transactional sends.
//
// Two implementations:
//
//   • `console` — prints the email to stdout. Default in dev so the
//     password-reset link and other transactional sends are visible
//     without provisioning a mail provider.
//
//   • `resend` — Resend HTTP API. Activated when RESEND_API_KEY is
//     set. Uses fetch directly so we don't pull in the Resend SDK
//     (small payload, simple auth, no SDK churn).
//
// All implementations accept a normalised EmailMessage; the dispatch
// layer (`infra/dispatch.ts`) routes notifications through it for
// `channel === "Email"` rows.

import "server-only";

export type EmailMessage = {
  to:       string | string[];
  subject:  string;
  text:     string;
  html?:    string;
  /** Override the configured from address. */
  from?:    string;
  replyTo?: string;
  /** Free-form template tag — surfaces in delivery logs. */
  template?: string;
  /** Idempotency key — used by Resend to deduplicate retries. */
  idempotencyKey?: string;
};

export type EmailResult =
  | { ok: true; id: string }
  | { ok: false; error: string };

export type EmailAdapter = {
  label: string;
  send(msg: EmailMessage): Promise<EmailResult>;
};

// ────────── console impl ────────────────────────────────────────────

const consoleAdapter: EmailAdapter = {
  label: "console",
  async send(msg) {
    const to = Array.isArray(msg.to) ? msg.to.join(", ") : msg.to;
    // eslint-disable-next-line no-console
    console.log(
      "\n────────────── EMAIL (dev console) ──────────────\n" +
      `to:        ${to}\n` +
      `from:      ${msg.from ?? "noreply@edify.dev"}\n` +
      `subject:   ${msg.subject}\n` +
      `template:  ${msg.template ?? "-"}\n` +
      `\n${msg.text}\n` +
      "─────────────────────────────────────────────────\n",
    );
    return { ok: true, id: `con_${Date.now().toString(36)}` };
  },
};

// ────────── Resend impl ─────────────────────────────────────────────

function makeResendAdapter(): EmailAdapter {
  const apiKey = requireEnv("RESEND_API_KEY");
  const from = process.env.EMAIL_FROM_ADDRESS ?? "Edify <noreply@edify.app>";
  return {
    label: "resend",
    async send(msg) {
      const body = {
        from: msg.from ?? from,
        to: Array.isArray(msg.to) ? msg.to : [msg.to],
        subject: msg.subject,
        text: msg.text,
        html: msg.html,
        reply_to: msg.replyTo,
        tags: msg.template ? [{ name: "template", value: msg.template }] : undefined,
      };
      const headers: Record<string, string> = {
        "content-type": "application/json",
        authorization: `Bearer ${apiKey}`,
      };
      if (msg.idempotencyKey) headers["idempotency-key"] = msg.idempotencyKey;

      const res = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        return { ok: false, error: `resend ${res.status}: ${text.slice(0, 200)}` };
      }
      const j = await res.json().catch(() => null) as { id?: string } | null;
      return { ok: true, id: j?.id ?? `resend_unknown` };
    },
  };
}

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

// ────────── resolver ────────────────────────────────────────────────

export function resolveEmail(): EmailAdapter {
  if (process.env.RESEND_API_KEY) {
    try { return makeResendAdapter(); }
    catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[edify-infra] email: Resend config failed; using console. Reason:", String(err));
    }
  }
  return consoleAdapter;
}
