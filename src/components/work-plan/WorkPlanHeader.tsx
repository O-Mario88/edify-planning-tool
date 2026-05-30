"use client";

import Link from "next/link";
import { Menu, Bell, ChevronDown } from "lucide-react";
import { workPlanHeader } from "@/lib/work-plan-mock";

export function WorkPlanHeader() {
  return (
    <header
      className="text-white pt-3 pb-5 px-4"
      style={{
        backgroundImage:
          "linear-gradient(180deg, #0e1c2c 0%, #0a1623 100%)",
      }}
    >
      <div className="flex items-center gap-3">
        <Link
          href="/dashboards/cpl"
          aria-label="Open dashboard"
          className="h-9 w-9 grid place-items-center rounded-md hover:bg-white/[.06]"
        >
          <Menu size={20} className="text-white" />
        </Link>

        <div className="flex-1 min-w-0">
          <div className="text-[18px] font-bold leading-tight truncate">
            {workPlanHeader.title}
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-1 text-body text-white/85 mt-0.5"
          >
            {workPlanHeader.month}
            <ChevronDown size={12} className="opacity-80" />
          </button>
        </div>

        <button
          type="button"
          aria-label="Notifications"
          className="relative h-9 w-9 grid place-items-center rounded-md hover:bg-white/[.06]"
        >
          <Bell size={18} />
          {workPlanHeader.notificationCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-rose-500 text-white text-[10px] font-extrabold tabular grid place-items-center">
              {workPlanHeader.notificationCount}
            </span>
          )}
        </button>

        <button
          type="button"
          aria-label="Profile"
          className="h-10 w-10 rounded-full bg-[var(--color-edify-primary)] grid place-items-center text-white text-[12px] font-extrabold ring-2 ring-white/10"
        >
          {workPlanHeader.user.initials}
        </button>
      </div>
    </header>
  );
}
