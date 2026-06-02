"use client";

// IdentityCluster — the ONE identity-chrome group: message bell +
// notification bell + account avatar. Every header (desktop PageHeader,
// dark mobile MobileTopBar, and the future AppHeader) renders this single
// component instead of mounting the three bells independently, so the
// cluster can never drift between surfaces and the collapse rule lives in
// one place.
//
// variant: "default" (light desktop chrome) | "dark" (mobile dark bar).
// Collapse rule (one source of truth): the message bell hides on the
// narrowest viewports (<sm) to keep the row breathable; notification +
// avatar always stay. This matches the prior MobileTopBar behaviour and
// is harmless on desktop (the cluster there only mounts at lg+).

import { MessageBell } from "@/components/messages/MessageBell";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { cn } from "@/lib/utils";

export function IdentityCluster({
  variant = "default",
  className,
}: {
  variant?: "default" | "dark";
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-2.5 shrink-0", className)}>
      <MessageBell variant={variant} />
      <NotificationBell variant={variant} />
      {/* The account avatar/menu lives in the sidebar profile (SidebarProfile),
          the single identity surface — intentionally not duplicated here. */}
    </div>
  );
}
