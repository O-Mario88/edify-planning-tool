// Reset-password endpoint. Consumes a token issued by
// /api/auth/forgot-password and updates the user's hashed password.

import { NextResponse } from "next/server";
import { consumeResetToken } from "@/lib/auth-runtime-store";
import { requireCsrf } from "@/lib/csrf";

export const dynamic = "force-dynamic";

type ResetBody = {
  token?: string;
  password?: string;
};

export async function POST(request: Request) {
  const csrf = requireCsrf(request);
  if (csrf) return csrf;

  let body: ResetBody;
  try {
    body = (await request.json()) as ResetBody;
  } catch {
    return NextResponse.json({ ok: false, message: "Invalid request." }, { status: 400 });
  }

  const token = body.token ?? "";
  const password = body.password ?? "";

  const result = consumeResetToken(token, password);
  if (!result.ok) {
    const message =
      result.reason === "WEAK_PASSWORD"
        ? "Password must be at least 6 characters."
        : result.reason === "EXPIRED"
          ? "This reset link has expired. Request a new one."
          : result.reason === "USED"
            ? "This reset link has already been used."
            : "This reset link is invalid.";
    return NextResponse.json({ ok: false, message }, { status: 400 });
  }

  return NextResponse.json({ ok: true, message: "Password updated. You can now sign in." });
}
