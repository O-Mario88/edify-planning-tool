import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ROLE_REDIRECT, type EdifyRole } from "@/lib/auth-public";

// Single entry point for "go to my dashboard". Resolves the user's role
// from the session cookie set on login, then redirects to the right
// role-specific dashboard. Unauthenticated users land on /login.
export default async function DashboardEntry() {
  const jar = await cookies();
  const role = jar.get("edify-role")?.value as EdifyRole | undefined;
  const target = role ? ROLE_REDIRECT[role] : null;
  redirect(target ?? "/login");
}
