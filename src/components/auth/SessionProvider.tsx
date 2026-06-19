import { type ReactNode } from "react";
import { getCurrentUserOrNull } from "@/lib/auth";
import { SessionProviderClient, type Session } from "@/components/auth/SessionContext";

// Server wrapper. Reads the cookie-resolved user once per request and
// pushes a serializable Session into the client context. Drop it into
// the root layout and every client component below it can call
// `useSession()` / `useRole()` without prop drilling.
//
// This sits in the ROOT layout, so it renders for EVERY request —
// including anonymous traffic to /login, /signup, and the public pages.
// It must therefore use the null-returning resolver: the throwing
// getCurrentUser() would 500 the entire site for anyone without a
// session (production hard-throws on anonymous, which would make even
// /login unreachable). Page-level route protection is middleware's job;
// this provider only surfaces identity. A null session is fully
// supported downstream (SessionContext defaults to null and
// useSession()/useRole() fall back gracefully).
export async function SessionProvider({ children }: { children: ReactNode }) {
  const u = await getCurrentUserOrNull();
  const value: Session | null = u
    ? {
        role:     u.role,
        name:     u.name,
        initials: u.initials,
        email:    u.email,
      }
    : null;
  return <SessionProviderClient value={value}>{children}</SessionProviderClient>;
}
