import { headers } from "next/headers";
import { DemoStoreProvider } from "@/components/demo/DemoStore";
import { Toaster } from "@/components/demo/Toaster";
import { RoleSwitcher } from "@/components/demo/RoleSwitcher";
import { getCurrentUser } from "@/lib/auth";

// Server wrapper that mounts the demo-mode interactivity layer:
//   • DemoStoreProvider — client-side overlay store (localStorage)
//   • Toaster           — top-right toast stack listening to the store
//   • RoleSwitcher      — floating bottom-right widget for live demos
//                         (dev-only; never shown in production builds)
//
// Hidden on the auth surfaces (/login, /signup, /forgot-password) so
// the role switcher doesn't appear before anyone signs in.

export async function DemoShell({ children }: { children: React.ReactNode }) {
  const h = await headers();
  const path = h.get("x-invoke-path") ?? h.get("x-pathname") ?? "";
  const isAuthRoute = path.startsWith("/login") || path.startsWith("/signup") || path.startsWith("/forgot-password");
  const u = await getCurrentUser().catch(() => null);
  const isDev = process.env.NODE_ENV !== "production";

  return (
    <DemoStoreProvider>
      {children}
      <Toaster />
      {isDev && !isAuthRoute && u && <RoleSwitcher currentRole={u.role} />}
    </DemoStoreProvider>
  );
}
