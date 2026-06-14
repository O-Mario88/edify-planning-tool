"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import type { CurrentUser, AppRole } from "@/lib/schools-mock";
import { cn } from "@/lib/utils";
import { CreateProjectModal } from "./CreateProjectModal";

// Special-projects action bar. Only ONE action is actually wired: "New Project"
// (opens CreateProjectModal). The other five buttons that used to live here
// (Import Schools / Assign Partner / Add Schools / Track Impact / Export Summary)
// were dead — no onClick, no href — so they were removed rather than shown as
// non-functional controls. Per-project Assign / Schedule / Track all live on the
// project monitor at /projects/[id].
const CREATE_ROLES: AppRole[] = ["Admin", "CountryDirector", "CountryProgramLead"];

export function SpActionBar({ user }: { user: CurrentUser }) {
  const [createOpen, setCreateOpen] = useState(false);
  const allowed = CREATE_ROLES.includes(user.role);

  return (
    <>
      <section className="flex">
        <button
          type="button"
          disabled={!allowed}
          onClick={allowed ? () => setCreateOpen(true) : undefined}
          title={!allowed ? `Requires: ${CREATE_ROLES.join(", ")}` : undefined}
          className={cn(
            "h-12 px-4 rounded-xl border flex items-center gap-2 text-[13px] font-semibold transition-colors",
            "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)]",
            !allowed && "opacity-55 cursor-not-allowed hover:bg-[var(--color-edify-primary)]",
          )}
        >
          <Plus size={15} />
          <span className="truncate">New Project</span>
        </button>
      </section>
      <CreateProjectModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </>
  );
}
