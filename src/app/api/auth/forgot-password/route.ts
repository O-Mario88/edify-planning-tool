// Forgot-password endpoint.
//
// Generates a reset token for known emails and stores it in the runtime
// store. Returns the same safe message in both cases — we never reveal
// whether an email is in the system.
//
// Real email delivery is not wired in this codebase; the response
// includes `devToken` ONLY in non-production builds so a tester can
// complete the reset flow end-to-end. The token is integration-ready —
// drop a real mailer in here and the dev surface disappears.

import { NextResponse } from "next/server";
import { createResetToken } from "@/lib/auth-runtime-store";
import { requireCsrf } from "@/lib/csrf";
import { ipFromRequest, rateLimit, rateLimitResponse } from "@/lib/rate-limit";

export const dynamic = "force-dynamic";

type ForgotBody = { email?: string };

const SAFE_MESSAGE = "If this email exists, a reset link will be sent.";

// 4 forgot-password attempts per IP per 10 minutes. Generous enough
// for a real user trying a couple of email addresses; tight enough to
// stop email-enumeration scripts.
const FORGOT_RATE = { max: 4, windowMs: 10 * 60 * 1000 } as const;

export async function POST(request: Request) {
  const csrf = requireCsrf(request);
  if (csrf) return csrf;

  const ip = ipFromRequest(request);
  const rl = await rateLimit(`forgot:${ip}`, FORGOT_RATE);
  if (!rl.ok) {
    return rateLimitResponse(rl, "Too many reset requests. Please wait and try again.");
  }

  let body: ForgotBody;
  try {
    body = (await request.json()) as ForgotBody;
  } catch {
    // Same safe message even on malformed body — avoid leaking semantics.
    return NextResponse.json({ ok: true, message: SAFE_MESSAGE });
  }

  const email = body.email?.trim().toLowerCase() ?? "";
  const record = email ? createResetToken(email) : null;

  // Constant-ish delay so attackers can't time-test which emails exist.
  await new Promise((r) => setTimeout(r, 120));

  // Production: send the email here (record.token in the link).
  // Dev: expose the token to the client so the demo flow completes.
  const payload: Record<string, unknown> = { ok: true, message: SAFE_MESSAGE };
  if (record && process.env.NODE_ENV !== "production") {
    payload.devToken = record.token;
    payload.devExpiresAt = record.expiresAt;
  }
  return NextResponse.json(payload);
}
