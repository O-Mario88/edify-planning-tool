// Shared session + role guard for the /api/cceo/* surface (spec §23).
//
// Every CCEO route: (a) requires a session cookie, (b) 403s unless the
// signed-in role is CCEO (Admin allowed for support/debug), (c) reads all
// data through the signed-in user's staffId. This file is NOT a route
// (no route.ts name) — it's the one place the guard + response envelope
// live so the 14 routes stay thin.

import "server-only";
import { NextResponse } from "next/server";
import { getCurrentUserOrNull, type DemoUser } from "@/lib/auth";

export type NextAction = { label: string; reason: string; href: string };

export type CceoGuard =
  | { user: DemoUser; error: null }
  | { user: null; error: NextResponse };

/** Resolve the session and enforce CCEO (or Admin) scope. */
export async function requireCceo(): Promise<CceoGuard> {
  const user = await getCurrentUserOrNull();
  if (!user) {
    return {
      user: null,
      error: NextResponse.json(
        { error: "Unauthorized — sign in required." },
        { status: 401 },
      ),
    };
  }
  if (user.role !== "CCEO" && user.role !== "Admin") {
    return {
      user: null,
      error: NextResponse.json(
        { error: "Forbidden — this surface is scoped to the CCEO role." },
        { status: 403 },
      ),
    };
  }
  return { user, error: null };
}

/** Canonical { data, nextActions? } envelope, never cached. */
export function ok(data: unknown, nextActions?: NextAction[]) {
  const body =
    nextActions && nextActions.length > 0 ? { data, nextActions } : { data };
  return NextResponse.json(body, { headers: { "Cache-Control": "no-store" } });
}
