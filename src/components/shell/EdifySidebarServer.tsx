import { getCurrentUser } from "@/lib/auth";
import { EdifySidebar, type EdifyRole } from "@/components/shell/EdifySidebar";

// Server-component wrapper that resolves the active user from the session
// cookie (lib/auth.ts) and renders the existing client-side EdifySidebar
// with the right role + identity. Pages just drop in <EdifySidebarServer />
// — no role hardcoding, no drift between roles and the actual logged-in
// user.
//
// Use the optional `roleOverride` to force a sidebar variant for a screen
// that's role-specific regardless of who's looking (e.g. the HR-only
// support-review tab). 99% of pages should pass nothing.
export async function EdifySidebarServer({
  roleOverride,
}: {
  roleOverride?: EdifyRole;
} = {}) {
  const user = await getCurrentUser();
  return (
    <EdifySidebar
      role={roleOverride ?? user.role}
      user={{ name: user.name, initials: user.initials, online: true }}
    />
  );
}
