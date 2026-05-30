"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { EdifyRole } from "@/lib/auth-public";

// Client-side session shape. The full DemoUser lives server-side; we only
// surface the parts client components actually need for rendering.
export type Session = {
  role: EdifyRole;
  name: string;
  initials: string;
  email: string;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProviderClient({
  value,
  children,
}: {
  value: Session;
  children: ReactNode;
}) {
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

// Read the current session from any client component. Returns null when
// rendered outside a SessionProvider (e.g. login screen). Components that
// need to render before sign-in fall back gracefully.
export function useSession(): Session | null {
  return useContext(SessionContext);
}

// Convenience: get the role with a sensible default for unauth views.
export function useRole(defaultRole: EdifyRole = "CCEO"): EdifyRole {
  return useContext(SessionContext)?.role ?? defaultRole;
}
