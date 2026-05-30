"use client";

import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import type { EdifyRole } from "@/lib/auth-public";

// Thin compat wrapper around RoleBottomNav. When no `role` prop is
// passed the underlying nav resolves the role from the cookie-driven
// SessionContext, so callers don't need to know the user's role.
// Older call sites that explicitly pass a role still win.
export function MobileBottomNav({ role }: { role?: EdifyRole } = {}) {
  return <RoleBottomNav role={role} />;
}
