import type { ReactNode } from "react";
import { AppTopHeader } from "./AppTopHeader";
import type { Role } from "@/lib/workflow-mock";

// AppShell wires every page to the same page-level chrome: the top
// header (title + filters + role-aware avatar) and the standard
// content gutter.
//
// The role-aware *left sidebar* used to live here too, but every page
// that mounts AppShell sits inside the `(shell)` route group whose
// layout already renders <EdifySidebarServer /> exactly once. Mounting
// the sidebar here as well caused the page to render two sidebars
// side by side. This component now leaves layout chrome to the route
// group and focuses purely on the page header + content gutter.
export function AppShell({
  role,
  title,
  subtitle,
  filters,
  searchPlaceholder,
  showRoleSwitcher,
  children,
}: {
  role: Role;
  title: string;
  subtitle: string;
  filters?: ("financialYear" | "month" | "region" | "scope")[];
  searchPlaceholder?: string;
  showRoleSwitcher?: boolean;
  children: ReactNode;
}) {
  return (
    <>
      <AppTopHeader
        role={role}
        title={title}
        subtitle={subtitle}
        filters={filters}
        searchPlaceholder={searchPlaceholder}
        showRoleSwitcher={showRoleSwitcher}
      />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
        {children}
      </div>
    </>
  );
}
