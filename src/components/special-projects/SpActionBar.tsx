"use client";

import {
  Plus,
  Upload,
  Handshake,
  UserPlus,
  LineChart,
  Download,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { specialProjectActions, type SpecialProjectAction } from "@/lib/special-projects-mock";
import type { CurrentUser } from "@/lib/schools-mock";
import { cn } from "@/lib/utils";
import { CreateProjectModal } from "./CreateProjectModal";

const iconMap: Record<SpecialProjectAction["icon"], LucideIcon> = {
  plus:      Plus,
  import:    Upload,
  handshake: Handshake,
  userPlus:  UserPlus,
  lineChart: LineChart,
  download:  Download,
};

function isAllowed(a: SpecialProjectAction, user: CurrentUser): boolean {
  if (!a.requiresRole) return true;
  return a.requiresRole.includes(user.role);
}

export function SpActionBar({ user }: { user: CurrentUser }) {
  const [createOpen, setCreateOpen] = useState(false);
  return (
    <>
      <section className="grid grid-cols-6 gap-3">
        {specialProjectActions.map((a) => {
          const Icon = iconMap[a.icon];
          const allowed = isAllowed(a, user);
          const primary = a.primary && allowed;
          return (
            <button
              key={a.key}
              type="button"
              disabled={!allowed}
              onClick={a.key === "new" && allowed ? () => setCreateOpen(true) : undefined}
              title={!allowed ? `Requires: ${a.requiresRole?.join(", ")}` : undefined}
              className={cn(
                "h-12 px-4 rounded-xl border flex items-center gap-2 text-[13px] font-semibold transition-colors",
                primary
                  ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)]"
                  : "bg-white border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
                !allowed && "opacity-55 cursor-not-allowed hover:bg-white",
              )}
            >
              <Icon size={15} />
              <span className="truncate">{a.label}</span>
            </button>
          );
        })}
      </section>
      <CreateProjectModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </>
  );
}
