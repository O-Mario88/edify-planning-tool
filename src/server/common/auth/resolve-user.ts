import "server-only";
import { EdifyRole } from "@prisma/client";
import { getCurrentUserOrNull } from "@/lib/auth";
import { prisma } from "../../prisma/prisma.service";
import type { AuthUser } from "./auth-user";

// edify-web's signed session cookie stays the CREDENTIAL; the DB User table is
// the IDENTITY. We resolve the AuthUser the ported services expect by looking
// the signed-in email up in the DB (exactly what JwtStrategy.validate did, but
// keyed by email instead of a JWT sub). Reading roles/activeRole from the DB row
// also sidesteps the web↔EdifyRole string mismatch (e.g. "RVP" vs
// "RegionalVicePresident") — we never trust the web role string for identity.

// The few web-only accounts with no DB User row (the env-gated super-admin)
// still need a usable principal. Map their web role onto an EdifyRole.
const WEB_ROLE_TO_EDIFY_ROLE: Record<string, EdifyRole> = {
  Admin: EdifyRole.Admin,
};

/** Resolve the current request's principal, or null if unauthenticated. */
export async function resolveAuthUser(): Promise<AuthUser | null> {
  const session = await getCurrentUserOrNull();
  if (!session) return null;

  const dbUser = await prisma.user.findFirst({
    where: { email: session.email, isActive: true, deletedAt: null },
    include: { staffProfile: true },
  });

  if (dbUser) {
    return {
      userId: dbUser.id,
      email: dbUser.email,
      name: dbUser.name,
      roles: dbUser.roles,
      activeRole: dbUser.activeRole,
      staffProfileId: dbUser.staffProfile?.id,
    };
  }

  // No DB row (super-admin / unseeded account): synthesize from the session.
  const role = WEB_ROLE_TO_EDIFY_ROLE[String(session.role)] ?? EdifyRole.Admin;
  return {
    userId: `web:${session.email}`,
    email: session.email,
    name: session.name,
    roles: [role],
    activeRole: role,
    staffProfileId: undefined,
  };
}
