// /focus — Focus Mode for field users.
//
// CCEO + Partner users only. Other roles get bounced to their own
// dashboard — Focus Mode is deliberately field-shaped. The page
// pulls the user's actions from the role-action-engine, then projects
// them through the FocusModeView composer for a minimal, mobile-first
// surface with one decision per glance.
//
// No charts. No analytics. By design.

import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { buildRoleActionBoard } from "@/lib/actions/role-action-engine";
import { FocusModeView } from "@/components/focus/FocusModeView";
import {
  cceoFocusFromActions,
  partnerFocusFromActions,
} from "@/components/focus/focus-composers";

const FOCUS_ROLES = new Set([
  "CCEO",
  "PartnerAdmin",
  "PartnerFieldOfficer",
  "PartnerViewer",
]);

export default async function FocusPage() {
  const user = await getCurrentUser();
  if (!FOCUS_ROLES.has(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  // Read the same cookie header the CommandStack uses so digests
  // share the "last viewed" state.
  const jar = await cookies();
  const cookieHeader = jar.getAll().map((c) => `${c.name}=${c.value}`).join("; ");
  const board = buildRoleActionBoard({
    role: user.role, name: user.name, email: user.email, cookieHeader,
  });

  if (user.role === "CCEO") {
    const focus = cceoFocusFromActions(user.name, board.inbox);
    return <FocusModeView {...focus} variant="cceo" />;
  }
  // Partner sub-types share the partner Focus layout.
  const focus = partnerFocusFromActions(user.name, board.inbox);
  return <FocusModeView {...focus} variant="partner" />;
}
