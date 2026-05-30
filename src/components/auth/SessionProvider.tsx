import { type ReactNode } from "react";
import { getCurrentUser } from "@/lib/auth";
import { SessionProviderClient, type Session } from "@/components/auth/SessionContext";

// Server wrapper. Reads the cookie-resolved user once per request and
// pushes a serializable Session into the client context. Drop it into
// the root layout and every client component below it can call
// `useSession()` / `useRole()` without prop drilling.
export async function SessionProvider({ children }: { children: ReactNode }) {
  const u = await getCurrentUser();
  const value: Session = {
    role:     u.role,
    name:     u.name,
    initials: u.initials,
    email:    u.email,
  };
  return <SessionProviderClient value={value}>{children}</SessionProviderClient>;
}
