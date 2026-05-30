// SMS adapter.
//
// Two implementations:
//
//   • `console` — prints the SMS. Default in dev.
//
//   • `twilio` — Twilio Programmable Messaging REST API via fetch
//     (no SDK). Activated when TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN
//     + TWILIO_FROM are present.
//
// Critical-priority notifications route here from the dispatcher.

import "server-only";

export type SmsMessage = {
  to:    string;          // E.164, e.g. "+256700000000"
  body:  string;
  /** Free-form template tag for logs. */
  template?: string;
};

export type SmsResult =
  | { ok: true; id: string }
  | { ok: false; error: string };

export type SmsAdapter = {
  label: string;
  send(msg: SmsMessage): Promise<SmsResult>;
};

// ────────── console impl ────────────────────────────────────────────

const consoleAdapter: SmsAdapter = {
  label: "console",
  async send(msg) {
    // eslint-disable-next-line no-console
    console.log(
      "\n────────────── SMS (dev console) ──────────────\n" +
      `to:       ${msg.to}\n` +
      `template: ${msg.template ?? "-"}\n` +
      `\n${msg.body}\n` +
      "────────────────────────────────────────────────\n",
    );
    return { ok: true, id: `sms_con_${Date.now().toString(36)}` };
  },
};

// ────────── Twilio impl ─────────────────────────────────────────────

function makeTwilioAdapter(): SmsAdapter {
  const sid    = requireEnv("TWILIO_ACCOUNT_SID");
  const token  = requireEnv("TWILIO_AUTH_TOKEN");
  const from   = requireEnv("TWILIO_FROM");
  const auth   = "Basic " + Buffer.from(`${sid}:${token}`).toString("base64");

  return {
    label: "twilio",
    async send(msg) {
      // E.164 sanity check — Twilio rejects malformed numbers with a
      // 400, but failing here gives a much cleaner audit message.
      if (!/^\+\d{7,15}$/.test(msg.to)) {
        return { ok: false, error: `invalid E.164: ${msg.to}` };
      }
      const url = `https://api.twilio.com/2010-04-01/Accounts/${sid}/Messages.json`;
      const params = new URLSearchParams({ From: from, To: msg.to, Body: msg.body });
      const res = await fetch(url, {
        method: "POST",
        headers: {
          authorization: auth,
          "content-type": "application/x-www-form-urlencoded",
        },
        body: params,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        return { ok: false, error: `twilio ${res.status}: ${text.slice(0, 200)}` };
      }
      const j = await res.json().catch(() => null) as { sid?: string } | null;
      return { ok: true, id: j?.sid ?? "twilio_unknown" };
    },
  };
}

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

// ────────── resolver ────────────────────────────────────────────────

export function resolveSms(): SmsAdapter {
  if (process.env.TWILIO_ACCOUNT_SID && process.env.TWILIO_AUTH_TOKEN && process.env.TWILIO_FROM) {
    try { return makeTwilioAdapter(); }
    catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[edify-infra] sms: Twilio config failed; using console. Reason:", String(err));
    }
  }
  return consoleAdapter;
}
