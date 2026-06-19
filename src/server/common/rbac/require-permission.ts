import type { AuthUser } from "../auth/auth-user";
import { ForbiddenError } from "../errors";
import { permissionsForRole, type PermissionKey } from "./permissions";

// Replaces edify-api's Nest PermissionsGuard + @RequirePermissions decorator.
// Route handlers / service entrypoints call requirePermission() where the
// controller used to declare @RequirePermissions(...). Object-level checks
// (ownership/scope) remain inside services via AuthorizationService.assertCanAccess.

/** Throw ForbiddenError unless the user's active role grants ALL given perms. */
export function requirePermission(user: AuthUser, ...perms: PermissionKey[]): void {
  const granted = new Set(permissionsForRole(user.activeRole));
  const missing = perms.filter((p) => !granted.has(p));
  if (missing.length) {
    throw new ForbiddenError(`Missing permission(s): ${missing.join(", ")}`);
  }
}

/** Non-throwing variant for conditional UI/data gating. */
export function hasPermission(user: AuthUser, perm: PermissionKey): boolean {
  return permissionsForRole(user.activeRole).includes(perm);
}
