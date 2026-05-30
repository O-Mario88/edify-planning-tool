import { type ReactNode } from "react";
import { EdifySidebarServer } from "@/components/shell/EdifySidebarServer";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { PageTitleProvider } from "@/components/shell/PageTitleContext";
import { MobileTopBar } from "@/components/shell/MobileTopBar";
import { RouteTitleSync } from "@/components/shell/RouteTitleSync";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { getCurrentUserOrNull } from "@/lib/auth";

// Shared shell layout for every authenticated, sidebar-bearing page.
//
// Why this exists: before this layout, every page mounted
// <EdifySidebarServer /> itself, so every route transition tore down and
// rebuilt the entire sidebar (35 lucide icons, role menu, usePathname).
// Pulling it into a route-group layout lets the App Router keep the
// sidebar mounted across navigations — only the {children} slot streams in.
//
// Viewport behaviour (delegated entirely to EdifySidebar via
// useMobileDrawer):
//   • Mobile + tablet (<lg): sidebar lives off-screen via `-translate-x-full`,
//     reachable through the hamburger button useMobileDrawer mounts at
//     top-left (`lg:hidden fixed top-3 left-3`).
//   • Desktop (≥lg): sidebar pins persistently in flow.
// The sidebar is always mounted so the hamburger is guaranteed on
// every route — the earlier `hidden md:flex` wrapper accidentally
// killed the hamburger on mobile by hiding its host (display:none
// also un-renders the sidebar's drawer + fixed hamburger trigger).

export default async function ShellLayout({ children }: { children: ReactNode }) {
  // Resolve the signed-in user once at the shell level so the
  // mobile/tablet top bar + the desktop PageHeader avatar both read
  // identity through context — no per-page prop-drilling.
  const user = await getCurrentUserOrNull();
  const identity = {
    name:     user?.name     ?? "Edify",
    initials: user?.initials ?? "—",
    color:    "#2f5f7a",
  };

  // Resolve unread-message count + recent inbox slice once and
  // broadcast via context.  The MessageBell reads the count for its
  // badge; MessageDrawer reads the slice to render rows without a
  // client-side fetch.  Import is inline to keep this layout pure
  // when there's no user.
  let unreadMessageCount = 0;
  let recentMessages: Awaited<ReturnType<typeof import("@/lib/messages-v2/access").messagesForUser>> = [];
  if (user) {
    const { messagesForUser } = await import("@/lib/messages-v2/access");
    const inbox = messagesForUser(user, "inbox");
    unreadMessageCount = inbox.filter((m) => m.status === "unread" || m.status === "action_required").length;
    // Top 20 by createdAt (newest first) — MessageDrawer trims/filters
    // client-side.
    recentMessages = [...inbox]
      .sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1))
      .slice(0, 20);
  }

  return (
    <PageTitleProvider
      identity={identity}
      unreadMessageCount={unreadMessageCount}
      recentMessages={recentMessages}
    >
      {/* Stamps the MobileTopBar title from a route → title map so
          every page in the (shell) group reads correctly even when
          the page doesn't explicitly register one. Per-page
          `useSetPageTitle()` overrides still win because they run
          after this default. */}
      <RouteTitleSync />
      <div className="flex min-h-screen w-full bg-[var(--color-page)]">
        <EdifySidebarServer />
        <main id="main-content" className="flex-1 min-w-0">
          {/* Premium dark chrome for mobile + tablet. Hidden at lg+
              where the pinned sidebar + in-page PageHeader take over. */}
          <MobileTopBar userInitials={identity.initials} userColor={identity.color} />
          {children}
        </main>
        {/* Phone-only bottom tab bar. Hidden from md+ where the sidebar
            carries navigation. Role-aware via the SessionContext. */}
        <RoleBottomNav />
        {/* Universal ⌘K command palette — mounted once at the shell so
            it's reachable from every (shell) route. Toggled via ⌘K /
            Ctrl+K or via the magnifier icon in the MobileTopBar. */}
        <CommandPalette />
      </div>
    </PageTitleProvider>
  );
}
