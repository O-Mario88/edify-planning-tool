"use client";

import Link from "next/link";
import {
  Building2,
  UserPlus,
  Handshake,
  Flag,
  Download,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  schoolQuickActions,
  isActionAllowed,
  type CurrentUser,
  type SchoolQuickAction,
} from "@/lib/schools-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<SchoolQuickAction["icon"], LucideIcon> = {
  school:    Building2,
  userPlus:  UserPlus,
  handshake: Handshake,
  flag:      Flag,
  download:  Download,
};

export function SchoolQuickActions({ user }: { user: CurrentUser }) {
  return (
    <SectionCard title="Quick Actions">
      <div className="grid grid-cols-5 gap-3">
        {schoolQuickActions.map((a) => {
          const Icon = iconMap[a.icon];
          const allowed = isActionAllowed(a, user);

          const inner = (
            <div className={cn("flex items-start gap-3", !allowed && "opacity-55")}>
              <span className="w-9 h-9 rounded-md grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                <Icon size={16} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-bold leading-tight">{a.title}</div>
                <div className="text-[11px] muted mt-0.5 truncate">
                  {allowed ? a.subtitle : "Restricted for this role"}
                </div>
              </div>
            </div>
          );

          if (!allowed) {
            return (
              <div
                key={a.key}
                aria-disabled
                className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 cursor-not-allowed"
                title={`Requires: ${a.requiresRole?.join(", ")}`}
              >
                {inner}
              </div>
            );
          }

          return (
            <Link
              key={a.key}
              href={a.href}
              className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 hover:bg-[var(--color-edify-soft)]/50 transition-colors"
            >
              {inner}
            </Link>
          );
        })}
      </div>
    </SectionCard>
  );
}
