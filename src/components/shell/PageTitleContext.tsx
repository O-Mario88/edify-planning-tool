"use client";

// Page-title + identity context.
//
// One context, two responsibilities:
//   • Title/date: pages register their title via `useSetPageTitle()`
//     so the shell-level <MobileTopBar> reads the right text.
//   • Identity:   the signed-in user's initials / name / avatar color
//     are stamped here at the shell layer so any descendant (MobileTopBar,
//     PageHeader, future drawers) can render the avatar without
//     prop-drilling.
//
// Identity is set once at the shell layout boundary (server-resolved
// from the cookie session); it never changes within a route, so a
// single context provider is the right shape.

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Message } from "@/lib/messages-v2/types";

type PageMeta = {
  title:      string;
  /** Optional date / period label rendered next to the title in the
   *  dark bar. Pages like Today / My Targets set this; most leave it
   *  unset so the bar reads as title-only. */
  dateLabel?: string;
};

export type ShellIdentity = {
  name:     string;
  initials: string;
  /** Avatar background colour. Defaults to the brand primary at the
   *  shell boundary; per-role overrides can be passed in. */
  color:    string;
};

type Ctx = {
  meta:                PageMeta;
  setMeta:             (next: PageMeta) => void;
  identity:            ShellIdentity;
  /** Unread internal-message count — resolved once at the shell layout
   *  boundary (server) and read by any descendant via
   *  `useUnreadMessageCount()`.  Drives the MessageBell badge. */
  unreadMessageCount:  number;
  /** Recent inbox slice (top ~20) — resolved server-side at the shell
   *  layout boundary so the MessageDrawer can render without an extra
   *  client-side fetch.  Read via `useRecentMessages()`. */
  recentMessages:      Message[];
};

const PageTitleCtx = createContext<Ctx | null>(null);

const DEFAULT_IDENTITY: ShellIdentity = {
  name:     "Edify",
  initials: "—",
  color:    "#2f5f7a",
};

export function PageTitleProvider({
  children,
  identity = DEFAULT_IDENTITY,
  unreadMessageCount = 0,
  recentMessages = [],
}: {
  children: ReactNode;
  identity?: ShellIdentity;
  unreadMessageCount?: number;
  recentMessages?: Message[];
}) {
  const [meta, setMeta] = useState<PageMeta>({ title: "Edify" });
  const value = useMemo<Ctx>(
    () => ({ meta, setMeta, identity, unreadMessageCount, recentMessages }),
    [meta, identity, unreadMessageCount, recentMessages],
  );
  return <PageTitleCtx.Provider value={value}>{children}</PageTitleCtx.Provider>;
}

export function usePageTitle(): PageMeta {
  const ctx = useContext(PageTitleCtx);
  return ctx?.meta ?? { title: "Edify" };
}

export function useShellIdentity(): ShellIdentity {
  const ctx = useContext(PageTitleCtx);
  return ctx?.identity ?? DEFAULT_IDENTITY;
}

export function useUnreadMessageCount(): number {
  const ctx = useContext(PageTitleCtx);
  return ctx?.unreadMessageCount ?? 0;
}

/** Recent-inbox slice resolved at the shell-layout boundary. Used by
 *  MessageDrawer to render without a client-side fetch. */
export function useRecentMessages(): Message[] {
  const ctx = useContext(PageTitleCtx);
  return ctx?.recentMessages ?? [];
}

/** Register this page's title (+ optional date label) with the shell
 *  context. Safe to call from any client component — typically called
 *  by PageHeader / StubPage / EntityIndex.
 *
 *  Implementation note: we destructure `setMeta` directly off the
 *  context. React's useState setters are referentially stable across
 *  renders, so this effect's dependency list only "really changes"
 *  when `title` or `dateLabel` change. The earlier version depended
 *  on the whole `ctx` (which the provider memoises against `meta`),
 *  which meant every setMeta call → new meta → new ctx → re-run the
 *  effect → setMeta again → infinite loop. That loop jammed React's
 *  reconciliation pipeline and silently broke router navigations.
 */
export function useSetPageTitle(title: string | undefined, dateLabel?: string) {
  const ctx = useContext(PageTitleCtx);
  const setMeta = ctx?.setMeta;

  useEffect(() => {
    if (!setMeta) return;
    // No explicit title → leave the route-level default (RouteTitleSync)
    // in place rather than stamping a fallback over it.
    if (!title) return;
    setMeta({ title, dateLabel });
  }, [setMeta, title, dateLabel]);
}
