// GET /api/cceo/today-actions — the role action board (the same engine the
// dashboard greeting hero + CommandStack consume): mission header, next-3
// actions, full inbox, done-today checklist, changed-since feed. The engine
// reads the `edify-last-viewed` cookie itself, so we pass the raw cookie
// header through. ?fy=/?week=/?month= are ignored (the board is "today").

import type { NextRequest } from "next/server";
import { requireCceo, ok, type NextAction } from "../_auth";
import { buildRoleActionBoard } from "@/lib/actions/role-action-engine";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  const board = buildRoleActionBoard({
    role: user.role,
    name: user.name,
    email: user.email,
    cookieHeader: req.headers.get("cookie"),
  });

  const nextActions: NextAction[] = board.nextThree.map((a) => ({
    label: a.title,
    reason: a.description,
    href: a.primaryAction.href ?? "/dashboard",
  }));

  return ok(board, nextActions);
}
